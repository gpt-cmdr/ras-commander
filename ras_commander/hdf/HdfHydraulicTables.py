"""
HdfHydraulicTables - Extract hydraulic property tables (HTAB) from HEC-RAS geometry HDF files

All methods are static and designed to be used without instantiation.

Hydraulic property tables contain preprocessed hydraulic properties computed during
geometry preprocessing. These tables enable hydraulic analysis without re-running HEC-RAS,
including:
- Area vs elevation curves
- Conveyance vs elevation
- Wetted perimeter vs elevation
- Top width vs elevation
- Rating curves and stage-discharge relationships

Available Functions:
- get_xs_htab() - Extract property table for a single cross section
- get_all_xs_htabs() - Extract property tables for all cross sections

Technical Notes:
    Property tables are stored in geometry HDF files (.g##.hdf), NOT plan HDF files.
    Path: /Geometry/Cross Sections/Property Tables/

    Data Structure:
        - XSEC Info: Index array mapping XS to property table rows [start_index, count, ds_cell]
        - XSEC Value: Property table data (N rows × 23 columns)
        - Variables attribute: Column names and units

    23 Hydraulic Properties Available:
        1. Elevation
        2-4. Area (LOB, Channel, ROB)
        5-7. Area Ineffective (LOB, Channel, ROB)
        8-10. Conveyance (LOB, Channel, ROB)
        11-13. Wetted Perimeter (LOB, Channel, ROB)
        14-16. Manning's n (LOB, Channel, ROB)
        17-20. Top Width (Total, LOB, Channel, ROB)
        21. Alpha (velocity distribution coefficient)
        22. Storage Area
        23. Beta (momentum coefficient)

Example Usage:
    >>> from ras_commander import HdfHydraulicTables
    >>> from pathlib import Path
    >>>
    >>> # Get property table for specific cross section
    >>> hdf_file = Path("BaldEagle.g01.hdf")
    >>> htab = HdfHydraulicTables.get_xs_htab(hdf_file, "Bald Eagle", "Loc Hav", "1")
    >>>
    >>> # Plot area-elevation curve
    >>> import matplotlib.pyplot as plt
    >>> plt.plot(htab['Elevation'], htab['Area_Total'])
    >>> plt.xlabel('Elevation (ft)')
    >>> plt.ylabel('Area (sq ft)')
    >>> plt.title('Cross Section Area-Elevation Curve')
    >>> plt.show()
    >>>
    >>> # Calculate flow at specific stage
    >>> target_elev = 665.0
    >>> idx = (htab['Elevation'] - target_elev).abs().idxmin()
    >>> flow_area = htab.loc[idx, 'Area_Total']
    >>> conveyance = htab.loc[idx, 'Conveyance_Total']
    >>> print(f"At elevation {target_elev} ft:")
    >>> print(f"  Flow area: {flow_area:.1f} sq ft")
    >>> print(f"  Conveyance: {conveyance:.1f} cfs")

References:
    - See HdfXsec for cross section geometry extraction
    - See RasGeometry for plain text geometry operations
    - Property tables computed during geometry preprocessing in HEC-RAS
"""

from pathlib import Path
from typing import Union, Optional, Dict, Tuple
import h5py
import pandas as pd
import numpy as np

from ..LoggingConfig import get_logger
from ..Decorators import log_call, standardize_input

logger = get_logger(__name__)


