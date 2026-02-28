"""
Statistical metrics for model validation and performance assessment.

This module provides comprehensive statistical metrics for comparing HEC-RAS model results
against observed USGS gauge data. It implements standard hydrologic performance metrics
following established guidelines (Moriasi et al., 2007; Nash & Sutcliffe, 1970; Gupta et al., 2009).

PBIAS Sign Convention:
    This module uses PBIAS = 100 * sum(sim - obs) / sum(obs), where positive values
    indicate model overestimation. This matches HEC-HMS convention (confirmed via
    decompilation of HMS 4.13). Note that Moriasi et al. (2007) uses the opposite
    sign convention (obs - sim), but classification thresholds use |PBIAS| and are
    unaffected by sign choice.

Classes:
- RasUsgsMetrics - Static class with all validation metric methods

Example:
    >>> import numpy as np
    >>> from ras_commander.usgs.metrics import RasUsgsMetrics
    >>> observed = np.array([100, 200, 300, 250, 150])
    >>> modeled = np.array([110, 190, 295, 260, 145])
    >>> nse = RasUsgsMetrics.nash_sutcliffe_efficiency(observed, modeled)
    >>> print(f"NSE: {nse:.3f}")
    >>> metrics = RasUsgsMetrics.calculate_all_metrics(observed, modeled)
"""

import numpy as np
import pandas as pd
from typing import Union, Dict, Tuple, Optional
from ..LoggingConfig import get_logger
from ..Decorators import log_call
from ..RasUtils import RasUtils

logger = get_logger(__name__)


