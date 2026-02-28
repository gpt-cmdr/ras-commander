"""
USGS Visualization Module

Provides comparison plot functions for USGS gauge data vs HEC-RAS model results.

This module uses lazy loading for matplotlib to reduce import overhead for users
who don't use plotting functionality.

Classes:
- RasUsgsVisualization - Static class with all visualization methods

Methods:
- plot_timeseries_comparison() - Main comparison plot with observed and modeled hydrographs
- plot_scatter_comparison() - Scatter plot of observed vs modeled values
- plot_residuals() - Residual analysis plots (4-panel diagnostic)
- plot_hydrograph() - Simple single time series plot
"""

import pandas as pd
from typing import Optional, Dict, Tuple, TYPE_CHECKING
from pathlib import Path
from ..LoggingConfig import get_logger
from ..Decorators import log_call

logger = get_logger(__name__)

# Type hints only - matplotlib not imported at runtime unless used
if TYPE_CHECKING:
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure


class RasUsgsVisualization:
    """
    Static class providing publication-quality comparison plots for model validation.

    All methods are static - call directly without instantiation:
        fig = RasUsgsVisualization.plot_timeseries_comparison(aligned_data, metrics=metrics)

    Uses lazy imports for matplotlib to reduce import overhead.
    """

    @staticmethod
    @log_call
    def plot_timeseries_comparison(
        aligned_data: pd.DataFrame,
        metrics: Optional[Dict[str, float]] = None,
        title: Optional[str] = None,
        save_path: Optional[Path] = None,
        units: str = 'cfs'
    ) -> 'Figure':
        """
        Create time series comparison plot of observed vs modeled hydrographs.

        Shows observed (blue solid line) and modeled (red dashed line) time series
        with optional metrics annotation box.

        Parameters
        ----------
        aligned_data : pd.DataFrame
            Aligned time series data with columns:
            - 'datetime' : datetime64[ns] - timestamps
            - 'observed' : float - observed values (USGS)
            - 'modeled' : float - modeled values (HEC-RAS)
        metrics : dict, optional
            Dictionary of validation metrics to display in annotation box.
            Expected keys: 'nse', 'kge', 'pbias', 'rmse'
        title : str, optional
            Plot title. If None, no title is set.
        save_path : Path, optional
            Path to save figure. If None, figure is not saved.
        units : str, optional
            Units label for y-axis and metrics annotation. Default is 'cfs'.

        Returns
        -------
        matplotlib.figure.Figure
            Figure object for further customization

        Examples
        --------
        >>> import pandas as pd
        >>> from datetime import datetime, timedelta
        >>> from ras_commander.usgs.visualization import RasUsgsVisualization
        >>>
        >>> # Create sample aligned data
        >>> dates = pd.date_range(start='2024-06-15', periods=100, freq='1H')
        >>> aligned = pd.DataFrame({
        ...     'datetime': dates,
        ...     'observed': np.random.randn(100).cumsum() + 1000,
        ...     'modeled': np.random.randn(100).cumsum() + 1000
        ... })
        >>>
        >>> # Create metrics dictionary
        >>> metrics = {
        ...     'nse': 0.823,
        ...     'kge': 0.798,
        ...     'pbias': -4.2,
        ...     'rmse': 245.3
        ... }
        >>>
        >>> # Generate plot
        >>> fig = RasUsgsVisualization.plot_timeseries_comparison(
        ...     aligned,
        ...     metrics=metrics,
        ...     title='USGS-01646500 Flow Comparison',
        ...     units='cfs'
        ... )
        >>> plt.show()

        Notes
        -----
        - Uses blue solid line for observed data (USGS standard)
        - Uses red dashed line for modeled data (HEC-RAS)
        - Metrics box positioned in upper left corner
        - Saved figures use dpi=150 for print quality
        """
        # Lazy import
        import matplotlib.pyplot as plt

        # Create figure and axis
        fig, ax = plt.subplots(figsize=(12, 6))

        # Plot time series
        ax.plot(
            aligned_data['datetime'],
            aligned_data['observed'],
            'b-',
            label='Observed (USGS)',
            linewidth=1.5
        )
        ax.plot(
            aligned_data['datetime'],
            aligned_data['modeled'],
            'r--',
            label='Modeled (HEC-RAS)',
            linewidth=1.5
        )

        # Labels and legend
        ax.set_xlabel('Date', fontsize=11)
        ax.set_ylabel(f'Flow ({units})', fontsize=11)
        ax.legend(loc='upper right', fontsize=10)
        ax.grid(True, alpha=0.3)

        # Add metrics annotation if provided
        if metrics:
            metrics_text = (
                f"NSE = {metrics.get('nse', float('nan')):.3f}\n"
                f"KGE = {metrics.get('kge', float('nan')):.3f}\n"
                f"PBIAS = {metrics.get('pbias', float('nan')):.1f}%\n"
                f"RMSE = {metrics.get('rmse', float('nan')):.1f} {units}"
            )
            ax.text(
                0.02, 0.98,
                metrics_text,
                transform=ax.transAxes,
                verticalalignment='top',
                fontfamily='monospace',
                fontsize=9,
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8, edgecolor='gray')
            )

        # Add title if provided
        if title:
            ax.set_title(title, fontsize=13, fontweight='bold')

        # Tight layout
        fig.tight_layout()

        # Save if path provided
        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(save_path, dpi=150, bbox_inches='tight')

        return fig

    @staticmethod
    @log_call
    def plot_scatter_comparison(
        aligned_data: pd.DataFrame,
        metrics: Optional[Dict[str, float]] = None,
        save_path: Optional[Path] = None,
        units: str = 'cfs'
    ) -> 'Figure':
        """
        Create scatter plot of observed vs modeled values.

        Shows one-to-one comparison with 1:1 reference line and optional R² annotation.

        Parameters
        ----------
        aligned_data : pd.DataFrame
            Aligned time series data with columns:
            - 'datetime' : datetime64[ns] - timestamps
            - 'observed' : float - observed values (USGS)
            - 'modeled' : float - modeled values (HEC-RAS)
        metrics : dict, optional
            Dictionary of validation metrics. If provided and contains 'correlation',
            R² will be displayed. Can also display 'nse' if present.
        save_path : Path, optional
            Path to save figure. If None, figure is not saved.
        units : str, optional
            Units label for axis labels. Default is 'cfs'.

        Returns
        -------
        matplotlib.figure.Figure
            Figure object for further customization

        Examples
        --------
        >>> from ras_commander.usgs.visualization import RasUsgsVisualization
        >>>
        >>> # Generate scatter plot with R² annotation
        >>> metrics = {'correlation': 0.912, 'nse': 0.823}
        >>> fig = RasUsgsVisualization.plot_scatter_comparison(aligned, metrics=metrics)
        >>> plt.show()

        Notes
        -----
        - Equal aspect ratio ensures visual accuracy
        - Black dashed line shows perfect 1:1 agreement
        - Points plotted with 50% transparency to show density
        - Saved figures use dpi=150 for print quality
        """
        # Lazy import
        import matplotlib.pyplot as plt

        # Create figure with square aspect
        fig, ax = plt.subplots(figsize=(8, 8))

        # Scatter plot
        ax.scatter(
            aligned_data['observed'],
            aligned_data['modeled'],
            alpha=0.5,
            s=20,
            color='steelblue',
            edgecolors='none'
        )

        # 1:1 line (use dropna to avoid NaN in range calculation)
        valid = aligned_data[['observed', 'modeled']].dropna()
        max_val = max(valid['observed'].max(), valid['modeled'].max())
        min_val = min(valid['observed'].min(), valid['modeled'].min())
        ax.plot(
            [min_val, max_val],
            [min_val, max_val],
            'k--',
            label='1:1 Line',
            linewidth=1.5
        )

        # Labels and styling
        ax.set_xlabel(f'Observed Flow ({units})', fontsize=11)
        ax.set_ylabel(f'Modeled Flow ({units})', fontsize=11)
        ax.set_aspect('equal', adjustable='box')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper left', fontsize=10)

        # Add R² annotation if metrics provided
        if metrics:
            annotation_text = ""
            if 'correlation' in metrics:
                r_squared = metrics['correlation'] ** 2
                annotation_text += f"R² = {r_squared:.3f}\n"
            if 'nse' in metrics:
                annotation_text += f"NSE = {metrics['nse']:.3f}"

            if annotation_text:
                ax.text(
                    0.05, 0.95,
                    annotation_text.strip(),
                    transform=ax.transAxes,
                    verticalalignment='top',
                    fontfamily='monospace',
                    fontsize=10,
                    bbox=dict(boxstyle='round', facecolor='white', alpha=0.8, edgecolor='gray')
                )

        # Tight layout
        fig.tight_layout()

        # Save if path provided
        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(save_path, dpi=150, bbox_inches='tight')

        return fig

    @staticmethod
    @log_call
    def plot_residuals(
        aligned_data: pd.DataFrame,
        save_path: Optional[Path] = None,
        units: str = 'cfs'
    ) -> 'Figure':
        """
        Create residual analysis plots (4-panel diagnostic).

        Generates comprehensive residual diagnostics:
        1. Residuals over time
        2. Residual histogram
        3. Residuals vs modeled values
        4. Q-Q plot (normal probability plot)

        Parameters
        ----------
        aligned_data : pd.DataFrame
            Aligned time series data with columns:
            - 'datetime' : datetime64[ns] - timestamps
            - 'observed' : float - observed values (USGS)
            - 'modeled' : float - modeled values (HEC-RAS)
        save_path : Path, optional
            Path to save figure. If None, figure is not saved.
        units : str, optional
            Units label for residual axis labels. Default is 'cfs'.

        Returns
        -------
        matplotlib.figure.Figure
            Figure object for further customization

        Examples
        --------
        >>> from ras_commander.usgs.visualization import RasUsgsVisualization
        >>>
        >>> # Generate residual diagnostics
        >>> fig = RasUsgsVisualization.plot_residuals(aligned, units='ft')
        >>> plt.show()

        Notes
        -----
        - Residuals calculated as: modeled - observed
        - Zero line shown in red dashed for reference
        - Q-Q plot tests normality assumption
        - Saved figures use dpi=150 for print quality
        """
        # Lazy imports
        import matplotlib.pyplot as plt
        try:
            from scipy import stats
            has_scipy = True
        except ImportError:
            has_scipy = False

        # Calculate residuals (drop NaN pairs)
        valid = aligned_data[['observed', 'modeled']].dropna()
        residuals = valid['modeled'] - valid['observed']
        residual_times = aligned_data.loc[valid.index, 'datetime']

        # Create 2x2 subplot figure
        fig, axes = plt.subplots(2, 2, figsize=(12, 10))

        # 1. Residuals over time (top left)
        axes[0, 0].plot(residual_times, residuals, 'b-', linewidth=1, alpha=0.7)
        axes[0, 0].axhline(y=0, color='r', linestyle='--', linewidth=1.5)
        axes[0, 0].set_xlabel('Date', fontsize=10)
        axes[0, 0].set_ylabel(f'Residual ({units})', fontsize=10)
        axes[0, 0].set_title('Residuals Over Time', fontsize=11, fontweight='bold')
        axes[0, 0].grid(True, alpha=0.3)

        # 2. Histogram (top right)
        axes[0, 1].hist(residuals, bins=30, edgecolor='black', alpha=0.7, color='steelblue')
        axes[0, 1].axvline(x=0, color='r', linestyle='--', linewidth=1.5)
        axes[0, 1].set_xlabel(f'Residual ({units})', fontsize=10)
        axes[0, 1].set_ylabel('Frequency', fontsize=10)
        axes[0, 1].set_title('Residual Distribution', fontsize=11, fontweight='bold')
        axes[0, 1].grid(True, alpha=0.3, axis='y')

        # 3. Residuals vs modeled (bottom left)
        axes[1, 0].scatter(
            valid['modeled'],
            residuals,
            alpha=0.5,
            s=20,
            color='steelblue',
            edgecolors='none'
        )
        axes[1, 0].axhline(y=0, color='r', linestyle='--', linewidth=1.5)
        axes[1, 0].set_xlabel(f'Modeled Flow ({units})', fontsize=10)
        axes[1, 0].set_ylabel(f'Residual ({units})', fontsize=10)
        axes[1, 0].set_title('Residuals vs Modeled', fontsize=11, fontweight='bold')
        axes[1, 0].grid(True, alpha=0.3)

        # 4. Q-Q plot (bottom right) - requires scipy
        if has_scipy:
            stats.probplot(residuals, dist="norm", plot=axes[1, 1])
            axes[1, 1].set_title('Q-Q Plot (Normal)', fontsize=11, fontweight='bold')
        else:
            # Fallback: sorted residuals vs expected normal quantiles
            import numpy as np
            n = len(residuals)
            sorted_res = np.sort(residuals)
            expected = np.linspace(0.5/n, 1 - 0.5/n, n)
            from numpy import erfinv
            theoretical = np.sqrt(2) * erfinv(2 * expected - 1)
            axes[1, 1].scatter(theoretical, sorted_res, s=15, alpha=0.6, color='steelblue')
            axes[1, 1].plot([-3, 3], [-3 * np.std(residuals) + np.mean(residuals),
                             3 * np.std(residuals) + np.mean(residuals)], 'r--')
            axes[1, 1].set_xlabel('Theoretical Quantiles')
            axes[1, 1].set_ylabel('Sample Quantiles')
            axes[1, 1].set_title('Q-Q Plot (Normal) [scipy not installed]', fontsize=11, fontweight='bold')
        axes[1, 1].grid(True, alpha=0.3)

        # Overall title
        fig.suptitle('Residual Analysis', fontsize=14, fontweight='bold', y=0.995)

        # Tight layout with space for suptitle
        fig.tight_layout(rect=[0, 0, 1, 0.99])

        # Save if path provided
        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(save_path, dpi=150, bbox_inches='tight')

        return fig

    @staticmethod
    @log_call
    def plot_hydrograph(
        df: pd.DataFrame,
        time_column: str = 'datetime',
        value_column: str = 'value',
        title: Optional[str] = None,
        ylabel: str = 'Flow (cfs)',
        save_path: Optional[Path] = None
    ) -> 'Figure':
        """
        Create simple single time series hydrograph plot.

        General-purpose time series plotting function for single hydrographs.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame containing time series data
        time_column : str, default='datetime'
            Name of column containing datetime values
        value_column : str, default='value'
            Name of column containing flow/stage values
        title : str, optional
            Plot title. If None, no title is set.
        ylabel : str, default='Flow (cfs)'
            Y-axis label
        save_path : Path, optional
            Path to save figure. If None, figure is not saved.

        Returns
        -------
        matplotlib.figure.Figure
            Figure object for further customization

        Examples
        --------
        >>> from ras_commander.usgs.visualization import RasUsgsVisualization
        >>>
        >>> # Plot simple hydrograph
        >>> fig = RasUsgsVisualization.plot_hydrograph(
        ...     df,
        ...     time_column='datetime',
        ...     value_column='flow',
        ...     title='USGS-01646500 Observed Flow',
        ...     ylabel='Discharge (cfs)'
        ... )
        >>> plt.show()

        Notes
        -----
        - Blue solid line used for consistency with USGS standards
        - Flexible column naming for different data sources
        - Saved figures use dpi=150 for print quality
        """
        # Lazy import
        import matplotlib.pyplot as plt

        # Create figure
        fig, ax = plt.subplots(figsize=(12, 6))

        # Plot time series
        ax.plot(
            df[time_column],
            df[value_column],
            'b-',
            linewidth=1.5
        )

        # Labels and styling
        ax.set_xlabel('Date', fontsize=11)
        ax.set_ylabel(ylabel, fontsize=11)
        ax.grid(True, alpha=0.3)

        # Add title if provided
        if title:
            ax.set_title(title, fontsize=13, fontweight='bold')

        # Tight layout
        fig.tight_layout()

        # Save if path provided
        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(save_path, dpi=150, bbox_inches='tight')

        return fig

    @staticmethod
    @log_call
    def plot_flow_duration_curve(
        observed: 'pd.Series',
        modeled: Optional['pd.Series'] = None,
        title: Optional[str] = None,
        save_path: Optional[Path] = None,
        units: str = 'cfs',
        log_scale: bool = True
    ) -> 'Figure':
        """
        Create flow duration curve (exceedance probability) plot.

        Plots observed (and optionally modeled) values sorted in descending order
        against their exceedance probability. Useful for evaluating model
        performance across the full range of flow or stage conditions, including
        both high-flow (flood) and low-flow (baseflow) regimes.

        Parameters
        ----------
        observed : pd.Series or np.ndarray
            Observed values (flow or stage) from USGS gauge.
            Index values are ignored; only the data values are used.
        modeled : pd.Series or np.ndarray, optional
            Modeled values from HEC-RAS. If None, only observed curve is shown.
        title : str, optional
            Plot title. If None, uses 'Flow Duration Curve'.
        save_path : Path, optional
            Path to save figure. If None, figure is not saved.
        units : str, default='cfs'
            Units label for y-axis (e.g. 'cfs', 'm³/s', 'ft').
        log_scale : bool, default=True
            If True, uses logarithmic y-axis scale. Recommended for flow;
            set False for stage.

        Returns
        -------
        matplotlib.figure.Figure
            Figure object for further customization

        Notes
        -----
        Exceedance probability is computed as rank / (n + 1) × 100%, using the
        Weibull plotting position formula. NaN values are dropped before plotting.

        Examples
        --------
        >>> fig = RasUsgsVisualization.plot_flow_duration_curve(
        ...     observed=usgs_flow,
        ...     modeled=ras_flow,
        ...     title='Potomac River at Little Falls — Flow Duration Curve',
        ...     units='cfs'
        ... )
        >>> plt.show()
        """
        # Lazy import
        import matplotlib.pyplot as plt
        import numpy as np

        fig, ax = plt.subplots(figsize=(10, 7))

        def _exceedance_curve(values):
            """Return (exceedance_pct, sorted_values) dropping NaNs."""
            arr = np.asarray(values, dtype=float)
            arr = arr[~np.isnan(arr)]
            arr_sorted = np.sort(arr)[::-1]  # descending
            n = len(arr_sorted)
            rank = np.arange(1, n + 1)
            exceedance = rank / (n + 1) * 100.0  # Weibull plotting position
            return exceedance, arr_sorted

        exc_obs, vals_obs = _exceedance_curve(observed)
        ax.plot(exc_obs, vals_obs, 'b-', linewidth=1.8, label='Observed (USGS)', zorder=3)

        if modeled is not None:
            exc_mod, vals_mod = _exceedance_curve(modeled)
            ax.plot(exc_mod, vals_mod, 'r--', linewidth=1.8, label='Modeled (HEC-RAS)', zorder=2)

        if log_scale:
            ax.set_yscale('log')

        ax.set_xlabel('Exceedance Probability (%)', fontsize=11)
        ax.set_ylabel(f'{units.upper()} ({"log scale" if log_scale else "linear"})', fontsize=11)
        ax.set_xlim(0, 100)
        ax.grid(True, which='both', alpha=0.3)
        ax.legend(fontsize=10)

        plot_title = title if title else 'Flow Duration Curve'
        ax.set_title(plot_title, fontsize=13, fontweight='bold')

        fig.tight_layout()

        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(save_path, dpi=150, bbox_inches='tight')

        return fig

    @staticmethod
    @log_call
    def plot_cumulative_comparison(
        aligned_data: 'pd.DataFrame',
        title: Optional[str] = None,
        save_path: Optional[Path] = None,
        units: str = 'cfs'
    ) -> 'Figure':
        """
        Create cumulative flow (or stage) comparison plot.

        Shows the cumulative sum of observed and modeled values over time.
        Useful for identifying systematic volume bias — if the cumulative
        modeled curve consistently runs above (or below) observed, the model
        over- (or under-) estimates total volume.

        Parameters
        ----------
        aligned_data : pd.DataFrame
            Aligned time series data with columns:
            - 'datetime' : datetime64[ns] — timestamps
            - 'observed' : float — observed values (USGS)
            - 'modeled'  : float — modeled values (HEC-RAS)
        title : str, optional
            Plot title. If None, uses 'Cumulative Flow Comparison'.
        save_path : Path, optional
            Path to save figure. If None, figure is not saved.
        units : str, default='cfs'
            Units label for y-axis annotation (e.g. 'cfs', 'm³/s', 'ft').

        Returns
        -------
        matplotlib.figure.Figure
            Figure object for further customization

        Notes
        -----
        Rows containing NaN in either 'observed' or 'modeled' are excluded
        from the cumulative sum (pairwise removal). The cumulative error panel
        shows modeled − observed cumulative, so positive values indicate
        the model is accumulating more volume than observed.

        Examples
        --------
        >>> fig = RasUsgsVisualization.plot_cumulative_comparison(
        ...     aligned_data=df,
        ...     title='Potomac River at Little Falls — Cumulative Flow',
        ...     units='cfs'
        ... )
        >>> plt.show()
        """
        # Lazy import
        import matplotlib.pyplot as plt
        import numpy as np

        # Validate required columns
        required = {'datetime', 'observed', 'modeled'}
        missing = required - set(aligned_data.columns)
        if missing:
            raise ValueError(f"aligned_data missing required columns: {missing}")

        # Pairwise NaN removal
        mask = ~(aligned_data['observed'].isna() | aligned_data['modeled'].isna())
        df_clean = aligned_data[mask].reset_index(drop=True)

        obs_cum = np.cumsum(df_clean['observed'].values)
        mod_cum = np.cumsum(df_clean['modeled'].values)
        cum_error = mod_cum - obs_cum  # positive = model accumulating more

        dates = df_clean['datetime']

        fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

        # Panel 1: Cumulative comparison
        axes[0].plot(dates, obs_cum, 'b-', linewidth=1.8, label='Observed (USGS)', zorder=3)
        axes[0].plot(dates, mod_cum, 'r--', linewidth=1.8, label='Modeled (HEC-RAS)', zorder=2)
        axes[0].set_ylabel(f'Cumulative {units.upper()}', fontsize=11)
        axes[0].legend(fontsize=10)
        axes[0].grid(True, alpha=0.3)
        axes[0].set_title(
            title if title else 'Cumulative Flow Comparison',
            fontsize=13, fontweight='bold'
        )

        # Panel 2: Cumulative error (modeled - observed)
        axes[1].fill_between(dates, cum_error, 0,
                             where=cum_error >= 0, alpha=0.4, color='red',
                             label='Over-prediction')
        axes[1].fill_between(dates, cum_error, 0,
                             where=cum_error < 0, alpha=0.4, color='blue',
                             label='Under-prediction')
        axes[1].axhline(0, color='black', linewidth=0.8, linestyle='-')
        axes[1].set_ylabel(f'Cumulative Error\n(Mod − Obs, {units.upper()})', fontsize=11)
        axes[1].set_xlabel('Date', fontsize=11)
        axes[1].legend(fontsize=10, loc='upper left')
        axes[1].grid(True, alpha=0.3)

        # Final volume error annotation
        if len(obs_cum) > 0 and obs_cum[-1] != 0:
            final_pct = (cum_error[-1] / obs_cum[-1]) * 100
            axes[1].annotate(
                f'Final volume error: {final_pct:+.1f}%',
                xy=(0.99, 0.95),
                xycoords='axes fraction',
                ha='right', va='top',
                fontsize=10,
                bbox=dict(boxstyle='round,pad=0.3', facecolor='lightyellow', alpha=0.8)
            )

        fig.tight_layout()

        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(save_path, dpi=150, bbox_inches='tight')

        return fig


# Backward-compatible module-level aliases
plot_timeseries_comparison = RasUsgsVisualization.plot_timeseries_comparison
plot_scatter_comparison = RasUsgsVisualization.plot_scatter_comparison
plot_residuals = RasUsgsVisualization.plot_residuals
plot_hydrograph = RasUsgsVisualization.plot_hydrograph

# Phase 5: New visualization aliases
plot_flow_duration_curve = RasUsgsVisualization.plot_flow_duration_curve
plot_cumulative_comparison = RasUsgsVisualization.plot_cumulative_comparison
