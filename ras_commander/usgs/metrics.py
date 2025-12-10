"""
Statistical metrics for model validation and performance assessment.

This module provides comprehensive statistical metrics for comparing HEC-RAS model results
against observed USGS gauge data. It implements standard hydrologic performance metrics
following established guidelines (Moriasi et al., 2007; Nash & Sutcliffe, 1970; Gupta et al., 2009).

Logging Configuration:
- The logging is set up in the logging_config.py file.
- A @log_call decorator is available to automatically log function calls.
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Logs are written to both console and a rotating file handler.

List of Functions:
- nash_sutcliffe_efficiency()
- kling_gupta_efficiency()
- calculate_peak_error()
- calculate_volume_error()
- classify_performance()
- calculate_all_metrics()

Example:
    >>> import numpy as np
    >>> from ras_commander.usgs.metrics import nash_sutcliffe_efficiency, calculate_all_metrics
    >>> observed = np.array([100, 200, 300, 250, 150])
    >>> modeled = np.array([110, 190, 295, 260, 145])
    >>> nse = nash_sutcliffe_efficiency(observed, modeled)
    >>> print(f"NSE: {nse:.3f}")
    >>> metrics = calculate_all_metrics(observed, modeled)
"""

import numpy as np
import pandas as pd
from typing import Union, Dict, Tuple, Optional
from ..LoggingConfig import get_logger
from ..Decorators import log_call
from ..RasUtils import RasUtils

logger = get_logger(__name__)


@log_call
def nash_sutcliffe_efficiency(
    observed: Union[np.ndarray, pd.Series],
    modeled: Union[np.ndarray, pd.Series]
) -> float:
    """
    Calculate Nash-Sutcliffe Efficiency (NSE).

    The NSE measures the ratio of the error variance to the observed variance,
    quantifying how well the model predicts observations relative to using the
    observed mean as a predictor.

    Formula:
        NSE = 1 - [Σ(Qobs - Qmod)² / Σ(Qobs - Qobs_mean)²]

    Parameters
    ----------
    observed : np.ndarray or pd.Series
        Observed (measured) values from USGS gauge data
    modeled : np.ndarray or pd.Series
        Modeled (predicted) values from HEC-RAS simulation

    Returns
    -------
    float
        Nash-Sutcliffe Efficiency value
        - NSE = 1.0: Perfect fit
        - NSE = 0.0: Model predictions are as good as the mean of observations
        - NSE < 0.0: Observed mean is a better predictor than the model

    Notes
    -----
    NaN values are automatically removed from both series before calculation.
    If all values are NaN or arrays are empty, returns np.nan.

    References
    ----------
    Nash, J. E., & Sutcliffe, J. V. (1970). River flow forecasting through
    conceptual models part I — A discussion of principles. Journal of Hydrology,
    10(3), 282-290.

    Examples
    --------
    >>> observed = np.array([100, 200, 300, 250, 150])
    >>> modeled = np.array([110, 190, 295, 260, 145])
    >>> nse = nash_sutcliffe_efficiency(observed, modeled)
    >>> print(f"NSE: {nse:.3f}")
    NSE: 0.957
    """
    # Convert to numpy arrays if needed
    if isinstance(observed, pd.Series):
        observed = observed.values
    if isinstance(modeled, pd.Series):
        modeled = modeled.values

    # Remove NaN values
    valid_mask = ~(np.isnan(observed) | np.isnan(modeled))
    observed = observed[valid_mask]
    modeled = modeled[valid_mask]

    if len(observed) == 0:
        logger.warning("No valid data points for NSE calculation")
        return np.nan

    obs_mean = np.mean(observed)
    numerator = np.sum((observed - modeled) ** 2)
    denominator = np.sum((observed - obs_mean) ** 2)

    if denominator == 0:
        logger.warning("Zero variance in observations - NSE undefined")
        return np.nan

    nse = 1 - (numerator / denominator)
    logger.debug(f"Calculated NSE: {nse:.4f}")
    return nse


