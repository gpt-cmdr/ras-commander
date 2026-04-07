"""
RasTerrainModWriter - Create terrain modifications in HEC-RAS terrain HDF files.

Writes channel modifications (and modification groups) to terrain HDF files
and updates the .rasmap XML to register them. This enables programmatic
terrain modification without the RASMapper GUI.

Supports:
    - Channel modifications (TakeLower) along polylines
    - Modification groups for organizing multiple modifications
    - Writing to both terrain HDF and .rasmap XML

Key Functions:
    add_channel_modification():
        Add a channel terrain modification along a polyline alignment.

    add_modification_group():
        Add an empty modification group to terrain HDF and .rasmap.

Platform:
    Cross-platform (no pythonnet/RasMapperLib required for writing).

Requirements:
    - h5py for HDF5 writing
    - numpy for array operations
"""

import logging
import numpy as np
from pathlib import Path
from typing import Union, List, Optional, Tuple
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# Modification type constants
MODIFICATION_SET_VALUE = 0
MODIFICATION_TAKE_HIGHER = 1
MODIFICATION_TAKE_LOWER = 2
MODIFICATION_ADD_VALUE = 3


class RasTerrainModWriter:
    """Write terrain modifications to HEC-RAS terrain HDF and .rasmap files."""

    @staticmethod
    def add_channel_modification(
        terrain_hdf_path: Union[str, Path],
        rasmap_path: Union[str, Path],
        name: str,
        polyline_points: np.ndarray,
        width: float = 50.0,
        depth: float = 10.0,
        left_slope: float = 3.0,
        right_slope: float = 3.0,
        max_extent: float = 200.0,
        elev_pt_tolerance: float = 50.0,
        group_name: str = "Modifications",
    ) -> Path:
        """
        Add a channel terrain modification along a polyline alignment.

        Creates a trapezoidal channel cut into the terrain along the given
        polyline. The channel uses "TakeLower" mode - the terrain is lowered
        where the channel cross-section is below the existing ground.

        Parameters
        ----------
        terrain_hdf_path : Path
            Path to the terrain HDF file (e.g., Terrain50.hdf).
        rasmap_path : Path
            Path to the .rasmap XML file.
        name : str
            Name for this channel modification (e.g., "Main Channel").
        polyline_points : np.ndarray
            Nx2 array of (x, y) coordinates defining the channel alignment.
            Must be in the same coordinate system as the terrain.
        width : float
            Bottom width of the trapezoidal channel in terrain units (default 50).
        depth : float
            Depth of the channel below the terrain surface (default 10).
        left_slope : float
            Left side slope as H:V ratio (default 3.0 = 3H:1V).
        right_slope : float
            Right side slope as H:V ratio (default 3.0 = 3H:1V).
        max_extent : float
            Maximum lateral extent of the modification in terrain units (default 200).
        elev_pt_tolerance : float
            Elevation point tolerance (default 50).
        group_name : str
            Name of the modification group (default "Modifications").

        Returns
        -------
        Path
            Path to the modified terrain HDF file.
        """
        import h5py

        terrain_hdf_path = Path(terrain_hdf_path)
        rasmap_path = Path(rasmap_path)
        polyline_points = np.asarray(polyline_points, dtype=np.float64)

        if polyline_points.ndim != 2 or polyline_points.shape[1] != 2:
            raise ValueError("polyline_points must be Nx2 array of (x, y) coordinates")
        if len(polyline_points) < 2:
            raise ValueError("polyline_points must have at least 2 points")

        logger.info(f"Adding channel modification '{name}' to {terrain_hdf_path.name}")
        logger.info(f"  Alignment: {len(polyline_points)} points")
        logger.info(f"  Channel: width={width}, depth={depth}, slopes={left_slope}/{right_slope}")

        # Step 1: Write to terrain HDF
        RasTerrainModWriter._write_channel_to_hdf(
            terrain_hdf_path, name, polyline_points,
            width, depth, left_slope, right_slope,
            max_extent, elev_pt_tolerance
        )

        # Step 2: Update .rasmap XML
        RasTerrainModWriter._update_rasmap_xml(
            rasmap_path, terrain_hdf_path, name,
            mod_type="GroundLineModificationLayer",
            default_mod_type=MODIFICATION_TAKE_LOWER,
            elev_pt_tolerance=elev_pt_tolerance,
            group_name=group_name,
        )

        logger.info(f"Channel modification '{name}' added successfully")
        return terrain_hdf_path

    @staticmethod
    def add_modification_group(
        terrain_hdf_path: Union[str, Path],
        rasmap_path: Union[str, Path],
        group_name: str = "Modifications",
    ) -> None:
        """
        Add an empty modification group to terrain HDF and .rasmap.

        This creates the group structure without any actual modifications.
        Use add_channel_modification() to add modifications to the group.

        Parameters
        ----------
        terrain_hdf_path : Path
            Path to the terrain HDF file.
        rasmap_path : Path
            Path to the .rasmap XML file.
        group_name : str
            Name for the modification group (default "Modifications").
        """
        import h5py

        terrain_hdf_path = Path(terrain_hdf_path)
        rasmap_path = Path(rasmap_path)

        # Create the Modifications group in HDF if it doesn't exist
        with h5py.File(terrain_hdf_path, 'a') as f:
            if 'Modifications' not in f:
                f.create_group('Modifications')
                logger.info(f"Created /Modifications group in {terrain_hdf_path.name}")

        # Update .rasmap XML
        RasTerrainModWriter._ensure_modification_group_in_rasmap(
            rasmap_path, terrain_hdf_path, group_name
        )

    @staticmethod
    def _write_channel_to_hdf(
        terrain_hdf_path: Path,
        name: str,
        polyline_points: np.ndarray,
        width: float,
        depth: float,
        left_slope: float,
        right_slope: float,
        max_extent: float,
        elev_pt_tolerance: float,
    ) -> None:
        """Write channel modification data to terrain HDF file."""
        import h5py

        with h5py.File(terrain_hdf_path, 'a') as f:
            # Create /Modifications group if needed
            mods = f.require_group('Modifications')

            # Create the named modification group
            if name in mods:
                logger.warning(f"Modification '{name}' already exists, overwriting")
                del mods[name]

            mod_grp = mods.create_group(name)

            # Set type attributes
            mod_grp.attrs['Type'] = np.bytes_('Levee')
            mod_grp.attrs['Subtype'] = np.bytes_('Channel')
            mod_grp.attrs['Priority'] = np.int32(0)

            # Write polyline using HEC-RAS HDF5Storage format
            # Polyline Info: [start_index, num_points, part_start, num_parts]
            n_pts = len(polyline_points)
            polyline_info = np.array([[0, n_pts, 0, 1]], dtype=np.int32)
            mod_grp.create_dataset('Polyline Info', data=polyline_info)

            # Polyline Parts: [start_index, num_points_in_part]
            polyline_parts = np.array([[0, n_pts]], dtype=np.int32)
            mod_grp.create_dataset('Polyline Parts', data=polyline_parts)

            # Polyline Points: Nx2 array of (x, y)
            mod_grp.create_dataset('Polyline Points', data=polyline_points)

            # Compute station values along the polyline
            dx = np.diff(polyline_points[:, 0])
            dy = np.diff(polyline_points[:, 1])
            segment_lengths = np.sqrt(dx**2 + dy**2)
            stations = np.zeros(n_pts)
            stations[1:] = np.cumsum(segment_lengths)
            total_length = stations[-1]

            # Create a simple profile: depth below ground at start, middle, end
            # The profile is station-elevation pairs where elevation = -depth
            # (relative to terrain surface, interpreted by HEC-RAS)
            profile_stations = np.array([0.0, total_length / 2, total_length])
            profile_elevations = np.array([-depth, -depth, -depth])
            profile_data = np.column_stack([profile_stations, profile_elevations])
            mod_grp.create_dataset('Profile', data=profile_data)

            # Write attributes as a compound dataset
            # This matches the GroundLineModificationLayer attribute schema
            attr_dtype = np.dtype([
                ('SystemName', 'S64'),
                ('Computed System Name', 'S64'),
                ('Top Elevation', '<f4'),
                ('Width', '<f4'),
                ('LeftSlope', '<f4'),
                ('RightSlope', '<f4'),
                ('Transition Fraction', '<f4'),
                ('Max Extent', '<f4'),
                ('Elev Pt Tolerance', '<f4'),
                ('ElevationType', '<i4'),
                ('ElevationValue', '<f4'),
            ])

            attrs_data = np.array([(
                name.encode('utf-8')[:64],  # SystemName
                name.encode('utf-8')[:64],  # Computed System Name
                np.float32(0.0),            # Top Elevation (0 = use terrain)
                np.float32(width),
                np.float32(left_slope),
                np.float32(right_slope),
                np.float32(0.5),            # Transition Fraction
                np.float32(max_extent),
                np.float32(elev_pt_tolerance),
                np.int32(MODIFICATION_TAKE_LOWER),
                np.float32(-depth),         # ElevationValue (negative = below terrain)
            )], dtype=attr_dtype)

            mod_grp.create_dataset('Attributes', data=attrs_data)

            # Create empty Control Points group
            cp_grp = mod_grp.create_group('Control Points')
            cp_grp.attrs['Type'] = np.bytes_('ControlCrossSection')

            logger.info(f"Wrote channel modification '{name}' to HDF: "
                       f"{n_pts} pts, length={total_length:.1f}, "
                       f"width={width}, depth={depth}")

    @staticmethod
    def _ensure_modification_group_in_rasmap(
        rasmap_path: Path,
        terrain_hdf_path: Path,
        group_name: str,
    ) -> ET.Element:
        """Ensure the modification group exists in .rasmap XML. Returns the group element."""
        tree = ET.parse(rasmap_path)
        root = tree.getroot()

        # Find the terrain layer that matches our HDF file
        terrain_layer = None
        terrains = root.find('.//Terrains')
        if terrains is None:
            raise ValueError(f"No <Terrains> element found in {rasmap_path}")

        terrain_filename = f".\\{terrain_hdf_path.relative_to(terrain_hdf_path.parent.parent)}"
        # Normalize to forward or back slashes to match
        for layer in terrains.findall('Layer'):
            layer_file = layer.get('Filename', '')
            if terrain_hdf_path.name in layer_file:
                terrain_layer = layer
                break

        if terrain_layer is None:
            raise ValueError(
                f"Terrain layer for {terrain_hdf_path.name} not found in {rasmap_path}"
            )

        # Find or create the modification group layer
        mod_group = None
        for child in terrain_layer.findall('Layer'):
            if child.get('Type') == 'ElevationModificationGroup':
                mod_group = child
                break

        if mod_group is None:
            mod_group = ET.SubElement(terrain_layer, 'Layer')
            mod_group.set('Name', group_name)
            mod_group.set('Type', 'ElevationModificationGroup')
            logger.info(f"Created modification group '{group_name}' in .rasmap")

        tree.write(rasmap_path, xml_declaration=False, encoding='unicode')
        return mod_group

    @staticmethod
    def _update_rasmap_xml(
        rasmap_path: Path,
        terrain_hdf_path: Path,
        name: str,
        mod_type: str,
        default_mod_type: int,
        elev_pt_tolerance: float,
        group_name: str,
    ) -> None:
        """Update .rasmap XML to include the terrain modification layer."""
        # Ensure the group exists first
        mod_group = RasTerrainModWriter._ensure_modification_group_in_rasmap(
            rasmap_path, terrain_hdf_path, group_name
        )

        # Re-parse since _ensure_modification_group_in_rasmap may have written
        tree = ET.parse(rasmap_path)
        root = tree.getroot()

        # Find the mod group again
        terrains = root.find('.//Terrains')
        terrain_layer = None
        for layer in terrains.findall('Layer'):
            if terrain_hdf_path.name in layer.get('Filename', ''):
                terrain_layer = layer
                break

        mod_group = None
        for child in terrain_layer.findall('Layer'):
            if child.get('Type') == 'ElevationModificationGroup':
                mod_group = child
                break

        # Check if modification layer already exists
        for child in mod_group.findall('Layer'):
            if child.get('Name') == name:
                logger.warning(f"Modification layer '{name}' already in .rasmap, replacing")
                mod_group.remove(child)

        # Add the modification layer
        mod_layer = ET.SubElement(mod_group, 'Layer')
        mod_layer.set('Name', name)
        mod_layer.set('Type', mod_type)

        default_type_el = ET.SubElement(mod_layer, 'DefaultModificationType')
        default_type_el.set('Value', str(default_mod_type))

        default_tol_el = ET.SubElement(mod_layer, 'DefaultElevPtTol')
        default_tol_el.set('Value', str(int(elev_pt_tolerance)))

        # Add control points sub-layer
        cp_layer = ET.SubElement(mod_layer, 'Layer')
        cp_layer.set('Name', 'Control Points')
        cp_layer.set('Type', 'ElevationControlPointLayer')

        tree.write(rasmap_path, xml_declaration=False, encoding='unicode')
        logger.info(f"Added modification layer '{name}' to .rasmap")
