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

import sys
import os
from pathlib import Path
from typing import Any, List, Dict, Optional, Tuple, Union
import logging

# Lazy imports - these are always needed for type hints and basic operations
import pandas as pd
import numpy as np

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
        - Format: /A/B/C/D/E/F/ (common) or //A/B/C/D/E/F/ (accepted)
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
                and pathname.strip('/').count('/') == 5
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

        # Split and validate parts
        # DSS path format is typically: /A/B/C/D/E/F/
        # Split by '/' gives: ['', 'A', 'B', 'C', 'D', 'E', 'F', '']
        # Some tools use: //A/B/C/D/E/F/
        # Split by '/' gives: ['', '', 'A', 'B', 'C', 'D', 'E', 'F', '']
        parts = pathname.split('/')
        if pathname.startswith('//'):
            expected_len = 9
            part_values = parts[2:-1]  # skip two empties + trailing empty
        else:
            expected_len = 8
            part_values = parts[1:-1]  # skip leading empty + trailing empty

        if len(parts) != expected_len:
            return ValidationResult(
                check_name="path_format",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=(
                    "DSS path must have 6 parts "
                    "(/A/B/C/D/E/F/), got "
                    f"{len(pathname.strip('/').split('/'))}: {pathname}"
                ),
                details={
                    "pathname": pathname,
                    "expected_parts": 6,
                    "actual_parts": len(pathname.strip('/').split('/'))
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
            times: Datetime values. Pass ``n_times + 1`` values to provide
                explicit interval boundaries, or ``n_times`` values to provide
                interval end times. For ``n_times`` period data, the interval is
                inferred from ``grid_info["interval_minutes"]``, consecutive
                times, the pathname D/E parts, or 60 minutes.
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

        Returns:
            List of DSS pathnames written, one per timestep.

        Raises:
            FileNotFoundError: If DSS file doesn't exist and
                create_if_missing=False.
            ValueError: If inputs are malformed or grid metadata is incomplete.
            ImportError: If pyjnius is not installed.
            RuntimeError: If the Java grid write operation fails.

        Notes:
            HEC Monolith 3.3.x exposes ``hec.io.GridContainer`` and
            ``hec.heclib.grid.GridData/GridInfo`` for grid records. This method
            writes through ``hec.heclib.grid.GriddedData.storeGriddedData()``
            because it is the stable Java API path from pyjnius for grid data.
        """
        RasDss._configure_jvm()

        from jnius import autoclass
        from ras_commander.RasUtils import RasUtils

        if grid_info is None:
            raise ValueError("grid_info is required")

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
        if not dss_path.exists():
            if not create_if_missing:
                raise FileNotFoundError(f"DSS file not found: {dss_path}")
            dss_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"DSS file will be created: {dss_path}")

        dss_file_str = str(RasUtils.safe_resolve(dss_path))

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
    def write_timeseries(
        dss_file: Union[str, Path],
        pathname: str,
        times: Union[List, np.ndarray, pd.DatetimeIndex],
        values: Union[List, np.ndarray],
        units: str = "CFS",
        data_type: str = "INST-VAL",
        create_if_missing: bool = True,
    ) -> None:
        """
        Write a time series to a DSS file.

        Creates or updates a time series record in a DSS file using the
        HEC Monolith Java bridge. Supports DSS V6 and V7 formats.

        Args:
            dss_file: Path to DSS file (created if missing and create_if_missing=True)
            pathname: DSS pathname (e.g., "//BASIN/LOCATION/FLOW//1HOUR/FORECAST/")
            times: Array of datetime values (datetime objects, DatetimeIndex, or
                   numpy datetime64 array)
            values: Array of numeric values (same length as times)
            units: Data units string (e.g., "CFS", "FEET", "MM", "IN")
            data_type: DSS data type string:
                - "INST-VAL" - Instantaneous values (default)
                - "PER-AVER" - Period average (e.g., precipitation)
                - "PER-CUM"  - Period cumulative
                - "INST-CUM" - Instantaneous cumulative
            create_if_missing: Create DSS file if it doesn't exist (default True)

        Raises:
            FileNotFoundError: If DSS file doesn't exist and create_if_missing=False
            ValueError: If times and values have different lengths
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
        RasDss._configure_jvm()

        from jnius import autoclass
        from ras_commander.RasUtils import RasUtils

        # Validate inputs
        values = np.asarray(values, dtype=np.float64)
        if len(times) != len(values):
            raise ValueError(
                f"times ({len(times)}) and values ({len(values)}) must have same length"
            )
        if len(times) == 0:
            raise ValueError("times and values must not be empty")

        # Resolve DSS file path
        dss_path = Path(dss_file)
        if not dss_path.exists():
            if not create_if_missing:
                raise FileNotFoundError(f"DSS file not found: {dss_path}")
            # HecDss.open() will create the file
            dss_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"DSS file will be created: {dss_path.name}")
            logger.debug(f"DSS file creation path: {dss_path}")

        dss_file_str = str(RasUtils.safe_resolve(dss_path))

        # Convert times to HEC epoch (minutes since 1899-12-31)
        hec_times = RasDss._datetimes_to_hec_times(times)

        # Detect interval from time spacing
        if len(hec_times) > 1:
            intervals = np.diff(hec_times)
            interval_minutes = int(np.median(intervals))
        else:
            interval_minutes = 60  # Default 1 hour

        # Load Java classes
        HecDss = autoclass('hec.heclib.dss.HecDss')
        TimeSeriesContainer = autoclass('hec.io.TimeSeriesContainer')

        # Create TimeSeriesContainer
        tsc = TimeSeriesContainer()
        tsc.fullName = pathname
        tsc.units = units
        tsc.type = data_type
        tsc.interval = interval_minutes

        # Set times array (Java int[])
        n = len(values)
        tsc.numberValues = n

        # Convert numpy arrays to Java-compatible arrays
        # pyjnius handles int[] and double[] conversion from Python lists
        tsc.times = hec_times.tolist()
        tsc.values = values.tolist()

        # Open DSS file and write
        dss = None
        try:
            dss = HecDss.open(dss_file_str)
            dss.put(tsc)
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
    ) -> None:
        """
        Write a time series DataFrame to a DSS file.

        Convenience wrapper around write_timeseries() that accepts a DataFrame
        with a DatetimeIndex and a value column.

        Args:
            dss_file: Path to DSS file
            pathname: DSS pathname
            df: DataFrame with DatetimeIndex and value column
            value_column: Name of column containing values (default "value")
            units: Data units string
            data_type: DSS data type string
            create_if_missing: Create DSS file if it doesn't exist

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
        try:
            return pd.Timestamp(pd.to_datetime(value, format="%d%b%Y:%H%M"))
        except ValueError:
            try:
                return pd.Timestamp(pd.to_datetime(value.replace(":", " ")))
            except Exception:
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
    def _grid_time_windows(
        times: Union[List, np.ndarray, pd.DatetimeIndex],
        n_times: int,
        data_type_code: int,
        grid_info: Dict[str, Any],
        pathname_parts: List[str],
    ) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
        """Convert user times into per-grid start/end windows."""
        dt_index = pd.DatetimeIndex(pd.to_datetime(times))
        if dt_index.tz is not None:
            dt_index = dt_index.tz_convert(None)

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
            numpy int array of minutes since HEC epoch (1899-12-31 00:00:00)
        """
        HEC_EPOCH = np.datetime64('1899-12-31T00:00:00')

        if isinstance(times, pd.DatetimeIndex):
            dt64 = times.values.astype('datetime64[m]')
        elif isinstance(times, np.ndarray):
            dt64 = times.astype('datetime64[m]')
        else:
            # List of datetime objects
            dt64 = np.array(times, dtype='datetime64[m]')

        # Calculate minutes since HEC epoch
        delta = dt64 - HEC_EPOCH
        minutes = delta.astype(np.int64)

        if minutes.max() > np.iinfo(np.int32).max:
            logger.warning(
                f"HEC epoch minutes ({minutes.max()}) exceeds int32 range; "
                "passing as int64 — verify HEC-DSS Java bridge accepts int64"
            )
        return minutes


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
