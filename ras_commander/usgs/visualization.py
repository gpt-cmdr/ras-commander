"""
USGS Visualization Module

Provides comparison plot functions for USGS gauge data vs HEC-RAS model results.

This module uses lazy loading for matplotlib to reduce import overhead for users
who don't use plotting functionality.

Functions:
- plot_timeseries_comparison() - Main comparison plot with observed and modeled hydrographs
- plot_scatter_comparison() - Scatter plot of observed vs modeled values
- plot_residuals() - Residual analysis plots (4-panel diagnostic)
- plot_hydrograph() - Simple single time series plot
"""

import pandas as pd
from typing import Optional, Dict, Tuple, TYPE_CHECKING
from pathlib import Path

# Type hints only - matplotlib not imported at runtime unless used
if TYPE_CHECKING:
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure


def plot_timeseries_comparison(
    aligned_data: pd.DataFrame,
    metrics: Optional[Dict[str, float]] = None,
    title: Optional[str] = None,
    save_path: Optional[Path] = None
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

    Returns
    -------
    matplotlib.figure.Figure
        Figure object for further customization

    Examples
    --------
    >>> import pandas as pd
    >>> from datetime import datetime, timedelta
    >>> from ras_commander.usgs.visualization import plot_timeseries_comparison
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
    >>> fig = plot_timeseries_comparison(
    ...     aligned,
    ...     metrics=metrics,
    ...     title='USGS-01646500 Flow Comparison'
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
    ax.set_ylabel('Flow (cfs)', fontsize=11)
    ax.legend(loc='upper right', fontsize=10)
    ax.grid(True, alpha=0.3)

    # Add metrics annotation if provided
    if metrics:
        metrics_text = (
            f"NSE = {metrics.get('nse', float('nan')):.3f}\n"
            f"KGE = {metrics.get('kge', float('nan')):.3f}\n"
            f"PBIAS = {metrics.get('pbias', float('nan')):.1f}%\n"
            f"RMSE = {metrics.get('rmse', float('nan')):.1f} cfs"
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
        fig.savefig(save_path, dpi=150, bbox_inches='tight')

    return fig


def plot_scatter_comparison(
    aligned_data: pd.DataFrame,
    metrics: Optional[Dict[str, float]] = None,
    save_path: Optional[Path] = None
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

    Returns
    -------
    matplotlib.figure.Figure
        Figure object for further customization

    Examples
    --------
    >>> from ras_commander.usgs.visualization import plot_scatter_comparison
    >>>
    >>> # Generate scatter plot with R² annotation
    >>> metrics = {'correlation': 0.912, 'nse': 0.823}
    >>> fig = plot_scatter_comparison(aligned, metrics=metrics)
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

    # 1:1 line
    max_val = max(
        aligned_data['observed'].max(),
        aligned_data['modeled'].max()
    )
    min_val = min(
        aligned_data['observed'].min(),
        aligned_data['modeled'].min()
    )
    ax.plot(
        [min_val, max_val],
        [min_val, max_val],
        'k--',
        label='1:1 Line',
        linewidth=1.5
    )

    # Labels and styling
    ax.set_xlabel('Observed Flow (cfs)', fontsize=11)
    ax.set_ylabel('Modeled Flow (cfs)', fontsize=11)
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
        fig.savefig(save_path, dpi=150, bbox_inches='tight')

    return fig


def plot_residuals(
    aligned_data: pd.DataFrame,
    save_path: Optional[Path] = None
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

    Returns
    -------
    matplotlib.figure.Figure
        Figure object for further customization

    Examples
    --------
    >>> from ras_commander.usgs.visualization import plot_residuals
    >>>
    >>> # Generate residual diagnostics
    >>> fig = plot_residuals(aligned)
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
    from scipy import stats

    # Calculate residuals
    residuals = aligned_data['modeled'] - aligned_data['observed']

    # Create 2x2 subplot figure
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))

    # 1. Residuals over time (top left)
    axes[0, 0].plot(aligned_data['datetime'], residuals, 'b-', linewidth=1, alpha=0.7)
    axes[0, 0].axhline(y=0, color='r', linestyle='--', linewidth=1.5)
    axes[0, 0].set_xlabel('Date', fontsize=10)
    axes[0, 0].set_ylabel('Residual (cfs)', fontsize=10)
    axes[0, 0].set_title('Residuals Over Time', fontsize=11, fontweight='bold')
    axes[0, 0].grid(True, alpha=0.3)

    # 2. Histogram (top right)
    axes[0, 1].hist(residuals, bins=30, edgecolor='black', alpha=0.7, color='steelblue')
    axes[0, 1].axvline(x=0, color='r', linestyle='--', linewidth=1.5)
    axes[0, 1].set_xlabel('Residual (cfs)', fontsize=10)
    axes[0, 1].set_ylabel('Frequency', fontsize=10)
    axes[0, 1].set_title('Residual Distribution', fontsize=11, fontweight='bold')
    axes[0, 1].grid(True, alpha=0.3, axis='y')

    # 3. Residuals vs modeled (bottom left)
    axes[1, 0].scatter(
        aligned_data['modeled'],
        residuals,
        alpha=0.5,
        s=20,
        color='steelblue',
        edgecolors='none'
    )
    axes[1, 0].axhline(y=0, color='r', linestyle='--', linewidth=1.5)
    axes[1, 0].set_xlabel('Modeled Flow (cfs)', fontsize=10)
    axes[1, 0].set_ylabel('Residual (cfs)', fontsize=10)
    axes[1, 0].set_title('Residuals vs Modeled', fontsize=11, fontweight='bold')
    axes[1, 0].grid(True, alpha=0.3)

    # 4. Q-Q plot (bottom right)
    stats.probplot(residuals, dist="norm", plot=axes[1, 1])
    axes[1, 1].set_title('Q-Q Plot (Normal)', fontsize=11, fontweight='bold')
    axes[1, 1].grid(True, alpha=0.3)

    # Overall title
    fig.suptitle('Residual Analysis', fontsize=14, fontweight='bold', y=0.995)

    # Tight layout with space for suptitle
    fig.tight_layout(rect=[0, 0, 1, 0.99])

    # Save if path provided
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight')

    return fig


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
    >>> from ras_commander.usgs.visualization import plot_hydrograph
    >>>
    >>> # Plot simple hydrograph
    >>> fig = plot_hydrograph(
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
        fig.savefig(save_path, dpi=150, bbox_inches='tight')

    return fig