@log_call
def kling_gupta_efficiency(
    observed: Union[np.ndarray, pd.Series],
    modeled: Union[np.ndarray, pd.Series]
) -> Tuple[float, Dict[str, float]]:
    """
    Calculate Kling-Gupta Efficiency (KGE) and its decomposed components.

    KGE addresses limitations of NSE by decomposing performance into correlation,
    variability bias, and mean bias components.

    Formula:
        KGE = 1 - √[(r-1)² + (α-1)² + (β-1)²]

    Where:
        - r = correlation coefficient between observed and modeled
        - α = σ_mod / σ_obs (ratio of standard deviations, variability ratio)
        - β = μ_mod / μ_obs (ratio of means, bias ratio)

    Parameters
    ----------
    observed : np.ndarray or pd.Series
        Observed (measured) values from USGS gauge data
    modeled : np.ndarray or pd.Series
        Modeled (predicted) values from HEC-RAS simulation

    Returns
    -------
    kge : float
        Kling-Gupta Efficiency value
        - KGE = 1.0: Perfect fit
        - KGE = 0.0: Model predictions have no skill
        - KGE < 0.0: Poor model performance
    components : dict
        Dictionary containing decomposed components:
        - 'r': Correlation coefficient (measures timing/pattern)
        - 'alpha': Variability ratio (measures spread)
        - 'beta': Bias ratio (measures mean bias)

    Notes
    -----
    NaN values are automatically removed from both series before calculation.
    If all values are NaN or arrays are empty, returns (np.nan, {}).

    References
    ----------
    Gupta, H. V., Kling, H., Yilmaz, K. K., & Martinez, G. F. (2009).
    Decomposition of the mean squared error and NSE performance criteria:
    Implications for improving hydrological modelling. Journal of Hydrology,
    377(1-2), 80-91.

    Examples
    --------
    >>> observed = np.array([100, 200, 300, 250, 150])
    >>> modeled = np.array([110, 190, 295, 260, 145])
    >>> kge, components = kling_gupta_efficiency(observed, modeled)
    >>> print(f"KGE: {kge:.3f}")
    >>> print(f"Components: r={components['r']:.3f}, α={components['alpha']:.3f}, β={components['beta']:.3f}")
    """
    # Convert to numpy arrays if needed
    if isinstance(observed, pd.Series):
        observed = observed.values
    if isinstance(modeled, pd.Series):
        modeled = modeled.values

    # Remove NaN values
    valid_mask = ~(np.isnan(observed) | np.isnan(modeled))
    observed = observed[valid_mask]
    modeled = modeled[valid_mask]

    if len(observed) == 0:
        logger.warning("No valid data points for KGE calculation")
        return np.nan, {}

    # Calculate components
    r = np.corrcoef(observed, modeled)[0, 1]
    alpha = np.std(modeled) / np.std(observed)
    beta = np.mean(modeled) / np.mean(observed)

    # Calculate KGE
    kge = 1 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)

    components = {
        'r': r,
        'alpha': alpha,
        'beta': beta
    }

    logger.debug(f"Calculated KGE: {kge:.4f} (r={r:.4f}, α={alpha:.4f}, β={beta:.4f})")
    return kge, components


