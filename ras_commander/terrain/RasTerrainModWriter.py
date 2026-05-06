"""
RasTerrainModWriter - Create terrain modifications in HEC-RAS terrain HDF files.

Writes channel, high-ground, and fill-surface terrain modifications to terrain
HDF files and updates the .rasmap XML to register them. This enables
programmatic terrain modification without the RASMapper GUI.

Supports:
    - Channel modifications (TakeLower) along polylines
    - High-ground levee/road modifications (TakeHigher) along polylines
    - Fill-surface encroachment modifications (SetValue) along polylines
    - Polygon multipoint modifications with boundary and interior elevations
    - Modification groups for organizing multiple modifications
    - Writing to both terrain HDF and .rasmap XML

Platform:
    Cross-platform (no pythonnet/RasMapperLib required for writing).

Requirements:
    - h5py for HDF5 writing
    - numpy for array operations
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union
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

_MODIFICATION_TYPE_DISK_NAMES = {
    MODIFICATION_SET_VALUE: "SetValue",
    MODIFICATION_TAKE_HIGHER: "SetIfHigher",
    MODIFICATION_TAKE_LOWER: "SetIfLower",
    MODIFICATION_ADD_VALUE: "Add",
}

_MODIFICATION_TYPE_BY_DISK_NAME = {
    "setvalue": MODIFICATION_SET_VALUE,
    "set": MODIFICATION_SET_VALUE,
    "set_value": MODIFICATION_SET_VALUE,
    "setifhigher": MODIFICATION_TAKE_HIGHER,
    "takehigher": MODIFICATION_TAKE_HIGHER,
    "take_higher": MODIFICATION_TAKE_HIGHER,
    "higher": MODIFICATION_TAKE_HIGHER,
    "setiflower": MODIFICATION_TAKE_LOWER,
    "takelower": MODIFICATION_TAKE_LOWER,
    "take_lower": MODIFICATION_TAKE_LOWER,
    "lower": MODIFICATION_TAKE_LOWER,
    "add": MODIFICATION_ADD_VALUE,
    "addvalue": MODIFICATION_ADD_VALUE,
    "add_value": MODIFICATION_ADD_VALUE,
}

_RASTER_SOURCE_SUFFIXES = {
    ".adf",
    ".asc",
    ".bil",
    ".flt",
    ".img",
    ".tif",
    ".tiff",
    ".vrt",
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

        subtype_label = (
            "High Ground"
            if modification_type == MODIFICATION_TAKE_HIGHER
            else "Fill Surface"
        )
        logger.info(
            "Adding %s terrain modification '%s' to %s",
            subtype_label.lower(),
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
            subtype="Levee",
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
    def add_modification_polygon(
        terrain_hdf_path: Union[str, Path],
        name: str,
        polygon_coords: Any,
        elevation_method: str = "boundary_from_terrain",
        control_points: Optional[Sequence[Any]] = None,
        rasmap_path: Optional[Union[str, Path]] = None,
        boundary_elevations: Optional[Union[np.ndarray, Sequence[float]]] = None,
        mode: Union[str, int] = "set_value",
        elev_pt_tolerance: float = 50.0,
        group_name: str = "Modifications",
    ) -> Path:
        """
        Add a polygon multipoint terrain modification.

        This writes the RAS Mapper ``Polygons | Multipoint`` style sidecar
        data. Boundary elevations can be sampled from the terrain source raster
        references stored in the terrain HDF, supplied from polygon Z values, or
        passed explicitly. Interior control points are persisted as point
        features with their elevations for detention pond and wetland grading
        workflows.

        Parameters
        ----------
        terrain_hdf_path : Path
            Path to the copied terrain HDF file to modify.
        name : str
            Name for this terrain modification layer.
        polygon_coords : array-like or GeoJSON-like
            Polygon boundary as an Nx2/Nx3 ring or a sequence of rings. Rings
            are closed automatically when needed.
        elevation_method : {"boundary_from_terrain", "shape_z", "provided"}
            Source for polygon boundary elevations. ``boundary_from_terrain``
            samples the terrain source raster(s); ``shape_z`` uses the third
            coordinate from ``polygon_coords``; ``provided`` uses
            ``boundary_elevations``.
        control_points : sequence, optional
            Interior elevation points as ``(x, y, elevation)`` tuples or dicts
            with ``x``, ``y``, and ``elevation``/``z`` keys.
        rasmap_path : Path, optional
            Path to the .rasmap XML file. When omitted, the writer searches the
            terrain folder and project folder for a .rasmap referencing this
            terrain HDF.
        boundary_elevations : array-like, optional
            Explicit boundary elevations matching the closed polygon point
            count. Used with ``elevation_method="provided"``.
        mode : str or int
            Terrain merge mode. Multipoint polygon pond workflows typically use
            ``set_value``.
        elev_pt_tolerance : float
            Elevation point tolerance written to HDF and .rasmap metadata.
        group_name : str
            Name of the modification group in .rasmap.

        Returns
        -------
        Path
            Path to the modified terrain HDF file.
        """
        terrain_hdf_path = Path(terrain_hdf_path)
        if rasmap_path is None:
            rasmap_path = RasTerrainModWriter._infer_rasmap_path(terrain_hdf_path)
        else:
            rasmap_path = Path(rasmap_path)

        modification_type = RasTerrainModWriter._resolve_modification_type(mode)
        RasTerrainModWriter._validate_non_negative(
            "elev_pt_tolerance", elev_pt_tolerance
        )

        rings_xy, rings_z = RasTerrainModWriter._validate_polygon_rings(polygon_coords)
        control_xy, control_elevations, control_names = (
            RasTerrainModWriter._validate_control_points(control_points)
        )
        RasTerrainModWriter._validate_control_points_inside_polygon(
            control_xy, rings_xy[0]
        )

        boundary_xy = np.vstack(rings_xy)
        boundary_values = RasTerrainModWriter._boundary_elevations_for_polygon(
            terrain_hdf_path=terrain_hdf_path,
            boundary_xy=boundary_xy,
            rings_z=rings_z,
            elevation_method=elevation_method,
            boundary_elevations=boundary_elevations,
        )

        logger.info(
            "Adding polygon multipoint terrain modification '%s' to %s",
            name,
            terrain_hdf_path.name,
        )

        RasTerrainModWriter._write_polygon_to_hdf(
            terrain_hdf_path=terrain_hdf_path,
            name=name,
            rings_xy=rings_xy,
            boundary_elevations=boundary_values,
            control_xy=control_xy,
            control_elevations=control_elevations,
            control_names=control_names,
            modification_type=modification_type,
            elevation_method=elevation_method,
            elev_pt_tolerance=elev_pt_tolerance,
        )

        RasTerrainModWriter._update_rasmap_xml(
            rasmap_path,
            terrain_hdf_path,
            name,
            mod_type="PolygonElevationModificationLayer",
            default_mod_type=modification_type,
            elev_pt_tolerance=elev_pt_tolerance,
            group_name=group_name,
        )

        logger.info("Polygon terrain modification '%s' added successfully", name)
        return terrain_hdf_path

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

                modification_type = RasTerrainModWriter._modification_type_value(
                    RasTerrainModWriter._attr_value(
                        attr_row, "Elevation Type", "ElevationType", default=-1
                    )
                )
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
                        "width": RasTerrainModWriter._float_attr(
                            attr_row, "Top Width", "Width"
                        ),
                        "left_slope": RasTerrainModWriter._float_attr(
                            attr_row, "Left Slope", "LeftSlope"
                        ),
                        "right_slope": RasTerrainModWriter._float_attr(
                            attr_row, "Right Slope", "RightSlope"
                        ),
                        "max_extent": RasTerrainModWriter._float_attr(
                            attr_row, "Max Reach", "Max Extent"
                        ),
                        "elev_pt_tolerance": RasTerrainModWriter._float_attr(
                            attr_row, "Elev Pt Tolerance"
                        ),
                        "profile_points": RasTerrainModWriter._profile_point_count(
                            mod_grp
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
            mod_path = f"Modifications/{name}"
            if mod_path not in f:
                raise KeyError(f"Modification not found: {mod_path}")
            profile = RasTerrainModWriter._read_profile_array(f[mod_path])

        return pd.DataFrame(
            {
                "station": profile[:, 0],
                "elevation": profile[:, 1],
            }
        )

    @staticmethod
    @log_call
    def sample_modification_surface(
        terrain_hdf_path: Union[str, Path],
        name: str,
        points: Union[np.ndarray, Sequence[Sequence[float]], pd.DataFrame],
        existing_elevations: Optional[Union[np.ndarray, Sequence[float], pd.Series]] = None,
        x_col: str = "x",
        y_col: str = "y",
    ) -> pd.DataFrame:
        """
        Evaluate a line terrain modification at XY points.

        This helper reads the ground-line sidecar data written under
        ``/Modifications/<name>`` and computes the proposed trapezoidal
        surface at each supplied XY point. When ``existing_elevations`` are
        supplied, the terrain merge mode is applied and the returned
        ``modified_elevation`` and ``difference`` columns provide a lightweight
        before/after check without invoking the RAS Mapper GUI.

        Parameters
        ----------
        terrain_hdf_path : Path
            Terrain HDF containing the modification sidecar group.
        name : str
            Modification layer name under ``/Modifications``.
        points : array-like or pandas.DataFrame
            Nx2 XY coordinates or a DataFrame with ``x_col``/``y_col``.
        existing_elevations : array-like, optional
            Existing terrain elevations at the same points.
        x_col, y_col : str
            DataFrame coordinate column names used when ``points`` is a
            DataFrame.

        Returns
        -------
        pandas.DataFrame
            Columns include XY coordinates, projected line station, signed
            offset, proposed modification surface, merge-mode-applied
            elevation, and before/after difference when existing elevations are
            supplied.
        """
        line, profile, attrs = RasTerrainModWriter._read_ground_line_modification(
            terrain_hdf_path, name
        )
        xy = RasTerrainModWriter._points_to_xy(points, x_col=x_col, y_col=y_col)
        existing = RasTerrainModWriter._optional_elevations(
            existing_elevations, len(xy)
        )

        station, offset = RasTerrainModWriter._project_points_to_polyline(xy, line)
        surface = RasTerrainModWriter._ground_line_surface_from_offsets(
            station=station,
            offset=offset,
            profile=profile,
            width=float(attrs["width"]),
            left_slope=float(attrs["left_slope"]),
            right_slope=float(attrs["right_slope"]),
            max_extent=float(attrs["max_extent"]),
        )
        modified = RasTerrainModWriter._apply_modification_mode(
            existing, surface, int(attrs["modification_type"])
        )

        result = pd.DataFrame(
            {
                "x": xy[:, 0],
                "y": xy[:, 1],
                "line_station": station,
                "offset": offset,
                "distance": np.abs(offset),
                "modification_surface": surface,
                "in_extent": np.isfinite(surface),
                "modification_type": int(attrs["modification_type"]),
                "modification_mode": RasTerrainModWriter._mode_name(
                    int(attrs["modification_type"])
                ),
                "modified_elevation": modified,
            }
        )

        if existing is not None:
            result.insert(2, "existing_elevation", existing)
            result["difference"] = result["modified_elevation"] - existing

        return result

    @staticmethod
    @log_call
    def apply_modification_to_profile(
        terrain_hdf_path: Union[str, Path],
        name: str,
        profile: pd.DataFrame,
        x_coords: Optional[Sequence[float]] = None,
        y_coords: Optional[Sequence[float]] = None,
        station_col: str = "station",
        elevation_col: str = "elevation",
        x_col: str = "x",
        y_col: str = "y",
    ) -> pd.DataFrame:
        """
        Apply a line terrain modification to an existing terrain profile.

        The profile can either include XY coordinate columns or be paired with
        the original profile polyline coordinates. The returned DataFrame keeps
        the original profile station and adds proposed elevation and
        difference columns suitable for before/after profile plots.
        """
        if station_col not in profile.columns:
            raise ValueError(f"profile is missing station column '{station_col}'")
        if elevation_col not in profile.columns:
            raise ValueError(f"profile is missing elevation column '{elevation_col}'")

        if {x_col, y_col}.issubset(profile.columns):
            points = profile[[x_col, y_col]].to_numpy(dtype=np.float64)
        else:
            if x_coords is None or y_coords is None:
                raise ValueError(
                    "profile must include x/y columns or x_coords and y_coords "
                    "must be provided"
                )
            points = RasTerrainModWriter._xy_along_polyline_from_stations(
                x_coords=x_coords,
                y_coords=y_coords,
                stations=profile[station_col].to_numpy(dtype=np.float64),
            )

        sampled = RasTerrainModWriter.sample_modification_surface(
            terrain_hdf_path=terrain_hdf_path,
            name=name,
            points=points,
            existing_elevations=profile[elevation_col].to_numpy(dtype=np.float64),
            x_col=x_col,
            y_col=y_col,
        )

        return pd.DataFrame(
            {
                "station": profile[station_col].to_numpy(dtype=np.float64),
                "x": sampled["x"].to_numpy(dtype=np.float64),
                "y": sampled["y"].to_numpy(dtype=np.float64),
                "existing_elevation": sampled["existing_elevation"].to_numpy(
                    dtype=np.float64
                ),
                "modification_surface": sampled["modification_surface"].to_numpy(
                    dtype=np.float64
                ),
                "proposed_elevation": sampled["modified_elevation"].to_numpy(
                    dtype=np.float64
                ),
                "difference": sampled["difference"].to_numpy(dtype=np.float64),
                "line_station": sampled["line_station"].to_numpy(dtype=np.float64),
                "offset": sampled["offset"].to_numpy(dtype=np.float64),
                "in_extent": sampled["in_extent"].to_numpy(dtype=bool),
                "modification_mode": sampled["modification_mode"].to_numpy(),
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
            RasTerrainModWriter._create_hdf_dataset(
                mod_grp, 'Polyline Info', polyline_info
            )

            # Polyline Parts: [start_index, num_points_in_part]
            polyline_parts = np.array([[0, n_pts]], dtype=np.int32)
            RasTerrainModWriter._create_hdf_dataset(
                mod_grp, 'Polyline Parts', polyline_parts
            )

            # Polyline Points: Nx2 array of (x, y)
            RasTerrainModWriter._create_hdf_dataset(
                mod_grp, 'Polyline Points', polyline_points
            )
            mod_grp['Polyline Info'].attrs['Feature Type'] = np.bytes_('Polyline')

            profile_info = np.array([[0, len(profile_data)]], dtype=np.int32)
            RasTerrainModWriter._create_hdf_dataset(
                mod_grp, 'Profile Info', profile_info
            )
            RasTerrainModWriter._create_hdf_dataset(
                mod_grp, 'Profile Values', profile_data.astype(np.float32)
            )
            RasTerrainModWriter._create_hdf_dataset(mod_grp, 'Profile', profile_data)

            # Write attributes as a compound dataset
            # This matches the GroundLineModificationLayer attribute schema
            attr_dtype = np.dtype([
                ('System Name', 'S128'),
                ('Name', 'S128'),
                ('Elevation Type', 'S16'),
                ('Top Elevation', '<f4'),
                ('Top Width', '<f4'),
                ('Left Slope', '<f4'),
                ('Right Slope', '<f4'),
                ('Max Reach', '<f4'),
                ('Transition Percent', '<f4'),
                ('Elev Pt Tolerance', '<f4'),
            ])

            if elevation_value is None:
                elevation_value = float(np.mean(profile_data[:, 1]))
            if top_elevation is None:
                top_elevation = float(np.max(profile_data[:, 1]))

            attrs_data = np.array([(
                name.encode('utf-8')[:128],
                name.encode('utf-8')[:128],
                RasTerrainModWriter._modification_type_disk_name(modification_type)
                .encode('utf-8')[:16],
                np.float32(top_elevation),
                np.float32(width),
                np.float32(left_slope),
                np.float32(right_slope),
                np.float32(max_extent),
                np.float32(transition_fraction),
                np.float32(elev_pt_tolerance),
            )], dtype=attr_dtype)

            RasTerrainModWriter._create_hdf_dataset(
                mod_grp, 'Attributes', attrs_data
            )

            # Create empty Control Points group
            cp_grp = mod_grp.create_group('Control Points')
            cp_grp.attrs['Type'] = np.bytes_('ControlCrossSection')

            logger.info(f"Wrote ground-line modification '{name}' to HDF: "
                       f"{n_pts} pts, length={profile_data[-1, 0]:.1f}, "
                       f"width={width}, mode={modification_type}")

    @staticmethod
    def _write_polygon_to_hdf(
        terrain_hdf_path: Path,
        name: str,
        rings_xy: Sequence[np.ndarray],
        boundary_elevations: np.ndarray,
        control_xy: np.ndarray,
        control_elevations: np.ndarray,
        control_names: Sequence[str],
        modification_type: int,
        elevation_method: str,
        elev_pt_tolerance: float,
    ) -> None:
        """Write a polygon multipoint modification to a terrain HDF file."""
        import h5py

        polygon_parts: List[List[int]] = []
        all_points: List[np.ndarray] = []
        point_start = 0
        for ring in rings_xy:
            ring_count = int(len(ring))
            polygon_parts.append([point_start, ring_count])
            all_points.append(ring)
            point_start += ring_count

        polygon_points = np.vstack(all_points).astype(np.float64)
        polygon_info = np.array(
            [[0, len(polygon_points), 0, len(polygon_parts)]],
            dtype=np.int32,
        )
        polygon_parts_array = np.asarray(polygon_parts, dtype=np.int32)
        profile_values = RasTerrainModWriter._polygon_profile_values(
            rings_xy, boundary_elevations
        )
        profile_info = np.array([[0, len(profile_values)]], dtype=np.int32)
        boundary_points = np.column_stack(
            [polygon_points, boundary_elevations.astype(np.float64)]
        )

        if len(control_xy):
            control_points_xyz = np.column_stack(
                [control_xy, control_elevations.astype(np.float64)]
            )
            elevation_points = np.vstack([boundary_points, control_points_xyz])
        else:
            control_points_xyz = np.empty((0, 3), dtype=np.float64)
            elevation_points = boundary_points.copy()

        with h5py.File(terrain_hdf_path, "a") as f:
            mods = f.require_group("Modifications")

            if name in mods:
                logger.warning("Modification '%s' already exists, overwriting", name)
                del mods[name]

            mod_grp = mods.create_group(name)
            mod_grp.attrs["Type"] = np.bytes_("Polygon")
            mod_grp.attrs["Subtype"] = np.bytes_("Multipoint")
            mod_grp.attrs["Priority"] = np.int32(0)
            mod_grp.attrs["Boundary Elevation Method"] = np.bytes_(
                str(elevation_method)[:64]
            )

            polygon_info_ds = RasTerrainModWriter._create_hdf_dataset(
                mod_grp, "Polygon Info", polygon_info
            )
            polygon_parts_ds = RasTerrainModWriter._create_hdf_dataset(
                mod_grp, "Polygon Parts", polygon_parts_array
            )
            polygon_points_ds = RasTerrainModWriter._create_hdf_dataset(
                mod_grp, "Polygon Points", polygon_points
            )
            polygon_info_ds.attrs["Column"] = np.asarray(
                [
                    "Point Starting Index",
                    "Point Count",
                    "Part Starting Index",
                    "Part Count",
                ],
                dtype="S32",
            )
            polygon_info_ds.attrs["Feature Type"] = np.bytes_("Polygon")
            polygon_info_ds.attrs["Row"] = np.bytes_("Feature")
            polygon_parts_ds.attrs["Column"] = np.asarray(
                ["Point Starting Index", "Point Count"], dtype="S32"
            )
            polygon_parts_ds.attrs["Row"] = np.bytes_("Part")
            polygon_points_ds.attrs["Column"] = np.asarray(["X", "Y"], dtype="S8")
            polygon_points_ds.attrs["Row"] = np.bytes_("Points")

            profile_info_ds = RasTerrainModWriter._create_hdf_dataset(
                mod_grp, "Profile Info", profile_info
            )
            profile_values_ds = RasTerrainModWriter._create_hdf_dataset(
                mod_grp, "Profile Values", profile_values.astype(np.float32)
            )
            profile_info_ds.attrs["Column"] = np.asarray(
                ["Starting Index", "Count"], dtype="S16"
            )
            profile_info_ds.attrs["Row"] = np.bytes_("Feature")
            profile_values_ds.attrs["Column"] = np.asarray(["X", "Y"], dtype="S8")
            profile_values_ds.attrs["Row"] = np.bytes_("Values")

            RasTerrainModWriter._create_hdf_dataset(
                mod_grp, "Boundary Points", boundary_points
            )
            RasTerrainModWriter._create_hdf_dataset(
                mod_grp, "Boundary Elevations", boundary_elevations.astype(np.float32)
            )
            RasTerrainModWriter._create_hdf_dataset(
                mod_grp, "Elevation Points", elevation_points
            )

            method_key = (
                str(elevation_method)
                .strip()
                .lower()
                .replace("-", "_")
                .replace(" ", "_")
            )
            generate_boundary = method_key in {
                "boundary_from_terrain",
                "terrain",
                "from_terrain",
            }
            attr_dtype = np.dtype(
                [
                    ("Name", "S128"),
                    ("Elevation Value", "<f4"),
                    ("Elevation Type", "S11"),
                    ("Elev Pt Tolerance", "<f4"),
                    ("Generate Boundary Elevations", "u1"),
                    ("Use ShapeFile Z Elevations", "u1"),
                ]
            )
            attrs_data = np.array(
                [
                    (
                        name.encode("utf-8")[:128],
                        np.float32(0.0),
                        RasTerrainModWriter._modification_type_disk_name(
                            modification_type
                        ).encode("utf-8")[:11],
                        np.float32(elev_pt_tolerance),
                        np.uint8(1 if generate_boundary else 0),
                        np.uint8(1 if method_key in {"shape_z", "polygon_z", "z"} else 0),
                    )
                ],
                dtype=attr_dtype,
            )
            RasTerrainModWriter._create_hdf_dataset(
                mod_grp, "Attributes", attrs_data
            )

            cp_grp = mod_grp.create_group("Control Points")
            cp_grp.attrs["Type"] = np.bytes_("ElevationControlPointLayer")
            cp_points_ds = RasTerrainModWriter._create_hdf_dataset(
                cp_grp, "Points", control_xy.astype(np.float64)
            )
            cp_points_ds.attrs["Column"] = np.asarray(["X", "Y"], dtype="S8")
            cp_points_ds.attrs["Feature Type"] = np.bytes_("Point")
            cp_points_ds.attrs["Row"] = np.bytes_("Points")
            RasTerrainModWriter._create_hdf_dataset(
                cp_grp, "Elevations", control_elevations.astype(np.float32)
            )
            RasTerrainModWriter._create_hdf_dataset(
                cp_grp, "Elevation Points", control_points_xyz
            )

            cp_attr_dtype = np.dtype([("Name", "S128"), ("Elevation", "<f4")])
            cp_attrs = np.zeros(len(control_xy), dtype=cp_attr_dtype)
            for idx, (point_name, elevation) in enumerate(
                zip(control_names, control_elevations)
            ):
                cp_attrs[idx]["Name"] = str(point_name).encode("utf-8")[:128]
                cp_attrs[idx]["Elevation"] = np.float32(elevation)
            RasTerrainModWriter._create_hdf_dataset(cp_grp, "Attributes", cp_attrs)

            logger.info(
                "Wrote polygon multipoint modification '%s' to HDF: "
                "%d boundary pts, %d control pts, mode=%d",
                name,
                len(boundary_points),
                len(control_xy),
                modification_type,
            )

    @staticmethod
    def _polygon_profile_values(
        rings_xy: Sequence[np.ndarray],
        boundary_elevations: np.ndarray,
    ) -> np.ndarray:
        """Build RasMapper polygon perimeter profile values from boundary elevations."""
        rows: List[np.ndarray] = []
        elev_start = 0
        station_offset = 0.0
        for ring in rings_xy:
            elev_end = elev_start + len(ring)
            ring_elevations = boundary_elevations[elev_start:elev_end]
            stations = RasTerrainModWriter._station_values(ring)
            if rows:
                stations = stations + station_offset
            rows.append(np.column_stack([stations, ring_elevations]))
            station_offset = float(stations[-1])
            elev_start = elev_end

        if not rows:
            return np.empty((0, 2), dtype=np.float64)
        return np.vstack(rows).astype(np.float64)

    @staticmethod
    def _validate_polygon_rings(polygon_coords: Any) -> tuple[List[np.ndarray], List[np.ndarray]]:
        """Normalize polygon input to closed XY rings and optional Z arrays."""
        coords = RasTerrainModWriter._geojson_polygon_coordinates(polygon_coords)
        if RasTerrainModWriter._is_ring_like(coords):
            raw_rings = [coords]
        else:
            if not isinstance(coords, Sequence) or isinstance(coords, (str, bytes)):
                raise ValueError(
                    "polygon_coords must be a coordinate ring or sequence of rings"
                )
            raw_rings = list(coords)

        if len(raw_rings) == 0:
            raise ValueError("polygon_coords must contain at least one ring")

        rings_xy: List[np.ndarray] = []
        rings_z: List[np.ndarray] = []
        for ring_index, raw_ring in enumerate(raw_rings):
            if not RasTerrainModWriter._is_ring_like(raw_ring):
                raise ValueError("Each polygon ring must be a sequence of XY points")

            xy_rows: List[List[float]] = []
            z_rows: List[float] = []
            for point in raw_ring:
                x, y, z = RasTerrainModWriter._coordinate_to_xy_z(point)
                xy_rows.append([x, y])
                z_rows.append(z)

            if len(xy_rows) < 3:
                raise ValueError("Each polygon ring must contain at least three points")

            if xy_rows[0] != xy_rows[-1]:
                xy_rows.append(xy_rows[0].copy())
                z_rows.append(z_rows[0])

            if len(xy_rows) < 4:
                raise ValueError(
                    "Each polygon ring must contain at least four closed points"
                )

            xy = np.asarray(xy_rows, dtype=np.float64)
            z = np.asarray(z_rows, dtype=np.float64)
            if not np.all(np.isfinite(xy)):
                raise ValueError("polygon_coords XY values must be finite")

            area = RasTerrainModWriter._ring_signed_area(xy)
            if abs(area) <= 0.0:
                raise ValueError("Each polygon ring must enclose a non-zero area")

            if ring_index > 0:
                logger.debug("Writing polygon interior ring %d", ring_index)
            rings_xy.append(xy)
            rings_z.append(z)

        return rings_xy, rings_z

    @staticmethod
    def _geojson_polygon_coordinates(polygon_coords: Any) -> Any:
        if hasattr(polygon_coords, "__geo_interface__"):
            polygon_coords = polygon_coords.__geo_interface__

        if not isinstance(polygon_coords, dict):
            return polygon_coords

        geometry = polygon_coords
        if str(geometry.get("type", "")).lower() == "feature":
            geometry = geometry.get("geometry") or {}

        geometry_type = str(geometry.get("type", "")).lower()
        coordinates = geometry.get("coordinates")
        if geometry_type == "polygon":
            return coordinates
        if geometry_type == "multipolygon":
            return [ring for polygon in coordinates for ring in polygon]

        raise ValueError(
            "polygon_coords GeoJSON input must be Polygon or MultiPolygon geometry"
        )

    @staticmethod
    def _is_ring_like(value: Any) -> bool:
        if isinstance(value, np.ndarray):
            return value.ndim == 2 and value.shape[0] > 0 and value.shape[1] >= 2
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            return False
        return len(value) > 0 and RasTerrainModWriter._is_coordinate_like(value[0])

    @staticmethod
    def _is_coordinate_like(value: Any) -> bool:
        if isinstance(value, np.ndarray):
            if value.ndim != 1 or value.shape[0] < 2:
                return False
        elif not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            return False
        elif len(value) < 2:
            return False

        try:
            float(value[0])
            float(value[1])
        except (TypeError, ValueError):
            return False
        return True

    @staticmethod
    def _coordinate_to_xy_z(value: Any) -> tuple[float, float, float]:
        if not RasTerrainModWriter._is_coordinate_like(value):
            raise ValueError(f"Invalid polygon coordinate: {value!r}")
        x = float(value[0])
        y = float(value[1])
        z = np.nan
        if len(value) >= 3 and value[2] is not None:
            z = float(value[2])
        return x, y, z

    @staticmethod
    def _ring_signed_area(ring_xy: np.ndarray) -> float:
        x = ring_xy[:, 0]
        y = ring_xy[:, 1]
        return float(0.5 * np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))

    @staticmethod
    def _validate_control_points(
        control_points: Optional[Sequence[Any]],
    ) -> tuple[np.ndarray, np.ndarray, List[str]]:
        if control_points is None:
            return (
                np.empty((0, 2), dtype=np.float64),
                np.empty((0,), dtype=np.float64),
                [],
            )

        xy_rows: List[List[float]] = []
        elevations: List[float] = []
        names: List[str] = []
        for idx, point in enumerate(control_points):
            if isinstance(point, dict):
                x = RasTerrainModWriter._mapping_value(point, "x", "X")
                y = RasTerrainModWriter._mapping_value(point, "y", "Y")
                elevation = RasTerrainModWriter._mapping_value(
                    point, "elevation", "Elevation", "z", "Z"
                )
                point_name = point.get("name", point.get("Name", f"Control Point {idx + 1}"))
            else:
                if not isinstance(point, Sequence) or isinstance(point, (str, bytes)):
                    raise ValueError("control_points entries must be sequences or dicts")
                if len(point) < 3:
                    raise ValueError(
                        "control_points entries must include x, y, and elevation"
                    )
                x, y, elevation = point[:3]
                point_name = point[3] if len(point) >= 4 else f"Control Point {idx + 1}"

            x = float(x)
            y = float(y)
            elevation = float(elevation)
            if not np.isfinite([x, y, elevation]).all():
                raise ValueError("control_points must contain finite x/y/elevation values")

            xy_rows.append([x, y])
            elevations.append(elevation)
            names.append(str(point_name))

        if not xy_rows:
            return (
                np.empty((0, 2), dtype=np.float64),
                np.empty((0,), dtype=np.float64),
                [],
            )

        return (
            np.asarray(xy_rows, dtype=np.float64),
            np.asarray(elevations, dtype=np.float64),
            names,
        )

    @staticmethod
    def _mapping_value(mapping: Dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in mapping:
                return mapping[key]
        raise ValueError(f"control point is missing one of: {', '.join(keys)}")

    @staticmethod
    def _validate_control_points_inside_polygon(
        control_xy: np.ndarray,
        exterior_ring: np.ndarray,
    ) -> None:
        if len(control_xy) == 0:
            return

        outside = [
            idx
            for idx, point in enumerate(control_xy)
            if not RasTerrainModWriter._point_in_or_on_ring(point, exterior_ring)
        ]
        if outside:
            raise ValueError(
                "control_points must fall inside the polygon exterior; "
                f"outside point indices: {outside}"
            )

    @staticmethod
    def _point_in_or_on_ring(point: np.ndarray, ring: np.ndarray) -> bool:
        x = float(point[0])
        y = float(point[1])
        tolerance = 1e-9

        for start, end in zip(ring[:-1], ring[1:]):
            vector = end - start
            rel = point - start
            length2 = float(vector @ vector)
            if length2 <= 0:
                continue
            t = float((rel @ vector) / length2)
            if -tolerance <= t <= 1.0 + tolerance:
                closest = start + np.clip(t, 0.0, 1.0) * vector
                if np.linalg.norm(point - closest) <= tolerance:
                    return True

        inside = False
        for start, end in zip(ring[:-1], ring[1:]):
            xi, yi = start
            xj, yj = end
            intersects = (yi > y) != (yj > y)
            if intersects:
                x_intersect = (xj - xi) * (y - yi) / (yj - yi) + xi
                if x < x_intersect:
                    inside = not inside
        return inside

    @staticmethod
    def _boundary_elevations_for_polygon(
        terrain_hdf_path: Path,
        boundary_xy: np.ndarray,
        rings_z: Sequence[np.ndarray],
        elevation_method: str,
        boundary_elevations: Optional[Union[np.ndarray, Sequence[float]]],
    ) -> np.ndarray:
        method = str(elevation_method).strip().lower().replace("-", "_").replace(" ", "_")
        if boundary_elevations is not None:
            method = "provided"

        if method in {"provided", "explicit", "boundary_elevations"}:
            if boundary_elevations is None:
                raise ValueError(
                    "boundary_elevations is required when elevation_method='provided'"
                )
            elevations = np.asarray(boundary_elevations, dtype=np.float64)
            if elevations.ndim != 1 or len(elevations) != len(boundary_xy):
                raise ValueError(
                    "boundary_elevations must be a 1D array matching the closed "
                    "polygon boundary point count"
                )
            if not np.all(np.isfinite(elevations)):
                raise ValueError("boundary_elevations must contain finite values")
            return elevations

        if method in {"shape_z", "polygon_z", "z"}:
            elevations = np.concatenate(rings_z).astype(np.float64)
            if elevations.ndim != 1 or len(elevations) != len(boundary_xy):
                raise ValueError("polygon Z values do not match boundary point count")
            if not np.all(np.isfinite(elevations)):
                raise ValueError(
                    "polygon_coords must include finite Z values when "
                    "elevation_method='shape_z'"
                )
            return elevations

        if method in {"boundary_from_terrain", "terrain", "from_terrain"}:
            return RasTerrainModWriter._sample_terrain_elevations(
                terrain_hdf_path, boundary_xy
            )

        raise ValueError(
            "Unsupported elevation_method. Use 'boundary_from_terrain', "
            "'shape_z', or 'provided'."
        )

    @staticmethod
    def _sample_terrain_elevations(
        terrain_hdf_path: Path,
        xy: np.ndarray,
    ) -> np.ndarray:
        try:
            import rasterio
        except ImportError as exc:
            raise ImportError(
                "rasterio is required for elevation_method='boundary_from_terrain'."
            ) from exc

        raster_paths = RasTerrainModWriter._terrain_source_raster_paths(terrain_hdf_path)
        if not raster_paths:
            raise FileNotFoundError(
                "No source raster paths were found in or beside terrain HDF "
                f"{terrain_hdf_path}"
            )

        elevations = np.full(len(xy), np.nan, dtype=np.float64)
        for raster_path in raster_paths:
            pending = np.where(~np.isfinite(elevations))[0]
            if len(pending) == 0:
                break

            with rasterio.open(raster_path) as src:
                nodata = getattr(src, "nodata", None)
                sampled_values: List[float] = []
                for sample in src.sample(
                    [(float(x), float(y)) for x, y in xy[pending]]
                ):
                    if np.ma.is_masked(sample):
                        mask = np.ma.getmaskarray(sample)
                        value = np.nan if mask.size and mask.flat[0] else sample.data[0]
                    else:
                        sample_array = np.asarray(sample)
                        value = sample_array.flat[0] if sample_array.size else np.nan
                    sampled_values.append(float(value))

                sampled = np.asarray(sampled_values, dtype=np.float64)
                valid = np.isfinite(sampled)
                if nodata is not None and np.isfinite(float(nodata)):
                    valid &= sampled != float(nodata)
                elevations[pending[valid]] = sampled[valid]

        if not np.all(np.isfinite(elevations)):
            missing = np.where(~np.isfinite(elevations))[0].tolist()
            raise ValueError(
                "Could not sample finite terrain elevations for polygon boundary "
                f"point indices {missing} from source rasters: "
                f"{[str(path) for path in raster_paths]}"
            )

        return elevations

    @staticmethod
    def _terrain_source_raster_paths(terrain_hdf_path: Path) -> List[Path]:
        import h5py

        terrain_hdf_path = Path(terrain_hdf_path)
        candidates: List[Path] = []

        def add_candidate(text: str) -> None:
            cleaned = text.strip().strip("\"'").rstrip("\x00")
            if not cleaned:
                return
            normalized = cleaned.replace("\\", "/")
            if Path(normalized).suffix.lower() not in _RASTER_SOURCE_SUFFIXES:
                return

            raw_path = Path(normalized)
            search_bases = [terrain_hdf_path.parent, terrain_hdf_path.parent.parent]
            possible = [raw_path] if raw_path.is_absolute() else [
                base / raw_path for base in search_bases
            ]
            for candidate in possible:
                if candidate.exists():
                    candidates.append(candidate)
                    return

        with h5py.File(terrain_hdf_path, "r") as f:
            for value in f.attrs.values():
                for text in RasTerrainModWriter._iter_hdf_strings(value):
                    add_candidate(text)

            def visitor(_name, obj):
                for value in obj.attrs.values():
                    for text in RasTerrainModWriter._iter_hdf_strings(value):
                        add_candidate(text)
                if isinstance(obj, h5py.Dataset):
                    if obj.size <= 10000 and (
                        obj.dtype.names is not None or obj.dtype.kind in {"S", "U", "O"}
                    ):
                        for text in RasTerrainModWriter._iter_hdf_strings(obj[()]):
                            add_candidate(text)

            f.visititems(visitor)

        for suffix in (".tif", ".tiff", ".vrt"):
            fallback = terrain_hdf_path.with_suffix(suffix)
            if fallback.exists():
                candidates.append(fallback)

        unique: List[Path] = []
        seen = set()
        for candidate in candidates:
            key = str(candidate.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)
        return unique

    @staticmethod
    def _iter_hdf_strings(value: Any):
        if isinstance(value, str):
            yield value
            return
        if isinstance(value, (bytes, np.bytes_)):
            yield bytes(value).decode("utf-8", errors="ignore")
            return
        if isinstance(value, np.void) and value.dtype.names:
            for field_name in value.dtype.names:
                yield from RasTerrainModWriter._iter_hdf_strings(value[field_name])
            return
        if isinstance(value, np.ndarray):
            if value.dtype.names:
                for field_name in value.dtype.names:
                    yield from RasTerrainModWriter._iter_hdf_strings(value[field_name])
                return
            if value.dtype.kind in {"S", "U", "O"}:
                for item in value.reshape(-1):
                    yield from RasTerrainModWriter._iter_hdf_strings(item)
            return
        if isinstance(value, np.generic):
            yield from RasTerrainModWriter._iter_hdf_strings(value.item())
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for item in value:
                yield from RasTerrainModWriter._iter_hdf_strings(item)

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
    def _create_hdf_dataset(group, name: str, data: np.ndarray):
        """Create a chunked HDF dataset compatible with HEC H5Assist readers."""
        data = np.asarray(data)
        if data.shape and all(dim > 0 for dim in data.shape):
            return group.create_dataset(name, data=data, chunks=data.shape)
        return group.create_dataset(name, data=data)

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
    def _modification_type_disk_name(modification_type: int) -> str:
        """Return the RasMapper disk serializer name for a merge mode."""
        return _MODIFICATION_TYPE_DISK_NAMES[
            RasTerrainModWriter._resolve_modification_type(modification_type)
        ]

    @staticmethod
    def _modification_type_value(value) -> int:
        """Resolve an HDF attribute merge-mode scalar to the public integer code."""
        value = RasTerrainModWriter._decode_hdf_scalar(value)
        if value is None:
            return -1
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return -1
            try:
                return int(text)
            except ValueError:
                key = text.lower().replace("-", "_").replace(" ", "_")
                compact = key.replace("_", "")
                return _MODIFICATION_TYPE_BY_DISK_NAME.get(
                    key, _MODIFICATION_TYPE_BY_DISK_NAME.get(compact, -1)
                )
        try:
            if np.isnan(value):
                return -1
        except TypeError:
            pass
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    @staticmethod
    def _attr_value(attr_row: Dict[str, object], *names: str, default=np.nan):
        """Return the first matching attribute value from current or legacy fields."""
        for field_name in names:
            if field_name in attr_row:
                return attr_row[field_name]
        return default

    @staticmethod
    def _float_attr(attr_row: Dict[str, object], *names: str) -> float:
        value = RasTerrainModWriter._attr_value(attr_row, *names)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float("nan")

    @staticmethod
    def _profile_point_count(mod_grp) -> int:
        if "Profile Info" in mod_grp and len(mod_grp["Profile Info"]) > 0:
            info = np.asarray(mod_grp["Profile Info"][:], dtype=np.int64)
            return int(info[:, 1].sum())
        if "Profile Values" in mod_grp:
            return int(mod_grp["Profile Values"].shape[0])
        if "Profile" in mod_grp:
            return int(mod_grp["Profile"].shape[0])
        return 0

    @staticmethod
    def _read_profile_array(mod_grp) -> np.ndarray:
        if "Profile Values" in mod_grp:
            values = np.asarray(mod_grp["Profile Values"][:], dtype=np.float64)
            if "Profile Info" in mod_grp and len(mod_grp["Profile Info"]) > 0:
                start, count = np.asarray(mod_grp["Profile Info"][0], dtype=np.int64)
                values = values[start : start + count]
            return values

        if "Profile" in mod_grp:
            return np.asarray(mod_grp["Profile"][:], dtype=np.float64)

        raise KeyError(f"Modification profile not found: {mod_grp.name}/Profile Values")

    @staticmethod
    def _read_ground_line_modification(
        terrain_hdf_path: Union[str, Path],
        name: str,
    ):
        """Read ground-line geometry, profile, and attributes from a sidecar group."""
        import h5py

        terrain_hdf_path = Path(terrain_hdf_path)
        with h5py.File(terrain_hdf_path, "r") as f:
            mod_path = f"Modifications/{name}"
            if mod_path not in f:
                raise KeyError(f"Modification not found: {mod_path}")

            mod_grp = f[mod_path]
            if "Polyline Points" not in mod_grp:
                raise KeyError(f"Modification polyline not found: {mod_path}/Polyline Points")

            line = np.asarray(mod_grp["Polyline Points"][:], dtype=np.float64)
            profile = RasTerrainModWriter._read_profile_array(mod_grp)
            attr_row = {}
            if "Attributes" in mod_grp and len(mod_grp["Attributes"]) > 0:
                attr_row = {
                    key: RasTerrainModWriter._decode_hdf_scalar(value)
                    for key, value in zip(
                        mod_grp["Attributes"].dtype.names,
                        mod_grp["Attributes"][0],
                    )
                }

        if line.ndim != 2 or line.shape[1] < 2 or len(line) < 2:
            raise ValueError(f"Modification '{name}' has invalid polyline data")
        if profile.ndim != 2 or profile.shape[1] != 2 or len(profile) < 2:
            raise ValueError(f"Modification '{name}' has invalid profile data")

        attrs = {
            "width": RasTerrainModWriter._float_attr(attr_row, "Top Width", "Width"),
            "left_slope": RasTerrainModWriter._float_attr(
                attr_row, "Left Slope", "LeftSlope"
            ),
            "right_slope": RasTerrainModWriter._float_attr(
                attr_row, "Right Slope", "RightSlope"
            ),
            "max_extent": RasTerrainModWriter._float_attr(
                attr_row, "Max Reach", "Max Extent"
            ),
            "modification_type": RasTerrainModWriter._modification_type_value(
                RasTerrainModWriter._attr_value(
                    attr_row, "Elevation Type", "ElevationType", default=-1
                )
            ),
        }

        missing = [
            key for key, value in attrs.items()
            if isinstance(value, float) and not np.isfinite(value)
        ]
        if missing:
            raise ValueError(
                f"Modification '{name}' is missing required attributes: "
                f"{', '.join(missing)}"
            )
        if int(attrs["modification_type"]) < 0:
            raise ValueError(f"Modification '{name}' has unknown merge mode")

        return line[:, :2], profile, attrs

    @staticmethod
    def _points_to_xy(
        points: Union[np.ndarray, Sequence[Sequence[float]], pd.DataFrame],
        x_col: str,
        y_col: str,
    ) -> np.ndarray:
        if isinstance(points, pd.DataFrame):
            if x_col not in points.columns or y_col not in points.columns:
                raise ValueError(
                    f"points DataFrame must include '{x_col}' and '{y_col}' columns"
                )
            xy = points[[x_col, y_col]].to_numpy(dtype=np.float64)
        else:
            xy = np.asarray(points, dtype=np.float64)

        if xy.ndim != 2 or xy.shape[1] < 2:
            raise ValueError("points must be an Nx2 coordinate array")
        if len(xy) == 0:
            raise ValueError("points must contain at least one row")
        if not np.all(np.isfinite(xy[:, :2])):
            raise ValueError("points must contain finite XY coordinates")
        return xy[:, :2]

    @staticmethod
    def _optional_elevations(values, expected_len: int) -> Optional[np.ndarray]:
        if values is None:
            return None
        elevations = np.asarray(values, dtype=np.float64)
        if elevations.ndim != 1 or len(elevations) != expected_len:
            raise ValueError(
                "existing_elevations must be a 1D array matching the point count"
            )
        if not np.all(np.isfinite(elevations)):
            raise ValueError("existing_elevations must contain only finite values")
        return elevations

    @staticmethod
    def _project_points_to_polyline(
        points: np.ndarray,
        line: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Project points to the closest segment of a polyline."""
        starts = line[:-1]
        ends = line[1:]
        vectors = ends - starts
        lengths = np.linalg.norm(vectors, axis=1)
        if np.any(lengths <= 0):
            raise ValueError("Modification polyline contains a zero-length segment")

        cumulative = np.zeros(len(line), dtype=np.float64)
        cumulative[1:] = np.cumsum(lengths)

        best_dist2 = np.full(len(points), np.inf, dtype=np.float64)
        best_station = np.full(len(points), np.nan, dtype=np.float64)
        best_offset = np.full(len(points), np.nan, dtype=np.float64)

        for seg_idx, (start, vector, length) in enumerate(zip(starts, vectors, lengths)):
            rel = points - start
            t = np.clip((rel @ vector) / (length * length), 0.0, 1.0)
            closest = start + t[:, None] * vector
            delta = points - closest
            dist2 = np.einsum("ij,ij->i", delta, delta)
            improve = dist2 < best_dist2
            if not improve.any():
                continue

            cross = vector[0] * (points[:, 1] - start[1]) - vector[1] * (
                points[:, 0] - start[0]
            )
            signed_distance = np.sign(cross) * np.sqrt(dist2)
            best_dist2[improve] = dist2[improve]
            best_station[improve] = cumulative[seg_idx] + t[improve] * length
            best_offset[improve] = signed_distance[improve]

        return best_station, best_offset

    @staticmethod
    def _ground_line_surface_from_offsets(
        station: np.ndarray,
        offset: np.ndarray,
        profile: np.ndarray,
        width: float,
        left_slope: float,
        right_slope: float,
        max_extent: float,
    ) -> np.ndarray:
        """Compute the proposed ground-line surface at projected station/offsets."""
        half_width = width / 2.0
        distance = np.abs(offset)
        crest = np.interp(station, profile[:, 0], profile[:, 1])
        slopes = np.where(offset >= 0.0, left_slope, right_slope).astype(np.float64)

        surface = np.full(len(station), np.nan, dtype=np.float64)
        in_extent = distance <= max_extent
        on_crest = distance <= half_width
        surface[in_extent & on_crest] = crest[in_extent & on_crest]

        on_slope = in_extent & ~on_crest & (slopes > 0.0)
        lateral = distance[on_slope] - half_width
        surface[on_slope] = crest[on_slope] - lateral / slopes[on_slope]

        return surface

    @staticmethod
    def _apply_modification_mode(
        existing: Optional[np.ndarray],
        surface: np.ndarray,
        modification_type: int,
    ) -> np.ndarray:
        """Apply the HEC-RAS merge mode to existing elevations."""
        if existing is None:
            return surface.copy()

        modified = existing.copy()
        valid = np.isfinite(surface)
        if modification_type == MODIFICATION_SET_VALUE:
            modified[valid] = surface[valid]
        elif modification_type == MODIFICATION_TAKE_HIGHER:
            modified[valid] = np.maximum(existing[valid], surface[valid])
        elif modification_type == MODIFICATION_TAKE_LOWER:
            modified[valid] = np.minimum(existing[valid], surface[valid])
        elif modification_type == MODIFICATION_ADD_VALUE:
            modified[valid] = existing[valid] + surface[valid]
        else:
            raise ValueError(f"Unsupported terrain modification type: {modification_type}")
        return modified

    @staticmethod
    def _xy_along_polyline_from_stations(
        x_coords: Sequence[float],
        y_coords: Sequence[float],
        stations: np.ndarray,
    ) -> np.ndarray:
        """Interpolate XY coordinates along a profile polyline by station."""
        if len(x_coords) != len(y_coords):
            raise ValueError("x_coords and y_coords must have the same length")
        line = np.column_stack(
            [
                np.asarray(x_coords, dtype=np.float64),
                np.asarray(y_coords, dtype=np.float64),
            ]
        )
        if len(line) < 2:
            raise ValueError("x_coords and y_coords must define at least two points")
        if not np.all(np.isfinite(line)):
            raise ValueError("x_coords and y_coords must contain finite values")
        if not np.all(np.isfinite(stations)):
            raise ValueError("profile stations must contain finite values")

        line_stations = RasTerrainModWriter._station_values(line)
        if line_stations[-1] <= 0:
            raise ValueError("x_coords and y_coords must define a non-zero-length line")
        if stations.min(initial=0.0) < line_stations[0] or stations.max(initial=0.0) > line_stations[-1]:
            raise ValueError("profile stations fall outside the profile polyline length")

        return np.column_stack(
            [
                np.interp(stations, line_stations, line[:, 0]),
                np.interp(stations, line_stations, line[:, 1]),
            ]
        )

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
    def _infer_rasmap_path(terrain_hdf_path: Path) -> Path:
        """Find a project .rasmap file that references a terrain HDF."""
        terrain_hdf_path = Path(terrain_hdf_path)
        search_roots: List[Path] = []
        for root in (terrain_hdf_path.parent, terrain_hdf_path.parent.parent):
            if root not in search_roots and root.exists():
                search_roots.append(root)

        candidates: List[Path] = []
        for root in search_roots:
            candidates.extend(sorted(root.glob("*.rasmap")))

        unique_candidates: List[Path] = []
        seen = set()
        for candidate in candidates:
            key = str(candidate.resolve()).lower()
            if key not in seen:
                seen.add(key)
                unique_candidates.append(candidate)

        referencing: List[Path] = []
        for candidate in unique_candidates:
            try:
                root = ET.parse(candidate).getroot()
            except ET.ParseError:
                continue
            for layer in root.findall(".//Terrains/Layer"):
                if RasTerrainModWriter._layer_references_path(
                    layer.get("Filename", ""), candidate, terrain_hdf_path
                ):
                    referencing.append(candidate)
                    break

        if len(referencing) == 1:
            return referencing[0]
        if len(referencing) > 1:
            raise ValueError(
                "Multiple .rasmap files reference this terrain HDF; pass "
                f"rasmap_path explicitly: {[str(path) for path in referencing]}"
            )
        if len(unique_candidates) == 1:
            return unique_candidates[0]

        if unique_candidates:
            raise ValueError(
                "Could not infer rasmap_path because multiple .rasmap files were "
                f"found and none referenced {terrain_hdf_path.name}: "
                f"{[str(path) for path in unique_candidates]}"
            )
        raise FileNotFoundError(
            f"Could not infer rasmap_path for terrain HDF {terrain_hdf_path}; "
            "pass rasmap_path explicitly."
        )

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
        mod_group.set('Checked', 'True')
        mod_group.set('Expanded', 'True')

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
        mod_layer.set('Checked', 'True')
        mod_layer.set('Expanded', 'True')

        default_type_el = ET.SubElement(mod_layer, 'DefaultModificationType')
        default_type_el.set('Value', str(default_mod_type))

        default_tol_el = ET.SubElement(mod_layer, 'DefaultElevPtTol')
        default_tol_el.set('Value', str(int(elev_pt_tolerance)))

        # Add control points sub-layer
        cp_layer = ET.SubElement(mod_layer, 'Layer')
        cp_layer.set('Name', 'Control Points')
        cp_layer.set('Type', 'ElevationControlPointLayer')
        cp_layer.set('Checked', 'True')

        tree.write(rasmap_path, xml_declaration=False, encoding='unicode')
        logger.info(f"Added modification layer '{name}' to .rasmap")


class RasTerrainModification(RasTerrainModWriter):
    """User-facing alias for terrain modification writer APIs."""
