"""
RasHydroCompare - Hydrograph Comparison Utilities

This module provides utility functions for comparing hydrograph time series.
Useful for boundary condition matching, version validation, calibration
verification, and any workflow that needs time series comparison.

All functions are standalone and designed to work with numpy arrays.

Example Usage:
    >>> import numpy as np
    >>> from ras_commander import RasHydroCompare
    >>>
    >>> # Compare two hydrographs
    >>> ts1 = np.array([0, 100, 500, 300, 100, 0])
    >>> ts2 = np.array([0, 95, 490, 310, 105, 0])
    >>> result = RasHydroCompare.compare_hydrographs(ts1, ts2)
    >>> print(f"Correlation: {result['correlation']:.4f}")
    >>> print(f"NRMSE: {result['nrmse_pct']:.2f}%")
"""

import numpy as np
from typing import Dict, Optional

from .LoggingConfig import get_logger
from .Decorators import log_call

logger = get_logger(__name__)


class RasHydroCompare:
    """
    Hydrograph comparison utilities.

    Provides static methods for comparing time series using correlation
    and normalized root mean square error (NRMSE).

    All methods are static - no instantiation required.

    Example:
        >>> from ras_commander import RasHydroCompare
        >>> result = RasHydroCompare.compare_hydrographs(ts1, ts2)
        >>> print(result['correlation'])
    """

    @staticmethod
    @log_call
    def compare_hydrographs(
        ts1: np.ndarray,
        ts2: np.ndarray,
        truncate_to_shorter: bool = True
    ) -> Dict[str, float]:
        """
        Compare two hydrograph time series using correlation and NRMSE.

        Calculates Pearson correlation coefficient, normalized RMSE,
        peak difference, and peak ratio between two time series.

        Parameters:
            ts1 (np.ndarray): First time series (e.g., RAS boundary condition)
            ts2 (np.ndarray): Second time series (e.g., HMS DSS output)
            truncate_to_shorter (bool): If True, truncate to shorter array length.
                If False, raises ValueError for mismatched lengths. Default True.

        Returns:
            Dict[str, float]: {
                'correlation': float,   # Pearson r (-1 to 1)
                'nrmse_pct': float,     # Normalized RMSE as percentage
                'peak_diff': float,     # ts1 peak - ts2 peak
                'peak_ratio': float,    # ts1 peak / ts2 peak (0 if ts2 peak is 0)
            }

        Raises:
            ValueError: If truncate_to_shorter is False and arrays have different lengths

        Example:
            >>> ts1 = np.array([0, 100, 500, 300, 100, 0])
            >>> ts2 = np.array([0, 95, 490, 310, 105, 0])
            >>> result = RasHydroCompare.compare_hydrographs(ts1, ts2)
            >>> print(f"Correlation: {result['correlation']:.6f}")
            Correlation: 0.999847
            >>> print(f"NRMSE: {result['nrmse_pct']:.2f}%")
            NRMSE: 1.51%

        Notes:
            - Handles constant arrays (both zero, both identical)
            - Handles different lengths (truncate or raise)
            - Zero-range normalization (avoids division by zero)
            - NaN values are excluded from calculations
        """
        ts1 = np.asarray(ts1, dtype=np.float64)
        ts2 = np.asarray(ts2, dtype=np.float64)

        # Handle length mismatch
        if len(ts1) != len(ts2):
            if truncate_to_shorter:
                min_len = min(len(ts1), len(ts2))
                ts1 = ts1[:min_len]
                ts2 = ts2[:min_len]
            else:
                raise ValueError(
                    f"Time series have different lengths: {len(ts1)} vs {len(ts2)}. "
                    f"Set truncate_to_shorter=True to auto-truncate."
                )

        # Handle empty arrays
        if len(ts1) == 0:
            return {
                'correlation': 0.0,
                'nrmse_pct': 100.0,
                'peak_diff': 0.0,
                'peak_ratio': 0.0,
            }

        # Remove NaN values (paired removal)
        valid_mask = ~(np.isnan(ts1) | np.isnan(ts2))
        ts1_clean = ts1[valid_mask]
        ts2_clean = ts2[valid_mask]

        if len(ts1_clean) == 0:
            return {
                'correlation': 0.0,
                'nrmse_pct': 100.0,
                'peak_diff': 0.0,
                'peak_ratio': 0.0,
            }

        # Calculate peaks
        peak1 = float(np.max(ts1_clean))
        peak2 = float(np.max(ts2_clean))
        peak_diff = peak1 - peak2
        peak_ratio = peak1 / peak2 if peak2 != 0 else 0.0

        # Calculate correlation
        std1 = np.std(ts1_clean)
        std2 = np.std(ts2_clean)

        if std1 == 0 and std2 == 0:
            # Both constant - check if equal
            correlation = 1.0 if np.allclose(ts1_clean, ts2_clean) else 0.0
        elif std1 == 0 or std2 == 0:
            # One constant - correlation undefined, treat as no match
            correlation = 0.0
        else:
            correlation = float(np.corrcoef(ts1_clean, ts2_clean)[0, 1])

        # Calculate NRMSE
        rmse = float(np.sqrt(np.mean((ts1_clean - ts2_clean) ** 2)))
        data_range = float(np.max(ts1_clean) - np.min(ts1_clean))

        if data_range == 0:
            nrmse_pct = 0.0 if rmse == 0 else 100.0
        else:
            nrmse_pct = rmse / data_range * 100.0

        return {
            'correlation': correlation,
            'nrmse_pct': nrmse_pct,
            'peak_diff': peak_diff,
            'peak_ratio': peak_ratio,
        }

    @staticmethod
    def classify_match(
        correlation: float,
        nrmse_pct: float,
        exact_corr: float = 0.9999,
        exact_nrmse: float = 0.01,
        close_corr: float = 0.99,
        close_nrmse: float = 1.0,
        possible_corr: float = 0.95,
        possible_nrmse: float = 5.0
    ) -> str:
        """
        Classify match quality based on correlation and NRMSE thresholds.

        Parameters:
            correlation (float): Pearson correlation coefficient
            nrmse_pct (float): Normalized RMSE as percentage
            exact_corr (float): Minimum correlation for EXACT match (default 0.9999)
            exact_nrmse (float): Maximum NRMSE for EXACT match (default 0.01%)
            close_corr (float): Minimum correlation for CLOSE match (default 0.99)
            close_nrmse (float): Maximum NRMSE for CLOSE match (default 1.0%)
            possible_corr (float): Minimum correlation for POSSIBLE match (default 0.95)
            possible_nrmse (float): Maximum NRMSE for POSSIBLE match (default 5.0%)

        Returns:
            str: Match quality classification - "EXACT", "CLOSE", "POSSIBLE", or "MISMATCH"

        Example:
            >>> quality = RasHydroCompare.classify_match(0.99995, 0.005)
            >>> print(quality)
            EXACT
        """
        if correlation >= exact_corr and nrmse_pct <= exact_nrmse:
            return "EXACT"
        elif correlation >= close_corr and nrmse_pct <= close_nrmse:
            return "CLOSE"
        elif correlation >= possible_corr and nrmse_pct <= possible_nrmse:
            return "POSSIBLE"
        else:
            return "MISMATCH"
