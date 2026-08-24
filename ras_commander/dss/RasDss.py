"""
RasDss - DSS File Operations for ras-commander

Summary:
    Provides static methods for interacting with HEC-DSS files (versions 6 and 7),
    enabling reading of time series, extracting catalogs, extracting boundary time
    series, and fetching file metadata, all using HEC Monolith libraries accessed
    via pyjnius. JVM setup and dependency downloads are handled automatically at
    runtime.

Functions:
    _ensure_monolith():
        Ensures HEC Monolith Java libraries are installed (downloads if needed).
    _configure_jvm():
        Configures the JVM and sets classpath/library paths for pyjnius.
    get_catalog(dss_file):
        Returns a list of all data pathnames in a DSS file.
    read_timeseries(dss_file, pathname, start_date=None, end_date=None):
        Reads a DSS time series by pathname and returns it as a pandas DataFrame.
    read_grid(dss_file, pathname):
        Reads one exact DSS spatial grid record and its metadata.
    read_multiple_timeseries(dss_file, pathnames):
        Reads multiple DSS time series, returning a dict of pathname to DataFrame
        (or None on failure).
    get_info(dss_file):
        Returns summary information and statistics for a DSS file, including
        partial catalog.
    extract_boundary_timeseries(boundaries_df, project_dir=None, ras_object=None):
        Extracts DSS time series for DSS-defined boundary conditions in a
        DataFrame and appends results as a new column.
    write_grid_timeseries(dss_file, pathname, data, times, grid_info):
        Writes spatial grid records such as SHG gridded precipitation to DSS.
    copy_grid_with_zero_tail(source_dss, output_dss, pathname, tail_intervals):
        Rewrites one validated grid family to an atomic derivative and appends
        explicit zero-valued intervals while preserving NoData cells.
    shutdown_jvm():
        Placeholder for JVM lifecycle management (not typically required with
        pyjnius).

Lazy Loading:
    This module implements lazy loading for all heavy dependencies:
    - pyjnius: Only imported when DSS methods are actually called
    - jnius_config: Only imported during JVM configuration
    - HecMonolithDownloader: Only imported when ensuring monolith installation
    - Java classes: Only loaded after JVM is configured

    This ensures that importing RasDss has minimal overhead and users who don't
    use DSS functionality don't pay the cost of loading Java/pyjnius.
"""

import logging
import os
import re
import sys
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from math import isfinite
from numbers import Real
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

# Lazy imports - these are always needed for type hints and basic operations
import numpy as np
import pandas as pd

# Import decorator from parent package
from ..Decorators import log_call

logger = logging.getLogger(__name__)