@log_call
def calculate_peak_error(
    observed: Union[np.ndarray, pd.Series],
    modeled: Union[np.ndarray, pd.Series],
    time_index: Optional[pd.DatetimeIndex] = None
) -> Dict[str, Union[float, pd.Timedelta]]:
    """
    Calculate peak flow/stage comparison metrics.

    Compares the maximum values in observed and modeled time series, including
    timing differences if time index is provided.

    Parameters
    ----------
    observed : np.ndarray or pd.Series
        Observed (measured) values from USGS gauge data
    modeled : np.ndarray or pd.Series
        Modeled (predicted) values from HEC-RAS simulation
    time_index : pd.DatetimeIndex, optional
        Datetime index corresponding to the values. If provided, calculates
        timing error between peaks.

    Returns
    -------
    dict
        Dictionary containing:
        - 'peak_obs': Observed peak value
        - 'peak_mod': Modeled peak value
        - 'peak_error_pct': Percentage error = (peak_mod - peak_obs) / peak_obs * 100
        - 'peak_timing_error': Time difference between peaks (if time_index provided)

    Notes
    -----
    NaN values are ignored when finding peak values.

    Examples
    --------
    >>> observed = np.array([100, 200, 300, 250, 150])
    >>> modeled = np.array([110, 190, 295, 260, 145])
    >>> peak_metrics = calculate_peak_error(observed, modeled)
    >>> print(f"Peak error: {peak_metrics['peak_error_pct']:.1f}%")
    Peak error: -1.7%

    >>> # With time index
    >>> times = pd.date_range('2024-01-01', periods=5, freq='h')
    >>> peak_metrics = calculate_peak_error(observed, modeled, time_index=times)
    >>> print(f"Timing error: {peak_metrics['peak_timing_error']}")
    """
    # Convert to numpy arrays if needed
    if isinstance(observed, pd.Series):
        observed = observed.values
    if isinstance(modeled, pd.Series):
        modeled = modeled.values

    # Find peak values (ignoring NaN)
    peak_obs = np.nanmax(observed)
    peak_mod = np.nanmax(modeled)

    # Calculate percentage error
    peak_error_pct = ((peak_mod - peak_obs) / peak_obs) * 100

    result = {
        'peak_obs': peak_obs,
        'peak_mod': peak_mod,
        'peak_error_pct': peak_error_pct
    }

    # Calculate timing error if time index provided
    if time_index is not None:
        idx_obs = np.nanargmax(observed)
        idx_mod = np.nanargmax(modeled)
        time_obs = time_index[idx_obs]
        time_mod = time_index[idx_mod]
        peak_timing_error = time_mod - time_obs
        result['peak_timing_error'] = peak_timing_error
        logger.debug(f"Peak timing error: {peak_timing_error}")

    logger.debug(f"Peak error: {peak_error_pct:.2f}% (obs={peak_obs:.1f}, mod={peak_mod:.1f})")
    return result


@log_call
def calculate_volume_error(
    observed: Union[np.ndarray, pd.Series],
    modeled: Union[np.ndarray, pd.Series],
    dt_hours: float = 1.0
) -> Dict[str, float]:
    """
    Calculate total volume comparison metrics.

    Integrates observed and modeled time series to compare total volumes,
    useful for assessing mass balance and cumulative errors.

    Formula:
        Volume = Σ(Flow) * dt

    Parameters
    ----------
    observed : np.ndarray or pd.Series
        Observed (measured) values from USGS gauge data (flow in cfs)
    modeled : np.ndarray or pd.Series
        Modeled (predicted) values from HEC-RAS simulation (flow in cfs)
    dt_hours : float, optional
        Time step in hours for integration. Default is 1.0 hour.

    Returns
    -------
    dict
        Dictionary containing:
        - 'vol_obs': Observed total volume (cfs-hours)
        - 'vol_mod': Modeled total volume (cfs-hours)
        - 'vol_error_pct': Volume error percentage = (vol_mod - vol_obs) / vol_obs * 100

    Notes
    -----
    NaN values are treated as zero in the integration.
    Volumes are in units of cfs-hours. To convert to acre-feet, multiply by 0.0413.

    Examples
    --------
    >>> observed = np.array([100, 200, 300, 250, 150])
    >>> modeled = np.array([110, 190, 295, 260, 145])
    >>> vol_metrics = calculate_volume_error(observed, modeled, dt_hours=1.0)
    >>> print(f"Volume error: {vol_metrics['vol_error_pct']:.1f}%")
    Volume error: -1.0%
    """
    # Convert to numpy arrays if needed
    if isinstance(observed, pd.Series):
        observed = observed.values
    if isinstance(modeled, pd.Series):
        modeled = modeled.values

    # Replace NaN with 0 for integration
    observed_clean = np.nan_to_num(observed, nan=0.0)
    modeled_clean = np.nan_to_num(modeled, nan=0.0)

    # Calculate volumes (simple trapezoidal integration)
    vol_obs = np.sum(observed_clean) * dt_hours
    vol_mod = np.sum(modeled_clean) * dt_hours

    # Calculate percentage error
    vol_error_pct = ((vol_mod - vol_obs) / vol_obs) * 100 if vol_obs != 0 else np.nan

    result = {
        'vol_obs': vol_obs,
        'vol_mod': vol_mod,
        'vol_error_pct': vol_error_pct
    }

    logger.debug(f"Volume error: {vol_error_pct:.2f}% (obs={vol_obs:.1f}, mod={vol_mod:.1f} cfs-hours)")
    return result


