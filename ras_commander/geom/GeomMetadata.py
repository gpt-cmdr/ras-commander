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
from typing import Any, Dict, Optional, Union

import h5py

from ..LoggingConfig import get_logger
from ..Decorators import log_call

logger = get_logger(__name__)


class GeomMetadata:
    """
    Extract geometry metadata counts efficiently from HDF or plain text files.

    All methods are static and designed to be used without instantiation.
    """

    # Provenance is part of the classification contract. Unknown metadata
    # must not look like a valid geometry with zero hydraulic elements.
    DEFAULT_COUNTS = {
        'has_1d_xs': None,
        'has_2d_mesh': None,
        'num_cross_sections': 0,
        'num_inline_structures': 0,
        'num_bridges': 0,
        'num_culverts': 0,
        'num_weirs': 0,
        'num_gates': 0,
        'num_lateral_structures': 0,
        'num_sa_2d_connections': 0,
        # Cell counts are only materialized in the geometry HDF. A text-only
        # geometry can prove a 2D area exists, but its cell count is unknown.
        'mesh_cell_count': None,
        'mesh_area_names': [],
        'geometry_metadata_source': 'unavailable',
        'geometry_metadata_valid': False,
        'geometry_metadata_error': None,
    }

    @staticmethod
    def _new_counts() -> Dict[str, Any]:
        """Return independent defaults for one geometry inspection."""
        return {
            key: value.copy() if isinstance(value, list) else value
            for key, value in GeomMetadata.DEFAULT_COUNTS.items()
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
                - has_2d_mesh (bool): True when text declares a 2D flow area
                  or HDF metadata identifies a mesh area
                - num_cross_sections (int): Count of 1D cross sections
                - num_inline_structures (int): Total bridges + culverts + weirs
                - num_bridges (int): Bridge count
                - num_culverts (int): Culvert count
                - num_weirs (int): Inline weir count
                - num_gates (int): Gate count
                - num_lateral_structures (int): Lateral structure count
                - num_sa_2d_connections (int): SA to 2D connections count
                - mesh_cell_count (int | None): Total HDF mesh cells; ``None``
                  when only text geometry is available
                - mesh_area_names (list[str]): Names of 2D flow areas
                - geometry_metadata_source (str): ``hdf``, ``text``, or
                  ``unavailable``
                - geometry_metadata_valid (bool): Whether a geometry source
                  was successfully inspected
                - geometry_metadata_error (str | None): Failed source reads
                  encountered before success, or the terminal failure

        Note:
            Always returns a complete dict and never raises. The two
            ``has_*`` values remain ``None`` when no source can be inspected,
            so dispatch cannot mistake unreadable geometry for valid 1D.

        Example:
            >>> counts = GeomMetadata.get_geometry_counts("model.g01", "model.g01.hdf")
            >>> if counts['has_2d_mesh']:
            ...     print(f"2D areas: {counts['mesh_area_names']}")
        """
        result = GeomMetadata._new_counts()

        # Normalize paths
        geom_path = Path(geom_path) if geom_path else None
        hdf_path = Path(hdf_path) if hdf_path else None

        errors = []

        # Build HDF results into a fresh candidate so a failed read cannot
        # leak partial counts into the text fallback.
        if hdf_path and hdf_path.exists():
            try:
                logger.debug(f"Using HDF extraction for {hdf_path.name}")
                candidate = GeomMetadata._new_counts()
                result = GeomMetadata._get_counts_from_hdf(hdf_path, candidate)
                hdf_error = result.pop('_hdf_extraction_error', None)
                if hdf_error:
                    raise ValueError(hdf_error)
                result['geometry_metadata_source'] = 'hdf'
                result['geometry_metadata_valid'] = True

                # These two inventories are not stored in the geometry HDF.
                if geom_path and geom_path.exists():
                    result = GeomMetadata._add_text_only_counts(geom_path, result)
            except Exception as exc:
                errors.append(f"HDF inspection failed: {exc}")
                logger.warning(f"HDF extraction failed for {hdf_path}: {exc}")
                result = GeomMetadata._new_counts()

        if not result['geometry_metadata_valid'] and geom_path and geom_path.exists():
            try:
                logger.debug(f"Using text extraction for {geom_path.name}")
                candidate = GeomMetadata._new_counts()
                result = GeomMetadata._get_counts_from_text(geom_path, candidate)
                result['geometry_metadata_source'] = 'text'
                result['geometry_metadata_valid'] = True
            except Exception as exc:
                errors.append(f"Text inspection failed: {exc}")
                logger.warning(f"Text extraction failed for {geom_path}: {exc}")
                result = GeomMetadata._new_counts()

        if not result['geometry_metadata_valid'] and not errors:
            errors.append("Neither HDF nor geometry file exists")
            logger.warning(errors[-1])

        if result['geometry_metadata_valid']:
            result['has_1d_xs'] = result['num_cross_sections'] > 0
            if result['has_2d_mesh'] is None:
                result['has_2d_mesh'] = bool(result['mesh_area_names'])
        result['num_inline_structures'] = (
            result['num_bridges'] +
            result['num_culverts'] +
            result['num_weirs']
        )
        result['geometry_metadata_error'] = '; '.join(errors) if errors else None

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
                counts['num_cross_sections'] = GeomMetadata._get_xs_count_hdf(hdf)
                counts.update(GeomMetadata._get_structure_counts_hdf(hdf))
                counts.update(GeomMetadata._get_2d_info_hdf(hdf))
        except (OSError, KeyError, TypeError, ValueError) as exc:
            counts['_hdf_extraction_error'] = str(exc)
            logger.warning(
                "HDF geometry metadata extraction failed for %s",
                Path(hdf_path).name,
            )
            logger.debug(
                "HDF geometry metadata extraction failed for %s: %s",
                hdf_path,
                exc,
            )

        return counts

    @staticmethod
    def _get_xs_count_hdf(hdf: h5py.File) -> int:
        """Get 1D cross section count from geometry HDF."""
        path = '/Geometry/Cross Sections/Attributes'
        if path not in hdf:
            return 0
        dataset = hdf[path]
        if not isinstance(dataset, h5py.Dataset) or not dataset.shape:
            raise ValueError(f"Unreadable cross-section attributes dataset: {path}")
        return int(dataset.shape[0])

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

        path = '/Geometry/Structures/Attributes'
        if path not in hdf:
            return result

        attrs = hdf[path][()]
        dtype_names = attrs.dtype.names or ()

        # Older HDFs do not always expose Type. That is a supported schema
        # variant, not an unreadable dataset.
        if 'Type' not in dtype_names:
            logger.debug("No Type field in structures, total: %s", attrs.shape[0])
            return result

        for struct_type in attrs['Type']:
            if struct_type == 2:
                result['num_bridges'] += 1
            elif struct_type == 4:
                result['num_weirs'] += 1

        gate_path = '/Geometry/Structures/Gate Groups/Attributes'
        if gate_path in hdf:
            gate_dataset = hdf[gate_path]
            if not isinstance(gate_dataset, h5py.Dataset) or not gate_dataset.shape:
                raise ValueError(f"Unreadable gate-group attributes dataset: {gate_path}")
            result['num_gates'] = int(gate_dataset.shape[0])

        return result

    @staticmethod
    def _get_2d_info_hdf(hdf: h5py.File) -> Dict[str, Any]:
        """
        Get 2D mesh area names and cell counts from geometry HDF.

        Returns dict with: has_2d_mesh, mesh_area_names, mesh_cell_count
        """
        result = {
            'has_2d_mesh': False,
            'mesh_area_names': [],
            'mesh_cell_count': 0,
        }

        base_path = 'Geometry/2D Flow Areas'
        if base_path not in hdf:
            return result

        base_group = hdf[base_path]
        if not isinstance(base_group, h5py.Group):
            raise ValueError(f"Expected HDF group at {base_path}")

        attrs_path = f"{base_path}/Attributes"
        attributes_present = attrs_path in hdf
        if attributes_present:
            attrs = hdf[attrs_path][()]
            dtype_names = attrs.dtype.names or ()
            if 'Name' not in dtype_names:
                raise ValueError(f"2D area Attributes dataset has no Name field: {attrs_path}")
            for raw_name in attrs['Name']:
                if isinstance(raw_name, bytes):
                    raw_name = raw_name.decode('utf-8')
                name = str(raw_name).strip()
                if name and name not in result['mesh_area_names']:
                    result['mesh_area_names'].append(name)

        area_group_names = [
            name for name, item in base_group.items()
            if isinstance(item, h5py.Group)
        ]
        if not attributes_present and area_group_names:
            result['mesh_area_names'] = area_group_names

        cell_info_path = f"{base_path}/Cell Info"
        cell_rows = 0
        if cell_info_path in hdf:
            cell_info = hdf[cell_info_path][()]
            cell_rows = int(cell_info.shape[0]) if cell_info.ndim else 0
            if cell_info.size == 0:
                result['mesh_cell_count'] = 0
            elif cell_info.ndim >= 2 and cell_info.shape[1] >= 2:
                result['mesh_cell_count'] = int(cell_info[:, 1].sum())
            else:
                raise ValueError(f"Unexpected 2D Cell Info shape at {cell_info_path}")

        if not attributes_present and cell_info_path not in hdf and not area_group_names:
            raise ValueError(
                f"2D Flow Areas group has no Attributes, Cell Info, or area groups: {base_path}"
            )

        result['has_2d_mesh'] = bool(
            result['mesh_area_names'] or area_group_names or cell_rows
        )

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
            # Cross sections and 2D markers are classification-critical. Let
            # their parser errors reach the top-level provenance handler.
            from .GeomCrossSection import GeomCrossSection
            xs_df = GeomCrossSection.get_cross_sections(geom_path)
            counts['num_cross_sections'] = len(xs_df)

            mesh_info = GeomMetadata._get_2d_info_from_text(geom_path)
            counts.update(mesh_info)

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

        except Exception as e:
            raise ValueError(f"Geometry text parser failed for {geom_path}: {e}") from e

        return counts

    @staticmethod
    def _get_2d_info_from_text(geom_path: Path) -> Dict[str, Any]:
        """
        Extract 2D mesh info from plain text geometry file.

        Returns dict with: has_2d_mesh, mesh_area_names, mesh_cell_count

        Note: Mesh cell count is not directly available in plain text,
        only in HDF. Returns ``None`` for mesh_cell_count from text parsing.
        """
        result = {
            'has_2d_mesh': False,
            'mesh_area_names': [],
            'mesh_cell_count': None,
        }

        current_area = None
        with open(geom_path, 'r', encoding='utf-8', errors='replace') as handle:
            for raw_line in handle:
                line = raw_line.lstrip()
                if line.startswith('Storage Area='):
                    current_area = line.split('=', 1)[1].split(',', 1)[0].strip()
                    continue

                if not line.startswith('Storage Area Is2D=') or current_area is None:
                    continue

                raw_flag = line.split('=', 1)[1].split(',', 1)[0].strip()
                try:
                    is_2d = int(raw_flag)
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid Storage Area Is2D flag {raw_flag!r} for {current_area!r}"
                    ) from exc

                if is_2d == -1 and current_area and current_area not in result['mesh_area_names']:
                    result['mesh_area_names'].append(current_area)

        result['has_2d_mesh'] = bool(result['mesh_area_names'])

        return result