class RasUsgsMetrics:
    """
    Static class providing calibration and validation metrics for model assessment.

    All methods are static - call directly without instantiation:
        nse = RasUsgsMetrics.nash_sutcliffe_efficiency(observed, modeled)

    Methods follow HEC-HMS conventions where applicable (confirmed via
    decompilation of HMS 4.13 Java source).
    """

    @staticmethod
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
        >>> nse = RasUsgsMetrics.nash_sutcliffe_efficiency(observed, modeled)
        >>> print(f"NSE: {nse:.3f}")
        NSE: 0.957
        """
        # Convert to numpy arrays if needed
        if isinstance(observed, pd.Series):
            observed = observed.values
        if isinstance(modeled, pd.Series):
            modeled = modeled.values
        observed = np.asarray(observed, dtype=float)
        modeled = np.asarray(modeled, dtype=float)

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

    @staticmethod
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
        >>> kge, components = RasUsgsMetrics.kling_gupta_efficiency(observed, modeled)
        >>> print(f"KGE: {kge:.3f}")
        >>> print(f"Components: r={components['r']:.3f}, α={components['alpha']:.3f}, β={components['beta']:.3f}")
        """
        # Convert to numpy arrays if needed
        if isinstance(observed, pd.Series):
            observed = observed.values
        if isinstance(modeled, pd.Series):
            modeled = modeled.values
        observed = np.asarray(observed, dtype=float)
        modeled = np.asarray(modeled, dtype=float)

        # Remove NaN values
        valid_mask = ~(np.isnan(observed) | np.isnan(modeled))
        observed = observed[valid_mask]
        modeled = modeled[valid_mask]

        if len(observed) == 0:
            logger.warning("No valid data points for KGE calculation")
            return np.nan, {}

        # Calculate components with division-by-zero guards (matches HMS pattern)
        obs_std = np.std(observed)
        obs_mean = np.mean(observed)

        if obs_std == 0:
            logger.warning("KGE undefined: observed has zero standard deviation (constant values)")
            return np.nan, {}
        if obs_mean == 0:
            logger.warning("KGE undefined: observed has zero mean (beta ratio undefined)")
            return np.nan, {}

        r = np.corrcoef(observed, modeled)[0, 1]
        alpha = np.std(modeled) / obs_std
        beta = np.mean(modeled) / obs_mean

        # Calculate KGE
        kge = 1 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)

        components = {
            'r': r,
            'alpha': alpha,
            'beta': beta
        }

        logger.debug(f"Calculated KGE: {kge:.4f} (r={r:.4f}, α={alpha:.4f}, β={beta:.4f})")
        return kge, components

    @staticmethod
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
        >>> peak_metrics = RasUsgsMetrics.calculate_peak_error(observed, modeled)
        >>> print(f"Peak error: {peak_metrics['peak_error_pct']:.1f}%")
        Peak error: -1.7%

        >>> # With time index
        >>> times = pd.date_range('2024-01-01', periods=5, freq='h')
        >>> peak_metrics = RasUsgsMetrics.calculate_peak_error(observed, modeled, time_index=times)
        >>> print(f"Timing error: {peak_metrics['peak_timing_error']}")
        """
        # Convert to numpy arrays if needed
        if isinstance(observed, pd.Series):
            observed = observed.values
        if isinstance(modeled, pd.Series):
            modeled = modeled.values
        observed = np.asarray(observed, dtype=float)
        modeled = np.asarray(modeled, dtype=float)

        # Guard against all-NaN arrays
        if np.all(np.isnan(observed)) or np.all(np.isnan(modeled)):
            logger.warning("All-NaN array in peak error calculation")
            return {'peak_obs': np.nan, 'peak_mod': np.nan, 'peak_error_pct': np.nan}

        # Find peak values (ignoring NaN)
        peak_obs = np.nanmax(observed)
        peak_mod = np.nanmax(modeled)

        # Calculate percentage error (guard against zero observed peak)
        if peak_obs == 0:
            logger.warning("Peak observed value is zero - percentage error undefined")
            peak_error_pct = np.nan
        else:
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

    @staticmethod
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
        >>> vol_metrics = RasUsgsMetrics.calculate_volume_error(observed, modeled, dt_hours=1.0)
        >>> print(f"Volume error: {vol_metrics['vol_error_pct']:.1f}%")
        Volume error: -1.0%
        """
        # Convert to numpy arrays if needed
        if isinstance(observed, pd.Series):
            observed = observed.values
        if isinstance(modeled, pd.Series):
            modeled = modeled.values
        observed = np.asarray(observed, dtype=float)
        modeled = np.asarray(modeled, dtype=float)

        # Guard against all-NaN arrays
        if np.all(np.isnan(observed)) or np.all(np.isnan(modeled)):
            logger.warning("All-NaN array in volume error calculation")
            return {'vol_obs': np.nan, 'vol_mod': np.nan, 'vol_error_pct': np.nan}

        # Pairwise NaN removal (consistent with other metrics)
        valid_mask = ~(np.isnan(observed) | np.isnan(modeled))
        observed_clean = observed[valid_mask]
        modeled_clean = modeled[valid_mask]

        if len(observed_clean) == 0:
            logger.warning("No valid data points for volume error calculation")
            return {'vol_obs': np.nan, 'vol_mod': np.nan, 'vol_error_pct': np.nan}

        # Calculate volumes (rectangular integration — same method for both series)
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

    @staticmethod
    @log_call
    def classify_performance(metrics_dict: Dict[str, float]) -> str:
        """
        Classify model performance based on multiple metrics.

        Uses performance thresholds from Moriasi et al. (2007) for hydrologic models.
        Classification is based on NSE and |PBIAS| values.

        Performance Criteria (Moriasi et al., 2007, Table 4 - streamflow):
            - Very Good: NSE > 0.75 and |PBIAS| < 10%
            - Good: NSE > 0.65 and |PBIAS| < 15%
            - Satisfactory: NSE > 0.50 and |PBIAS| < 25%
            - Unsatisfactory: NSE <= 0.50 or |PBIAS| >= 25%

        Parameters
        ----------
        metrics_dict : dict
            Dictionary containing metric values. Must include:
            - 'nse': Nash-Sutcliffe Efficiency
            - 'pbias': Percent Bias (as percentage, positive=overestimation)

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
        >>> rating = RasUsgsMetrics.classify_performance(metrics)
        >>> print(rating)
        Very Good

        >>> metrics = {'nse': 0.55, 'pbias': 18.0}
        >>> rating = RasUsgsMetrics.classify_performance(metrics)
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

    # -------------------------------------------------------------------------
    # Phase 3: HMS-Parity Metrics (added v0.90.0)
    # Formulas confirmed via HEC-HMS 4.13 Java decompilation
    # -------------------------------------------------------------------------

    @staticmethod
    @log_call
    def modified_kling_gupta_efficiency(
        observed: Union[np.ndarray, pd.Series],
        modeled: Union[np.ndarray, pd.Series]
    ) -> Tuple[float, Dict[str, float]]:
        """
        Calculate Modified Kling-Gupta Efficiency (KGE') and its decomposed components.

        The Modified KGE (Kling et al., 2012) replaces the standard deviation ratio (alpha)
        from the original KGE (Gupta et al., 2009) with a coefficient of variation ratio
        (gamma), ensuring that the variability and bias components are independent.

        Formula:
            KGE' = 1 - sqrt[(r-1)^2 + (beta-1)^2 + (gamma-1)^2]

        Where:
            - r = Pearson correlation coefficient
            - beta = mu_mod / mu_obs (bias ratio, same as original KGE)
            - gamma = CV_mod / CV_obs where CV = sigma / mu (coefficient of variation)

        Parameters
        ----------
        observed : np.ndarray or pd.Series
            Observed (measured) values from USGS gauge data
        modeled : np.ndarray or pd.Series
            Modeled (predicted) values from HEC-RAS simulation

        Returns
        -------
        kge_prime : float
            Modified Kling-Gupta Efficiency value
            - KGE' = 1.0: Perfect fit
            - KGE' > -0.41: Model has skill (Knoben et al., 2019)
        components : dict
            Dictionary containing decomposed components:
            - 'r': Pearson correlation coefficient (timing/pattern)
            - 'beta': Bias ratio mu_mod/mu_obs (mean bias)
            - 'gamma': CV ratio CV_mod/CV_obs (variability)

        Notes
        -----
        NaN values are automatically removed from both series before calculation.
        Returns (np.nan, {}) if insufficient data or zero mean/std in observations.

        HMS Note: HEC-HMS 4.13 (k.java) uses an inverted CV definition (mu/sigma
        instead of sigma/mu), yielding gamma_HMS = 1/gamma_paper. This implementation
        follows the standard Kling et al. (2012) paper definition (CV = sigma/mu).

        References
        ----------
        Kling, H., Fuchs, M., & Paulin, M. (2012). Runoff conditions in the upper
        Danube basin under an ensemble of climate change scenarios. Journal of
        Hydrology, 424-425, 264-277.

        Examples
        --------
        >>> observed = np.array([100, 200, 300, 250, 150])
        >>> modeled = np.array([110, 190, 295, 260, 145])
        >>> kge_prime, comp = RasUsgsMetrics.modified_kling_gupta_efficiency(observed, modeled)
        >>> print(f"KGE': {kge_prime:.3f}, gamma={comp['gamma']:.3f}")
        """
        if isinstance(observed, pd.Series):
            observed = observed.values
        if isinstance(modeled, pd.Series):
            modeled = modeled.values
        observed = np.asarray(observed, dtype=float)
        modeled = np.asarray(modeled, dtype=float)

        valid_mask = ~(np.isnan(observed) | np.isnan(modeled))
        observed = observed[valid_mask]
        modeled = modeled[valid_mask]

        if len(observed) == 0:
            logger.warning("No valid data points for Modified KGE calculation")
            return np.nan, {}

        obs_std = np.std(observed)
        obs_mean = np.mean(observed)
        mod_std = np.std(modeled)
        mod_mean = np.mean(modeled)

        if obs_std == 0 or obs_mean == 0:
            logger.warning("Modified KGE undefined: observed has zero std or mean")
            return np.nan, {}

        r = np.corrcoef(observed, modeled)[0, 1]
        beta = mod_mean / obs_mean

        # CV ratio: gamma = CV_mod / CV_obs where CV = sigma / mu
        cv_obs = obs_std / obs_mean
        cv_mod = mod_std / mod_mean if mod_mean != 0 else np.nan
        if np.isnan(cv_mod):
            logger.warning("Modified KGE: modeled mean is zero, gamma undefined")
            return np.nan, {}
        gamma = cv_mod / cv_obs

        kge_prime = 1 - np.sqrt((r - 1)**2 + (beta - 1)**2 + (gamma - 1)**2)

        components = {'r': r, 'beta': beta, 'gamma': gamma}
        logger.debug(f"Modified KGE': {kge_prime:.4f} (r={r:.4f}, beta={beta:.4f}, gamma={gamma:.4f})")
        return kge_prime, components

    @staticmethod
    @log_call
    def rmse_stdev_ratio(
        observed: Union[np.ndarray, pd.Series],
        modeled: Union[np.ndarray, pd.Series]
    ) -> float:
        """
        Calculate RMSE-observations standard deviation ratio (RSR).

        RSR standardizes RMSE by dividing by the population standard deviation of
        the observations, providing a normalized error metric.

        Formula:
            RSR = RMSE / StdDev_population(obs)

        Where RMSE = sqrt(mean((obs - mod)^2)) and StdDev uses population formula (÷N).

        Parameters
        ----------
        observed : np.ndarray or pd.Series
            Observed (measured) values from USGS gauge data
        modeled : np.ndarray or pd.Series
            Modeled (predicted) values from HEC-RAS simulation

        Returns
        -------
        float
            RSR value:
            - RSR = 0: Perfect model (RMSE = 0)
            - RSR < 0.50: Very Good (Moriasi et al., 2007)
            - RSR 0.50-0.60: Good
            - RSR 0.60-0.70: Satisfactory
            - RSR > 0.70: Unsatisfactory

        Notes
        -----
        Uses population standard deviation (ddof=0), matching HEC-HMS convention
        (confirmed via z.java decompilation). numpy.std() defaults to ddof=0.
        Returns np.nan if observations have zero variance.

        References
        ----------
        Moriasi, D. N., et al. (2007). Model evaluation guidelines for systematic
        quantification of accuracy in watershed simulations. Transactions of the
        ASABE, 50(3), 885-900.

        Examples
        --------
        >>> observed = np.array([100, 200, 300, 250, 150])
        >>> modeled = np.array([110, 190, 295, 260, 145])
        >>> rsr = RasUsgsMetrics.rmse_stdev_ratio(observed, modeled)
        >>> print(f"RSR: {rsr:.3f}")
        """
        if isinstance(observed, pd.Series):
            observed = observed.values
        if isinstance(modeled, pd.Series):
            modeled = modeled.values
        observed = np.asarray(observed, dtype=float)
        modeled = np.asarray(modeled, dtype=float)

        valid_mask = ~(np.isnan(observed) | np.isnan(modeled))
        observed = observed[valid_mask]
        modeled = modeled[valid_mask]

        if len(observed) == 0:
            logger.warning("No valid data points for RSR calculation")
            return np.nan

        obs_std = np.std(observed)  # Population std (ddof=0), matches HMS

        if obs_std == 0:
            logger.warning("RSR undefined: observed has zero standard deviation")
            return np.nan

        rmse = np.sqrt(np.mean((observed - modeled) ** 2))
        rsr = rmse / obs_std

        logger.debug(f"RSR: {rsr:.4f} (RMSE={rmse:.4f}, StdDev={obs_std:.4f})")
        return rsr

    @staticmethod
    @log_call
    def r_squared(
        observed: Union[np.ndarray, pd.Series],
        modeled: Union[np.ndarray, pd.Series]
    ) -> float:
        """
        Calculate the coefficient of determination (R-squared).

        R-squared measures the proportion of variance in observed data explained
        by the model. Computed as the square of the Pearson correlation coefficient.

        Formula:
            R^2 = r^2

        Where r = Pearson correlation coefficient between observed and modeled.

        Parameters
        ----------
        observed : np.ndarray or pd.Series
            Observed (measured) values from USGS gauge data
        modeled : np.ndarray or pd.Series
            Modeled (predicted) values from HEC-RAS simulation

        Returns
        -------
        float
            R-squared value:
            - R^2 = 1.0: Perfect linear relationship
            - R^2 = 0.0: No linear relationship
            - R^2 > 0.5: Generally acceptable for hydrologic models

        Notes
        -----
        Unlike NSE, R-squared is insensitive to systematic bias. A model with
        perfect timing but consistent over-prediction will have high R-squared
        but lower NSE. Use both metrics together for comprehensive assessment.
        Matches HEC-HMS b.java implementation.

        Examples
        --------
        >>> observed = np.array([100, 200, 300, 250, 150])
        >>> modeled = np.array([110, 190, 295, 260, 145])
        >>> r2 = RasUsgsMetrics.r_squared(observed, modeled)
        >>> print(f"R^2: {r2:.3f}")
        """
        if isinstance(observed, pd.Series):
            observed = observed.values
        if isinstance(modeled, pd.Series):
            modeled = modeled.values
        observed = np.asarray(observed, dtype=float)
        modeled = np.asarray(modeled, dtype=float)

        valid_mask = ~(np.isnan(observed) | np.isnan(modeled))
        observed = observed[valid_mask]
        modeled = modeled[valid_mask]

        if len(observed) < 2:
            logger.warning("Insufficient data points for R-squared (need at least 2)")
            return np.nan

        if np.std(observed) == 0 or np.std(modeled) == 0:
            logger.warning("R-squared undefined: zero variance in observed or modeled data")
            return np.nan

        r = np.corrcoef(observed, modeled)[0, 1]
        r2 = r ** 2

        logger.debug(f"R-squared: {r2:.4f} (r={r:.4f})")
        return r2

    @staticmethod
    @log_call
    def log_nash_sutcliffe_efficiency(
        observed: Union[np.ndarray, pd.Series],
        modeled: Union[np.ndarray, pd.Series],
        offset: float = 0.0
    ) -> float:
        """
        Calculate Nash-Sutcliffe Efficiency on log-transformed data (logNSE).

        LogNSE applies log10 transformation before computing NSE, which emphasizes
        fit during low-flow periods where absolute errors are small but relative
        errors are important.

        Formula:
            logNSE = 1 - [sum(log10(obs) - log10(mod))^2 / sum(log10(obs) - mean(log10(obs)))^2]

        Parameters
        ----------
        observed : np.ndarray or pd.Series
            Observed (measured) values from USGS gauge data
        modeled : np.ndarray or pd.Series
            Modeled (predicted) values from HEC-RAS simulation
        offset : float, optional
            Offset added to both series before log transform to handle zeros.
            Default is 0.0 (zeros and negatives are excluded). Set to a small
            value (e.g., 0.01) to include zero-flow observations.

        Returns
        -------
        float
            Log-transformed NSE value (same interpretation as NSE):
            - logNSE = 1.0: Perfect fit in log space
            - logNSE > 0.5: Satisfactory low-flow performance
            - logNSE < 0.0: Poor low-flow prediction

        Notes
        -----
        Values <= 0 (after offset) are excluded from computation since log10 is
        undefined for non-positive values. A warning is issued if any values are
        excluded.

        HEC-HMS uses a different formulation (b_0.java): RMS of log errors rather
        than NSE on log-transformed data. This implementation follows the standard
        hydrological convention of applying NSE to log10-transformed values.

        Examples
        --------
        >>> observed = np.array([100, 200, 300, 250, 150])
        >>> modeled = np.array([110, 190, 295, 260, 145])
        >>> log_nse = RasUsgsMetrics.log_nash_sutcliffe_efficiency(observed, modeled)
        >>> print(f"logNSE: {log_nse:.3f}")
        """
        if isinstance(observed, pd.Series):
            observed = observed.values
        if isinstance(modeled, pd.Series):
            modeled = modeled.values
        observed = np.asarray(observed, dtype=float)
        modeled = np.asarray(modeled, dtype=float)

        valid_mask = ~(np.isnan(observed) | np.isnan(modeled))
        observed = observed[valid_mask]
        modeled = modeled[valid_mask]

        if len(observed) == 0:
            logger.warning("No valid data points for logNSE calculation")
            return np.nan

        # Apply offset and filter non-positive values
        obs_offset = observed + offset
        mod_offset = modeled + offset
        positive_mask = (obs_offset > 0) & (mod_offset > 0)

        n_excluded = np.sum(~positive_mask)
        if n_excluded > 0:
            logger.warning(f"logNSE: Excluded {n_excluded} non-positive values from calculation")

        obs_pos = obs_offset[positive_mask]
        mod_pos = mod_offset[positive_mask]

        if len(obs_pos) < 2:
            logger.warning("Insufficient positive values for logNSE calculation")
            return np.nan

        log_obs = np.log10(obs_pos)
        log_mod = np.log10(mod_pos)

        log_obs_mean = np.mean(log_obs)
        numerator = np.sum((log_obs - log_mod) ** 2)
        denominator = np.sum((log_obs - log_obs_mean) ** 2)

        if denominator == 0:
            logger.warning("Zero variance in log-transformed observations")
            return np.nan

        log_nse = 1 - (numerator / denominator)
        logger.debug(f"logNSE: {log_nse:.4f} (using {len(obs_pos)} positive values)")
        return log_nse

    @staticmethod
    @log_call
    def normalized_nash_sutcliffe(
        observed: Union[np.ndarray, pd.Series],
        modeled: Union[np.ndarray, pd.Series]
    ) -> float:
        """
        Calculate Normalized Nash-Sutcliffe Efficiency (NNSE).

        NNSE maps the NSE from its original range (-inf, 1] to the bounded
        range (0, 1], making it more interpretable and suitable for optimization.

        Formula:
            NNSE = 1 / (2 - NSE)

        Parameters
        ----------
        observed : np.ndarray or pd.Series
            Observed (measured) values from USGS gauge data
        modeled : np.ndarray or pd.Series
            Modeled (predicted) values from HEC-RAS simulation

        Returns
        -------
        float
            Normalized NSE value:
            - NNSE = 1.0: Perfect fit (NSE = 1.0)
            - NNSE = 0.5: Mean predictor (NSE = 0.0)
            - NNSE approaches 0: Very poor performance (NSE -> -inf)

        Notes
        -----
        Matches HEC-HMS m.java implementation. The normalization is monotonically
        related to NSE, so rankings are preserved.

        References
        ----------
        Nossent, J., & Bauwens, W. (2012). Application of a normalized Nash-Sutcliffe
        efficiency to improve the accuracy of the Sobol' sensitivity analysis of a
        hydrological model. EGU General Assembly 2012.

        Examples
        --------
        >>> observed = np.array([100, 200, 300, 250, 150])
        >>> modeled = np.array([110, 190, 295, 260, 145])
        >>> nnse = RasUsgsMetrics.normalized_nash_sutcliffe(observed, modeled)
        >>> print(f"NNSE: {nnse:.3f}")
        """
        nse = RasUsgsMetrics.nash_sutcliffe_efficiency(observed, modeled)

        if np.isnan(nse):
            return np.nan

        nnse = 1.0 / (2.0 - nse)
        logger.debug(f"NNSE: {nnse:.4f} (from NSE={nse:.4f})")
        return nnse

    @staticmethod
    @log_call
    def peak_weighted_rmse(
        observed: Union[np.ndarray, pd.Series],
        modeled: Union[np.ndarray, pd.Series]
    ) -> float:
        """
        Calculate Peak-Weighted Root Mean Square Error (PWRMSE).

        PWRMSE applies observation-based weights that amplify errors during
        high-flow periods, making it more sensitive to peak flow accuracy
        than standard RMSE.

        Formula:
            PWRMSE = sqrt(1/N * sum((sim - obs)^2 * w_i))

        Where:
            w_i = (obs_i + mean(obs)) / (2 * mean(obs))

        The weight equals 1.0 at the mean flow, >1.0 above mean (amplifying
        peak errors), and <1.0 below mean (reducing low-flow influence).

        Parameters
        ----------
        observed : np.ndarray or pd.Series
            Observed (measured) values from USGS gauge data
        modeled : np.ndarray or pd.Series
            Modeled (predicted) values from HEC-RAS simulation

        Returns
        -------
        float
            Peak-weighted RMSE value (same units as input data).
            Lower is better; 0 = perfect fit.

        Notes
        -----
        Matches HEC-HMS v.java implementation. Returns np.nan if observations
        have zero mean (weight denominator would be zero).

        Examples
        --------
        >>> observed = np.array([100, 200, 300, 250, 150])
        >>> modeled = np.array([110, 190, 295, 260, 145])
        >>> pw_rmse = RasUsgsMetrics.peak_weighted_rmse(observed, modeled)
        >>> print(f"PWRMSE: {pw_rmse:.2f}")
        """
        if isinstance(observed, pd.Series):
            observed = observed.values
        if isinstance(modeled, pd.Series):
            modeled = modeled.values
        observed = np.asarray(observed, dtype=float)
        modeled = np.asarray(modeled, dtype=float)

        valid_mask = ~(np.isnan(observed) | np.isnan(modeled))
        observed = observed[valid_mask]
        modeled = modeled[valid_mask]

        if len(observed) == 0:
            logger.warning("No valid data points for PWRMSE calculation")
            return np.nan

        obs_mean = np.mean(observed)
        if obs_mean == 0:
            logger.warning("PWRMSE undefined: observed mean is zero")
            return np.nan

        weights = (observed + obs_mean) / (2.0 * obs_mean)
        weighted_sq_errors = (modeled - observed) ** 2 * weights
        pwrmse = np.sqrt(np.mean(weighted_sq_errors))

        logger.debug(f"PWRMSE: {pwrmse:.4f}")
        return pwrmse

    @staticmethod
    @log_call
    def index_of_agreement(
        observed: Union[np.ndarray, pd.Series],
        modeled: Union[np.ndarray, pd.Series]
    ) -> float:
        """
        Calculate Willmott Index of Agreement (d).

        The Index of Agreement measures the degree to which modeled values
        approach observed values. Unlike R-squared, it is sensitive to
        differences in means and variances.

        Formula:
            d = 1 - [sum(sim - obs)^2 / sum(|sim - mean(obs)| + |obs - mean(obs)|)^2]

        Parameters
        ----------
        observed : np.ndarray or pd.Series
            Observed (measured) values from USGS gauge data
        modeled : np.ndarray or pd.Series
            Modeled (predicted) values from HEC-RAS simulation

        Returns
        -------
        float
            Index of Agreement value:
            - d = 1.0: Perfect agreement
            - d = 0.0: No agreement
            Always in range [0, 1].

        Notes
        -----
        Matches HEC-HMS f.java implementation (Willmott 1981). The denominator
        is the potential error, representing the largest possible squared difference
        between model and observations.

        References
        ----------
        Willmott, C. J. (1981). On the validation of models. Physical Geography,
        2(2), 184-194.

        Examples
        --------
        >>> observed = np.array([100, 200, 300, 250, 150])
        >>> modeled = np.array([110, 190, 295, 260, 145])
        >>> d = RasUsgsMetrics.index_of_agreement(observed, modeled)
        >>> print(f"d: {d:.3f}")
        """
        if isinstance(observed, pd.Series):
            observed = observed.values
        if isinstance(modeled, pd.Series):
            modeled = modeled.values
        observed = np.asarray(observed, dtype=float)
        modeled = np.asarray(modeled, dtype=float)

        valid_mask = ~(np.isnan(observed) | np.isnan(modeled))
        observed = observed[valid_mask]
        modeled = modeled[valid_mask]

        if len(observed) == 0:
            logger.warning("No valid data points for Index of Agreement calculation")
            return np.nan

        obs_mean = np.mean(observed)

        numerator = np.sum((modeled - observed) ** 2)
        denominator = np.sum((np.abs(modeled - obs_mean) + np.abs(observed - obs_mean)) ** 2)

        if denominator == 0:
            logger.warning("Index of Agreement: zero potential error (constant values)")
            return np.nan

        d = 1.0 - (numerator / denominator)
        logger.debug(f"Index of Agreement: {d:.4f}")
        return d

    @staticmethod
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
            - 'kge_modified': Modified KGE (Kling 2012, CV ratio)
            - 'kge_mod_r': Modified KGE correlation component
            - 'kge_mod_beta': Modified KGE bias component
            - 'kge_mod_gamma': Modified KGE variability component (CV ratio)
            - 'rsr': RMSE-observations standard deviation ratio
            - 'r_squared': Coefficient of determination (R²)
            - 'log_nse': Log-transformed Nash-Sutcliffe Efficiency
            - 'nnse': Normalized NSE mapped to (0, 1]
            - 'pwrmse': Peak-Weighted RMSE
            - 'index_of_agreement': Willmott Index of Agreement
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
        >>> metrics = RasUsgsMetrics.calculate_all_metrics(observed, modeled)
        >>> print(f"Performance: {metrics['performance_rating']}")
        >>> print(f"NSE: {metrics['nse']:.3f}, KGE: {metrics['kge']:.3f}")

        >>> # With time index for timing metrics
        >>> times = pd.date_range('2024-01-01', periods=5, freq='h')
        >>> metrics = RasUsgsMetrics.calculate_all_metrics(observed, modeled, time_index=times, dt_hours=1.0)
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
        obs_array = np.asarray(obs_array, dtype=float)
        mod_array = np.asarray(mod_array, dtype=float)

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
        metrics['nse'] = RasUsgsMetrics.nash_sutcliffe_efficiency(obs_clean, mod_clean)

        kge, kge_components = RasUsgsMetrics.kling_gupta_efficiency(obs_clean, mod_clean)
        metrics['kge'] = kge
        metrics['kge_r'] = kge_components.get('r', np.nan)
        metrics['kge_alpha'] = kge_components.get('alpha', np.nan)
        metrics['kge_beta'] = kge_components.get('beta', np.nan)

        # Use existing RasUtils functions for RMSE and PBIAS
        # Note: RasUtils.calculate_rmse returns normalized by default
        metrics['rmse'] = RasUtils.calculate_rmse(obs_clean, mod_clean, normalized=False)
        # PBIAS convention: 100 × Σ(sim - obs) / Σ(obs)
        # Positive = overestimation, Negative = underestimation (matches HMS convention)
        metrics['pbias'] = RasUtils.calculate_percent_bias(obs_clean, mod_clean, as_percentage=True)

        # Calculate correlation
        metrics['correlation'] = np.corrcoef(obs_clean, mod_clean)[0, 1]

        # HMS-parity metrics (Phase 3)
        kge_mod, kge_mod_components = RasUsgsMetrics.modified_kling_gupta_efficiency(obs_clean, mod_clean)
        metrics['kge_modified'] = kge_mod
        metrics['kge_mod_r'] = kge_mod_components.get('r', np.nan)
        metrics['kge_mod_beta'] = kge_mod_components.get('beta', np.nan)
        metrics['kge_mod_gamma'] = kge_mod_components.get('gamma', np.nan)

        metrics['rsr'] = RasUsgsMetrics.rmse_stdev_ratio(obs_clean, mod_clean)
        metrics['r_squared'] = RasUsgsMetrics.r_squared(obs_clean, mod_clean)
        metrics['log_nse'] = RasUsgsMetrics.log_nash_sutcliffe_efficiency(obs_clean, mod_clean)
        metrics['nnse'] = RasUsgsMetrics.normalized_nash_sutcliffe(obs_clean, mod_clean)
        metrics['pwrmse'] = RasUsgsMetrics.peak_weighted_rmse(obs_clean, mod_clean)
        metrics['index_of_agreement'] = RasUsgsMetrics.index_of_agreement(obs_clean, mod_clean)

        # Peak analysis - filter time_index with same valid_mask to keep alignment
        filtered_time_index = time_index[valid_mask] if time_index is not None else None
        peak_metrics = RasUsgsMetrics.calculate_peak_error(obs_clean, mod_clean, time_index=filtered_time_index)
        metrics.update(peak_metrics)

        # Volume analysis
        volume_metrics = RasUsgsMetrics.calculate_volume_error(obs_clean, mod_clean, dt_hours=dt_hours)
        metrics.update(volume_metrics)

        # Performance classification
        metrics['performance_rating'] = RasUsgsMetrics.classify_performance(metrics)

        logger.info(
            f"Calculated all metrics for {len(obs_clean)} points. "
            f"Performance: {metrics['performance_rating']} "
            f"(NSE={metrics['nse']:.3f}, KGE={metrics['kge']:.3f})"
        )

        return metrics


# Backward-compatible module-level aliases
nash_sutcliffe_efficiency = RasUsgsMetrics.nash_sutcliffe_efficiency
kling_gupta_efficiency = RasUsgsMetrics.kling_gupta_efficiency
calculate_peak_error = RasUsgsMetrics.calculate_peak_error
calculate_volume_error = RasUsgsMetrics.calculate_volume_error
classify_performance = RasUsgsMetrics.classify_performance
calculate_all_metrics = RasUsgsMetrics.calculate_all_metrics

# Phase 3: HMS-parity metric aliases
modified_kling_gupta_efficiency = RasUsgsMetrics.modified_kling_gupta_efficiency
rmse_stdev_ratio = RasUsgsMetrics.rmse_stdev_ratio
r_squared = RasUsgsMetrics.r_squared
log_nash_sutcliffe_efficiency = RasUsgsMetrics.log_nash_sutcliffe_efficiency
normalized_nash_sutcliffe = RasUsgsMetrics.normalized_nash_sutcliffe
peak_weighted_rmse = RasUsgsMetrics.peak_weighted_rmse
index_of_agreement = RasUsgsMetrics.index_of_agreement