class HdfHydraulicTables:
    """
    Extract hydraulic property tables (HTAB) from HEC-RAS geometry HDF files.

    All methods are static and designed to be used without instantiation.

    Property tables provide preprocessed hydraulic properties (area, conveyance,
    wetted perimeter, etc.) as functions of elevation for cross sections and structures.
    """

    @staticmethod
    def _get_xs_index(hdf_file: h5py.File, river: str, reach: str, rs: str) -> Optional[int]:
        """
        Find cross section index from river/reach/RS identifiers.

        Parameters:
            hdf_file (h5py.File): Open HDF file handle
            river (str): River name
            reach (str): Reach name
            rs (str): River station

        Returns:
            Optional[int]: Cross section index, or None if not found

        Notes:
            - Uses /Geometry/Cross Sections/Attributes to map names to indices
            - Case-sensitive matching
        """
        try:
            attrs_path = '/Geometry/Cross Sections/Attributes'
            if attrs_path not in hdf_file:
                logger.error(f"Attributes path not found: {attrs_path}")
                return None

            attrs = hdf_file[attrs_path][:]

            # Check if required fields exist
            required_fields = ['River', 'Reach', 'RS']
            for field in required_fields:
                if field not in attrs.dtype.names:
                    logger.error(f"Required field '{field}' not found in Attributes")
                    return None

            # Search for matching cross section
            for i, attr in enumerate(attrs):
                attr_river = attr['River'].decode('utf-8').strip()
                attr_reach = attr['Reach'].decode('utf-8').strip()
                attr_rs = attr['RS'].decode('utf-8').strip()

                if attr_river == river and attr_reach == reach and attr_rs == rs:
                    logger.debug(f"Found XS at index {i}: {river}/{reach}/RS {rs}")
                    return i

            logger.warning(f"Cross section not found: {river}/{reach}/RS {rs}")
            return None

        except Exception as e:
            logger.error(f"Error finding XS index: {str(e)}")
            return None

    @staticmethod
    def _extract_property_table(hdf_file: h5py.File, xs_index: int) -> Optional[pd.DataFrame]:
        """
        Extract property table for a cross section index.

        Parameters:
            hdf_file (h5py.File): Open HDF file handle
            xs_index (int): Cross section index

        Returns:
            Optional[pd.DataFrame]: Property table with all 23 hydraulic properties

        Notes:
            - Reads from /Geometry/Cross Sections/Property Tables/
            - Returns DataFrame with elevation + 22 other properties
        """
        try:
            prop_path = '/Geometry/Cross Sections/Property Tables'
            if prop_path not in hdf_file:
                logger.error(f"Property Tables path not found: {prop_path}")
                return None

            prop_tables = hdf_file[prop_path]

            # Read index info
            if 'XSEC Info' not in prop_tables:
                logger.error("XSEC Info not found in Property Tables")
                return None

            xsec_info = prop_tables['XSEC Info'][:]

            if xs_index >= len(xsec_info):
                logger.error(f"XS index {xs_index} out of range (max: {len(xsec_info)-1})")
                return None

            # Get start index and count for this XS
            start_idx = xsec_info[xs_index][0]
            count = xsec_info[xs_index][1]

            logger.debug(f"XS {xs_index}: start={start_idx}, count={count}")

            # Read property table values
            if 'XSEC Value' not in prop_tables:
                logger.error("XSEC Value not found in Property Tables")
                return None

            xsec_value = prop_tables['XSEC Value']

            # Extract data for this XS
            data = xsec_value[start_idx:start_idx + count, :]

            # Get column names from Variables attribute
            if 'Variables' in xsec_value.attrs:
                variables = xsec_value.attrs['Variables']
                # Variables is Nx2 array: [name, units]
                col_names = [var[0].decode('utf-8').strip() for var in variables]

                # Create friendly column names
                friendly_names = []
                for name in col_names:
                    # Convert names like "Area LOB" to "Area_LOB"
                    friendly = name.replace(' ', '_')
                    # Special handling for total values
                    if friendly == 'Area_Chan' and 'Area_LOB' in friendly_names:
                        # Calculate total area
                        pass  # Will compute after DataFrame creation
                    friendly_names.append(friendly)

            else:
                # Fallback column names
                col_names = [f'Property_{i}' for i in range(data.shape[1])]
                friendly_names = col_names

            # Create DataFrame
            df = pd.DataFrame(data, columns=friendly_names)

            # Calculate total values from LOB + Chan + ROB
            if 'Area_LOB' in df.columns and 'Area_Chan' in df.columns and 'Area_ROB' in df.columns:
                df['Area_Total'] = df['Area_LOB'] + df['Area_Chan'] + df['Area_ROB']

            if 'Conv_LOB' in df.columns and 'Conv_Chan' in df.columns and 'Conv_ROB' in df.columns:
                df['Conveyance_Total'] = df['Conv_LOB'] + df['Conv_Chan'] + df['Conv_ROB']

            if 'WP_LOB' in df.columns and 'WP_Chan' in df.columns and 'WP_ROB' in df.columns:
                df['Wetted_Perimeter_Total'] = df['WP_LOB'] + df['WP_Chan'] + df['WP_ROB']

            logger.info(f"Extracted property table: {len(df)} elevations × {len(df.columns)} properties")

            return df

        except Exception as e:
            logger.error(f"Error extracting property table: {str(e)}")
            return None

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_xs_htab(hdf_path: Union[str, Path],
                    river: str,
                    reach: str,
                    rs: str) -> pd.DataFrame:
        """
        Extract hydraulic property table (HTAB) for a cross section.

        Reads preprocessed hydraulic properties from geometry HDF file, including
        area, conveyance, wetted perimeter, top width, and other properties as
        functions of elevation.

        Parameters:
            hdf_path (Union[str, Path]): Path to geometry HDF file (.g##.hdf)
            river (str): River name (case-sensitive)
            reach (str): Reach name (case-sensitive)
            rs (str): River station (as string, e.g., "1")

        Returns:
            pd.DataFrame: Property table with columns:
                - Elevation: Water surface elevation (ft or m)
                - Area_LOB: Left overbank area (sq ft or sq m)
                - Area_Chan: Channel area
                - Area_ROB: Right overbank area
                - Area_Total: Total flow area (computed)
                - Area_Ineff_LOB: Ineffective area left overbank
                - Area_Ineff_Chan: Ineffective area channel
                - Area_Ineff_ROB: Ineffective area right overbank
                - Conv_LOB: Conveyance left overbank (cfs or cms)
                - Conv_Chan: Conveyance channel
                - Conv_ROB: Conveyance right overbank
                - Conveyance_Total: Total conveyance (computed)
                - WP_LOB: Wetted perimeter left overbank (ft or m)
                - WP_Chan: Wetted perimeter channel
                - WP_ROB: Wetted perimeter right overbank
                - Wetted_Perimeter_Total: Total wetted perimeter (computed)
                - Mann_N_LOB: Manning's n left overbank
                - Mann_N_Chan: Manning's n channel
                - Mann_N_ROB: Manning's n right overbank
                - Top_Width: Total top width (ft or m)
                - Top_Width_LOB: Top width left overbank
                - Top_Width_Chan: Top width channel
                - Top_Width_ROB: Top width right overbank
                - Alpha: Velocity distribution coefficient
                - Storage_Area: Storage area (sq ft or sq m)
                - Beta: Momentum coefficient

        Raises:
            FileNotFoundError: If HDF file doesn't exist
            ValueError: If cross section not found
            IOError: If HDF read fails

        Example:
            >>> from ras_commander import HdfHydraulicTables
            >>> from pathlib import Path
            >>> import matplotlib.pyplot as plt
            >>>
            >>> # Extract property table
            >>> hdf_file = Path("BaldEagle.g01.hdf")
            >>> htab = HdfHydraulicTables.get_xs_htab(hdf_file, "Bald Eagle", "Loc Hav", "1")
            >>>
            >>> print(f"Property table: {len(htab)} elevations")
            >>> print(f"Elevation range: {htab['Elevation'].min():.2f} to {htab['Elevation'].max():.2f}")
            >>>
            >>> # Plot area-elevation curve
            >>> plt.figure(figsize=(10, 6))
            >>> plt.plot(htab['Area_Total'], htab['Elevation'], 'b-', linewidth=2)
            >>> plt.xlabel('Flow Area (sq ft)')
            >>> plt.ylabel('Elevation (ft)')
            >>> plt.title('Cross Section Area-Elevation Curve')
            >>> plt.grid(True, alpha=0.3)
            >>> plt.show()
            >>>
            >>> # Calculate hydraulic radius
            >>> htab['Hydraulic_Radius'] = htab['Area_Total'] / htab['Wetted_Perimeter_Total']
            >>> print(f"Max hydraulic radius: {htab['Hydraulic_Radius'].max():.2f} ft")

        Notes:
            - Property tables are in GEOMETRY HDF (.g##.hdf), not plan HDF
            - Tables computed during geometry preprocessing in HEC-RAS
            - Use for rating curves, stage-discharge, hydraulic analysis
            - Total values (area, conveyance, WP) computed from LOB + Chan + ROB
            - See HdfXsec.get_cross_sections() for XS geometry
        """
        hdf_path = Path(hdf_path)

        if not hdf_path.exists():
            raise FileNotFoundError(f"Geometry HDF file not found: {hdf_path}")

        try:
            with h5py.File(hdf_path, 'r') as hdf:
                # Find cross section index
                xs_index = HdfHydraulicTables._get_xs_index(hdf, river, reach, rs)

                if xs_index is None:
                    raise ValueError(
                        f"Cross section not found in HDF: {river}/{reach}/RS {rs}\n"
                        f"Check that river, reach, and RS names match exactly (case-sensitive)"
                    )

                # Extract property table
                df = HdfHydraulicTables._extract_property_table(hdf, xs_index)

                if df is None:
                    raise IOError(f"Failed to extract property table for {river}/{reach}/RS {rs}")

                logger.info(
                    f"Extracted HTAB for {river}/{reach}/RS {rs}: "
                    f"{len(df)} elevations, {len(df.columns)} properties"
                )

                return df

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading property table from HDF: {str(e)}")
            raise IOError(f"Failed to read property table: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_all_xs_htabs(hdf_path: Union[str, Path]) -> Dict[Tuple[str, str, str], pd.DataFrame]:
        """
        Extract hydraulic property tables for ALL cross sections in geometry.

        Batch extraction of property tables for all cross sections, returned as
        a dictionary keyed by (river, reach, rs) tuples.

        Parameters:
            hdf_path (Union[str, Path]): Path to geometry HDF file (.g##.hdf)

        Returns:
            Dict[Tuple[str, str, str], pd.DataFrame]: Dictionary mapping
                (river, reach, rs) tuples to property table DataFrames

        Raises:
            FileNotFoundError: If HDF file doesn't exist
            IOError: If HDF read fails

        Example:
            >>> from ras_commander import HdfHydraulicTables
            >>> from pathlib import Path
            >>>
            >>> # Extract all property tables
            >>> hdf_file = Path("BaldEagle.g01.hdf")
            >>> all_htabs = HdfHydraulicTables.get_all_xs_htabs(hdf_file)
            >>>
            >>> print(f"Extracted {len(all_htabs)} property tables")
            >>>
            >>> # Access specific cross section
            >>> htab = all_htabs[("Bald Eagle", "Loc Hav", "1")]
            >>>
            >>> # Calculate statistics across all cross sections
            >>> max_areas = {}
            >>> for (river, reach, rs), htab in all_htabs.items():
            ...     max_area = htab['Area_Total'].max()
            ...     max_areas[rs] = max_area
            >>>
            >>> # Find cross section with largest area
            >>> largest_rs = max(max_areas, key=max_areas.get)
            >>> print(f"Largest XS: RS {largest_rs} with area {max_areas[largest_rs]:.1f} sq ft")

        Notes:
            - More efficient than calling get_xs_htab() repeatedly
            - Returns all cross sections in single HDF file read
            - Dictionary keys are (river, reach, rs) tuples for easy lookup
        """
        hdf_path = Path(hdf_path)

        if not hdf_path.exists():
            raise FileNotFoundError(f"Geometry HDF file not found: {hdf_path}")

        try:
            all_htabs = {}

            with h5py.File(hdf_path, 'r') as hdf:
                # Read attributes to get all river/reach/RS combinations
                attrs_path = '/Geometry/Cross Sections/Attributes'
                if attrs_path not in hdf:
                    logger.error(f"Attributes path not found: {attrs_path}")
                    return all_htabs

                attrs = hdf[attrs_path][:]

                # Extract property table for each cross section
                for i, attr in enumerate(attrs):
                    river = attr['River'].decode('utf-8').strip()
                    reach = attr['Reach'].decode('utf-8').strip()
                    rs = attr['RS'].decode('utf-8').strip()

                    # Extract property table
                    df = HdfHydraulicTables._extract_property_table(hdf, i)

                    if df is not None:
                        all_htabs[(river, reach, rs)] = df
                    else:
                        logger.warning(f"Failed to extract HTAB for {river}/{reach}/RS {rs}")

            logger.info(f"Extracted {len(all_htabs)} property tables from {hdf_path.name}")

            return all_htabs

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error reading property tables from HDF: {str(e)}")
            raise IOError(f"Failed to read property tables: {str(e)}")