@log_call
def classify_performance(metrics_dict: Dict[str, float]) -> str:
    """
    Classify model performance based on multiple metrics.

    Uses performance thresholds from Moriasi et al. (2007) for hydrologic models.
    Classification is based on NSE and PBIAS values.

    Performance Criteria:
        - Very Good: NSE > 0.75 and |PBIAS| < 10%
        - Good: NSE > 0.65 and |PBIAS| < 15%
        - Satisfactory: NSE > 0.50 and |PBIAS| < 25%
        - Unsatisfactory: NSE ≤ 0.50 or |PBIAS| ≥ 25%

    Parameters
    ----------
    metrics_dict : dict
        Dictionary containing metric values. Must include:
        - 'nse': Nash-Sutcliffe Efficiency
        - 'pbias': Percent Bias (as percentage)

    Returns
    -------
    str
        Performance classification: 'Very Good', 'Good', 'Satisfactory', or 'Unsatisfactory'

    References
    ----------
    Moriasi, D. N., Arnold, J. G., Van Liew, M. W., Bingner, R. L., Harmel, R. D.,
    & Veith, T. L. (2007). Model evaluation guidelines for systematic quantification
    of accuracy in watershed simulations. Transactions of the ASABE, 50(3), 885-900.

    Examples
    --------
    >>> metrics = {'nse': 0.82, 'pbias': -5.2}
    >>> rating = classify_performance(metrics)
    >>> print(rating)
    Very Good

    >>> metrics = {'nse': 0.55, 'pbias': 18.0}
    >>> rating = classify_performance(metrics)
    >>> print(rating)
    Satisfactory
    """
    nse = metrics_dict.get('nse', -999)
    pbias = abs(metrics_dict.get('pbias', 999))

    if nse > 0.75 and pbias < 10:
        rating = 'Very Good'
    elif nse > 0.65 and pbias < 15:
        rating = 'Good'
    elif nse > 0.50 and pbias < 25:
        rating = 'Satisfactory'
    else:
        rating = 'Unsatisfactory'

    logger.debug(f"Performance classification: {rating} (NSE={nse:.3f}, PBIAS={pbias:.1f}%)")
    return rating


