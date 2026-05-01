"""
RasTerrainModWriter - Create terrain modifications in HEC-RAS terrain HDF files.

Writes channel, high-ground, and fill-surface terrain modifications to terrain
HDF files and updates the .rasmap XML to register them. This enables
programmatic terrain modification without the RASMapper GUI.

Supports:
    - Channel modifications (TakeLower) along polylines
    - High-ground levee/road modifications (TakeHigher) along polylines
    - Fill-surface encroachment modifications (SetValue) along polylines
    - Modification groups for organizing multiple modifications
    - Writing to both terrain HDF and .rasmap XML

Platform:
    Cross-platform (no pythonnet/RasMapperLib required for writing).

Requirements:
    - h5py for HDF5 writing
    - numpy for array operations
"""

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

from ..Decorators import log_call
from ..LoggingConfig import get_logger

logger = get_logger(__name__)

# Modification type constants
MODIFICATION_SET_VALUE = 0
MODIFICATION_TAKE_HIGHER = 1
MODIFICATION_TAKE_LOWER = 2
MODIFICATION_ADD_VALUE = 3

_MODE_ALIASES = {
    "set": MODIFICATION_SET_VALUE,
    "set_value": MODIFICATION_SET_VALUE,
    "fill": MODIFICATION_SET_VALUE,
    "fill_surface": MODIFICATION_SET_VALUE,
    "take_higher": MODIFICATION_TAKE_HIGHER,
    "higher": MODIFICATION_TAKE_HIGHER,
    "high_ground": MODIFICATION_TAKE_HIGHER,
    "take_lower": MODIFICATION_TAKE_LOWER,
    "lower": MODIFICATION_TAKE_LOWER,
    "channel": MODIFICATION_TAKE_LOWER,
    "add": MODIFICATION_ADD_VALUE,
    "add_value": MODIFICATION_ADD_VALUE,
}


