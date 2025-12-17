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
from typing import List, Dict, Optional, Union
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
            print("\n" + "="*80)
            print("HEC Monolith libraries not found")
            print("Installing automatically (one-time download, ~20 MB)...")
            print("="*80)
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

        # Check if JVM already started
        try:
            from jnius import autoclass
            # If this succeeds, JVM already started
            RasDss._jvm_configured = True
            return
        except:
            pass

        # Get classpath and library path
        classpath = monolith.get_classpath()
        library_path = monolith.get_library_path()

        print("Configuring Java VM for DSS operations...")

        # Set JAVA_HOME if not already set
        if 'JAVA_HOME' not in os.environ:
            # Try to find Java
            java_candidates = [
                Path("C:/Program Files/Java/jre1.8.0_471"),
                Path("C:/Program Files/Java/jdk-11"),
                Path("C:/Program Files/Java/jdk-17"),
                Path("C:/Program Files (x86)/Java/jre1.8.0_471"),
            ]
            for java_home in java_candidates:
                if java_home.exists():
                    os.environ['JAVA_HOME'] = str(java_home)
                    print(f"  Found Java: {java_home}")
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
        print("[OK] Java VM configured")

    @staticmethod
    @log_call
    def get_catalog(dss_file: Union[str, Path]) -> List[str]:
        """
        Get list of all data paths in DSS file.

        Args:
            dss_file: Path to DSS file

        Returns:
            List of DSS path strings

        Example:
            paths = RasDss.get_catalog("sample.dss")
            for path in paths:
                print(path)
        """
        # Configure JVM (must be before first jnius import)
        RasDss._configure_jvm()

        # Import Java classes via pyjnius (lazy)
        from jnius import autoclass

        HecDss = autoclass('hec.heclib.dss.HecDss')

        dss_file = str(Path(dss_file).resolve())

        # Open DSS file
        dss = HecDss.open(dss_file)

        try:
            # Get catalog (returns Java Vector of pathname strings)
            catalog_vector = dss.getCatalogedPathnames()

            # Convert Java Vector to Python list
            paths = []
            for i in range(catalog_vector.size()):
                paths.append(str(catalog_vector.get(i)))

            return paths

        finally:
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

        HecDss = autoclass('hec.heclib.dss.HecDss')
        TimeSeriesContainer = autoclass('hec.io.TimeSeriesContainer')

        dss_file = str(Path(dss_file).resolve())

        # Open DSS file
        dss = HecDss.open(dss_file)

        try:
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
                print(f"Warning: Could not read {pathname}: {e}")
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
        dss_path = Path(dss_file)

        catalog = RasDss.get_catalog(dss_file)

        return {
            'filepath': str(dss_path.resolve()),
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

            ras = init_ras_project("project_path", "6.6")

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
            logger.info("No DSS-defined boundaries found")
            return result_df

        logger.info(f"Found {len(dss_boundaries)} DSS-defined boundaries")

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
                logger.info(
                    f"Row {idx}: Extracted {len(df_ts)} points from "
                    f"{dss_file_path.name}"
                )

            except Exception as e:
                logger.warning(f"Row {idx}: Failed to read DSS data: {e}")
                fail_count += 1

        logger.info(
            f"Extraction complete: {success_count} success, {fail_count} failed"
        )

        return result_df

    @staticmethod
    def shutdown_jvm():
        """
        Shutdown Java Virtual Machine.

        Note: With pyjnius, JVM shutdown is typically not needed.
        This is a placeholder for API compatibility.
        """
        logger.info("pyjnius handles JVM lifecycle automatically")
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
        - Format: //A/B/C/D/E/F/
        - Parts: A (basin/project), B (location), C (parameter),
                 D (date), E (interval), F (scenario)

        Args:
            pathname: DSS pathname to validate

        Returns:
            ValidationResult with detailed diagnostics

        Example:
            >>> from ras_commander.dss import RasDss
            >>> result = RasDss.check_pathname_format("//BASIN/LOC/FLOW/01JAN2020/1HOUR/OBS/")
            >>> print(result.passed)
            True
        """
        # Lazy import validation framework
        try:
            from ..validation_base import ValidationResult, ValidationSeverity
        except ImportError:
            # Return basic dict if validation framework not available
            if pathname.startswith('//') and pathname.endswith('/') and pathname.count('/') == 8:
                return {'passed': True, 'message': 'Format appears valid (validation framework not available)'}
            else:
                return {'passed': False, 'message': 'Format appears invalid (validation framework not available)'}

        # Check start with '//' and end with '/'
        if not pathname.startswith('//'):
            return ValidationResult(
                check_name="path_format",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"DSS path must start with '//': {pathname}",
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
        # DSS path format: //A/B/C/D/E/F/
        # Split by '/' gives: ['', '', 'A', 'B', 'C', 'D', 'E', 'F', '']
        parts = pathname.split('/')
        # Expected: 9 parts (2 empty at start, 6 data parts, 1 empty at end)
        if len(parts) != 9:
            return ValidationResult(
                check_name="path_format",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"DSS path must have 6 parts (//A/B/C/D/E/F/), got {len(parts)-3}: {pathname}",
                details={
                    "pathname": pathname,
                    "expected_parts": 6,
                    "actual_parts": len(parts) - 3
                }
            )

        # Extract parts (skip first two empty and last empty)
        part_names = ['basin', 'location', 'parameter', 'date', 'interval', 'scenario']
        part_values = parts[2:-1]

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
            from ..validation_base import ValidationResult, ValidationSeverity
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
            from ..validation_base import ValidationResult, ValidationSeverity
        except ImportError:
            # Try basic check without validation framework
            try:
                catalog = RasDss.get_catalog(dss_file)
                if pathname in catalog:
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

        # Check exact match
        if pathname in catalog:
            return ValidationResult(
                check_name="pathname_existence",
                severity=ValidationSeverity.INFO,
                passed=True,
                message="Pathname exists in DSS file",
                details={"total_paths": len(catalog)}
            )

        # Try case-insensitive match (DSS is case-sensitive but provide hint)
        pathname_upper = pathname.upper()
        if pathname_upper in [p.upper() for p in catalog]:
            return ValidationResult(
                check_name="pathname_existence",
                severity=ValidationSeverity.WARNING,
                passed=True,
                message="Pathname exists but case differs (DSS is case-sensitive)",
                details={"total_paths": len(catalog)}
            )

        # Find similar paths (match on location part - index 2)
        parts = pathname.split('/')
        if len(parts) >= 3:
            location = parts[2]
            similar = [p for p in catalog if location in p]
        else:
            similar = []

        return ValidationResult(
            check_name="pathname_existence",
            severity=ValidationSeverity.ERROR,
            passed=False,
            message="Pathname not found in DSS file",
            details={
                "pathname": pathname,
                "total_paths": len(catalog),
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
            from ..validation_base import ValidationResult, ValidationSeverity
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
            from ..validation_base import ValidationReport
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