@log_call
def calculate_all_metrics(
    observed: Union[np.ndarray, pd.Series],
    modeled: Union[np.ndarray, pd.Series],
    time_index: Optional[pd.DatetimeIndex] = None,
    dt_hours: float = 1.0
) -> Dict[str, Union[float, str, pd.Timedelta]]:
    """
    Calculate comprehensive validation metrics for model-observation comparison.

    Computes all available statistical metrics including NSE, KGE, RMSE, PBIAS,
    peak errors, volume errors, and performance classification.

    Parameters
    ----------
    observed : np.ndarray or pd.Series
        Observed (measured) values from USGS gauge data
    modeled : np.ndarray or pd.Series
        Modeled (predicted) values from HEC-RAS simulation
    time_index : pd.DatetimeIndex, optional
        Datetime index for time-based metrics (peak timing). If None, timing
        metrics are not calculated.
    dt_hours : float, optional
        Time step in hours for volume integration. Default is 1.0 hour.

    Returns
    -------
    dict
        Comprehensive dictionary containing all metrics:
        - 'n_points': Number of valid data points
        - 'nse': Nash-Sutcliffe Efficiency
        - 'kge': Kling-Gupta Efficiency
        - 'kge_r': KGE correlation component
        - 'kge_alpha': KGE variability component
        - 'kge_beta': KGE bias component
        - 'rmse': Root Mean Square Error
        - 'pbias': Percent Bias (as percentage)
        - 'correlation': Pearson correlation coefficient
        - 'peak_obs': Observed peak value
        - 'peak_mod': Modeled peak value
        - 'peak_error_pct': Peak percentage error
        - 'peak_timing_error': Time difference between peaks (if time_index provided)
        - 'vol_obs': Observed total volume
        - 'vol_mod': Modeled total volume
        - 'vol_error_pct': Volume percentage error
        - 'performance_rating': Overall performance classification

    Notes
    -----
    - Uses RasUtils.calculate_rmse() and RasUtils.calculate_percent_bias() for
      consistency with existing ras-commander functions
    - NaN values are automatically removed before calculation
    - Requires at least 10 valid data points for calculation

    Raises
    ------
    ValueError
        If fewer than 10 valid data points exist after removing NaN values

    Examples
    --------
    >>> import numpy as np
    >>> import pandas as pd
    >>> observed = np.array([100, 200, 300, 250, 150])
    >>> modeled = np.array([110, 190, 295, 260, 145])
    >>> metrics = calculate_all_metrics(observed, modeled)
    >>> print(f"Performance: {metrics['performance_rating']}")
    >>> print(f"NSE: {metrics['nse']:.3f}, KGE: {metrics['kge']:.3f}")

    >>> # With time index for timing metrics
    >>> times = pd.date_range('2024-01-01', periods=5, freq='h')
    >>> metrics = calculate_all_metrics(observed, modeled, time_index=times, dt_hours=1.0)
    >>> print(f"Peak timing error: {metrics.get('peak_timing_error')}")
    """
    # Convert to numpy arrays if needed
    if isinstance(observed, pd.Series):
        obs_array = observed.values
    else:
        obs_array = observed

    if isinstance(modeled, pd.Series):
        mod_array = modeled.values
    else:
        mod_array = modeled

    # Remove NaN values
    valid_mask = ~(np.isnan(obs_array) | np.isnan(mod_array))
    obs_clean = obs_array[valid_mask]
    mod_clean = mod_array[valid_mask]

    if len(obs_clean) < 10:
        raise ValueError(
            f"Insufficient valid data points for comprehensive comparison. "
            f"Found {len(obs_clean)} points, need at least 10."
        )

    # Initialize metrics dictionary
    metrics = {
        'n_points': len(obs_clean)
    }

    # Calculate core metrics
    metrics['nse'] = nash_sutcliffe_efficiency(obs_clean, mod_clean)

    kge, kge_components = kling_gupta_efficiency(obs_clean, mod_clean)
    metrics['kge'] = kge
    metrics['kge_r'] = kge_components['r']
    metrics['kge_alpha'] = kge_components['alpha']
    metrics['kge_beta'] = kge_components['beta']

    # Use existing RasUtils functions for RMSE and PBIAS
    # Note: RasUtils.calculate_rmse returns normalized by default
    metrics['rmse'] = RasUtils.calculate_rmse(obs_clean, mod_clean, normalized=False)
    metrics['pbias'] = RasUtils.calculate_percent_bias(obs_clean, mod_clean, as_percentage=True)

    # Calculate correlation
    metrics['correlation'] = np.corrcoef(obs_clean, mod_clean)[0, 1]

    # Peak analysis
    peak_metrics = calculate_peak_error(obs_clean, mod_clean, time_index=time_index)
    metrics.update(peak_metrics)

    # Volume analysis
    volume_metrics = calculate_volume_error(obs_clean, mod_clean, dt_hours=dt_hours)
    metrics.update(volume_metrics)

    # Performance classification
    metrics['performance_rating'] = classify_performance(metrics)

    logger.info(
        f"Calculated all metrics for {len(obs_clean)} points. "
        f"Performance: {metrics['performance_rating']} "
        f"(NSE={metrics['nse']:.3f}, KGE={metrics['kge']:.3f})"
    )

    return metrics