class RasDss:
    """
    Static class for DSS file operations.

    Uses HEC Monolith libraries (auto-downloaded on first use).
    Supports both DSS V6 and V7 formats.

    All heavy dependencies (pyjnius, Java) are lazy-loaded on first use.

    Usage:
        from ras_commander import RasDss

        # Read time series
        df = RasDss.read_timeseries("file.dss", "/BASIN/LOC/FLOW//1HOUR/OBS/")

        # Get catalog
        paths = RasDss.get_catalog("file.dss")
    """

    _jvm_configured = False
    _monolith = None

    @staticmethod
    def _ensure_monolith():
        """Ensure HEC Monolith is downloaded and available."""
        if RasDss._monolith is not None:
            return RasDss._monolith

        # Lazy import from same subpackage
        from ._hec_monolith import HecMonolithDownloader

        RasDss._monolith = HecMonolithDownloader()

        if not RasDss._monolith.is_installed():
            logger.info(
                "Installing HEC Monolith libraries for DSS operations "
                "(one-time download, ~20 MB)"
            )
            RasDss._monolith.install()

        return RasDss._monolith

    @staticmethod
    def _configure_jvm():
        """Configure JVM classpath for pyjnius (must be done before first import)."""
        if RasDss._jvm_configured:
            return

        # Ensure monolith is installed
        monolith = RasDss._ensure_monolith()

        # Lazy import pyjnius config
        try:
            import jnius_config
        except ImportError:
            raise ImportError(
                "pyjnius is required for DSS file operations.\n"
                "Install with: pip install pyjnius"
            )

        # Check if JVM already started using jnius_config (does NOT start the JVM)
        # IMPORTANT: Never import from jnius here - that would start the JVM with
        # an empty classpath before we can call jnius_config.add_classpath()
        if getattr(jnius_config, 'vm_running', False):
            RasDss._jvm_configured = True
            return

        # Get classpath and library path
        classpath = monolith.get_classpath()
        library_path = monolith.get_library_path()

        logger.debug("Configuring Java VM for DSS operations")

        # Set JAVA_HOME if not already set
        if 'JAVA_HOME' not in os.environ:
            # Dynamically discover Java installations using glob patterns.
            # Search standard Java install locations plus HEC application bundles.
            java_search_roots = [
                Path("C:/Program Files/Java"),
                Path("C:/Program Files (x86)/Java"),
            ]
            java_candidates = []
            for root in java_search_roots:
                if root.exists():
                    # Collect all jre* and jdk* directories, sorted newest first
                    java_candidates.extend(sorted(root.glob("jre*"), reverse=True))
                    java_candidates.extend(sorted(root.glob("jdk*"), reverse=True))
                    java_candidates.extend(sorted(root.glob("jdk-*"), reverse=True))

            # Also check JREs bundled with HEC applications (HMS, RAS, etc.)
            hec_apps = Path("C:/Program Files/HEC")
            if hec_apps.exists():
                java_candidates.extend(sorted(hec_apps.glob("*/*/jre"), reverse=True))
                java_candidates.extend(sorted(hec_apps.glob("**/jre"), reverse=True))

            def _has_jvm_lib(java_dir: Path) -> bool:
                """Check that a Java directory contains a usable JVM library."""
                if os.name == 'nt':
                    return bool(list(java_dir.rglob("jvm.dll")))
                else:
                    return bool(list(java_dir.rglob("libjvm.so")))

            for java_home in java_candidates:
                if java_home.is_dir() and _has_jvm_lib(java_home):
                    os.environ['JAVA_HOME'] = str(java_home)
                    logger.debug(f"Found Java runtime: {java_home}")
                    break
            else:
                raise RuntimeError(
                    "Java not found. Please set JAVA_HOME environment variable "
                    "or install Java JDK/JRE.\n"
                    "Download from: https://www.oracle.com/java/technologies/downloads/"
                )

        # Set classpath (must be done before first import from jnius)
        jnius_config.add_classpath(*classpath)

        # Set library path for native libraries
        if 'LD_LIBRARY_PATH' in os.environ:
            os.environ['LD_LIBRARY_PATH'] = (
                library_path + ':' + os.environ['LD_LIBRARY_PATH']
            )
        else:
            os.environ['LD_LIBRARY_PATH'] = library_path

        # Windows: Add to PATH for native DLLs
        if os.name == 'nt':
            os.environ['PATH'] = (
                library_path + os.pathsep + os.environ.get('PATH', '')
            )

        RasDss._jvm_configured = True
        logger.debug("Java VM configured for DSS operations")

    @staticmethod
    @log_call
    def get_catalog(dss_file: Union[str, Path]) -> pd.DataFrame:
        """
        Get catalog of all data paths in DSS file.

        Args:
            dss_file: Path to DSS file

        Returns:
            DataFrame with 'pathname' column containing all DSS pathnames

        Example:
            catalog = RasDss.get_catalog("sample.dss")
            print(f"Found {len(catalog)} pathnames")
            for pathname in catalog['pathname']:
                print(pathname)
        """
        # Configure JVM (must be before first jnius import)
        RasDss._configure_jvm()

        # Import Java classes via pyjnius (lazy)
        from jnius import autoclass
        from ras_commander.RasUtils import RasUtils

        HecDss = autoclass('hec.heclib.dss.HecDss')

        dss_file = str(RasUtils.safe_resolve(Path(dss_file)))

        # Open DSS file
        dss = None
        try:
            dss = HecDss.open(dss_file)
            # Get catalog (returns Java Vector of pathname strings)
            catalog_vector = dss.getCatalogedPathnames()

            # Convert Java Vector to Python list
            paths = []
            for i in range(catalog_vector.size()):
                paths.append(str(catalog_vector.get(i)))

            # Return as DataFrame for easier manipulation
            return pd.DataFrame({'pathname': paths})

        finally:
            if dss is not None:
                dss.done()

    @staticmethod
    @log_call
    def read_timeseries(
        dss_file: Union[str, Path],
        pathname: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Read time series from DSS file.

        Args:
            dss_file: Path to DSS file
            pathname: DSS pathname (e.g., "/BASIN/LOC/FLOW//1HOUR/OBS/")
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            pandas DataFrame with DatetimeIndex and 'value' column

        Example:
            df = RasDss.read_timeseries("file.dss", "/BASIN/LOC/FLOW//1HOUR/OBS/")
            print(df.head())
        """
        # Configure JVM (must be before first jnius import)
        RasDss._configure_jvm()

        # Import Java classes via pyjnius (lazy)
        from jnius import autoclass, cast
        from ras_commander.RasUtils import RasUtils

        HecDss = autoclass('hec.heclib.dss.HecDss')
        TimeSeriesContainer = autoclass('hec.io.TimeSeriesContainer')

        dss_file = str(RasUtils.safe_resolve(Path(dss_file)))

        # Open DSS file
        dss = None
        try:
            dss = HecDss.open(dss_file)
            # Read time series
            # True = ignore D-part (date) for wildcards
            container = dss.get(pathname, True)

            if container is None:
                raise ValueError(f"No data found for pathname: {pathname}")

            # Cast to TimeSeriesContainer to access fields
            tsc = cast('hec.io.TimeSeriesContainer', container)

            # Extract values and times from Java container
            # pyjnius automatically converts Java arrays to Python lists
            values = np.array(tsc.values)  # Java double[] -> numpy array
            times = np.array(tsc.times)    # Java int[] -> numpy array (minutes since 1899-12-31)

            # Convert HEC time to numpy datetime64
            # HEC epoch: December 31, 1899 00:00
            HEC_EPOCH = np.datetime64('1899-12-31T00:00:00')
            datetimes = HEC_EPOCH + times.astype('timedelta64[m]')

            # Create DataFrame
            df = pd.DataFrame({
                'value': values
            }, index=pd.DatetimeIndex(datetimes, name='datetime'))

            # Add metadata as attributes
            df.attrs['pathname'] = pathname
            df.attrs['units'] = str(tsc.units) if tsc.units else ""
            df.attrs['type'] = str(tsc.type) if tsc.type else ""
            df.attrs['interval'] = (
                int(tsc.interval) if hasattr(tsc, 'interval') else None
            )
            df.attrs['dss_file'] = dss_file

            return df

        finally:
            if dss is not None:
                dss.done()

    @staticmethod
    @log_call
    def read_grid(
        dss_file: Union[str, Path],
        pathname: str,
    ) -> Dict[str, Any]:
        """
        Read one spatial grid record from an exact DSS pathname.

        Args:
            dss_file: Path to an existing DSS file.
            pathname: Exact six-part DSS grid pathname. Wildcards are not
                accepted; D and E parts identify the record's time window.

        Returns:
            Dictionary containing:

            - ``dss_file``: Absolute DSS file path.
            - ``pathname``: Exact pathname requested.
            - ``data``: Two-dimensional ``float32`` array in row-major order.
              The HEC grid no-data sentinel is represented as ``numpy.nan``.
            - ``shape``: ``(rows, columns)``.
            - ``units`` and ``data_type``: DSS parameter metadata.
            - ``grid_type``: ``"albers"``, ``"specified"``, ``"hrap"``, or
              the runtime grid-info class name for another grid type.
            - ``crs`` and ``cell_size``: Spatial reference and resolution.
            - ``start_time`` and ``end_time``: Naive ``pandas.Timestamp``
              values parsed from pathname parts D and E when present.
            - ``metadata``: Grid dimensions, cell indexes, origin/projection,
              compression, type codes, missing-value count, and raw timing.

        Raises:
            FileNotFoundError: If ``dss_file`` does not exist.
            IsADirectoryError: If ``dss_file`` is not a file.
            ValueError: If the pathname is malformed, uses wildcards, or does
                not identify an existing exact record.
            TypeError: If the exact pathname identifies a non-grid record.
            ImportError: If pyjnius is not installed.
            RuntimeError: If the Java grid read fails or returns invalid data.
        """
        if not isinstance(pathname, str):
            raise ValueError(f"DSS pathname must be a string, got {type(pathname).__name__}")
        if "*" in pathname or "?" in pathname:
            raise ValueError(
                "read_grid requires an exact DSS pathname without wildcard "
                f"characters: {pathname}"
            )

        _, path_parts = RasDss._split_dss_pathname(pathname)

        dss_path = Path(dss_file)
        if not dss_path.exists():
            raise FileNotFoundError(f"DSS file not found: {dss_path}")
        if not dss_path.is_file():
            raise IsADirectoryError(f"DSS path is not a file: {dss_path}")

        RasDss._configure_jvm()

        from jnius import autoclass, cast
        from ras_commander.RasUtils import RasUtils

        HecDss = autoclass('hec.heclib.dss.HecDss')
        GridInfo = autoclass('hec.heclib.grid.GridInfo')
        dss_file_str = str(RasUtils.safe_resolve(dss_path))

        dss = None
        try:
            dss = HecDss.open(dss_file_str)
            if not dss.recordExists(pathname):
                raise ValueError(
                    f"No DSS record found for exact pathname {pathname} "
                    f"in {dss_file_str}"
                )

            container = dss.get(pathname)
            if container is None:
                raise RuntimeError(
                    f"HEC-DSS returned no container for existing pathname: {pathname}"
                )

            container_class = str(container.getClass().getName())
            if container_class != "hec.io.GridContainer":
                raise TypeError(
                    f"DSS pathname is not a spatial grid record: {pathname} "
                    f"(container type: {container_class})"
                )

            grid_container = cast('hec.io.GridContainer', container)
            grid_data = grid_container.getGridData()
            if grid_data is None:
                raise RuntimeError(f"Grid record contains no grid data: {pathname}")

            grid_info_base = grid_data.getGridInfo()
            if grid_info_base is None:
                raise RuntimeError(f"Grid record contains no grid metadata: {pathname}")

            grid_class = str(grid_info_base.getClass().getName())
            grid_info = cast(grid_class, grid_info_base)
            n_cols = int(grid_info.getNumberOfCellsX())
            n_rows = int(grid_info.getNumberOfCellsY())
            if n_rows <= 0 or n_cols <= 0:
                raise RuntimeError(
                    f"Grid record has invalid dimensions {n_rows}x{n_cols}: {pathname}"
                )

            values = np.asarray(grid_data.getData(), dtype=np.float32)
            expected_size = n_rows * n_cols
            if values.size != expected_size:
                raise RuntimeError(
                    f"Grid record returned {values.size} values for dimensions "
                    f"{n_rows}x{n_cols} ({expected_size} expected): {pathname}"
                )

            nodata_value = np.float32(GridInfo.getGridNodataValue())
            values = values.reshape((n_rows, n_cols), order="C").copy()
            values[values == nodata_value] = np.nan

            grid_class_name = grid_class.rsplit('.', 1)[-1]
            grid_type_names = {
                "AlbersInfo": "albers",
                "SpecifiedGridInfo": "specified",
                "HrapInfo": "hrap",
            }
            grid_type = grid_type_names.get(grid_class_name, grid_class_name)

            cell_size = float(grid_info.getCellSize())
            lower_left_cell = (
                int(grid_info.getLowerLeftCellX()),
                int(grid_info.getLowerLeftCellY()),
            )
            projection: Dict[str, Any] = {}
            origin = None

            if grid_class_name in {"AlbersInfo", "SpecifiedGridInfo"}:
                x_cell_zero = float(grid_info.getXCoordOfGridCellZero())
                y_cell_zero = float(grid_info.getYCoordOfGridCellZero())
                projection.update({
                    "x_coord_cell_zero": x_cell_zero,
                    "y_coord_cell_zero": y_cell_zero,
                })
                origin = (
                    x_cell_zero + lower_left_cell[0] * cell_size,
                    y_cell_zero + lower_left_cell[1] * cell_size,
                )

            if grid_class_name == "AlbersInfo":
                projection.update({
                    "datum_code": int(grid_info.getProjectionDatum()),
                    "units": str(grid_info.getProjectionUnits()),
                    "standard_parallel_1": float(grid_info.getFirstStandardParallel()),
                    "standard_parallel_2": float(grid_info.getSecondStandardParallel()),
                    "central_meridian": float(grid_info.getCentralMeridian()),
                    "latitude_of_origin": float(
                        grid_info.getLatitudeOfProjectionOrigin()
                    ),
                    "false_easting": float(grid_info.getFalseEasting()),
                    "false_northing": float(grid_info.getFalseNorthing()),
                })

            raw_start_time = str(grid_info.getStartTime())
            raw_end_time = str(grid_info.getEndTime())
            start_time = RasDss._parse_grid_dss_datetime(path_parts[3])
            end_time = RasDss._parse_grid_dss_datetime(path_parts[4])
            if start_time is None:
                try:
                    start_time = pd.Timestamp(pd.to_datetime(raw_start_time))
                except (TypeError, ValueError):
                    pass
            if end_time is None:
                try:
                    end_time = pd.Timestamp(pd.to_datetime(raw_end_time))
                except (TypeError, ValueError):
                    pass

            metadata = {
                "pathname_parts": dict(zip("ABCDEF", path_parts)),
                "grid_class": grid_class,
                "grid_type_code": int(grid_info.getGridType()),
                "data_type_code": int(grid_info.getDataType()),
                "shape": (n_rows, n_cols),
                "number_of_cells_x": n_cols,
                "number_of_cells_y": n_rows,
                "lower_left_cell": lower_left_cell,
                "origin": origin,
                "projection": projection,
                "number_missing": int(grid_data.getNumberMissing()),
                "nodata_value": float(nodata_value),
                "compression": {
                    "method": int(grid_info.getCompressionMethod()),
                    "base": float(grid_info.getCompressionBase()),
                    "scale_factor": float(grid_info.getCompressionScaleFactor()),
                    "element_size": int(grid_info.getSizeOfCompressedElements()),
                },
                "timing": {
                    "start": raw_start_time,
                    "end": raw_end_time,
                    "period": str(grid_info.getTimePeriod()),
                },
            }

            return {
                "dss_file": dss_file_str,
                "pathname": pathname,
                "data": values,
                "shape": (n_rows, n_cols),
                "units": str(grid_info.getDataUnits()),
                "data_type": str(grid_info.getDataTypeName()),
                "grid_type": grid_type,
                "crs": str(grid_info.getSpatialReferenceSystem()),
                "cell_size": cell_size,
                "start_time": start_time,
                "end_time": end_time,
                "metadata": metadata,
            }
        except (ValueError, TypeError):
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Failed to read DSS grid record: {exc}\n"
                f"  File: {dss_file_str}\n"
                f"  Pathname: {pathname}"
            ) from exc
        finally:
            if dss is not None:
                dss.done()

    @staticmethod
    @log_call
    def read_multiple_timeseries(
        dss_file: Union[str, Path],
        pathnames: List[str]
    ) -> Dict[str, pd.DataFrame]:
        """
        Read multiple time series from DSS file.

        Args:
            dss_file: Path to DSS file
            pathnames: List of DSS pathnames

        Returns:
            Dictionary mapping pathnames to DataFrames

        Example:
            paths = ["/BASIN/LOC1/FLOW//1HOUR/OBS/", "/BASIN/LOC2/FLOW//1HOUR/OBS/"]
            data = RasDss.read_multiple_timeseries("file.dss", paths)
            for path, df in data.items():
                print(f"{path}: {len(df)} points")
        """
        results = {}
        for pathname in pathnames:
            try:
                results[pathname] = RasDss.read_timeseries(dss_file, pathname)
            except Exception as e:
                logger.warning("Could not read DSS pathname: %s", pathname)
                logger.debug("DSS read failure for %s: %s", pathname, e)
                results[pathname] = None

        return results

    @staticmethod
    @log_call
    def get_info(dss_file: Union[str, Path]) -> Dict:
        """
        Get summary information about DSS file.

        Args:
            dss_file: Path to DSS file

        Returns:
            Dictionary with file information

        Example:
            info = RasDss.get_info("sample.dss")
            print(f"Total paths: {info['total_paths']}")
            print(f"File size: {info['file_size_mb']:.2f} MB")
        """
        from ras_commander.RasUtils import RasUtils
        dss_path = Path(dss_file)

        catalog = RasDss.get_catalog(dss_file)

        return {
            'filepath': str(RasUtils.safe_resolve(dss_path)),
            'filename': dss_path.name,
            'file_size_mb': dss_path.stat().st_size / (1024 * 1024),
            'total_paths': len(catalog),
            'first_5_paths': catalog[:5] if len(catalog) > 5 else catalog,
        }

    @staticmethod
    @log_call
    def extract_boundary_timeseries(
        boundaries_df: pd.DataFrame,
        project_dir: Optional[Union[str, Path]] = None,
        ras_object=None
    ) -> pd.DataFrame:
        """
        Extract DSS time series data for all DSS-defined boundaries.

        Reads boundaries_df and extracts time series for any boundary condition
        defined by a DSS file. Adds the extracted data to the dataframe.

        Args:
            boundaries_df: DataFrame from ras.boundaries_df
            project_dir: Project directory (for resolving relative DSS paths)
            ras_object: RasPrj object (alternative to project_dir)

        Returns:
            Enhanced DataFrame with 'dss_timeseries' column containing extracted data

        Example:
            from ras_commander import init_ras_project, RasDss

            ras = init_ras_project("project_path", "7.0")

            # Extract all DSS boundary data
            enhanced_boundaries = RasDss.extract_boundary_timeseries(
                ras.boundaries_df, ras_object=ras
            )

            # Now enhanced_boundaries has a 'dss_timeseries' column with DataFrames
            for idx, row in enhanced_boundaries.iterrows():
                if row['Use DSS']:
                    print(f"{row['bc_type']}: {len(row['dss_timeseries'])} points")
        """
        # Get project directory
        if ras_object is not None:
            project_dir = ras_object.project_folder
        elif project_dir is None:
            raise ValueError("Must provide either project_dir or ras_object")

        project_dir = Path(project_dir)

        # Create a copy to avoid modifying original
        result_df = boundaries_df.copy()

        # Add column for time series data
        result_df['dss_timeseries'] = None

        # Find DSS-defined boundaries
        # Note: 'Use DSS' column may be string 'True'/'False' or boolean True/False
        dss_boundaries = result_df[
            (result_df['Use DSS'] == True) | (result_df['Use DSS'] == 'True')
        ]

        if len(dss_boundaries) == 0:
            logger.debug("No DSS-defined boundaries found")
            return result_df

        logger.debug(f"Found {len(dss_boundaries)} DSS-defined boundaries")

        # Extract time series for each DSS boundary
        success_count = 0
        fail_count = 0

        for idx, row in dss_boundaries.iterrows():
            dss_file = row['DSS File']
            dss_path = row['DSS Path']

            if pd.isna(dss_file) or pd.isna(dss_path):
                logger.warning(f"Row {idx}: Missing DSS File or DSS Path")
                continue

            # Resolve DSS file path (may be relative to project directory)
            dss_file_path = Path(dss_file)
            if not dss_file_path.is_absolute():
                dss_file_path = project_dir / dss_file

            if not dss_file_path.exists():
                logger.warning(f"Row {idx}: DSS file not found: {dss_file_path}")
                fail_count += 1
                continue

            try:
                # Read time series
                df_ts = RasDss.read_timeseries(dss_file_path, dss_path)

                # Store in result
                result_df.at[idx, 'dss_timeseries'] = df_ts

                success_count += 1
                logger.debug(
                    f"Row {idx}: Extracted {len(df_ts)} points from "
                    f"{dss_file_path.name}"
                )

            except Exception as e:
                logger.warning(f"Row {idx}: Failed to read DSS data: {e}")
                fail_count += 1

        logger.info(
            "DSS boundary extraction complete: "
            f"{len(dss_boundaries)} found, {success_count} read, {fail_count} failed"
        )

        return result_df

    @staticmethod
    def shutdown_jvm():
        """
        Shutdown Java Virtual Machine.

        Note: With pyjnius, JVM shutdown is typically not needed.
        This is a placeholder for API compatibility.
        """
        logger.debug("pyjnius handles JVM lifecycle automatically")
        pass

    # =========================================================================
    # Validation Methods
    # =========================================================================

    @staticmethod
    @log_call
    def check_pathname_format(pathname: str):
        """
        Check DSS pathname format validity.

        Validates against DSS pathname specification:
        - Format: /A/B/C/D/E/F/
        - A blank A-part is represented as //B/C/D/E/F/
        - Parts: A (basin/project), B (location), C (parameter),
                 D (date), E (interval), F (scenario)

        Args:
            pathname: DSS pathname to validate

        Returns:
            ValidationResult with detailed diagnostics

        Example:
            >>> from ras_commander.dss import RasDss
            >>> result = RasDss.check_pathname_format("/BASIN/LOC/FLOW/01JAN2020/1HOUR/OBS/")
            >>> print(result.passed)
            True
        """
        # Lazy import validation framework
        try:
            from ..RasValidation import ValidationResult, ValidationSeverity
        except ImportError:
            # Return basic dict if validation framework not available
            if (
                pathname.startswith('/')
                and pathname.endswith('/')
                and len(pathname[1:-1].split('/')) == 6
            ):
                return {'passed': True, 'message': 'Format appears valid (validation framework not available)'}
            else:
                return {'passed': False, 'message': 'Format appears invalid (validation framework not available)'}

        # Check prefix and trailing slash
        if not pathname.startswith('/'):
            return ValidationResult(
                check_name="path_format",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"DSS path must start with '/': {pathname}",
                details={"pathname": pathname}
            )

        if not pathname.endswith('/'):
            return ValidationResult(
                check_name="path_format",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"DSS path must end with '/': {pathname}",
                details={"pathname": pathname}
            )

        # Preserve empty components while removing only the required outer
        # separators.  ``//B/C/D/E/F/`` is a normal six-part DSS pathname with
        # an empty A-part; stripping all slashes would incorrectly reduce it to
        # five parts.
        part_values = pathname[1:-1].split('/')

        if len(part_values) != 6:
            return ValidationResult(
                check_name="path_format",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=(
                    "DSS path must have 6 parts "
                    "(/A/B/C/D/E/F/), got "
                    f"{len(part_values)}: {pathname}"
                ),
                details={
                    "pathname": pathname,
                    "expected_parts": 6,
                    "actual_parts": len(part_values)
                }
            )

        # Extract parts into named components
        part_names = [
            'basin',
            'location',
            'parameter',
            'date',
            'interval',
            'scenario'
        ]

        # Check for empty parts (warning, not error - some DSS paths have empty parts)
        empty_parts = []
        for i, (name, value) in enumerate(zip(part_names, part_values), start=1):
            if not value:
                empty_parts.append((i, name))

        if empty_parts:
            empty_names = ", ".join(f"{name} (part {i})" for i, name in empty_parts)
            return ValidationResult(
                check_name="path_format",
                severity=ValidationSeverity.WARNING,
                passed=True,
                message=f"DSS path has empty parts: {empty_names}",
                details={
                    "pathname": pathname,
                    "empty_parts": empty_names,
                    "parts": dict(zip(part_names, part_values))
                }
            )

        # All checks passed
        return ValidationResult(
            check_name="path_format",
            severity=ValidationSeverity.INFO,
            passed=True,
            message="DSS path format is valid",
            details={"parts": dict(zip(part_names, part_values))}
        )

    @staticmethod
    @log_call
    def check_file_exists(dss_file: Union[str, Path]):
        """
        Check if DSS file exists and is accessible.

        Args:
            dss_file: Path to DSS file (str or Path)

        Returns:
            ValidationResult with file existence check outcome

        Example:
            >>> from pathlib import Path
            >>> result = RasDss.check_file_exists(Path("data.dss"))
            >>> if result.passed:
            ...     print("File exists and is accessible")
        """
        # Lazy import validation framework
        try:
            from ..RasValidation import ValidationResult, ValidationSeverity
        except ImportError:
            dss_file = Path(dss_file)
            if dss_file.exists() and dss_file.is_file():
                return {'passed': True, 'message': 'File exists (validation framework not available)'}
            else:
                return {'passed': False, 'message': 'File not found (validation framework not available)'}

        dss_file = Path(dss_file)

        if not dss_file.exists():
            return ValidationResult(
                check_name="file_existence",
                severity=ValidationSeverity.CRITICAL,
                passed=False,
                message=f"DSS file not found: {dss_file}",
                details={"dss_file": str(dss_file)}
            )

        if not dss_file.is_file():
            return ValidationResult(
                check_name="file_type",
                severity=ValidationSeverity.CRITICAL,
                passed=False,
                message=f"Path is not a file: {dss_file}",
                details={"dss_file": str(dss_file)}
            )

        # Check read permissions
        try:
            with open(dss_file, 'rb'):
                pass
        except PermissionError:
            return ValidationResult(
                check_name="file_accessibility",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"Permission denied reading: {dss_file}",
                details={"dss_file": str(dss_file)}
            )

        # File exists and is readable
        file_size_mb = dss_file.stat().st_size / (1024 * 1024)
        return ValidationResult(
            check_name="file_existence",
            severity=ValidationSeverity.INFO,
            passed=True,
            message="DSS file exists and is readable",
            details={
                "dss_file": str(dss_file),
                "file_size_mb": round(file_size_mb, 2)
            }
        )

    @staticmethod
    @log_call
    def check_pathname_exists(
        dss_file: Union[str, Path],
        pathname: str
    ):
        """
        Check if pathname exists in DSS file catalog.

        Args:
            dss_file: Path to DSS file (str or Path)
            pathname: DSS pathname to check

        Returns:
            ValidationResult with existence check outcome

        Example:
            >>> result = RasDss.check_pathname_exists(
            ...     "data.dss",
            ...     "//BASIN/FLOW/01JAN2020/1HOUR/RUN1/"
            ... )
            >>> if result.passed:
            ...     print("Pathname found in catalog")
        """
        # Lazy import validation framework
        try:
            from ..RasValidation import ValidationResult, ValidationSeverity
        except ImportError:
            # Try basic check without validation framework
            try:
                catalog = RasDss.get_catalog(dss_file)
                if isinstance(catalog, pd.DataFrame) and 'pathname' in catalog.columns:
                    catalog_paths = catalog['pathname'].astype(str).tolist()
                else:
                    catalog_paths = [str(p) for p in catalog]

                if pathname in catalog_paths:
                    return {'passed': True, 'message': 'Pathname exists (validation framework not available)'}
                else:
                    return {'passed': False, 'message': 'Pathname not found (validation framework not available)'}
            except Exception as e:
                return {'passed': False, 'message': f'Error checking: {e}'}

        dss_file = Path(dss_file)

        # Get catalog
        try:
            catalog = RasDss.get_catalog(str(dss_file))
        except Exception as e:
            return ValidationResult(
                check_name="catalog_access",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"Failed to read DSS catalog: {e}",
                details={"error": str(e), "dss_file": str(dss_file)}
            )

        # Normalize catalog to a list of path strings
        if isinstance(catalog, pd.DataFrame) and 'pathname' in catalog.columns:
            catalog_paths = catalog['pathname'].astype(str).tolist()
        elif hasattr(catalog, 'pathname'):
            # Defensive: if a custom object exposes a pathname attribute
            catalog_paths = list(getattr(catalog, 'pathname'))
        else:
            catalog_paths = [str(p) for p in catalog]

        # Check exact match
        if pathname in catalog_paths:
            return ValidationResult(
                check_name="pathname_existence",
                severity=ValidationSeverity.INFO,
                passed=True,
                message="Pathname exists in DSS file",
                details={"total_paths": len(catalog_paths)}
            )

        # Try case-insensitive match (DSS is case-sensitive but provide hint)
        pathname_upper = pathname.upper()
        if pathname_upper in [p.upper() for p in catalog_paths]:
            return ValidationResult(
                check_name="pathname_existence",
                severity=ValidationSeverity.WARNING,
                passed=True,
                message="Pathname exists but case differs (DSS is case-sensitive)",
                details={"total_paths": len(catalog_paths)}
            )

        # Find similar paths (match on location part - index 2)
        segments = pathname.strip('/').split('/')
        location = segments[1] if len(segments) >= 2 else ""
        if location:
            similar = [p for p in catalog_paths if location in p]
        else:
            similar = []

        return ValidationResult(
            check_name="pathname_existence",
            severity=ValidationSeverity.ERROR,
            passed=False,
            message="Pathname not found in DSS file",
            details={
                "pathname": pathname,
                "total_paths": len(catalog_paths),
                "similar_paths": similar[:5]  # First 5 similar paths
            }
        )

    @staticmethod
    @log_call
    def check_data_availability(
        dss_file: Union[str, Path],
        pathname: str,
        expected_start: Optional[str] = None,
        expected_end: Optional[str] = None
    ):
        """
        Check if time series data is available for the expected date range.

        Args:
            dss_file: Path to DSS file (str or Path)
            pathname: DSS pathname
            expected_start: Expected start date (optional, datetime or string)
            expected_end: Expected end date (optional, datetime or string)

        Returns:
            ValidationResult with data availability check outcome

        Example:
            >>> from datetime import datetime
            >>> result = RasDss.check_data_availability(
            ...     "data.dss",
            ...     "//BASIN/FLOW/01JAN2020/1HOUR/RUN1/",
            ...     expected_start=datetime(2020, 1, 1),
            ...     expected_end=datetime(2020, 12, 31)
            ... )
        """
        # Lazy import validation framework
        try:
            from ..RasValidation import ValidationResult, ValidationSeverity
        except ImportError:
            # Try basic check without validation framework
            try:
                df = RasDss.read_timeseries(dss_file, pathname)
                if df is not None and len(df) > 0:
                    return {'passed': True, 'message': f'Data available: {len(df)} points'}
                else:
                    return {'passed': False, 'message': 'No data found'}
            except Exception as e:
                return {'passed': False, 'message': f'Error reading data: {e}'}

        # Convert expected dates to datetime if strings
        if expected_start is not None and isinstance(expected_start, str):
            from datetime import datetime
            expected_start = datetime.strptime(expected_start, '%d%b%Y %H%M')
        if expected_end is not None and isinstance(expected_end, str):
            from datetime import datetime
            expected_end = datetime.strptime(expected_end, '%d%b%Y %H%M')

        # Read time series
        try:
            df = RasDss.read_timeseries(str(dss_file), pathname)
        except Exception as e:
            return ValidationResult(
                check_name="data_read",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"Failed to read time series data: {e}",
                details={"error": str(e), "pathname": pathname}
            )

        # Check if data is empty
        if df is None or len(df) == 0:
            return ValidationResult(
                check_name="data_availability",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="Time series data is empty",
                details={"pathname": pathname}
            )

        # Extract actual date range
        actual_start = df.index.min()
        actual_end = df.index.max()

        details = {
            "data_points": len(df),
            "actual_start": actual_start.strftime('%Y-%m-%d %H:%M:%S'),
            "actual_end": actual_end.strftime('%Y-%m-%d %H:%M:%S'),
            "units": df.attrs.get('units', 'unknown'),
            "interval": df.attrs.get('interval', 'unknown')
        }

        # Check date range coverage if expected dates provided
        if expected_start and expected_end:
            if actual_start > expected_start:
                return ValidationResult(
                    check_name="date_coverage",
                    severity=ValidationSeverity.WARNING,
                    passed=True,
                    message=f"Data starts later than expected: {actual_start} > {expected_start}",
                    details={**details, "expected_start": expected_start.strftime('%Y-%m-%d %H:%M:%S')}
                )

            if actual_end < expected_end:
                return ValidationResult(
                    check_name="date_coverage",
                    severity=ValidationSeverity.WARNING,
                    passed=True,
                    message=f"Data ends earlier than expected: {actual_end} < {expected_end}",
                    details={**details, "expected_end": expected_end.strftime('%Y-%m-%d %H:%M:%S')}
                )

        # All checks passed
        return ValidationResult(
            check_name="data_availability",
            severity=ValidationSeverity.INFO,
            passed=True,
            message=f"Time series data available ({len(df)} points from {actual_start.strftime('%Y-%m-%d')} to {actual_end.strftime('%Y-%m-%d')})",
            details=details
        )

    @staticmethod
    @log_call
    def check_pathname(
        dss_file: Union[str, Path],
        pathname: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ):
        """
        Comprehensive DSS pathname validation.

        Performs:
        1. Format validation
        2. File existence check
        3. Pathname existence check
        4. Data availability check (if date range provided)

        Args:
            dss_file: Path to DSS file (str or Path)
            pathname: DSS pathname to validate
            start_date: Optional start date for availability check
            end_date: Optional end date for availability check

        Returns:
            ValidationReport with all validation results

        Example:
            >>> report = RasDss.check_pathname(
            ...     dss_file="boundary.dss",
            ...     pathname="//BASIN/FLOW/STAGE/01JAN2020/1HOUR//",
            ...     start_date="01JAN2020 0000",
            ...     end_date="31DEC2020 2400"
            ... )
            >>> if not report.is_valid:
            ...     print(report.summary())
        """
        # Lazy import validation framework
        try:
            from ..RasValidation import ValidationReport
        except ImportError:
            # Return basic dict if validation framework not available
            results = []
            format_ok = RasDss.check_pathname_format(pathname).get('passed', False)
            results.append(f"Format: {'OK' if format_ok else 'FAIL'}")

            file_ok = RasDss.check_file_exists(dss_file).get('passed', False)
            results.append(f"File: {'OK' if file_ok else 'FAIL'}")

            if file_ok:
                exists_ok = RasDss.check_pathname_exists(dss_file, pathname).get('passed', False)
                results.append(f"Exists: {'OK' if exists_ok else 'FAIL'}")

            return {'results': results, 'is_valid': all('OK' in r for r in results)}

        from datetime import datetime

        report = ValidationReport(
            target=f"DSS Pathname: {pathname}",
            timestamp=datetime.now(),
            results=[]
        )

        # Check 1: Format
        result = RasDss.check_pathname_format(pathname)
        report.results.append(result)
        if not result.passed:
            return report  # Stop if format invalid

        # Check 2: File existence
        file_result = RasDss.check_file_exists(dss_file)
        report.results.append(file_result)
        if not file_result.passed:
            return report  # Stop if file doesn't exist

        # Check 3: Pathname existence
        exists_result = RasDss.check_pathname_exists(dss_file, pathname)
        report.results.append(exists_result)
        if not exists_result.passed:
            return report  # Stop if pathname doesn't exist

        # Check 4: Data availability (if dates provided)
        if start_date or end_date:
            avail_result = RasDss.check_data_availability(
                dss_file, pathname, start_date, end_date
            )
            report.results.append(avail_result)

        return report

    @staticmethod
    def is_valid_pathname(pathname: str) -> bool:
        """
        Quick boolean check for pathname format.

        Args:
            pathname: DSS pathname to validate

        Returns:
            True if pathname format is valid

        Example:
            >>> if RasDss.is_valid_pathname("//BASIN/LOC/FLOW/01JAN2020/1HOUR/OBS/"):
            ...     print("Valid format")
        """
        result = RasDss.check_pathname_format(pathname)
        # Handle both ValidationResult and dict return types
        if hasattr(result, 'passed'):
            return result.passed
        elif isinstance(result, dict):
            return result.get('passed', False)
        return False

    @staticmethod
    def is_pathname_available(
        dss_file: Union[str, Path],
        pathname: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> bool:
        """
        Quick boolean check for pathname availability.

        Args:
            dss_file: Path to DSS file (str or Path)
            pathname: DSS pathname to check
            start_date: Optional start date
            end_date: Optional end date

        Returns:
            True if pathname exists and has data

        Example:
            >>> if RasDss.is_pathname_available("data.dss", "//BASIN/FLOW/.../"):
            ...     print("Data is available")
        """
        report = RasDss.check_pathname(dss_file, pathname, start_date, end_date)
        # Handle both ValidationReport and dict return types
        if hasattr(report, 'is_valid'):
            return report.is_valid
        elif isinstance(report, dict):
            return report.get('is_valid', False)
        return False

    # =========================================================================
    # DSS Write Operations
    # =========================================================================

    @staticmethod
    @log_call
    def write_grid_timeseries(
        dss_file: Union[str, Path],
        pathname: str,
        data: np.ndarray,
        times: Union[List, np.ndarray, pd.DatetimeIndex],
        grid_info: Dict[str, Any],
        create_if_missing: bool = True,
        *,
        dss_version: Optional[int] = None,
    ) -> List[str]:
        """
        Write a time-varying spatial grid series to HEC-DSS.

        Creates one DSS grid record per timestep using the HEC Monolith Java
        bridge. The method is designed for HEC-RAS gridded precipitation DSS
        records such as::

            /SHG/MARFC/PRECIP/01SEP2018:0200/01SEP2018:0300/NEXRAD/

        Args:
            dss_file: Path to DSS file (created if missing and
                create_if_missing=True).
            pathname: DSS grid pathname template. Parts A, B, C, and F are
                preserved; Parts D and E are replaced with each timestep's
                start/end window.
            data: 3-D array with shape ``(n_times, n_rows, n_cols)``.
                NaN/inf values and values equal to ``grid_info["nodata_value"]``
                are written as the HEC grid no-data sentinel.
            times: Timezone-naive datetime values. Pass ``n_times + 1`` values
                to provide explicit interval boundaries, or ``n_times`` values
                to provide interval end times. For ``n_times`` period data, the
                interval is inferred from ``grid_info["interval_minutes"]``,
                consecutive times, the pathname D/E parts, or 60 minutes.
            grid_info: Grid metadata. Common keys are:
                - ``cellsize`` or ``cell_size``: cell size in CRS units.
                - ``origin``: physical lower-left coordinate ``(x, y)``.
                - ``lower_left_cell_x`` / ``lower_left_cell_y``: explicit HEC
                  cell indexes, used instead of ``origin`` when provided.
                - ``x_coord_cell_zero`` / ``y_coord_cell_zero``: physical
                  coordinate of HEC cell zero, default 0.
                - ``crs``: ``"SHG"``/``"EPSG:5070"`` for HEC SHG Albers
                  metadata, or WKT for a specified grid.
                - ``units``: data units, default ``"mm"``.
                - ``data_type``: DSS grid data type, default ``"PER-CUM"``.
                - ``compression``: ``"PRECIP_2_BYTE"``, ``"ZLIB"``, or
                  ``None``. Defaults to ``"PRECIP_2_BYTE"``.
            create_if_missing: Create DSS file if it doesn't exist.
            dss_version: Major DSS version to use when creating a new file.
                Pass 6 or 7 explicitly, or omit it to preserve the bridge's
                current default. Existing files must match an explicit value.
                For DSS6, default precipitation compression is configured with
                the version-specific safe base/scale ordering.

        Returns:
            List of DSS pathnames written, one per timestep.

        Raises:
            FileNotFoundError: If DSS file doesn't exist and
                create_if_missing=False.
            ValueError: If inputs are malformed, timestamps are timezone-aware,
                grid metadata is incomplete, ``dss_version`` is invalid, or an
                existing file does not match the requested version.
            ImportError: If pyjnius is not installed.
            RuntimeError: If the Java grid write operation fails.

        Notes:
            HEC Monolith 3.3.x exposes ``hec.io.GridContainer`` and
            ``hec.heclib.grid.GridData/GridInfo`` for grid records. This method
            writes through ``hec.heclib.grid.GriddedData.storeGriddedData()``
            because it is the stable Java API path from pyjnius for grid data.
        """
        dss_version = RasDss._validate_dss_version(dss_version)
        if grid_info is None:
            raise ValueError("grid_info is required")
        grid_info = dict(grid_info)

        # HEC Monolith's DSS6 precipitation-compression setter exposes its
        # base and scale positions opposite to DSS7. Supply the known-safe V6
        # defaults when the caller selects DSS6 and has not overridden them.
        compression = grid_info.get("compression", "PRECIP_2_BYTE")
        if dss_version == 6 and isinstance(compression, str):
            compression_text = compression.upper().replace("-", "_")
            if compression_text in {"PRECIP", "PRECIP2BYTE", "PRECIP_2_BYTE"}:
                grid_info.setdefault("compression_base", 100.0)
                grid_info.setdefault("compression_scale_factor", 0.0)

        grid_array = np.asarray(data, dtype=np.float32)
        if grid_array.ndim != 3:
            raise ValueError(
                "data must have shape (n_times, n_rows, n_cols); "
                f"got {grid_array.shape}"
            )

        n_times, n_rows, n_cols = grid_array.shape
        if n_times == 0 or n_rows == 0 or n_cols == 0:
            raise ValueError(
                "data dimensions must be non-empty; "
                f"got {grid_array.shape}"
            )

        prefix, path_parts = RasDss._split_dss_pathname(pathname)
        data_type = str(grid_info.get("data_type", "PER-CUM")).upper().replace("_", "-")
        data_type_code = RasDss._grid_data_type_code(data_type)
        time_windows = RasDss._grid_time_windows(
            times=times,
            n_times=n_times,
            data_type_code=data_type_code,
            grid_info=grid_info,
            pathname_parts=path_parts,
        )

        dss_path = Path(dss_file)
        file_existed = dss_path.exists()
        if file_existed and not dss_path.is_file():
            raise IsADirectoryError(f"DSS path is not a file: {dss_path}")
        if file_existed and dss_version is not None:
            existing_version = RasDss.get_file_version(dss_path)
            if existing_version != dss_version:
                raise ValueError(
                    f"Existing DSS file is version {existing_version}, not "
                    f"requested version {dss_version}: {dss_path}"
                )
        if not file_existed:
            if not create_if_missing:
                raise FileNotFoundError(f"DSS file not found: {dss_path}")
            dss_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"DSS file will be created: {dss_path.name}")
            logger.debug(f"DSS file creation path: {dss_path}")

        RasDss._configure_jvm()

        from jnius import autoclass
        from ras_commander.RasUtils import RasUtils

        dss_file_str = str(RasUtils.safe_resolve(dss_path))

        # GriddedData creates a missing file with the bridge default. When the
        # caller requests DSS6 or DSS7 explicitly, create that empty database
        # first so the grid writer attaches to the requested file format.
        if not file_existed and dss_version is not None:
            RasDss._create_empty_dss(dss_path, dss_version)

        GridInfo = autoclass('hec.heclib.grid.GridInfo')
        GridData = autoclass('hec.heclib.grid.GridData')
        GriddedData = autoclass('hec.heclib.grid.GriddedData')
        HecTime = autoclass('hec.heclib.util.HecTime')
        AlbersInfo = autoclass('hec.heclib.grid.AlbersInfo')
        SpecifiedGridInfo = autoclass('hec.heclib.grid.SpecifiedGridInfo')
        HrapInfo = autoclass('hec.heclib.grid.HrapInfo')

        hec_nodata = float(GridInfo.getGridNodataValue())
        source_nodata = grid_info.get("nodata_value", None)
        written_pathnames: List[str] = []

        writer = None
        try:
            writer = GriddedData()
            status = writer.setDSSFileName(dss_file_str)
            if status != 0:
                raise RuntimeError(f"setDSSFileName returned status {status}")

            for index, (start_time, end_time) in enumerate(time_windows):
                d_part = RasDss._format_grid_dss_datetime(start_time)
                e_part = RasDss._format_grid_dss_datetime(end_time)
                record_parts = list(path_parts)
                record_parts[3] = d_part
                record_parts[4] = e_part
                record_pathname = RasDss._build_dss_pathname(prefix, record_parts)

                java_grid_info = RasDss._create_java_grid_info(
                    grid_info=grid_info,
                    n_rows=n_rows,
                    n_cols=n_cols,
                    start_part=d_part,
                    end_part=e_part,
                    data_type_code=data_type_code,
                    GridInfo=GridInfo,
                    AlbersInfo=AlbersInfo,
                    SpecifiedGridInfo=SpecifiedGridInfo,
                    HrapInfo=HrapInfo,
                )

                frame = np.asarray(grid_array[index], dtype=np.float32)
                flat = frame.ravel(order="C").astype(np.float32, copy=True)
                nodata_mask = ~np.isfinite(flat)
                if source_nodata is not None:
                    nodata_mask |= flat == np.float32(source_nodata)
                flat[nodata_mask] = np.float32(hec_nodata)

                java_grid_data = GridData(flat.tolist(), java_grid_info)
                java_grid_data.updateStatistics()

                writer.setPathname(record_pathname)
                writer.setGriddedPathnameParts(
                    record_parts[0],
                    record_parts[1],
                    record_parts[2],
                    record_parts[5],
                )

                start_date, start_clock = RasDss._split_grid_datetime_part(d_part)
                end_date, end_clock = RasDss._split_grid_datetime_part(e_part)
                if data_type_code in (2, 3):  # INST-VAL or INST-CUM
                    writer.setGridTime(HecTime(end_date, end_clock))
                else:
                    writer.setGriddedTimeWindow(
                        HecTime(start_date, start_clock),
                        HecTime(end_date, end_clock),
                    )

                status = writer.storeGriddedData(java_grid_info, java_grid_data)
                if status != 0:
                    raise RuntimeError(
                        f"storeGriddedData returned status {status} for {record_pathname}"
                    )

                written_pathnames.append(record_pathname)

            logger.info(
                f"Wrote {len(written_pathnames)} grid records to {Path(dss_file_str).name} "
                f"(shape={n_rows}x{n_cols}, units={grid_info.get('units', 'mm')}, "
                f"type={data_type})"
            )
            return written_pathnames
        except ValueError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"Failed to write grid time series to DSS: {e}\n"
                f"  File: {dss_file_str}\n"
                f"  Pathname template: {pathname}\n"
                f"  Data shape: {grid_array.shape}"
            ) from e
        finally:
            if writer is not None:
                writer.done()

    @staticmethod
    @log_call
    def copy_grid_with_zero_tail(
        source_dss: Union[str, Path],
        output_dss: Union[str, Path],
        pathname: str,
        tail_intervals: int,
        *,
        time_shift_minutes: int = 0,
        output_pathname: Optional[str] = None,
        x_shift: float = 0.0,
        y_shift: float = 0.0,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """Create a non-destructive grid derivative with an explicit zero tail.

        The output contains only the uniquely matched source grid family and
        the appended tail. Source records are streamed one frame at a time and
        rewritten with their decoded values and write-relevant metadata;
        unrelated source records are not copied. Optional time, pathname, and
        whole-cell origin translations are mechanical metadata transforms.

        The intended workflow is upstream preparation of a run-local gridded
        precipitation or rainfall-excess DSS derivative for a HEC-RAS
        rain-on-grid scenario. A caller can preserve an immutable AORC-like
        source, express UTC grid timestamps on the model clock with an
        explicitly chosen shift, rename the forcing family, apply an approved
        whole-cell origin translation, and append explicit zero-forcing
        intervals so post-storm routing or recession can continue after the
        source rainfall ends. In the source PR workflow, ``RasScenario``
        accepted the already-prepared ``forcing_excess_dss`` and wired it to
        Gridded/DSS precipitation; it did not call this preparation method.

        This method does not calculate rainfall or rainfall excess,
        scientifically transpose a storm, reproject, resample, or interpolate
        grids, infer a time zone, or decide engineering suitability. Those
        scientific and study-specific decisions remain caller responsibilities.

        ``overwrite=False`` publishes with an atomic hard-link create-if-absent
        operation. Filesystems without compatible hard-link support fail closed
        with ``OSError``; the method never falls back to a clobbering replace.
        ``overwrite=True`` atomically replaces the destination and therefore
        replaces its file metadata and hard-link identity. Output symlinks,
        junctions, and other reparse points are rejected before resolution.

        Args:
            source_dss: Existing source DSS file, which is never modified.
            output_dss: Destination DSS file for the derivative.
            pathname: Six-part family selector whose D and E parts are blank.
            tail_intervals: Positive number of zero-valued records to append.
            time_shift_minutes: Signed whole-minute shift for every window.
            output_pathname: Optional output family selector with blank D/E.
                When omitted, caller-supplied A/B/C/F casing is preserved even
                though source-family selection is case-insensitive.
            x_shift: Signed x-origin translation in source grid units. It must
                be an exact whole-cell increment.
            y_shift: Signed y-origin translation in source grid units. It must
                be an exact whole-cell increment.
            overwrite: Atomically replace an existing destination after full
                temporary readback. When false, publish only by atomic hard
                link if the destination still does not exist.

        Returns:
            A dictionary describing source coverage, translations, DSS
            version, accepted source SHA-256, rewritten source paths, and
            appended tail paths.

        Raises:
            FileNotFoundError: If the source DSS does not exist.
            FileExistsError: If the destination exists without ``overwrite``.
            IsADirectoryError: If a DSS path is not a regular file.
            ValueError: If inputs, family timing, metadata, or NoData masks are
                unsafe or ambiguous.
            ImportError: If the optional Java bridge is unavailable.
            OSError: If directory, hard-link publication, or replacement fails.
            RuntimeError: If source stability, grid I/O, or complete temporary
                readback verification fails.

        Notes:
            D/E tokens must use exact ``DDMMMYYYY:HHMM`` minute syntax. A
            narrow ``2400`` token is accepted as next-day midnight. Native
            HEC-DSS grid catalogs spell midnight record ends as prior-day
            ``2400`` and midnight record starts as same-day ``0000``; returned
            pathnames follow that role-specific convention. The source is
            SHA-256 checked before access, after the validation pass, and after
            the streaming write pass. Any detected mismatch aborts before
            publication. Every temporary record is reopened and compared
            exactly before publish.
        """
        from ras_commander.RasUtils import RasUtils

        raw_output = Path(output_dss)
        if RasDss._is_reparse_point(raw_output):
            raise ValueError(
                "output_dss must not be a symlink, junction, or reparse point"
            )
        source = RasUtils.safe_resolve(Path(source_dss))
        output_parent = RasUtils.safe_resolve(raw_output.parent)
        output = output_parent / raw_output.name
        if not source.exists():
            raise FileNotFoundError(f"DSS file not found: {source}")
        if not source.is_file():
            raise IsADirectoryError(f"DSS path is not a file: {source}")

        same_file = source == output
        if output.exists() and not same_file:
            try:
                same_file = os.path.samefile(source, output)
            except OSError:
                same_file = False
        if same_file:
            raise ValueError("output_dss must differ from source_dss")

        if type(tail_intervals) is not int or tail_intervals <= 0:
            raise ValueError("tail_intervals must be a positive integer")
        if type(time_shift_minutes) is not int:
            raise ValueError("time_shift_minutes must be an integer")
        if type(overwrite) is not bool:
            raise ValueError("overwrite must be a boolean")
        x_shift = RasDss._normalize_finite_real(x_shift, "x_shift")
        y_shift = RasDss._normalize_finite_real(y_shift, "y_shift")

        _, selector_parts = RasDss._validate_grid_family_selector(
            pathname,
            "pathname",
        )
        derivative_pathname = (
            pathname if output_pathname is None else output_pathname
        )
        _, derivative_parts = RasDss._validate_grid_family_selector(
            derivative_pathname,
            "output_pathname",
        )
        canonical_derivative_pathname = RasDss._build_dss_pathname(
            "/",
            derivative_parts,
        )

        if output.exists() and not output.is_file():
            raise IsADirectoryError(f"Output DSS path is not a file: {output}")
        if output.exists() and not overwrite:
            raise FileExistsError(f"Output DSS already exists: {output}")

        RasDss._best_effort_close_dss_file(source, "before initial source hash")
        source_sha256 = RasDss._sha256_file(source)
        reference: Optional[Dict[str, Any]] = None
        reference_signature: Optional[Dict[str, Any]] = None
        nodata_mask: Optional[np.ndarray] = None
        try:
            catalog = RasDss.get_catalog(source)
            records = RasDss._select_grid_family_records(
                catalog,
                pathname,
                selector_parts,
            )
            for record in records:
                grid = RasDss.read_grid(source, record[2])
                signature, mask = RasDss._validate_grid_record_metadata(
                    grid,
                    record,
                    reference_signature,
                    nodata_mask,
                )
                if reference is None:
                    reference = grid
                    reference_signature = signature
                    nodata_mask = mask
            source_version = RasDss.get_file_version(source)
        finally:
            RasDss._best_effort_close_dss_file(
                source,
                "after source catalog/prevalidation",
            )

        if reference is None or reference_signature is None or nodata_mask is None:
            raise ValueError("Grid family records could not be read completely")
        del grid
        if RasDss._sha256_file(source) != source_sha256:
            raise RuntimeError("Source DSS changed during grid-family validation")

        metadata = reference["metadata"]
        cell_size = float(reference["cell_size"])
        x_shift_cells = RasDss._whole_grid_cell_shift(
            x_shift,
            cell_size,
            "x_shift",
        )
        y_shift_cells = RasDss._whole_grid_cell_shift(
            y_shift,
            cell_size,
            "y_shift",
        )
        lower_left = tuple(metadata["lower_left_cell"])
        output_lower_left = (
            int(lower_left[0]) + x_shift_cells,
            int(lower_left[1]) + y_shift_cells,
        )
        RasDss._validate_java_int32(output_lower_left[0], "lower-left x cell")
        RasDss._validate_java_int32(output_lower_left[1], "lower-left y cell")

        interval = records[0][1] - records[0][0]
        source_boundaries = [records[0][0]] + [
            end for _, end, _ in records
        ]
        output_boundaries = RasDss._translated_grid_boundaries(
            source_boundaries,
            interval,
            time_shift_minutes,
            tail_intervals,
        )
        output_source_end = output_boundaries[len(records)]

        expected_catalog_pathnames = RasDss._expected_native_grid_pathnames(
            canonical_derivative_pathname,
            output_boundaries,
        )

        zero_frame = np.where(
            nodata_mask,
            np.float32(np.nan),
            np.float32(0.0),
        )
        grid_info = RasDss._grid_write_info_from_record(
            reference,
            output_lower_left,
        )
        expected_output_signature = dict(reference_signature)
        expected_output_signature["lower_left_cell"] = output_lower_left
        projection = reference_signature["projection"]
        expected_output_signature["origin"] = (
            float(projection["x_coord_cell_zero"])
            + output_lower_left[0] * cell_size,
            float(projection["y_coord_cell_zero"])
            + output_lower_left[1] * cell_size,
        )
        del reference

        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(
            f".{output.stem}.{uuid4().hex}.tmp{output.suffix or '.dss'}"
        )
        while temporary.exists():
            temporary = output.with_name(
                f".{output.stem}.{uuid4().hex}.tmp{output.suffix or '.dss'}"
            )

        written_count = 0
        source_value_digests: List[str] = []
        try:
            RasDss._create_empty_dss(temporary, source_version)
            try:
                for index, record in enumerate(records):
                    grid = RasDss.read_grid(source, record[2])
                    RasDss._validate_grid_record_metadata(
                        grid,
                        record,
                        reference_signature,
                        nodata_mask,
                    )
                    frame = np.asarray(grid["data"], dtype=np.float32)
                    source_value_digests.append(RasDss._grid_value_digest(frame))
                    returned = RasDss.write_grid_timeseries(
                        dss_file=temporary,
                        pathname=canonical_derivative_pathname,
                        data=frame[np.newaxis, :, :],
                        times=[
                            output_boundaries[index].to_pydatetime(),
                            output_boundaries[index + 1].to_pydatetime(),
                        ],
                        grid_info=grid_info,
                        create_if_missing=False,
                    )
                    RasDss._validate_grid_writer_return(
                        returned,
                        canonical_derivative_pathname,
                        output_boundaries[index],
                        output_boundaries[index + 1],
                    )
                    written_count += 1
            finally:
                RasDss._best_effort_close_dss_file(
                    source,
                    "after source reread/write",
                )

            if RasDss._sha256_file(source) != source_sha256:
                raise RuntimeError("Source DSS changed during grid-family rewrite")
            del frame, grid

            source_count = len(records)
            for tail_index in range(tail_intervals):
                index = source_count + tail_index
                returned = RasDss.write_grid_timeseries(
                    dss_file=temporary,
                    pathname=canonical_derivative_pathname,
                    data=zero_frame[np.newaxis, :, :],
                    times=[
                        output_boundaries[index].to_pydatetime(),
                        output_boundaries[index + 1].to_pydatetime(),
                    ],
                    grid_info=grid_info,
                    create_if_missing=False,
                )
                RasDss._validate_grid_writer_return(
                    returned,
                    canonical_derivative_pathname,
                    output_boundaries[index],
                    output_boundaries[index + 1],
                )
                written_count += 1

            if written_count != len(expected_catalog_pathnames):
                raise RuntimeError(
                    "Grid derivative writer return count does not match the "
                    "independently expected record count"
                )

            temporary_version = RasDss.get_file_version(temporary)
            if temporary_version != source_version:
                raise RuntimeError(
                    "Grid derivative changed DSS major version: "
                    f"source={source_version}, output={temporary_version}"
                )
            temporary_paths = list(
                RasDss.get_catalog(temporary)["pathname"].astype(str)
            )
            if (
                len(temporary_paths) != len(expected_catalog_pathnames)
                or set(temporary_paths) != set(expected_catalog_pathnames)
            ):
                raise RuntimeError(
                    "Temporary grid derivative catalog does not match the "
                    "independently expected pathnames"
                )

            for index, expected_pathname in enumerate(expected_catalog_pathnames):
                output_grid = RasDss.read_grid(temporary, expected_pathname)
                RasDss._validate_grid_record_metadata(
                    output_grid,
                    (
                        output_boundaries[index],
                        output_boundaries[index + 1],
                        expected_pathname,
                    ),
                    expected_output_signature,
                    nodata_mask,
                )
                output_frame = np.asarray(output_grid["data"], dtype=np.float32)
                if index < len(records):
                    if (
                        RasDss._grid_value_digest(output_frame)
                        != source_value_digests[index]
                    ):
                        raise RuntimeError(
                            "Temporary grid derivative changed decoded source "
                            f"values or orientation: {expected_pathname}"
                        )
                else:
                    output_mask = ~np.isfinite(output_frame)
                    if not np.array_equal(output_mask, nodata_mask):
                        raise RuntimeError(
                            "Temporary grid derivative changed the tail NoData "
                            f"footprint: {expected_pathname}"
                        )
                    if np.any(output_frame[~output_mask] != np.float32(0.0)):
                        raise RuntimeError(
                            "Temporary grid derivative tail contains nonzero "
                            f"data: {expected_pathname}"
                        )

            RasDss._close_dss_file(temporary)
            if overwrite:
                os.replace(temporary, output)
            else:
                try:
                    os.link(temporary, output)
                except FileExistsError as exc:
                    raise FileExistsError(
                        "Output DSS appeared while the derivative was being built: "
                        f"{output}"
                    ) from exc
                except OSError as exc:
                    raise OSError(
                        "Atomic no-clobber DSS publication requires hard-link "
                        f"support in the output directory: {output.parent}"
                    ) from exc
                try:
                    temporary.unlink()
                except OSError as exc:
                    logger.warning(
                        "Published derivative but could not remove temporary "
                        "hard-link alias: %s (%s)",
                        temporary,
                        exc,
                    )
        finally:
            RasDss._cleanup_temporary_dss(temporary)

        rewritten_count = len(records)
        rewritten_pathnames = expected_catalog_pathnames[:rewritten_count]
        shifted_pathnames = []
        for record, rewritten_pathname in zip(records, rewritten_pathnames):
            _, record_parts = RasDss._split_dss_pathname(record[2])
            canonical_source_pathname = RasDss._build_dss_pathname(
                "/",
                record_parts,
            )
            if canonical_source_pathname != rewritten_pathname:
                shifted_pathnames.append(rewritten_pathname)
        return {
            "source_dss": str(source),
            "output_dss": str(output),
            "source_sha256": source_sha256,
            "dss_version": source_version,
            "pathname": pathname,
            "output_pathname": canonical_derivative_pathname,
            "source_record_count": rewritten_count,
            "appended_record_count": tail_intervals,
            "interval_minutes": int(interval.total_seconds() // 60),
            "time_shift_minutes": time_shift_minutes,
            "x_shift": x_shift,
            "y_shift": y_shift,
            "output_lower_left_cell": output_lower_left,
            "source_start": records[0][0].isoformat(),
            "source_end": records[-1][1].isoformat(),
            "output_start": output_boundaries[0].isoformat(),
            "output_source_end": output_source_end.isoformat(),
            "padded_end": output_boundaries[-1].isoformat(),
            "written_source_pathnames": rewritten_pathnames,
            "shifted_pathnames": shifted_pathnames,
            "appended_pathnames": expected_catalog_pathnames[rewritten_count:],
        }

    @staticmethod
    @log_call
    def get_file_version(dss_file: Union[str, Path]) -> int:
        """Return the major HEC-DSS file version (6 or 7).

        Args:
            dss_file: Existing DSS file to inspect.

        Raises:
            FileNotFoundError: If the path does not exist.
            IsADirectoryError: If the path is not a file.
            ValueError: If the file is not a supported DSS 6 or DSS 7 database.
        """
        dss_path = Path(dss_file)
        if not dss_path.exists():
            raise FileNotFoundError(f"DSS file not found: {dss_path}")
        if not dss_path.is_file():
            raise IsADirectoryError(f"DSS path is not a file: {dss_path}")

        RasDss._configure_jvm()

        from jnius import autoclass
        from ras_commander.RasUtils import RasUtils

        HecDataManager = autoclass('hec.heclib.dss.HecDataManager')
        resolved_path = str(RasUtils.safe_resolve(dss_path))
        version = int(HecDataManager.getDssFileVersion(resolved_path))
        if version not in (6, 7):
            raise ValueError(
                f"File is not a supported HEC-DSS database: {dss_path}"
            )
        return version

    @staticmethod
    def _validate_dss_version(dss_version: Optional[int]) -> Optional[int]:
        """Validate an optional explicit HEC-DSS creation version."""
        if dss_version is None:
            return None
        if type(dss_version) is not int or dss_version not in (6, 7):
            raise ValueError("dss_version must be the integer 6, 7, or None")
        return dss_version

    @staticmethod
    @log_call
    def write_timeseries(
        dss_file: Union[str, Path],
        pathname: str,
        times: Union[List, np.ndarray, pd.DatetimeIndex],
        values: Union[List, np.ndarray],
        units: str = "CFS",
        data_type: str = "INST-VAL",
        create_if_missing: bool = True,
        *,
        dss_version: Optional[int] = None,
    ) -> None:
        """
        Write a time series to a DSS file.

        Creates or updates a time series record in a DSS file using the
        HEC Monolith Java bridge. Supports DSS V6 and V7 formats.

        Args:
            dss_file: Path to DSS file (created if missing and create_if_missing=True)
            pathname: DSS pathname (e.g., "//BASIN/LOCATION/FLOW//1HOUR/FORECAST/")
            times: Array of timezone-naive datetime values (datetime objects,
                   DatetimeIndex, or numpy datetime64 array). Values must be
                   aligned exactly to whole minutes.
            values: Array of numeric values (same length as times)
            units: Data units string (e.g., "CFS", "FEET", "MM", "IN")
            data_type: DSS data type string:
                - "INST-VAL" - Instantaneous values (default)
                - "PER-AVER" - Period average (e.g., precipitation)
                - "PER-CUM"  - Period cumulative
                - "INST-CUM" - Instantaneous cumulative
            create_if_missing: Create DSS file if it doesn't exist (default True)
            dss_version: Major DSS version to use when creating a new file.
                Pass 6 or 7 explicitly, or omit it to preserve the bridge's
                current default. Existing files must match an explicit value.

        Raises:
            FileNotFoundError: If DSS file doesn't exist and create_if_missing=False
            ValueError: If times and values have different lengths, are empty,
                or contain timestamps that cannot be represented exactly as
                HEC int32 epoch minutes; if ``dss_version`` is invalid; or if
                an existing file does not match the requested version.
            ImportError: If pyjnius is not installed
            RuntimeError: If Java write operation fails

        Example:
            >>> import pandas as pd
            >>> import numpy as np
            >>> from ras_commander import RasDss
            >>>
            >>> # Create time series data
            >>> times = pd.date_range("2024-01-01", periods=24, freq="h")
            >>> values = np.random.uniform(100, 500, 24)
            >>>
            >>> # Write to DSS file
            >>> RasDss.write_timeseries(
            ...     "output.dss",
            ...     "//BASIN/UPSTREAM/FLOW//1HOUR/FORECAST/",
            ...     times, values,
            ...     units="CFS",
            ...     data_type="INST-VAL"
            ... )

        Note:
            The Java bridge (pyjnius + HEC Monolith) is configured automatically
            on first use. The HEC epoch is 1899-12-31 00:00:00; times are stored
            as integer minutes since that epoch.
        """
        from ras_commander.RasUtils import RasUtils

        dss_version = RasDss._validate_dss_version(dss_version)

        # Validate inputs
        values = np.asarray(values, dtype=np.float64)
        if len(times) != len(values):
            raise ValueError(
                f"times ({len(times)}) and values ({len(values)}) must have same length"
            )
        if len(times) == 0:
            raise ValueError("times and values must not be empty")

        # Validate the model-clock representation before JVM setup or any
        # filesystem mutation.
        hec_times = RasDss._datetimes_to_hec_times(times)

        # Resolve DSS file path
        dss_path = Path(dss_file)
        file_existed = dss_path.exists()
        if file_existed and not dss_path.is_file():
            raise IsADirectoryError(f"DSS path is not a file: {dss_path}")
        if file_existed and dss_version is not None:
            existing_version = RasDss.get_file_version(dss_path)
            if existing_version != dss_version:
                raise ValueError(
                    f"Existing DSS file is version {existing_version}, not "
                    f"requested version {dss_version}: {dss_path}"
                )
        if not file_existed:
            if not create_if_missing:
                raise FileNotFoundError(f"DSS file not found: {dss_path}")
            # HecDss.open() will create the file
            dss_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"DSS file will be created: {dss_path.name}")
            logger.debug(f"DSS file creation path: {dss_path}")

        dss_file_str = str(RasUtils.safe_resolve(dss_path))

        # Detect interval from time spacing
        if len(hec_times) > 1:
            intervals = np.diff(hec_times)
            interval_minutes = int(np.median(intervals))
        else:
            interval_minutes = 60  # Default 1 hour

        RasDss._configure_jvm()

        from jnius import autoclass, cast

        # Load Java classes
        HecDss = autoclass('hec.heclib.dss.HecDss')
        TimeSeriesContainer = autoclass('hec.io.TimeSeriesContainer')
        HecTimeArray = autoclass('hec.heclib.util.HecTimeArray')

        # Create TimeSeriesContainer
        tsc = TimeSeriesContainer()
        tsc.fullName = pathname
        tsc.units = units
        tsc.type = data_type
        tsc.interval = interval_minutes
        tsc.setStoreAsDoubles(True)

        # Use typed Java setters. PyJNIus cannot reliably assign primitive
        # array fields directly, and HecDss.put() has an ambiguous overload.
        n = len(values)
        time_status = tsc.setTimes(HecTimeArray(hec_times.tolist()))
        value_status = tsc.setValues(values.tolist())
        if time_status != 0 or value_status != 0:
            raise RuntimeError(
                "HEC time-series container rejected input arrays: "
                f"times={time_status}, values={value_status}"
            )
        tsc.numberValues = n

        # Open DSS file and write
        dss = None
        try:
            dss = (
                HecDss.open(dss_file_str, dss_version)
                if dss_version is not None and not file_existed
                else HecDss.open(dss_file_str)
            )
            dss.put(cast('hec.io.DataContainer', tsc))
            logger.info(f"Wrote {n} values to {Path(dss_file_str).name}")
            logger.debug(
                f"DSS write details: file={dss_file_str}, pathname={pathname}, "
                f"units={units}, type={data_type}, interval={interval_minutes}min"
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to write time series to DSS: {e}\n"
                f"  File: {dss_file_str}\n"
                f"  Pathname: {pathname}\n"
                f"  Values: {n} points, range [{values.min():.2f}, {values.max():.2f}]"
            ) from e
        finally:
            if dss is not None:
                dss.done()

    @staticmethod
    @log_call
    def write_timeseries_from_dataframe(
        dss_file: Union[str, Path],
        pathname: str,
        df: pd.DataFrame,
        value_column: str = "value",
        units: str = "CFS",
        data_type: str = "INST-VAL",
        create_if_missing: bool = True,
        *,
        dss_version: Optional[int] = None,
    ) -> None:
        """
        Write a time series DataFrame to a DSS file.

        Convenience wrapper around write_timeseries() that accepts a DataFrame
        with a DatetimeIndex and a value column.

        Args:
            dss_file: Path to DSS file
            pathname: DSS pathname
            df: DataFrame with a timezone-naive DatetimeIndex and value column
            value_column: Name of column containing values (default "value")
            units: Data units string
            data_type: DSS data type string
            create_if_missing: Create DSS file if it doesn't exist
            dss_version: Major DSS version (6 or 7) for new-file creation.
                Omit it to preserve the current default. Existing files must
                match an explicit value.

        Example:
            >>> # Read from one DSS file, write to another
            >>> df = RasDss.read_timeseries("input.dss", pathname)
            >>> RasDss.write_timeseries_from_dataframe(
            ...     "output.dss", new_pathname, df, units="CFS"
            ... )
        """
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError(
                f"DataFrame must have DatetimeIndex, got {type(df.index).__name__}"
            )
        if value_column not in df.columns:
            raise ValueError(
                f"Column '{value_column}' not found. Available: {list(df.columns)}"
            )

        RasDss.write_timeseries(
            dss_file=dss_file,
            pathname=pathname,
            times=df.index,
            values=df[value_column].values,
            units=units,
            data_type=data_type,
            create_if_missing=create_if_missing,
            dss_version=dss_version,
        )

    @staticmethod
    def _is_reparse_point(path: Path) -> bool:
        """Return whether an existing path is a symlink/junction/reparse point."""
        if not os.path.lexists(path):
            return False
        try:
            path_stat = os.lstat(path)
        except OSError as exc:
            raise OSError(f"Could not safely inspect output path: {path}") from exc
        file_attributes = int(getattr(path_stat, "st_file_attributes", 0))
        if file_attributes & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
            return True
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction and is_junction())

    @staticmethod
    def _normalize_finite_real(value: Real, label: str) -> float:
        """Normalize one accepted Real scalar to a finite float."""
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"{label} must be a finite number")
        try:
            normalized = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{label} must be a finite number") from exc
        if not isfinite(normalized):
            raise ValueError(f"{label} must be a finite number")
        return normalized

    @staticmethod
    def _sha256_file(path: Path) -> str:
        """Return a streaming SHA-256 digest without materializing the file."""
        digest = sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _validate_java_int32(value: int, label: str) -> None:
        """Reject values that cannot be passed safely to a Java int."""
        if value < -(2**31) or value > 2**31 - 1:
            raise ValueError(f"Translated {label} exceeds Java int32 bounds: {value}")

    @staticmethod
    def _translated_grid_boundaries(
        source_boundaries: List[pd.Timestamp],
        interval: pd.Timedelta,
        time_shift_minutes: int,
        tail_intervals: int,
    ) -> List[pd.Timestamp]:
        """Translate source boundaries and append tail boundaries safely."""
        try:
            shift = pd.Timedelta(minutes=time_shift_minutes)
            translated = [pd.Timestamp(value) + shift for value in source_boundaries]
            boundary = translated[-1]
            for _ in range(tail_intervals):
                boundary = boundary + interval
                translated.append(boundary)
        except Exception as exc:
            raise ValueError(
                "Time shift or zero-tail extension exceeds supported datetime bounds"
            ) from exc
        return translated

    @staticmethod
    def _format_native_grid_end_datetime(value: pd.Timestamp) -> str:
        """Format a grid-window end using native HEC-DSS midnight spelling."""
        timestamp = pd.Timestamp(value)
        if timestamp == timestamp.normalize():
            try:
                previous_day = timestamp - pd.Timedelta(days=1)
            except Exception as exc:
                raise ValueError(
                    "Grid end time cannot be represented with native 2400 syntax"
                ) from exc
            return previous_day.strftime("%d%b%Y:2400").upper()
        return RasDss._format_grid_dss_datetime(timestamp)

    @staticmethod
    def _expected_native_grid_pathnames(
        pathname: str,
        boundaries: List[pd.Timestamp],
    ) -> List[str]:
        """Build exact pathnames as stored by native HEC-DSS grid catalogs."""
        _, parts = RasDss._split_dss_pathname(pathname)
        expected = []
        for start, end in zip(boundaries, boundaries[1:]):
            record_parts = list(parts)
            record_parts[3] = RasDss._format_grid_dss_datetime(start)
            record_parts[4] = RasDss._format_native_grid_end_datetime(end)
            expected.append(RasDss._build_dss_pathname("/", record_parts))
        return expected

    @staticmethod
    def _validate_grid_writer_return(
        returned: Any,
        pathname: str,
        expected_start: pd.Timestamp,
        expected_end: pd.Timestamp,
    ) -> str:
        """Require one exact-family writer result with the expected time window."""
        if not isinstance(returned, list) or len(returned) != 1:
            raise RuntimeError(
                "Grid derivative writer returned an unexpected ordered pathname: "
                f"{returned}"
            )
        returned_pathname = returned[0]
        try:
            prefix, returned_parts = RasDss._split_dss_pathname(returned_pathname)
            _, family_parts = RasDss._split_dss_pathname(pathname)
            start = RasDss._parse_strict_grid_dss_datetime(returned_parts[3])
            end = RasDss._parse_strict_grid_dss_datetime(returned_parts[4])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "Grid derivative writer returned an unexpected ordered pathname: "
                f"{returned}"
            ) from exc
        if (
            prefix != "/"
            or tuple(returned_parts[index] for index in (0, 1, 2, 5))
            != tuple(family_parts[index] for index in (0, 1, 2, 5))
            or start != pd.Timestamp(expected_start)
            or end != pd.Timestamp(expected_end)
        ):
            raise RuntimeError(
                "Grid derivative writer returned an unexpected ordered pathname: "
                f"{returned}"
            )
        return returned_pathname

    @staticmethod
    def _grid_value_digest(data: np.ndarray) -> str:
        """Hash float32 grid values with canonical NaN and signed-zero bits."""
        normalized = np.array(data, dtype="<f4", order="C", copy=True)
        if normalized.ndim != 2:
            raise ValueError("Grid data digest requires a two-dimensional frame")
        nan_mask = ~np.isfinite(normalized)
        zero_mask = normalized == np.float32(0.0)
        bits = normalized.view("<u4")
        bits[nan_mask] = np.uint32(0x7FC00000)
        bits[zero_mask] = np.uint32(0)
        return sha256(bits.tobytes(order="C")).hexdigest()

    @staticmethod
    def _validate_grid_family_selector(
        pathname: str,
        label: str,
    ) -> Tuple[str, List[str]]:
        """Validate an exact A/B/C/F grid-family selector."""
        prefix, parts = RasDss._split_dss_pathname(pathname)
        if parts[3] or parts[4]:
            raise ValueError(
                f"{label} must select a grid family with blank D and E parts"
            )
        if any("*" in part or "?" in part for part in parts):
            raise ValueError(f"{label} must not contain wildcard characters")
        return prefix, parts

    @staticmethod
    def _select_grid_family_records(
        catalog: pd.DataFrame,
        pathname: str,
        selector_parts: List[str],
    ) -> List[Tuple[pd.Timestamp, pd.Timestamp, str]]:
        """Return one validated, ordered grid family from a DSS catalog."""
        if not isinstance(catalog, pd.DataFrame) or "pathname" not in catalog:
            raise ValueError("DSS catalog must contain a pathname column")

        selector_key = tuple(
            selector_parts[index].casefold() for index in (0, 1, 2, 5)
        )
        family_variants = set()
        records: List[Tuple[pd.Timestamp, pd.Timestamp, str]] = []
        for candidate in catalog["pathname"].astype(str):
            try:
                _, candidate_parts = RasDss._split_dss_pathname(candidate)
            except ValueError:
                continue
            candidate_key = tuple(
                candidate_parts[index].casefold() for index in (0, 1, 2, 5)
            )
            if candidate_key != selector_key:
                continue

            family_variants.add(
                tuple(candidate_parts[index] for index in (0, 1, 2, 5))
            )
            start = RasDss._parse_strict_grid_dss_datetime(candidate_parts[3])
            end = RasDss._parse_strict_grid_dss_datetime(candidate_parts[4])
            if start is None or end is None or end <= start:
                raise ValueError(
                    f"Grid record has an invalid time window: {candidate}"
                )
            records.append((start, end, candidate))

        if not records:
            raise ValueError(
                f"No grid records matched pathname family {pathname}"
            )
        if len(family_variants) != 1:
            raise ValueError(
                "Grid family selector is ambiguous across case-distinct "
                f"A/B/C/F parts: {sorted(family_variants)}"
            )

        records.sort(key=lambda item: (item[0], item[1], item[2]))
        windows = [(start, end) for start, end, _ in records]
        if len(set(windows)) != len(windows):
            raise ValueError(
                "Grid family selector is ambiguous because multiple records "
                "use the same time window"
            )

        intervals = {end - start for start, end, _ in records}
        if len(intervals) != 1:
            raise ValueError("Matched grid records do not use one uniform interval")
        for previous, current in zip(records, records[1:]):
            if current[0] != previous[1]:
                raise ValueError(
                    "Matched grid records are not contiguous: "
                    f"{previous[2]} then {current[2]}"
                )
        return records

    @staticmethod
    def _grid_record_metadata_signature(grid: Dict[str, Any]) -> Dict[str, Any]:
        """Return all available write-relevant metadata for comparison."""
        metadata = grid.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("Grid record is missing metadata")
        if metadata.get("lower_left_cell") is None:
            raise ValueError("Grid record is missing lower-left cell metadata")
        compression = metadata.get("compression")
        if not isinstance(compression, dict):
            raise ValueError("Grid record is missing compression metadata")

        return {
            "shape": tuple(grid.get("shape", ())),
            "metadata_shape": tuple(metadata.get("shape", ())),
            "number_of_cells": (
                metadata.get("number_of_cells_x"),
                metadata.get("number_of_cells_y"),
            ),
            "cell_size": grid.get("cell_size"),
            "lower_left_cell": tuple(metadata["lower_left_cell"]),
            "origin": metadata.get("origin"),
            "grid_type": grid.get("grid_type"),
            "grid_class": metadata.get("grid_class"),
            "grid_type_code": metadata.get("grid_type_code"),
            "crs": grid.get("crs"),
            "units": grid.get("units"),
            "data_type": grid.get("data_type"),
            "data_type_code": metadata.get("data_type_code"),
            "nodata_value": metadata.get("nodata_value"),
            "projection": metadata.get("projection"),
            # element_size is the compressed payload length and legitimately
            # varies by record. Method/base/scale are the write configuration.
            "compression": {
                key: compression.get(key)
                for key in ("method", "base", "scale_factor")
            },
        }

    @staticmethod
    def _validate_grid_family_metadata(
        grids: List[Dict[str, Any]],
        records: List[Tuple[pd.Timestamp, pd.Timestamp, str]],
    ) -> np.ndarray:
        """Validate family metadata and return its stable NoData footprint."""
        if len(grids) != len(records) or not grids:
            raise ValueError("Grid family records could not be read completely")
        reference_signature = None
        reference_mask = None
        for grid, record in zip(grids, records):
            signature, mask = RasDss._validate_grid_record_metadata(
                grid,
                record,
                reference_signature,
                reference_mask,
            )
            if reference_signature is None:
                reference_signature = signature
                reference_mask = mask
        if reference_mask is None:
            raise ValueError("Grid family records could not be read completely")
        return reference_mask

    @staticmethod
    def _validate_grid_record_metadata(
        grid: Dict[str, Any],
        record: Tuple[pd.Timestamp, pd.Timestamp, str],
        reference_signature: Optional[Dict[str, Any]],
        reference_mask: Optional[np.ndarray],
    ) -> Tuple[Dict[str, Any], np.ndarray]:
        """Validate one streamed grid record against a compact reference."""
        start, end, record_path = record
        RasDss._validate_grid_raw_timing(grid, start, end, record_path)
        signature = RasDss._grid_record_metadata_signature(grid)
        data = np.asarray(grid.get("data"), dtype=np.float32)
        if data.ndim != 2 or data.shape != tuple(signature["shape"]):
            raise ValueError(
                f"Grid record data shape does not match its metadata: {record_path}"
            )
        if tuple(signature["metadata_shape"]) != data.shape:
            raise ValueError(
                f"Grid record metadata shape does not match its data: {record_path}"
            )
        expected_cells = (data.shape[1], data.shape[0])
        if tuple(signature["number_of_cells"]) != expected_cells:
            raise ValueError(
                f"Grid record cell counts do not match its data: {record_path}"
            )

        nodata = ~np.isfinite(data)
        reported_missing = grid["metadata"].get("number_missing")
        if reported_missing is None or int(reported_missing) != int(nodata.sum()):
            raise ValueError(
                f"Grid record NoData count disagrees with its data: {record_path}"
            )

        if reference_signature is None:
            cell_size = signature["cell_size"]
            if (
                isinstance(cell_size, bool)
                or not isinstance(cell_size, Real)
                or not isfinite(float(cell_size))
                or float(cell_size) <= 0
            ):
                raise ValueError(f"Grid family has invalid cell size: {cell_size}")
            if signature["grid_type"] not in {"albers", "specified"}:
                raise ValueError(
                    "Grid family uses an unsupported metadata class for safe "
                    f"rewrite: {signature['grid_class']}"
                )
            if signature["origin"] is None:
                raise ValueError("Grid family is missing a physical grid origin")
            return signature, nodata.copy()

        mismatched = [
            name
            for name, value in signature.items()
            if value != reference_signature[name]
        ]
        if mismatched:
            raise ValueError(
                "Matched grid records have inconsistent write metadata "
                f"({', '.join(mismatched)}): {record_path}"
            )
        if reference_mask is None or not np.array_equal(nodata, reference_mask):
            raise ValueError(
                "Matched grid records do not share one stable NoData footprint: "
                f"{record_path}"
            )
        return signature, nodata

    @staticmethod
    def _validate_grid_raw_timing(
        grid: Dict[str, Any],
        expected_start: pd.Timestamp,
        expected_end: pd.Timestamp,
        record_path: str,
    ) -> None:
        """Require independent raw and normalized timing to match a pathname."""
        metadata = grid.get("metadata")
        timing = metadata.get("timing") if isinstance(metadata, dict) else None
        if not isinstance(timing, dict):
            raise ValueError(
                f"Grid record is missing raw timing metadata: {record_path}"
            )
        raw_start = RasDss._parse_grid_raw_datetime(timing.get("start"))
        raw_end = RasDss._parse_grid_raw_datetime(timing.get("end"))
        if raw_start is None or raw_end is None:
            raise ValueError(
                f"Grid record has missing or invalid raw timing metadata: {record_path}"
            )
        if raw_start != expected_start or raw_end != expected_end:
            raise ValueError(
                "Grid record raw timing metadata disagrees with its pathname: "
                f"{record_path}"
            )
        top_start = grid.get("start_time")
        top_end = grid.get("end_time")
        if (
            top_start is None
            or top_end is None
            or pd.Timestamp(top_start) != expected_start
            or pd.Timestamp(top_end) != expected_end
        ):
            raise ValueError(
                "Grid record normalized timing disagrees with its pathname: "
                f"{record_path}"
            )

    @staticmethod
    def _parse_grid_raw_datetime(value: Any) -> Optional[pd.Timestamp]:
        """Parse only the exact pathname or Java raw grid time spellings."""
        parsed = RasDss._parse_strict_grid_dss_datetime(value)
        if parsed is not None:
            return parsed
        if not isinstance(value, str):
            return None
        match = re.fullmatch(
            r"(\d{1,2}) "
            r"(January|February|March|April|May|June|July|August|September|"
            r"October|November|December) "
            r"(\d{4}), (\d{2}):(\d{2})",
            value,
        )
        if match is None:
            return None
        day_text, month_text, year_text, hour_text, minute_text = match.groups()
        months = {
            "January": 1,
            "February": 2,
            "March": 3,
            "April": 4,
            "May": 5,
            "June": 6,
            "July": 7,
            "August": 8,
            "September": 9,
            "October": 10,
            "November": 11,
            "December": 12,
        }
        hour = int(hour_text)
        minute = int(minute_text)
        if hour == 24:
            if minute != 0:
                return None
            hour = 0
            day_offset = 1
        elif 0 <= hour <= 23 and 0 <= minute <= 59:
            day_offset = 0
        else:
            return None
        try:
            parsed_datetime = datetime(
                int(year_text),
                months[month_text],
                int(day_text),
                hour,
                minute,
            ) + timedelta(days=day_offset)
            return pd.Timestamp(parsed_datetime)
        except (OverflowError, ValueError):
            return None

    @staticmethod
    def _whole_grid_cell_shift(
        shift: float,
        cell_size: float,
        label: str,
    ) -> int:
        """Return an exact whole-cell quotient for a spatial translation."""
        try:
            quotient = Decimal(str(shift)) / Decimal(str(cell_size))
        except (InvalidOperation, ZeroDivisionError) as exc:
            raise ValueError(f"{label} cannot be resolved in grid cells") from exc
        integral = quotient.to_integral_value()
        if quotient != integral:
            raise ValueError(f"{label} must be an exact whole grid-cell increment")
        return int(integral)

    @staticmethod
    def _grid_write_info_from_record(
        grid: Dict[str, Any],
        output_lower_left: Tuple[int, int],
    ) -> Dict[str, Any]:
        """Map one validated read-grid result back to writer metadata."""
        metadata = grid["metadata"]
        projection = dict(metadata.get("projection") or {})
        compression = dict(metadata.get("compression") or {})
        required_compression = {"method", "base", "scale_factor"}
        missing_compression = sorted(required_compression - compression.keys())
        if missing_compression:
            raise ValueError(
                "Grid record is missing compression fields required for rewrite: "
                f"{missing_compression}"
            )
        required_projection = {
            "x_coord_cell_zero",
            "y_coord_cell_zero",
        }
        if grid["grid_type"] == "albers":
            required_projection.update(
                {
                    "datum_code",
                    "units",
                    "standard_parallel_1",
                    "standard_parallel_2",
                    "central_meridian",
                    "latitude_of_origin",
                    "false_easting",
                    "false_northing",
                }
            )
        missing_projection = sorted(required_projection - projection.keys())
        if missing_projection:
            raise ValueError(
                "Grid record is missing projection fields required for rewrite: "
                f"{missing_projection}"
            )
        grid_info = {
            "cell_size": float(grid["cell_size"]),
            "lower_left_cell_x": int(output_lower_left[0]),
            "lower_left_cell_y": int(output_lower_left[1]),
            "crs": grid["crs"],
            "grid_type": grid["grid_type"],
            "units": grid["units"],
            "data_type": grid["data_type"],
            "nodata_value": metadata.get("nodata_value"),
            "compression": compression.get("method"),
            "compression_element_size": 0,
            # The Java setter's final two positional values are exposed in the
            # opposite order by getCompressionBase()/getCompressionScaleFactor().
            "compression_base": compression.get("scale_factor", 0.0),
            "compression_scale_factor": compression.get("base", 100.0),
        }
        if grid["grid_type"] in {"albers", "specified"}:
            grid_info.update(
                {
                    "x_coord_cell_zero": projection.get(
                        "x_coord_cell_zero",
                        0.0,
                    ),
                    "y_coord_cell_zero": projection.get(
                        "y_coord_cell_zero",
                        0.0,
                    ),
                }
            )
        if grid["grid_type"] == "albers":
            grid_info.update(
                {
                    "projection_datum": projection.get("datum_code"),
                    "projection_units": projection.get("units"),
                    "standard_parallel_1": projection.get("standard_parallel_1"),
                    "standard_parallel_2": projection.get("standard_parallel_2"),
                    "central_meridian": projection.get("central_meridian"),
                    "latitude_of_origin": projection.get("latitude_of_origin"),
                    "false_easting": projection.get("false_easting"),
                    "false_northing": projection.get("false_northing"),
                }
            )
        return grid_info

    @staticmethod
    def _create_empty_dss(dss_file: Path, dss_version: int) -> None:
        """Create an empty DSS file at an explicit major version."""
        if dss_file.exists():
            raise FileExistsError(f"Temporary DSS path already exists: {dss_file}")
        if dss_version not in (6, 7):
            raise ValueError(f"Unsupported DSS version: {dss_version}")

        RasDss._configure_jvm()

        from jnius import autoclass

        from ras_commander.RasUtils import RasUtils

        HecDss = autoclass("hec.heclib.dss.HecDss")
        resolved_path = str(RasUtils.safe_resolve(dss_file))
        dss = None
        try:
            dss = HecDss.open(resolved_path, dss_version)
            if dss is None:
                raise RuntimeError(
                    f"HEC-DSS did not create version {dss_version}: {dss_file}"
                )
        finally:
            if dss is not None:
                dss.done()
        if not dss_file.is_file():
            raise RuntimeError(
                f"HEC-DSS did not create temporary file: {dss_file}"
            )

    @staticmethod
    def _close_dss_file(dss_file: Path) -> None:
        """Release native DSS handles associated with one resolved path."""
        RasDss._configure_jvm()

        from jnius import autoclass

        from ras_commander.RasUtils import RasUtils

        GriddedData = autoclass("hec.heclib.grid.GriddedData")
        GriddedData.close(str(RasUtils.safe_resolve(dss_file)), True)

    @staticmethod
    def _best_effort_close_dss_file(dss_file: Path, phase: str) -> None:
        """Path-close one DSS without masking a phase's primary exception."""
        try:
            RasDss._close_dss_file(dss_file)
        except Exception as exc:
            logger.warning(
                "Could not close DSS %s %s (%s)",
                dss_file,
                phase,
                exc,
            )

    @staticmethod
    def _cleanup_temporary_dss(dss_file: Path) -> None:
        """Best-effort close and removal that never masks a primary error."""
        try:
            if dss_file.exists():
                RasDss._close_dss_file(dss_file)
        except Exception as exc:
            logger.warning(
                "Could not close temporary DSS during cleanup: %s (%s)",
                dss_file,
                exc,
            )
        try:
            dss_file.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning(
                "Could not remove temporary DSS during cleanup: %s (%s)",
                dss_file,
                exc,
            )

    @staticmethod
    def _split_dss_pathname(pathname: str) -> Tuple[str, List[str]]:
        """Return DSS pathname prefix and six A-F parts."""
        if (
            not isinstance(pathname, str)
            or not pathname.startswith("/")
            or not pathname.endswith("/")
        ):
            raise ValueError(f"DSS pathname must start and end with '/': {pathname}")

        prefix = "//" if pathname.startswith("//") else "/"
        parts = pathname.split("/")
        path_parts = parts[2:-1] if prefix == "//" else parts[1:-1]
        if len(path_parts) != 6:
            raise ValueError(
                "DSS pathname must have 6 parts (/A/B/C/D/E/F/), "
                f"got {len(path_parts)}: {pathname}"
            )
        return prefix, path_parts

    @staticmethod
    def _build_dss_pathname(prefix: str, parts: List[str]) -> str:
        """Build a DSS pathname from a prefix and A-F parts."""
        if len(parts) != 6:
            raise ValueError(f"Expected 6 DSS pathname parts, got {len(parts)}")
        if prefix == "//":
            return f"//{'/'.join(parts)}/"
        return f"/{'/'.join(parts)}/"

    @staticmethod
    def _format_grid_dss_datetime(value: pd.Timestamp) -> str:
        """Format datetime for DSS grid D/E pathname parts."""
        return pd.Timestamp(value).strftime("%d%b%Y:%H%M").upper()

    @staticmethod
    def _parse_grid_dss_datetime(value: str) -> Optional[pd.Timestamp]:
        """Parse a DSS grid D/E datetime part, returning None when blank."""
        if not value:
            return None
        if value.endswith(":2400"):
            day = pd.Timestamp(pd.to_datetime(value[:-5], format="%d%b%Y"))
            return day + pd.Timedelta(days=1)
        try:
            return pd.Timestamp(pd.to_datetime(value, format="%d%b%Y:%H%M"))
        except ValueError:
            try:
                return pd.Timestamp(pd.to_datetime(value.replace(":", " ")))
            except Exception:
                return None

    @staticmethod
    def _parse_strict_grid_dss_datetime(value: str) -> Optional[pd.Timestamp]:
        """Parse exact minute-granularity DSS grid time with a 2400 exception."""
        if not isinstance(value, str) or not value:
            return None
        match = re.fullmatch(
            r"(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
            r"(\d{4}):(\d{2})(\d{2})",
            value,
        )
        if match is None:
            return None
        day_text, month_text, year_text, hour_text, minute_text = match.groups()
        months = {
            "JAN": 1,
            "FEB": 2,
            "MAR": 3,
            "APR": 4,
            "MAY": 5,
            "JUN": 6,
            "JUL": 7,
            "AUG": 8,
            "SEP": 9,
            "OCT": 10,
            "NOV": 11,
            "DEC": 12,
        }
        hour = int(hour_text)
        minute = int(minute_text)
        if hour == 24:
            if minute != 0:
                return None
            hour = 0
            day_offset = 1
        elif 0 <= hour <= 23 and 0 <= minute <= 59:
            day_offset = 0
        else:
            return None
        try:
            parsed = datetime(
                int(year_text),
                months[month_text],
                int(day_text),
                hour,
                minute,
            ) + timedelta(days=day_offset)
            return pd.Timestamp(parsed)
        except (OverflowError, ValueError):
            return None

    @staticmethod
    def _split_grid_datetime_part(value: str) -> Tuple[str, str]:
        """Split a DSS grid datetime part into HecTime date and time strings."""
        if ":" not in value:
            raise ValueError(f"Grid datetime part must contain ':': {value}")
        date_part, time_part = value.split(":", 1)
        return date_part, time_part

    @staticmethod
    def _grid_data_type_code(data_type: str) -> int:
        """Return HEC grid data type code for a DSS data type string."""
        data_type_codes = {
            "PER-AVER": 0,
            "PER-CUM": 1,
            "INST-VAL": 2,
            "INST-CUM": 3,
            "FREQ": 4,
            "PER-MIN": 6,
            "PER-MAX": 7,
        }
        normalized = str(data_type).upper().replace("_", "-")
        if normalized not in data_type_codes:
            raise ValueError(
                f"Unsupported grid data_type '{data_type}'. "
                f"Valid values: {sorted(data_type_codes)}"
            )
        return data_type_codes[normalized]

    @staticmethod
    def _reject_timezone_aware_times(
        times: Union[List, np.ndarray, pd.DatetimeIndex],
    ) -> None:
        """Reject timestamps whose model-clock representation is ambiguous.

        HEC-DSS records store calendar-clock values without timezone metadata.
        Silently converting aware timestamps would choose a model clock on the
        caller's behalf, so writers require callers to convert to the intended
        clock and remove timezone metadata explicitly.
        """
        if isinstance(times, pd.DatetimeIndex):
            if times.tz is not None:
                raise ValueError(
                    "times must be timezone-naive; explicitly convert to the "
                    "intended HEC-RAS model clock and remove timezone metadata "
                    "before writing"
                )
            return

        if (
            isinstance(times, np.ndarray)
            and np.issubdtype(times.dtype, np.datetime64)
        ):
            return

        values = [times] if isinstance(times, (str, bytes)) else list(times)
        for value in values:
            parsed = value
            if isinstance(value, str):
                try:
                    parsed = pd.Timestamp(value)
                except (TypeError, ValueError, OverflowError):
                    continue
            if getattr(parsed, "tzinfo", None) is not None or getattr(
                parsed,
                "tz",
                None,
            ) is not None:
                raise ValueError(
                    "times must be timezone-naive; explicitly convert to the "
                    "intended HEC-RAS model clock and remove timezone metadata "
                    "before writing"
                )

    @staticmethod
    def _grid_time_windows(
        times: Union[List, np.ndarray, pd.DatetimeIndex],
        n_times: int,
        data_type_code: int,
        grid_info: Dict[str, Any],
        pathname_parts: List[str],
    ) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
        """Convert user times into per-grid start/end windows."""
        RasDss._reject_timezone_aware_times(times)
        dt_index = pd.DatetimeIndex(pd.to_datetime(times))

        if len(dt_index) == n_times + 1:
            return [
                (pd.Timestamp(dt_index[i]), pd.Timestamp(dt_index[i + 1]))
                for i in range(n_times)
            ]

        if len(dt_index) != n_times:
            raise ValueError(
                "times must contain n_times end times or n_times + 1 boundary "
                f"times; got {len(dt_index)} times for {n_times} grid frames"
            )

        end_times = [pd.Timestamp(value) for value in dt_index]
        if data_type_code in (2, 3):  # INST-VAL or INST-CUM
            return [(value, value) for value in end_times]

        interval_minutes = grid_info.get("interval_minutes")
        if interval_minutes is None and len(end_times) > 1:
            deltas = np.diff(np.array(end_times, dtype="datetime64[m]")).astype(int)
            positive_deltas = deltas[deltas > 0]
            if len(positive_deltas):
                interval_minutes = int(np.median(positive_deltas))

        if interval_minutes is None:
            pathname_start = RasDss._parse_grid_dss_datetime(pathname_parts[3])
            pathname_end = RasDss._parse_grid_dss_datetime(pathname_parts[4])
            if pathname_start is not None and pathname_end is not None:
                delta = pathname_end - pathname_start
                interval_minutes = int(delta.total_seconds() // 60)

        if interval_minutes is None:
            interval_minutes = 60

        interval = pd.Timedelta(minutes=int(interval_minutes))
        if interval <= pd.Timedelta(0):
            raise ValueError(
                f"Grid interval must be positive, got {interval_minutes} minutes"
            )

        return [(value - interval, value) for value in end_times]

    @staticmethod
    def _grid_info_number(
        grid_info: Dict[str, Any],
        keys: List[str],
        default: Any = None,
    ) -> Any:
        """Return first present grid_info numeric value."""
        for key in keys:
            if key in grid_info and grid_info[key] is not None:
                return grid_info[key]
        return default

    @staticmethod
    def _grid_origin_xy(
        grid_info: Dict[str, Any]
    ) -> Tuple[Optional[float], Optional[float]]:
        """Extract optional physical lower-left origin from grid_info."""
        if "origin" not in grid_info or grid_info["origin"] is None:
            return (
                grid_info.get("origin_x"),
                grid_info.get("origin_y"),
            )

        origin = grid_info["origin"]
        if isinstance(origin, dict):
            return (
                origin.get("x", origin.get("origin_x")),
                origin.get("y", origin.get("origin_y")),
            )
        if isinstance(origin, (list, tuple)) and len(origin) >= 2:
            return origin[0], origin[1]
        raise ValueError("grid_info['origin'] must be (x, y) or a dict with x/y")

    @staticmethod
    def _hec_projection_datum(GridInfo: Any, datum: Any) -> int:
        """Normalize projection datum to a HEC GridInfo datum code."""
        if isinstance(datum, int):
            return datum
        datum_text = str(datum or "NAD83").upper().replace("_", "")
        if datum_text == "NAD27":
            return GridInfo.getNad27()
        if datum_text == "UNDEFINED":
            return GridInfo.getUndefinedProjectionDatum()
        return GridInfo.getNad83()

    @staticmethod
    def _create_java_grid_info(
        grid_info: Dict[str, Any],
        n_rows: int,
        n_cols: int,
        start_part: str,
        end_part: str,
        data_type_code: int,
        GridInfo: Any,
        AlbersInfo: Any,
        SpecifiedGridInfo: Any,
        HrapInfo: Any,
    ) -> Any:
        """Create and populate the Java GridInfo subclass for one record."""
        cell_size = RasDss._grid_info_number(
            grid_info,
            ["cellsize", "cell_size", "cell_size_m", "dx", "resolution"],
        )
        if cell_size is None:
            raise ValueError("grid_info must include cellsize or cell_size")
        cell_size = float(cell_size)
        if cell_size <= 0:
            raise ValueError(f"cellsize must be positive, got {cell_size}")

        x_cell_zero = float(
            RasDss._grid_info_number(
                grid_info,
                ["x_coord_cell_zero", "x_coord_of_grid_cell_zero", "x_cell_zero"],
                0.0,
            )
        )
        y_cell_zero = float(
            RasDss._grid_info_number(
                grid_info,
                ["y_coord_cell_zero", "y_coord_of_grid_cell_zero", "y_cell_zero"],
                0.0,
            )
        )

        origin_x, origin_y = RasDss._grid_origin_xy(grid_info)
        lower_left_cell_x = RasDss._grid_info_number(
            grid_info,
            ["lower_left_cell_x", "lowerLeftCellX", "ll_cell_x"],
        )
        lower_left_cell_y = RasDss._grid_info_number(
            grid_info,
            ["lower_left_cell_y", "lowerLeftCellY", "ll_cell_y"],
        )
        if lower_left_cell_x is None:
            if origin_x is None:
                lower_left_cell_x = 0
            else:
                lower_left_cell_x = int(
                    round((float(origin_x) - x_cell_zero) / cell_size)
                )
        if lower_left_cell_y is None:
            if origin_y is None:
                lower_left_cell_y = 0
            else:
                lower_left_cell_y = int(
                    round((float(origin_y) - y_cell_zero) / cell_size)
                )

        crs = str(grid_info.get("crs", "SHG"))
        grid_type = str(grid_info.get("grid_type", "")).lower()
        crs_upper = crs.upper()
        if not grid_type:
            if crs_upper in {"SHG", "EPSG:5070", "5070"} or "ALBERS" in crs_upper:
                grid_type = "albers"
            else:
                grid_type = "specified"

        if grid_type == "hrap":
            java_grid_info = HrapInfo()
            data_source = grid_info.get("data_source")
            if data_source:
                java_grid_info.setDataSource(str(data_source))
        elif grid_type == "specified":
            java_grid_info = SpecifiedGridInfo()
            java_grid_info.setSpatialReference(
                str(grid_info.get("crs_name", "Specified Grid")),
                crs,
                x_cell_zero,
                y_cell_zero,
            )
        else:
            java_grid_info = AlbersInfo()
            java_grid_info.setProjectionInfo(
                RasDss._hec_projection_datum(
                    GridInfo,
                    grid_info.get("projection_datum", "NAD83"),
                ),
                str(grid_info.get("projection_units", "METERS")),
                float(grid_info.get("standard_parallel_1", 29.5)),
                float(grid_info.get("standard_parallel_2", 45.5)),
                float(grid_info.get("central_meridian", -96.0)),
                float(grid_info.get("latitude_of_origin", 23.0)),
                float(grid_info.get("false_easting", 0.0)),
                float(grid_info.get("false_northing", 0.0)),
                x_cell_zero,
                y_cell_zero,
            )

        java_grid_info.setCellInfo(
            int(lower_left_cell_x),
            int(lower_left_cell_y),
            int(n_cols),
            int(n_rows),
            cell_size,
        )
        java_grid_info.setParameterInfo(str(grid_info.get("units", "mm")), data_type_code)
        java_grid_info.setGridTimes(start_part, end_part)

        compression = grid_info.get("compression", "PRECIP_2_BYTE")
        if compression is not None:
            if isinstance(compression, int):
                compression_method = compression
            else:
                compression_text = str(compression).upper().replace("-", "_")
                if compression_text in {"PRECIP", "PRECIP2BYTE", "PRECIP_2_BYTE"}:
                    compression_method = GridInfo.getPrecip2Byte()
                elif compression_text in {"ZLIB", "ZLIB_DEFLATE"}:
                    compression_method = GridInfo.getZlibDeflate()
                elif compression_text in {"NONE", "UNDEFINED"}:
                    compression_method = GridInfo.getUndefinedCompressionMethod()
                else:
                    raise ValueError(f"Unsupported grid compression: {compression}")
            java_grid_info.setCompressionInfo(
                int(compression_method),
                int(grid_info.get("compression_element_size", 0)),
                float(grid_info.get("compression_base", 0.0)),
                float(grid_info.get("compression_scale_factor", 100.0)),
            )

        return java_grid_info

    @staticmethod
    def _datetimes_to_hec_times(
        times: Union[List, np.ndarray, pd.DatetimeIndex]
    ) -> np.ndarray:
        """
        Convert datetime values to HEC epoch times (minutes since 1899-12-31).

        Args:
            times: Array of datetime-like values

        Returns:
            numpy int32 array of minutes since HEC epoch
            (1899-12-31 00:00:00)
        """
        hec_epoch = np.datetime64('1899-12-31T00:00:00', 'm')
        RasDss._reject_timezone_aware_times(times)

        try:
            if isinstance(times, pd.DatetimeIndex):
                datetime_values = times.values.astype('datetime64[us]')
            elif isinstance(times, np.ndarray):
                datetime_values = times.astype('datetime64[us]')
            else:
                datetime_values = pd.to_datetime(times).to_numpy(
                    dtype='datetime64[us]'
                )
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("times must contain valid datetime values") from exc

        if np.isnat(datetime_values).any():
            raise ValueError("times must not contain NaT values")

        minute_values = datetime_values.astype('datetime64[m]')
        if not np.array_equal(
            datetime_values,
            minute_values.astype('datetime64[us]'),
        ):
            raise ValueError("times must be aligned exactly to whole minutes")

        minutes = (
            (minute_values - hec_epoch)
            .astype('timedelta64[m]')
            .astype(np.int64)
        )
        if minutes.size:
            int32_info = np.iinfo(np.int32)
            if minutes.min() < int32_info.min or minutes.max() > int32_info.max:
                raise ValueError("times exceed the supported HEC int32 minute range")

        return minutes.astype(np.int32)


if __name__ == "__main__":
    """Test RasDss class"""
    import sys

    print("="*80)
    print("RasDss Test")
    print("="*80)

    # Test file (from TestData)
    test_data_dir = Path(__file__).parent.parent.parent / "TestData"

    # Find a DSS file to test with
    dss_files = list(test_data_dir.glob("*.dss"))

    if not dss_files:
        print("No DSS files found in TestData/")
        sys.exit(1)

    # Use BaldEagleDamBrk.dss (V7 file that we know works)
    test_file = test_data_dir / "BaldEagleDamBrk.dss"

    if not test_file.exists():
        # Use first available file
        test_file = dss_files[0]

    print(f"\nTest file: {test_file.name}")
    print(f"Size: {test_file.stat().st_size / 1024:.2f} KB")

    # Get file info
    print("\n" + "-"*80)
    print("Getting file info...")
    print("-"*80)
    info = RasDss.get_info(test_file)
    for key, value in info.items():
        if key == 'first_5_paths':
            print(f"{key}:")
            for path in value:
                print(f"  - {path}")
        else:
            print(f"{key}: {value}")

    # Get full catalog
    print("\n" + "-"*80)
    print("Getting catalog...")
    print("-"*80)
    catalog = RasDss.get_catalog(test_file)
    print(f"Total paths: {len(catalog)}")

    if len(catalog) > 0:
        # Read first time series
        print("\n" + "-"*80)
        print(f"Reading time series: {catalog[0]}")
        print("-"*80)
        df = RasDss.read_timeseries(test_file, catalog[0])

        print(f"\nDataFrame shape: {df.shape}")
        print(f"Date range: {df.index.min()} to {df.index.max()}")
        print(f"Value range: {df['value'].min():.2f} to {df['value'].max():.2f}")
        print(f"Units: {df.attrs.get('units', 'N/A')}")

        print("\nFirst 10 rows:")
        print(df.head(10))

        print("\nLast 10 rows:")
        print(df.tail(10))

    print("\n" + "="*80)
    print("Test complete!")
    print("="*80)
