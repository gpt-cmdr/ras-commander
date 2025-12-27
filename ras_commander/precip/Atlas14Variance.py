"""
Atlas14Variance: Spatial variance analysis for Atlas 14 precipitation.

This module provides tools to analyze spatial variability of NOAA Atlas 14
precipitation frequency estimates within HEC-RAS model domains. This is
particularly useful for determining whether uniform rainfall assumptions
are valid for rain-on-grid modeling.

Key Features:
- Calculate min/max/mean/range statistics within 2D flow areas
- Analyze variance across multiple durations and return periods
- Generate reports and visualizations
- Export to CSV for engineering review

Example:
    >>> from ras_commander.precip import Atlas14Variance
    >>>
    >>> # Analyze variance for a HEC-RAS project
    >>> results = Atlas14Variance.analyze(
    ...     geom_hdf="MyProject.g01.hdf",
    ...     durations=[6, 12, 24],
    ...     return_periods=[10, 25, 50, 100]
    ... )
    >>>
    >>> # High variance indicates spatially variable rainfall
    >>> print(results[results['range_pct'] > 10])

References:
    - Based on workflow from HEC-Commander Atlas_14_Variance notebooks
    - NOAA Atlas 14: https://hdsc.nws.noaa.gov/pfds/
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Literal

import numpy as np
import pandas as pd

try:
    import geopandas as gpd
    from shapely.geometry import box, mapping
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    gpd = None

try:
    import xarray as xr
    import rioxarray
    RIOXARRAY_AVAILABLE = True
except ImportError:
    RIOXARRAY_AVAILABLE = False
    xr = None

from ..LoggingConfig import get_logger, log_call
from .Atlas14Grid import Atlas14Grid

logger = get_logger(__name__)


class Atlas14Variance:
    """
    Analyze spatial variance of Atlas 14 precipitation frequency estimates.

    This class provides methods to:
    - Calculate precipitation variance statistics within polygons
    - Analyze variance across HEC-RAS 2D flow areas
    - Generate reports suitable for engineering review
    - Export results to CSV and generate plots

    The variance analysis helps determine if uniform rainfall assumptions
    are appropriate for a given model domain. High variance (>10%) may
    indicate that spatially distributed precipitation should be considered.

    Note:
        This class uses static methods and should not be instantiated.
    """

    # Variance denominator options for calculating range percentage
    VARIANCE_DENOMINATORS = ['min', 'max', 'mean']

    @staticmethod
    def _check_dependencies() -> None:
        """Check that required dependencies are available."""
        if not GEOPANDAS_AVAILABLE:
            raise ImportError(
                "Variance analysis requires 'geopandas'. "
                "Install with: pip install geopandas"
            )

    @staticmethod
    @log_call
    def calculate_stats(
        data: np.ndarray,
        mask: Optional[np.ndarray] = None,
        variance_denominator: Literal['min', 'max', 'mean'] = 'min'
    ) -> Dict[str, float]:
        """
        Calculate precipitation statistics for an array.

        Args:
            data: 2D array of precipitation values (in inches)
            mask: Optional boolean mask (True = include, False = exclude)
            variance_denominator: Denominator for range percentage calculation:
                - 'min': range_pct = (max - min) / min * 100
                - 'max': range_pct = (max - min) / max * 100
                - 'mean': range_pct = (max - min) / mean * 100

        Returns:
            Dictionary with keys: min, max, mean, range, range_pct
        """
        if mask is not None:
            values = data[mask]
        else:
            values = data.flatten()

        # Remove NaN values
        values = values[~np.isnan(values)]

        if len(values) == 0:
            return {
                'min': np.nan,
                'max': np.nan,
                'mean': np.nan,
                'range': np.nan,
                'range_pct': np.nan,
                'cell_count': 0
            }

        min_val = float(np.min(values))
        max_val = float(np.max(values))
        mean_val = float(np.mean(values))
        range_val = max_val - min_val

        # Calculate range percentage
        if variance_denominator == 'min':
            denom = min_val
        elif variance_denominator == 'max':
            denom = max_val
        else:  # mean
            denom = mean_val

        if denom > 0:
            range_pct = (range_val / denom) * 100
        else:
            range_pct = np.nan

        return {
            'min': min_val,
            'max': max_val,
            'mean': mean_val,
            'range': range_val,
            'range_pct': range_pct,
            'cell_count': len(values)
        }

    @staticmethod
    @log_call
    def analyze(
        geom_hdf: Union[str, Path],
        durations: Optional[List[int]] = None,
        return_periods: Optional[List[int]] = None,
        extent_source: Literal["2d_flow_area", "project_extent"] = "2d_flow_area",
        mesh_area_names: Optional[List[str]] = None,
        buffer_percent: float = 10.0,
        variance_denominator: Literal['min', 'max', 'mean'] = 'min',
        output_dir: Optional[Union[str, Path]] = None,
        ras_object: Optional['RasPrj'] = None
    ) -> pd.DataFrame:
        """
        Analyze spatial variance of Atlas 14 precipitation for a HEC-RAS project.

        This method downloads Atlas 14 data for the project extent and calculates
        variance statistics for each duration/return period combination. Results
        can be used to assess whether uniform rainfall assumptions are valid.

        Args:
            geom_hdf: Path to HEC-RAS geometry HDF file
            durations: List of storm durations in hours. If None, uses
                      [6, 12, 24, 48, 72, 96].
            return_periods: List of return periods in years. If None, uses
                           [10, 25, 50, 100, 200, 500].
            extent_source: Source for extent extraction:
                - "2d_flow_area": Analyze within 2D flow area polygons
                - "project_extent": Analyze within full project extent
            mesh_area_names: Optional list of specific 2D area names to analyze.
                            If None, analyzes all 2D areas.
            buffer_percent: Buffer around extent for data download (default 10%)
            variance_denominator: Denominator for range percentage ('min', 'max', 'mean')
            output_dir: Optional directory for saving results (CSV, plots)
            ras_object: Optional RasPrj object for multi-project workflows

        Returns:
            DataFrame with columns:
                - mesh_area: Name of 2D flow area (or 'Project Extent')
                - duration_hr: Storm duration in hours
                - return_period_yr: Return period in years
                - min_inches: Minimum precipitation depth
                - max_inches: Maximum precipitation depth
                - mean_inches: Mean precipitation depth
                - range_inches: Range (max - min)
                - range_pct: Range as percentage of denominator
                - cell_count: Number of grid cells in analysis

        Example:
            >>> results = Atlas14Variance.analyze(
            ...     geom_hdf="MyProject.g01.hdf",
            ...     durations=[6, 12, 24],
            ...     return_periods=[10, 50, 100],
            ...     variance_denominator='min'
            ... )
            >>> # Check for high variance events
            >>> high_var = results[results['range_pct'] > 10]
            >>> print(f"Events with >10% variance: {len(high_var)}")
        """
        Atlas14Variance._check_dependencies()

        from ..hdf import HdfMesh

        geom_hdf = Path(geom_hdf)

        if durations is None:
            durations = [6, 12, 24, 48, 72, 96]
        if return_periods is None:
            return_periods = [10, 25, 50, 100, 200, 500]

        logger.info(
            f"Starting Atlas 14 variance analysis for {geom_hdf.name}"
        )
        logger.info(
            f"Durations: {durations} hours, Return periods: {return_periods} years"
        )

        # Get Atlas 14 data for project extent
        pfe_data = Atlas14Grid.get_pfe_from_project(
            geom_hdf=geom_hdf,
            extent_source=extent_source,
            mesh_area_names=mesh_area_names,
            durations=durations,
            return_periods=return_periods,
            buffer_percent=buffer_percent,
            ras_object=ras_object
        )

        # Get analysis polygons
        if extent_source == "2d_flow_area":
            mesh_areas = HdfMesh.get_mesh_areas(geom_hdf)

            if mesh_area_names:
                mesh_areas = mesh_areas[
                    mesh_areas['mesh_name'].isin(mesh_area_names)
                ]

            if mesh_areas.empty:
                logger.warning(
                    "No 2D flow areas found, using project extent"
                )
                # Create bounding box polygon
                bounds = pfe_data['bounds']
                extent_poly = box(*bounds)
                mesh_areas = gpd.GeoDataFrame(
                    {'mesh_name': ['Project Extent']},
                    geometry=[extent_poly],
                    crs="EPSG:4326"
                )
        else:
            bounds = pfe_data['bounds']
            extent_poly = box(*bounds)
            mesh_areas = gpd.GeoDataFrame(
                {'mesh_name': ['Project Extent']},
                geometry=[extent_poly],
                crs="EPSG:4326"
            )

        # Ensure WGS84 for analysis
        if mesh_areas.crs is not None and mesh_areas.crs != "EPSG:4326":
            mesh_areas = mesh_areas.to_crs("EPSG:4326")

        # Build coordinate arrays for masking
        lat = pfe_data['lat']
        lon = pfe_data['lon']
        ari = pfe_data['ari']

        # Create meshgrid for point containment testing
        lon_grid, lat_grid = np.meshgrid(lon, lat)

        # Build results
        results = []

        for _, mesh_row in mesh_areas.iterrows():
            mesh_name = mesh_row['mesh_name']
            mesh_geom = mesh_row['geometry']

            logger.info(f"Analyzing mesh area: {mesh_name}")

            # Create mask for points within polygon
            # This is a simple approach - for production, use rasterio.features.rasterize
            from shapely.geometry import Point
            mask = np.zeros((len(lat), len(lon)), dtype=bool)

            for i in range(len(lat)):
                for j in range(len(lon)):
                    pt = Point(lon[j], lat[i])
                    if mesh_geom.contains(pt):
                        mask[i, j] = True

            cell_count = mask.sum()
            logger.debug(f"  Cells within polygon: {cell_count}")

            if cell_count == 0:
                logger.warning(f"  No grid cells within {mesh_name}")
                continue

            for duration in durations:
                key = f'pfe_{duration}hr'
                if key not in pfe_data:
                    continue

                data_3d = pfe_data[key]

                for rp in return_periods:
                    # Find ARI index
                    ari_idx = np.argmin(np.abs(ari - rp))

                    # Extract 2D slice for this return period
                    data_2d = data_3d[:, :, ari_idx]

                    # Calculate stats within mask
                    stats = Atlas14Variance.calculate_stats(
                        data_2d,
                        mask=mask,
                        variance_denominator=variance_denominator
                    )

                    results.append({
                        'mesh_area': mesh_name,
                        'duration_hr': duration,
                        'return_period_yr': int(ari[ari_idx]),
                        'min_inches': stats['min'],
                        'max_inches': stats['max'],
                        'mean_inches': stats['mean'],
                        'range_inches': stats['range'],
                        'range_pct': stats['range_pct'],
                        'cell_count': stats['cell_count']
                    })

        df = pd.DataFrame(results)

        # Save results if output directory specified
        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            csv_path = output_dir / f"{geom_hdf.stem}_atlas14_variance.csv"
            df.to_csv(csv_path, index=False)
            logger.info(f"Results saved to: {csv_path}")

        # Log summary statistics
        if not df.empty:
            max_range = df['range_pct'].max()
            mean_range = df['range_pct'].mean()
            logger.info(
                f"Variance analysis complete: "
                f"max range = {max_range:.1f}%, mean range = {mean_range:.1f}%"
            )

            if max_range > 10:
                logger.warning(
                    f"High variance detected (>{max_range:.1f}%). "
                    "Consider using spatially distributed precipitation."
                )

        return df

    @staticmethod
    @log_call
    def analyze_quick(
        geom_hdf: Union[str, Path],
        duration: int = 24,
        return_period: int = 100
    ) -> Dict[str, float]:
        """
        Quick variance check for a single duration/return period.

        This is a convenience method for rapid variance assessment using
        a single representative event (default: 100-year, 24-hour).

        Args:
            geom_hdf: Path to HEC-RAS geometry HDF file
            duration: Storm duration in hours (default 24)
            return_period: Return period in years (default 100)

        Returns:
            Dictionary with min, max, mean, range, range_pct values

        Example:
            >>> stats = Atlas14Variance.analyze_quick("MyProject.g01.hdf")
            >>> if stats['range_pct'] > 10:
            ...     print("Consider spatially variable rainfall")
        """
        df = Atlas14Variance.analyze(
            geom_hdf=geom_hdf,
            durations=[duration],
            return_periods=[return_period]
        )

        if df.empty:
            return {
                'min': np.nan,
                'max': np.nan,
                'mean': np.nan,
                'range': np.nan,
                'range_pct': np.nan
            }

        row = df.iloc[0]
        return {
            'min': row['min_inches'],
            'max': row['max_inches'],
            'mean': row['mean_inches'],
            'range': row['range_inches'],
            'range_pct': row['range_pct']
        }

    @staticmethod
    @log_call
    def generate_report(
        results_df: pd.DataFrame,
        output_dir: Union[str, Path],
        project_name: Optional[str] = None,
        include_plots: bool = True
    ) -> Path:
        """
        Generate a variance analysis report with plots.

        Args:
            results_df: DataFrame from analyze() method
            output_dir: Directory for output files
            project_name: Optional project name for report title
            include_plots: Whether to generate matplotlib plots

        Returns:
            Path to generated report directory

        Example:
            >>> results = Atlas14Variance.analyze("MyProject.g01.hdf")
            >>> report_dir = Atlas14Variance.generate_report(
            ...     results,
            ...     output_dir="reports/",
            ...     project_name="My Project"
            ... )
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if project_name is None:
            project_name = "Atlas 14 Variance Analysis"

        # Save detailed CSV
        csv_path = output_dir / "variance_statistics.csv"
        results_df.to_csv(csv_path, index=False)
        logger.info(f"Saved statistics to: {csv_path}")

        # Generate summary by mesh area
        summary = results_df.groupby('mesh_area').agg({
            'min_inches': 'min',
            'max_inches': 'max',
            'mean_inches': 'mean',
            'range_pct': ['mean', 'max']
        }).round(2)
        summary.columns = ['_'.join(col).strip() for col in summary.columns]
        summary_path = output_dir / "variance_summary.csv"
        summary.to_csv(summary_path)
        logger.info(f"Saved summary to: {summary_path}")

        # Generate plots if requested
        if include_plots:
            try:
                import matplotlib.pyplot as plt

                # Plot 1: Range percentage by duration
                fig, ax = plt.subplots(figsize=(10, 6))

                for mesh_area in results_df['mesh_area'].unique():
                    mesh_df = results_df[results_df['mesh_area'] == mesh_area]

                    # Average across return periods
                    by_duration = mesh_df.groupby('duration_hr')['range_pct'].mean()
                    ax.plot(by_duration.index, by_duration.values,
                           marker='o', label=mesh_area)

                ax.set_xlabel('Duration (hours)')
                ax.set_ylabel('Mean Range (%)')
                ax.set_title(f'{project_name}\nPrecipitation Variance by Duration')
                ax.legend()
                ax.grid(True, alpha=0.3)

                plot_path = output_dir / "variance_by_duration.png"
                plt.savefig(plot_path, dpi=150, bbox_inches='tight')
                plt.close()
                logger.info(f"Saved plot: {plot_path}")

                # Plot 2: Heatmap of range percentage
                if len(results_df['mesh_area'].unique()) == 1:
                    pivot = results_df.pivot(
                        index='duration_hr',
                        columns='return_period_yr',
                        values='range_pct'
                    )

                    fig, ax = plt.subplots(figsize=(10, 6))
                    im = ax.imshow(pivot.values, aspect='auto', cmap='YlOrRd')

                    ax.set_xticks(range(len(pivot.columns)))
                    ax.set_xticklabels(pivot.columns)
                    ax.set_yticks(range(len(pivot.index)))
                    ax.set_yticklabels(pivot.index)

                    ax.set_xlabel('Return Period (years)')
                    ax.set_ylabel('Duration (hours)')
                    ax.set_title(f'{project_name}\nPrecipitation Range (%)')

                    plt.colorbar(im, ax=ax, label='Range %')

                    plot_path = output_dir / "variance_heatmap.png"
                    plt.savefig(plot_path, dpi=150, bbox_inches='tight')
                    plt.close()
                    logger.info(f"Saved plot: {plot_path}")

            except ImportError:
                logger.warning("matplotlib not available, skipping plots")

        logger.info(f"Report generated in: {output_dir}")
        return output_dir

    @staticmethod
    def is_uniform_rainfall_appropriate(
        results_df: pd.DataFrame,
        threshold_pct: float = 10.0
    ) -> Tuple[bool, str]:
        """
        Determine if uniform rainfall is appropriate based on variance analysis.

        Args:
            results_df: DataFrame from analyze() method
            threshold_pct: Maximum acceptable range percentage (default 10%)

        Returns:
            Tuple of (is_appropriate, explanation)

        Example:
            >>> results = Atlas14Variance.analyze("MyProject.g01.hdf")
            >>> ok, msg = Atlas14Variance.is_uniform_rainfall_appropriate(results)
            >>> print(msg)
        """
        if results_df.empty:
            return False, "No variance data available"

        max_range = results_df['range_pct'].max()
        mean_range = results_df['range_pct'].mean()

        # Find worst case
        worst_row = results_df.loc[results_df['range_pct'].idxmax()]

        if max_range <= threshold_pct:
            return True, (
                f"Uniform rainfall appropriate. "
                f"Maximum variance is {max_range:.1f}% "
                f"(threshold: {threshold_pct}%)"
            )
        else:
            return False, (
                f"Spatially variable rainfall recommended. "
                f"Maximum variance is {max_range:.1f}% "
                f"(threshold: {threshold_pct}%) "
                f"at {worst_row['duration_hr']}-hr, "
                f"{worst_row['return_period_yr']}-year event."
            )
