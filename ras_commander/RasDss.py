"""
RasDss - DSS File Operations for ras-commander

Read HEC-DSS files (V6 and V7) using HEC Monolith libraries via pyjnius.
Lazy loading - no imports until methods are called.

Based on dssrip2 approach: https://github.com/mkoohafkan/dssrip2
Java bridge: pyjnius (https://pyjnius.readthedocs.io/)
"""

import sys
import os
from pathlib import Path
from typing import List, Dict, Optional, Union
import pandas as pd
import numpy as np
import logging

from .Decorators import log_call

logger = logging.getLogger(__name__)


class RasDss:
    """
    Static class for DSS file operations.

    Uses HEC Monolith libraries (auto-downloaded on first use).
    Supports both DSS V6 and V7 formats.

    Usage:
        from RasDss import RasDss

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

        # Lazy import
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

        # Lazy import pyjnius
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
                    "Java not found. Please set JAVA_HOME environment variable or install Java JDK/JRE.\n"
                    "Download from: https://www.oracle.com/java/technologies/downloads/"
                )

        # Set classpath (must be done before first import from jnius)
        jnius_config.add_classpath(*classpath)

        # Set library path for native libraries
        if 'LD_LIBRARY_PATH' in os.environ:
            os.environ['LD_LIBRARY_PATH'] = library_path + ':' + os.environ['LD_LIBRARY_PATH']
        else:
            os.environ['LD_LIBRARY_PATH'] = library_path

        # Windows: Add to PATH for native DLLs
        if os.name == 'nt':
            os.environ['PATH'] = library_path + os.pathsep + os.environ.get('PATH', '')

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

        # Import Java classes via pyjnius
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

        # Import Java classes via pyjnius
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
            values = np.array(tsc.values)  # Java double[] → Python list → numpy array
            times = np.array(tsc.times)    # Java int[] → Python list → numpy array (minutes since 1899-12-31)

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
            df.attrs['interval'] = int(tsc.interval) if hasattr(tsc, 'interval') else None
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
            from ras_commander import init_ras_project
            from ras_commander.RasDss import RasDss

            ras = init_ras_project("project_path", "6.6")

            # Extract all DSS boundary data
            enhanced_boundaries = RasDss.extract_boundary_timeseries(ras.boundaries_df, ras_object=ras)

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
                logger.info(f"Row {idx}: Extracted {len(df_ts)} points from {dss_file_path.name}")

            except Exception as e:
                logger.warning(f"Row {idx}: Failed to read DSS data: {e}")
                fail_count += 1

        logger.info(f"Extraction complete: {success_count} success, {fail_count} failed")

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


if __name__ == "__main__":
    """Test RasDss class"""
    import sys

    print("="*80)
    print("RasDss Test")
    print("="*80)

    # Test file (from TestData)
    test_data_dir = Path(__file__).parent.parent / "TestData"

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
