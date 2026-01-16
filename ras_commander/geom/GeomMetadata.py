"""
GeomMetadata - Geometry element count extraction for HEC-RAS geometry files

This module provides efficient extraction of geometry element counts, preferring
HDF-based extraction (fast) with plain text fallback (slower but always available).

Use this module to get a quick overview of geometry file contents without loading
full geometry data. The counts are used by RasPrj.get_geom_entries() to populate
geom_df metadata columns.

All methods are static and designed to be used without instantiation.

List of Functions:
- get_geometry_counts() - Main entry point returning all counts as dict
- _get_counts_from_hdf() - HDF-based extraction (fast)
- _get_counts_from_text() - Plain text fallback (slower)

Example Usage:
    >>> from ras_commander.geom import GeomMetadata
    >>> from pathlib import Path
    >>>
    >>> # Get counts using HDF (if available) or text fallback
    >>> counts = GeomMetadata.get_geometry_counts(
    ...     geom_path=Path("model.g01"),
    ...     hdf_path=Path("model.g01.hdf")
    ... )
    >>> print(f"Cross sections: {counts['num_cross_sections']}")
    >>> print(f"2D mesh areas: {counts['mesh_area_names']}")
    >>> print(f"Total mesh cells: {counts['mesh_cell_count']}")

Performance Notes:
    - HDF path: ~10-50ms for all counts (single file read)
    - Text path: ~100-500ms per geometry file (full file parse)
    - Always prefer HDF when .g##.hdf file exists
"""

from pathlib import Path
from typing import Union, Optional, Dict, Any, List
import h5py

from ..LoggingConfig import get_logger
from ..Decorators import log_call

logger = get_logger(__name__)