class RasTerrainModWriter:
    """Write terrain modifications to HEC-RAS terrain HDF and .rasmap files."""

    @staticmethod
    @log_call
    def add_high_ground_modification(
        terrain_hdf_path: Union[str, Path],
        rasmap_path: Union[str, Path],
        name: str,
        polyline_points: Union[np.ndarray, Sequence[Sequence[float]]],
        top_width: float = 20.0,
        side_slope: float = 2.0,
        left_slope: Optional[float] = None,
        right_slope: Optional[float] = None,
        max_extent: float = 100.0,
        elevation: Optional[float] = None,
        profile_points: Optional[Union[np.ndarray, Sequence[Sequence[float]]]] = None,
        mode: Union[str, int] = "take_higher",
        elev_pt_tolerance: float = 50.0,
        transition_fraction: float = 0.5,
        group_name: str = "Modifications",
    ) -> Path:
        """
        Add a high-ground line terrain modification for levees or roads.

        This writes the RAS Mapper ``Lines | High Ground`` style terrain
        modification. The default mode is ``take_higher`` so the proposed
        trapezoidal crest raises low ground but does not cut terrain that is
        already higher. Pass ``mode="fill_surface"`` or use
        :meth:`add_fill_surface_modification` for encroachment fill surfaces.

        Parameters
        ----------
        terrain_hdf_path : Path
            Path to the copied terrain HDF file to modify.
        rasmap_path : Path
            Path to the .rasmap XML file where the terrain layer is registered.
        name : str
            Name for this terrain modification layer.
        polyline_points : array-like
            Nx2 or Nx3 array of line coordinates. Nx3 input uses the third
            column as the crest/fill elevation profile when ``elevation`` and
            ``profile_points`` are omitted.
        top_width : float
            Flat crest/top width in terrain units.
        side_slope : float
            Default side slope as H:V ratio, used when left/right are omitted.
        left_slope, right_slope : float, optional
            Explicit left and right side slopes as H:V ratios.
        max_extent : float
            Maximum lateral extent width in terrain units.
        elevation : float, optional
            Constant crest/fill elevation. Required when ``polyline_points`` has
            no Z column and ``profile_points`` is not provided.
        profile_points : array-like, optional
            Nx2 station/elevation profile along the line. Overrides Z values in
            ``polyline_points`` when provided.
        mode : {"take_higher", "fill_surface"} or int
            Terrain merge mode. ``take_higher`` writes Higher Terrain Value;
            ``fill_surface`` writes Set Value.
        elev_pt_tolerance : float
            Elevation point tolerance.
        transition_fraction : float
            Transition fraction written to the HDF attribute table.
        group_name : str
            Name of the modification group in .rasmap.

        Returns
        -------
        Path
            Path to the modified terrain HDF file.
        """
        terrain_hdf_path = Path(terrain_hdf_path)
        rasmap_path = Path(rasmap_path)
        line_points = RasTerrainModWriter._validate_polyline_points(polyline_points)
        modification_type = RasTerrainModWriter._resolve_modification_type(mode)

        if modification_type not in {MODIFICATION_TAKE_HIGHER, MODIFICATION_SET_VALUE}:
            raise ValueError(
                "High-ground modifications support mode='take_higher' or "
                "mode='fill_surface'"
            )

        left = side_slope if left_slope is None else left_slope
        right = side_slope if right_slope is None else right_slope
        RasTerrainModWriter._validate_ground_line_dimensions(
            top_width, left, right, max_extent, elev_pt_tolerance, transition_fraction
        )

        stations = RasTerrainModWriter._station_values(line_points[:, :2])
        profile_data = RasTerrainModWriter._build_profile_data(
            line_points=line_points,
            stations=stations,
            elevation=elevation,
            profile_points=profile_points,
        )

        subtype = "High Ground" if modification_type == MODIFICATION_TAKE_HIGHER else "Fill Surface"
        logger.info(
            "Adding %s terrain modification '%s' to %s",
            subtype.lower(),
            name,
            terrain_hdf_path.name,
        )

        RasTerrainModWriter._write_ground_line_to_hdf(
            terrain_hdf_path=terrain_hdf_path,
            name=name,
            polyline_points=line_points[:, :2],
            profile_data=profile_data,
            width=top_width,
            left_slope=left,
            right_slope=right,
            max_extent=max_extent,
            elev_pt_tolerance=elev_pt_tolerance,
            modification_type=modification_type,
            transition_fraction=transition_fraction,
            subtype=subtype,
        )

        RasTerrainModWriter._update_rasmap_xml(
            rasmap_path,
            terrain_hdf_path,
            name,
            mod_type="GroundLineModificationLayer",
            default_mod_type=modification_type,
            elev_pt_tolerance=elev_pt_tolerance,
            group_name=group_name,
        )

        logger.info("Terrain modification '%s' added successfully", name)
        return terrain_hdf_path

    @staticmethod
    @log_call
    def add_fill_surface_modification(
        terrain_hdf_path: Union[str, Path],
        rasmap_path: Union[str, Path],
        name: str,
        polyline_points: Union[np.ndarray, Sequence[Sequence[float]]],
        top_width: float = 20.0,
        side_slope: float = 2.0,
        left_slope: Optional[float] = None,
        right_slope: Optional[float] = None,
        max_extent: float = 100.0,
        elevation: Optional[float] = None,
        profile_points: Optional[Union[np.ndarray, Sequence[Sequence[float]]]] = None,
        elev_pt_tolerance: float = 50.0,
        transition_fraction: float = 0.5,
        group_name: str = "Modifications",
    ) -> Path:
        """
        Add a set-value fill-surface terrain modification along a line.

        This is a convenience wrapper around :meth:`add_high_ground_modification`
        with ``mode="fill_surface"`` for floodway and encroachment fill
        workflows.
        """
        return RasTerrainModWriter.add_high_ground_modification(
            terrain_hdf_path=terrain_hdf_path,
            rasmap_path=rasmap_path,
            name=name,
            polyline_points=polyline_points,
            top_width=top_width,
            side_slope=side_slope,
            left_slope=left_slope,
            right_slope=right_slope,
            max_extent=max_extent,
            elevation=elevation,
            profile_points=profile_points,
            mode="fill_surface",
            elev_pt_tolerance=elev_pt_tolerance,
            transition_fraction=transition_fraction,
            group_name=group_name,
        )

    @staticmethod
    @log_call
    def add_channel_modification(
        terrain_hdf_path: Union[str, Path],
        rasmap_path: Union[str, Path],
        name: str,
        polyline_points: Union[np.ndarray, Sequence[Sequence[float]]],
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
        terrain_hdf_path = Path(terrain_hdf_path)
        rasmap_path = Path(rasmap_path)
        line_points = RasTerrainModWriter._validate_polyline_points(polyline_points)[:, :2]
        RasTerrainModWriter._validate_ground_line_dimensions(
            width, left_slope, right_slope, max_extent, elev_pt_tolerance, 0.5
        )
        RasTerrainModWriter._validate_positive("depth", depth)

        logger.info(f"Adding channel modification '{name}' to {terrain_hdf_path.name}")
        logger.info(f"  Alignment: {len(line_points)} points")
        logger.info(f"  Channel: width={width}, depth={depth}, slopes={left_slope}/{right_slope}")

        stations = RasTerrainModWriter._station_values(line_points)
        profile_data = np.column_stack(
            [
                np.array([0.0, stations[-1] / 2, stations[-1]], dtype=np.float64),
                np.full(3, -float(depth), dtype=np.float64),
            ]
        )

        RasTerrainModWriter._write_ground_line_to_hdf(
            terrain_hdf_path=terrain_hdf_path,
            name=name,
            polyline_points=line_points,
            profile_data=profile_data,
            width=width,
            left_slope=left_slope,
            right_slope=right_slope,
            max_extent=max_extent,
            elev_pt_tolerance=elev_pt_tolerance,
            modification_type=MODIFICATION_TAKE_LOWER,
            transition_fraction=0.5,
            subtype="Channel",
            elevation_value=-float(depth),
            top_elevation=0.0,
        )

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
    @log_call
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
    @log_call
    def list_modifications(terrain_hdf_path: Union[str, Path]) -> pd.DataFrame:
        """
        List terrain modifications stored in a terrain HDF sidecar group.

        Returns
        -------
        pandas.DataFrame
            One row per modification with name, subtype, merge mode, width,
            slopes, max extent, and profile point count.
        """
        import h5py

        terrain_hdf_path = Path(terrain_hdf_path)
        rows: List[Dict[str, object]] = []

        with h5py.File(terrain_hdf_path, "r") as f:
            mods = f.get("Modifications")
            if mods is None:
                return pd.DataFrame(
                    columns=[
                        "name",
                        "type",
                        "subtype",
                        "priority",
                        "modification_type",
                        "modification_mode",
                        "width",
                        "left_slope",
                        "right_slope",
                        "max_extent",
                        "elev_pt_tolerance",
                        "profile_points",
                    ]
                )

            for mod_name, mod_grp in mods.items():
                attr_row = {}
                if "Attributes" in mod_grp and len(mod_grp["Attributes"]) > 0:
                    attr_row = {
                        key: RasTerrainModWriter._decode_hdf_scalar(value)
                        for key, value in zip(
                            mod_grp["Attributes"].dtype.names,
                            mod_grp["Attributes"][0],
                        )
                    }

                modification_type = int(attr_row.get("ElevationType", -1))
                rows.append(
                    {
                        "name": mod_name,
                        "type": RasTerrainModWriter._decode_hdf_scalar(
                            mod_grp.attrs.get("Type", "")
                        ),
                        "subtype": RasTerrainModWriter._decode_hdf_scalar(
                            mod_grp.attrs.get("Subtype", "")
                        ),
                        "priority": int(mod_grp.attrs.get("Priority", 0)),
                        "modification_type": modification_type,
                        "modification_mode": RasTerrainModWriter._mode_name(
                            modification_type
                        ),
                        "width": float(attr_row.get("Width", np.nan)),
                        "left_slope": float(attr_row.get("LeftSlope", np.nan)),
                        "right_slope": float(attr_row.get("RightSlope", np.nan)),
                        "max_extent": float(attr_row.get("Max Extent", np.nan)),
                        "elev_pt_tolerance": float(
                            attr_row.get("Elev Pt Tolerance", np.nan)
                        ),
                        "profile_points": int(
                            mod_grp["Profile"].shape[0] if "Profile" in mod_grp else 0
                        ),
                    }
                )

        return pd.DataFrame(rows)

    @staticmethod
    @log_call
    def get_modification_profile(
        terrain_hdf_path: Union[str, Path],
        name: str,
    ) -> pd.DataFrame:
        """
        Read a terrain modification station/elevation profile from HDF.

        This helper verifies the writer output and gives users a lightweight
        way to inspect levee or fill-surface elevations before sampling the
        modified terrain with :class:`RasTerrainMod`.
        """
        import h5py

        terrain_hdf_path = Path(terrain_hdf_path)
        with h5py.File(terrain_hdf_path, "r") as f:
            profile_path = f"Modifications/{name}/Profile"
            if profile_path not in f:
                raise KeyError(f"Modification profile not found: {profile_path}")
            profile = np.asarray(f[profile_path][:], dtype=np.float64)

        return pd.DataFrame(
            {
                "station": profile[:, 0],
                "elevation": profile[:, 1],
            }
        )

    @staticmethod
    @log_call
    def compare_before_after_profiles(
        rasmap_existing: Union[str, Path],
        rasmap_modified: Union[str, Path],
        geom_hdf_path: Union[str, Path],
        x_coords: List[float],
        y_coords: List[float],
        filter_tolerance: float = 0.01,
    ) -> pd.DataFrame:
        """
        Compare terrain profiles before and after a terrain modification.

        This delegates to :meth:`RasTerrainMod.compare_terrain_profiles`, so it
        requires HEC-RAS/RasMapperLib on the host. The writer itself remains
        cross-platform and does not import pythonnet until this helper is used.
        """
        from .RasTerrainMod import RasTerrainMod

        return RasTerrainMod.compare_terrain_profiles(
            rasmap_existing=rasmap_existing,
            rasmap_proposed=rasmap_modified,
            geom_hdf_path=geom_hdf_path,
            x_coords=x_coords,
            y_coords=y_coords,
            filter_tolerance=filter_tolerance,
        )

    @staticmethod
    def _write_ground_line_to_hdf(
        terrain_hdf_path: Path,
        name: str,
        polyline_points: np.ndarray,
        width: float,
        left_slope: float,
        right_slope: float,
        max_extent: float,
        elev_pt_tolerance: float,
        modification_type: int,
        transition_fraction: float,
        subtype: str,
        profile_data: np.ndarray,
        elevation_value: Optional[float] = None,
        top_elevation: Optional[float] = None,
    ) -> None:
        """Write a ground-line modification to a terrain HDF file."""
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
            mod_grp.attrs['Subtype'] = np.bytes_(subtype)
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

            if elevation_value is None:
                elevation_value = float(np.mean(profile_data[:, 1]))
            if top_elevation is None:
                top_elevation = float(np.max(profile_data[:, 1]))

            attrs_data = np.array([(
                name.encode('utf-8')[:64],  # SystemName
                name.encode('utf-8')[:64],  # Computed System Name
                np.float32(top_elevation),
                np.float32(width),
                np.float32(left_slope),
                np.float32(right_slope),
                np.float32(transition_fraction),
                np.float32(max_extent),
                np.float32(elev_pt_tolerance),
                np.int32(modification_type),
                np.float32(elevation_value),
            )], dtype=attr_dtype)

            mod_grp.create_dataset('Attributes', data=attrs_data)

            # Create empty Control Points group
            cp_grp = mod_grp.create_group('Control Points')
            cp_grp.attrs['Type'] = np.bytes_('ControlCrossSection')

            logger.info(f"Wrote ground-line modification '{name}' to HDF: "
                       f"{n_pts} pts, length={profile_data[-1, 0]:.1f}, "
                       f"width={width}, mode={modification_type}")

    @staticmethod
    def _validate_polyline_points(
        polyline_points: Union[np.ndarray, Sequence[Sequence[float]]],
    ) -> np.ndarray:
        """Validate and return an Nx2/Nx3 terrain modification polyline."""
        points = np.asarray(polyline_points, dtype=np.float64)

        if points.ndim != 2 or points.shape[1] not in {2, 3}:
            raise ValueError("polyline_points must be an Nx2 or Nx3 coordinate array")
        if len(points) < 2:
            raise ValueError("polyline_points must have at least 2 points")
        if not np.all(np.isfinite(points[:, :2])):
            raise ValueError("polyline_points XY coordinates must contain only finite values")

        stations = RasTerrainModWriter._station_values(points[:, :2])
        if stations[-1] <= 0:
            raise ValueError("polyline_points must define a non-zero-length line")

        return points

    @staticmethod
    def _station_values(xy_points: np.ndarray) -> np.ndarray:
        """Compute cumulative station values along an XY polyline."""
        dx = np.diff(xy_points[:, 0])
        dy = np.diff(xy_points[:, 1])
        segment_lengths = np.sqrt(dx**2 + dy**2)
        stations = np.zeros(len(xy_points), dtype=np.float64)
        stations[1:] = np.cumsum(segment_lengths)
        return stations

    @staticmethod
    def _build_profile_data(
        line_points: np.ndarray,
        stations: np.ndarray,
        elevation: Optional[float],
        profile_points: Optional[Union[np.ndarray, Sequence[Sequence[float]]]],
    ) -> np.ndarray:
        """Build station/elevation profile data for a ground-line modification."""
        if profile_points is not None:
            profile_data = np.asarray(profile_points, dtype=np.float64)
            if profile_data.ndim != 2 or profile_data.shape[1] != 2:
                raise ValueError("profile_points must be an Nx2 station/elevation array")
            if len(profile_data) < 2:
                raise ValueError("profile_points must contain at least 2 rows")
            if not np.all(np.isfinite(profile_data)):
                raise ValueError("profile_points must contain only finite values")
            if np.any(np.diff(profile_data[:, 0]) < 0):
                raise ValueError("profile_points stations must be monotonically increasing")
            return profile_data

        if elevation is not None:
            RasTerrainModWriter._validate_finite("elevation", elevation)
            return np.array(
                [
                    [0.0, float(elevation)],
                    [float(stations[-1]), float(elevation)],
                ],
                dtype=np.float64,
            )

        if line_points.shape[1] == 3:
            if not np.all(np.isfinite(line_points[:, 2])):
                raise ValueError(
                    "polyline_points Z values must be finite when elevation "
                    "or profile_points is not provided"
                )
            return np.column_stack([stations, line_points[:, 2]])

        raise ValueError(
            "elevation or profile_points is required when polyline_points has no Z column"
        )

    @staticmethod
    def _validate_ground_line_dimensions(
        width: float,
        left_slope: float,
        right_slope: float,
        max_extent: float,
        elev_pt_tolerance: float,
        transition_fraction: float,
    ) -> None:
        """Validate common line terrain modification dimensions."""
        RasTerrainModWriter._validate_positive("width", width)
        RasTerrainModWriter._validate_non_negative("left_slope", left_slope)
        RasTerrainModWriter._validate_non_negative("right_slope", right_slope)
        RasTerrainModWriter._validate_positive("max_extent", max_extent)
        RasTerrainModWriter._validate_non_negative("elev_pt_tolerance", elev_pt_tolerance)
        RasTerrainModWriter._validate_finite("transition_fraction", transition_fraction)

        if not 0 <= float(transition_fraction) <= 1:
            raise ValueError("transition_fraction must be between 0 and 1")

    @staticmethod
    def _validate_positive(name: str, value: float) -> None:
        RasTerrainModWriter._validate_finite(name, value)
        if float(value) <= 0:
            raise ValueError(f"{name} must be greater than zero")

    @staticmethod
    def _validate_non_negative(name: str, value: float) -> None:
        RasTerrainModWriter._validate_finite(name, value)
        if float(value) < 0:
            raise ValueError(f"{name} must be greater than or equal to zero")

    @staticmethod
    def _validate_finite(name: str, value: float) -> None:
        if not np.isfinite(float(value)):
            raise ValueError(f"{name} must be finite")

    @staticmethod
    def _resolve_modification_type(mode: Union[str, int]) -> int:
        """Resolve a string/int terrain merge mode to the HEC-RAS integer code."""
        if isinstance(mode, str):
            key = mode.strip().lower().replace("-", "_").replace(" ", "_")
            if key not in _MODE_ALIASES:
                raise ValueError(
                    f"Unsupported terrain modification mode '{mode}'. "
                    f"Supported modes: {', '.join(sorted(_MODE_ALIASES))}"
                )
            return _MODE_ALIASES[key]

        modification_type = int(mode)
        if modification_type not in {
            MODIFICATION_SET_VALUE,
            MODIFICATION_TAKE_HIGHER,
            MODIFICATION_TAKE_LOWER,
            MODIFICATION_ADD_VALUE,
        }:
            raise ValueError(f"Unsupported terrain modification type: {mode}")
        return modification_type

    @staticmethod
    def _mode_name(modification_type: int) -> str:
        """Return a readable terrain merge mode name for an integer code."""
        names = {
            MODIFICATION_SET_VALUE: "set_value",
            MODIFICATION_TAKE_HIGHER: "take_higher",
            MODIFICATION_TAKE_LOWER: "take_lower",
            MODIFICATION_ADD_VALUE: "add_value",
        }
        return names.get(modification_type, "unknown")

    @staticmethod
    def _decode_hdf_scalar(value):
        """Decode HDF byte strings and numpy scalar values for helper output."""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace").rstrip("\x00")
        if isinstance(value, np.bytes_):
            return bytes(value).decode("utf-8", errors="replace").rstrip("\x00")
        if isinstance(value, np.generic):
            return value.item()
        return value

    @staticmethod
    def _find_terrain_layer(
        root: ET.Element,
        rasmap_path: Path,
        terrain_hdf_path: Path,
    ) -> ET.Element:
        """Find the .rasmap terrain layer that references a terrain HDF."""
        terrains = root.find(".//Terrains")
        if terrains is None:
            raise ValueError(f"No <Terrains> element found in {rasmap_path}")

        for layer in terrains.findall("Layer"):
            if RasTerrainModWriter._layer_references_path(
                layer.get("Filename", ""), rasmap_path, terrain_hdf_path
            ):
                return layer

        raise ValueError(
            f"Terrain layer for {terrain_hdf_path.name} not found in {rasmap_path}"
        )

    @staticmethod
    def _layer_references_path(layer_file: str, rasmap_path: Path, target_path: Path) -> bool:
        """Check whether a .rasmap Filename attribute references target_path."""
        if not layer_file:
            return False

        normalized = layer_file.replace("\\", "/")
        candidate = Path(normalized)
        if not candidate.is_absolute():
            candidate = rasmap_path.parent / candidate

        try:
            if candidate.resolve() == target_path.resolve():
                return True
        except OSError:
            pass

        return Path(normalized).name == target_path.name

    @staticmethod
    def _ensure_modification_group_in_rasmap(
        rasmap_path: Path,
        terrain_hdf_path: Path,
        group_name: str,
    ) -> ET.Element:
        """Ensure the modification group exists in .rasmap XML. Returns the group element."""
        tree = ET.parse(rasmap_path)
        root = tree.getroot()

        terrain_layer = RasTerrainModWriter._find_terrain_layer(
            root, rasmap_path, terrain_hdf_path
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
        terrain_layer = RasTerrainModWriter._find_terrain_layer(
            root, rasmap_path, terrain_hdf_path
        )

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