class GeomMetadata:
    """
    Extract geometry metadata counts efficiently from HDF or plain text files.

    All methods are static and designed to be used without instantiation.
    """

    # Default return values for graceful degradation
    DEFAULT_COUNTS = {
        'has_1d_xs': False,
        'has_2d_mesh': False,
        'num_cross_sections': 0,
        'num_inline_structures': 0,
        'num_bridges': 0,
        'num_culverts': 0,
        'num_weirs': 0,
        'num_gates': 0,
        'num_lateral_structures': 0,
        'num_sa_2d_connections': 0,
        'mesh_cell_count': 0,
        'mesh_area_names': [],
    }

    @staticmethod
    @log_call
    def get_geometry_counts(
        geom_path: Union[str, Path],
        hdf_path: Optional[Union[str, Path]] = None
    ) -> Dict[str, Any]:
        """
        Extract all geometry element counts from geometry file.

        Prefers HDF-based extraction (fast) when hdf_path is provided and exists.
        Falls back to plain text parsing when HDF is not available.

        Parameters:
            geom_path: Path to plain text geometry file (.g##)
            hdf_path: Optional path to geometry HDF file (.g##.hdf)

        Returns:
            dict with keys:
                - has_1d_xs (bool): True if num_cross_sections > 0
                - has_2d_mesh (bool): True if mesh_area_names is not empty
                - num_cross_sections (int): Count of 1D cross sections
                - num_inline_structures (int): Total bridges + culverts + weirs
                - num_bridges (int): Bridge count
                - num_culverts (int): Culvert count
                - num_weirs (int): Inline weir count
                - num_gates (int): Gate count
                - num_lateral_structures (int): Lateral structure count
                - num_sa_2d_connections (int): SA to 2D connections count
                - mesh_cell_count (int): Total 2D mesh cells
                - mesh_area_names (list[str]): Names of 2D flow areas

        Note:
            Always returns a complete dict with all keys, using defaults on failure.
            Graceful degradation is critical - never raises exceptions.

        Example:
            >>> counts = GeomMetadata.get_geometry_counts("model.g01", "model.g01.hdf")
            >>> if counts['has_2d_mesh']:
            ...     print(f"2D areas: {counts['mesh_area_names']}")
        """
        # Start with default values
        result = GeomMetadata.DEFAULT_COUNTS.copy()

        # Normalize paths
        geom_path = Path(geom_path) if geom_path else None
        hdf_path = Path(hdf_path) if hdf_path else None

        try:
            # Try HDF extraction first (fast path)
            if hdf_path and hdf_path.exists():
                logger.debug(f"Using HDF extraction for {hdf_path.name}")
                result = GeomMetadata._get_counts_from_hdf(hdf_path, result)

                # For lateral structures and SA/2D connections, need plain text
                # (these are NOT stored in HDF geometry file)
                if geom_path and geom_path.exists():
                    result = GeomMetadata._add_text_only_counts(geom_path, result)

            # Fall back to plain text parsing
            elif geom_path and geom_path.exists():
                logger.debug(f"Using text extraction for {geom_path.name}")
                result = GeomMetadata._get_counts_from_text(geom_path, result)

            else:
                logger.warning("Neither HDF nor geometry file exists")

        except Exception as e:
            logger.warning(f"Failed to extract geometry metadata: {e}")
            # Keep default values on failure

        # Calculate derived fields
        result['has_1d_xs'] = result['num_cross_sections'] > 0
        result['has_2d_mesh'] = len(result['mesh_area_names']) > 0
        result['num_inline_structures'] = (
            result['num_bridges'] +
            result['num_culverts'] +
            result['num_weirs']
        )

        return result

    @staticmethod
    def _get_counts_from_hdf(
        hdf_path: Path,
        counts: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Extract counts from geometry HDF file (fast path).

        Parameters:
            hdf_path: Path to geometry HDF file
            counts: Dict to update with counts (modified in place)

        Returns:
            Updated counts dict
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf:
                # Cross sections
                counts['num_cross_sections'] = GeomMetadata._get_xs_count_hdf(hdf)

                # Structures (bridges, culverts, weirs, gates)
                structure_counts = GeomMetadata._get_structure_counts_hdf(hdf)
                counts.update(structure_counts)

                # 2D mesh areas and cell counts
                mesh_info = GeomMetadata._get_2d_info_hdf(hdf)
                counts.update(mesh_info)

        except Exception as e:
            logger.warning(f"HDF extraction failed for {hdf_path}: {e}")

        return counts

    @staticmethod
    def _get_xs_count_hdf(hdf: h5py.File) -> int:
        """Get 1D cross section count from geometry HDF."""
        try:
            path = '/Geometry/Cross Sections/Attributes'
            if path in hdf:
                return hdf[path].shape[0]
        except Exception as e:
            logger.debug(f"XS count HDF error: {e}")
        return 0

    @staticmethod
    def _get_structure_counts_hdf(hdf: h5py.File) -> Dict[str, int]:
        """
        Get inline structure counts from geometry HDF.

        Note: HDF stores all inline structures together. We parse the Type field
        to break down by structure type:
        - Type 2: Bridge
        - Type 3: Culvert
        - Type 4: Inline Weir

        Returns dict with: num_bridges, num_culverts, num_weirs, num_gates
        """
        result = {
            'num_bridges': 0,
            'num_culverts': 0,
            'num_weirs': 0,
            'num_gates': 0,
        }

        try:
            path = '/Geometry/Structures/Attributes'
            if path not in hdf:
                return result

            attrs = hdf[path][:]

            # Check if 'Type' field exists
            if 'Type' not in attrs.dtype.names:
                # Fall back to total count if no type breakdown
                total = attrs.shape[0]
                logger.debug(f"No Type field in structures, total: {total}")
                return result

            types = attrs['Type']

            # Count by type
            # Based on HEC-RAS structure types:
            # Type 2 = Bridge/Culvert structure
            # Within Bridge/Culvert, need to look for culvert count vs bridge
            # For simplicity, count Type 2 as potential bridge/culvert
            # Type 4 = Inline Weir
            for struct_type in types:
                if struct_type == 2:
                    # Bridge/Culvert - need more info to differentiate
                    # For now, count as bridges (culverts are within bridge structures)
                    result['num_bridges'] += 1
                elif struct_type == 4:
                    result['num_weirs'] += 1

            # Gates: Check for gate groups in structures
            if '/Geometry/Structures/Gate Groups' in hdf:
                try:
                    gate_groups = hdf['/Geometry/Structures/Gate Groups']
                    if 'Attributes' in gate_groups:
                        result['num_gates'] = gate_groups['Attributes'].shape[0]
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"Structure counts HDF error: {e}")

        return result

    @staticmethod
    def _get_2d_info_hdf(hdf: h5py.File) -> Dict[str, Any]:
        """
        Get 2D mesh area names and cell counts from geometry HDF.

        Returns dict with: mesh_area_names, mesh_cell_count
        """
        result = {
            'mesh_area_names': [],
            'mesh_cell_count': 0,
        }

        try:
            base_path = 'Geometry/2D Flow Areas'
            if base_path not in hdf:
                return result

            # Get area names
            if f"{base_path}/Attributes" in hdf:
                attrs = hdf[f"{base_path}/Attributes"][()]
                if 'Name' in attrs.dtype.names:
                    names = []
                    for name in attrs['Name']:
                        if isinstance(name, bytes):
                            name = name.decode('utf-8')
                        # Strip trailing spaces
                        names.append(name.strip())
                    result['mesh_area_names'] = names

            # Get cell counts from Cell Info
            if f"{base_path}/Cell Info" in hdf:
                cell_info = hdf[f"{base_path}/Cell Info"][()]
                # Cell info format: (start_index, cell_count) per area
                total_cells = sum(info[1] for info in cell_info)
                result['mesh_cell_count'] = int(total_cells)

        except Exception as e:
            logger.debug(f"2D info HDF error: {e}")

        return result

    @staticmethod
    def _add_text_only_counts(
        geom_path: Path,
        counts: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Add counts that are only available from plain text (not in HDF).

        Specifically: lateral structures and SA/2D connections.

        Parameters:
            geom_path: Path to plain text geometry file
            counts: Dict to update (modified in place)

        Returns:
            Updated counts dict
        """
        try:
            # Lazy import to avoid circular dependency
            from .GeomLateral import GeomLateral

            try:
                lat_df = GeomLateral.get_lateral_structures(geom_path)
                counts['num_lateral_structures'] = len(lat_df)
            except Exception as e:
                logger.debug(f"Lateral structures count error: {e}")

            try:
                conn_df = GeomLateral.get_connections(geom_path)
                counts['num_sa_2d_connections'] = len(conn_df)
            except Exception as e:
                logger.debug(f"Connections count error: {e}")

        except Exception as e:
            logger.debug(f"Text-only counts error: {e}")

        return counts

    @staticmethod
    def _get_counts_from_text(
        geom_path: Path,
        counts: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Get all counts from plain text geometry file (fallback path).

        Parameters:
            geom_path: Path to plain text geometry file
            counts: Dict to update (modified in place)

        Returns:
            Updated counts dict
        """
        try:
            # Cross sections
            try:
                from .GeomCrossSection import GeomCrossSection
                xs_df = GeomCrossSection.get_cross_sections(geom_path)
                counts['num_cross_sections'] = len(xs_df)
            except Exception as e:
                logger.debug(f"XS count text error: {e}")

            # Bridges
            try:
                from .GeomBridge import GeomBridge
                bridges_df = GeomBridge.get_bridges(geom_path)
                counts['num_bridges'] = len(bridges_df)
            except Exception as e:
                logger.debug(f"Bridges count text error: {e}")

            # Culverts - get from all bridge locations
            try:
                from .GeomCulvert import GeomCulvert
                culverts_df = GeomCulvert.get_all(geom_path)
                counts['num_culverts'] = len(culverts_df)
            except Exception as e:
                logger.debug(f"Culverts count text error: {e}")

            # Inline weirs and gates
            try:
                from .GeomInlineWeir import GeomInlineWeir
                weirs_df = GeomInlineWeir.get_weirs(geom_path)
                counts['num_weirs'] = len(weirs_df)

                # Count gates from weirs with gates
                if 'HasGate' in weirs_df.columns:
                    counts['num_gates'] = weirs_df['HasGate'].sum()
            except Exception as e:
                logger.debug(f"Weirs/gates count text error: {e}")

            # Lateral structures
            try:
                from .GeomLateral import GeomLateral
                laterals_df = GeomLateral.get_lateral_structures(geom_path)
                counts['num_lateral_structures'] = len(laterals_df)
            except Exception as e:
                logger.debug(f"Laterals count text error: {e}")

            # SA/2D connections
            try:
                from .GeomLateral import GeomLateral
                connections_df = GeomLateral.get_connections(geom_path)
                counts['num_sa_2d_connections'] = len(connections_df)
            except Exception as e:
                logger.debug(f"Connections count text error: {e}")

            # 2D mesh areas - parse from text
            try:
                mesh_info = GeomMetadata._get_2d_info_from_text(geom_path)
                counts.update(mesh_info)
            except Exception as e:
                logger.debug(f"2D mesh text error: {e}")

        except Exception as e:
            logger.warning(f"Text extraction failed for {geom_path}: {e}")

        return counts

    @staticmethod
    def _get_2d_info_from_text(geom_path: Path) -> Dict[str, Any]:
        """
        Extract 2D mesh info from plain text geometry file.

        Returns dict with: mesh_area_names, mesh_cell_count

        Note: Mesh cell count is not directly available in plain text,
        only in HDF. Returns 0 for mesh_cell_count from text parsing.
        """
        result = {
            'mesh_area_names': [],
            'mesh_cell_count': 0,  # Not available in plain text
        }

        try:
            with open(geom_path, 'r') as f:
                content = f.read()

            # Find 2D Flow Area names
            # Format in geometry file: "2D Flow Area="
            import re
            pattern = r'2D Flow Area=\s*(.+?)(?:\s*,|$)'
            matches = re.findall(pattern, content, re.MULTILINE)

            # Clean up names
            area_names = []
            for match in matches:
                name = match.strip().rstrip(',')
                if name and name not in area_names:
                    area_names.append(name)

            result['mesh_area_names'] = area_names

        except Exception as e:
            logger.debug(f"2D info text extraction error: {e}")

        return result
