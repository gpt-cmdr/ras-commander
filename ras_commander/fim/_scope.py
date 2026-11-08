"""Read-only model dimensions and fail-closed 2D mapping scope checks."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from .errors import FimUnsupportedError


@dataclass(frozen=True)
class FimModelScope:
    """Dimensional evidence, without executing a mapping method.

    ``methods`` lists candidate engine registry keys for the dimension. It does
    not establish installed capabilities, preparation support or qualification.
    """

    dimension: str
    mesh_names: Tuple[str, ...]
    cross_section_count: int
    reach_count: int
    storage_area_names: Tuple[str, ...]
    methods: Tuple[str, ...]
    river_centerline_records: int
    text_reaches: int
    text_1d_nodes: int
    hdf_path: Path
    geometry_path: Optional[Path]

    def __post_init__(self):
        for name in ("mesh_names", "storage_area_names", "methods"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "hdf_path", Path(self.hdf_path))
        if self.geometry_path is not None:
            object.__setattr__(self, "geometry_path", Path(self.geometry_path))

    def to_dict(self):
        """Return detached JSON-friendly evidence, including legacy count keys."""
        return {
            "dimension": self.dimension,
            "mesh_names": list(self.mesh_names),
            "cross_section_count": self.cross_section_count,
            "cross_section_records": self.cross_section_count,
            "reach_count": self.reach_count,
            "storage_area_names": list(self.storage_area_names),
            "storage_areas": len(self.storage_area_names),
            "methods": list(self.methods),
            "river_centerline_records": self.river_centerline_records,
            "text_reaches": self.text_reaches,
            "text_1d_nodes": self.text_1d_nodes,
            "hdf_path": str(self.hdf_path),
            "geometry_path": str(self.geometry_path) if self.geometry_path else None,
        }


def _name(value):
    if not isinstance(value, (str, bytes)):
        raise FimUnsupportedError("model scope name is not a string")
    try:
        return (value.decode("utf-8") if isinstance(value, bytes) else value).strip("\0 \t\r\n")
    except UnicodeError as exc:
        raise FimUnsupportedError("model scope name is not valid UTF-8") from exc


def inspect_model_scope(hdf_path, geom_path=None):
    """Inspect metadata and source declarations without reading geometry arrays.

    Only small storage-name/mesh-count tables are materialized. River/XS tables
    and cell coordinates are inspected by shape, never read. Source text remains
    evidence of 1D geometry when compiled river/XS tables are absent.
    """
    import h5py
    import numpy as np
    from ..fast_hdf import read_attr, read_typed
    from ..geom.GeomParser import GeomParser

    path = Path(hdf_path).resolve(strict=True)
    with h5py.File(path, "r") as source:
        def group_at(name):
            obj = source.get(name)
            if obj is not None and not isinstance(obj, h5py.Group):
                raise FimUnsupportedError(f"malformed model scope group: {name}")
            return obj

        def count(group_path):
            group = group_at(group_path)
            if group is None:
                return 0
            # Pipe/conduit and 2D bridge hydraulic tables are not river XS.
            sizes = []
            for name in ("Attributes", "Polyline Info", "River Stations", "River Names", "Reach Names"):
                obj = group.get(name)
                if obj is not None:
                    if not isinstance(obj, h5py.Dataset) or obj.ndim == 0:
                        raise FimUnsupportedError(f"malformed model scope identity: {group_path}/{name}")
                    sizes.append(obj.shape[0])
            points = group.get("Polyline Points")
            if points is not None and (not isinstance(points, h5py.Dataset) or points.ndim != 2 or points.shape[1] != 2):
                raise FimUnsupportedError(f"malformed model scope polyline: {group_path}")
            records = max(sizes, default=0)
            # Keep guards closed without mislabelling vertices as XS/reaches.
            if not records and points is not None and points.shape[0]:
                raise FimUnsupportedError(f"orphaned polyline geometry lacks feature identities: {group_path}")
            return records

        areas = group_at("Geometry/2D Flow Areas")
        physical_counts = {}
        has_physical_counts = False
        meshes = []
        if areas is not None:
            attrs = areas.get("Attributes")
            if attrs is not None:
                if (not isinstance(attrs, h5py.Dataset) or attrs.ndim != 1
                        or not attrs.dtype.names or not {"Name", "Cell Count"}.issubset(attrs.dtype.names)
                        or attrs.dtype.fields["Cell Count"][0].kind not in "iuf"):
                    raise FimUnsupportedError("malformed 2D flow-area attributes")
                has_physical_counts = True
                for row in read_typed(attrs):
                    name = _name(row["Name"])
                    value = row["Cell Count"]
                    if not name or name in physical_counts or not np.isfinite(value) or int(value) != value or value < 0:
                        raise FimUnsupportedError("invalid 2D physical cell count/name")
                    physical_counts[name] = int(value)
            for name, group in areas.items():
                if not isinstance(group, h5py.Group):
                    continue
                coords = group.get("Cells Center Coordinate")
                if coords is None:
                    continue
                if (not isinstance(coords, h5py.Dataset) or coords.ndim != 2
                        or coords.shape[1] != 2 or coords.dtype.kind not in "fiu"):
                    raise FimUnsupportedError(f"malformed compiled mesh centers: {name}")
                if has_physical_counts and name not in physical_counts:
                    raise FimUnsupportedError(f"compiled mesh missing from physical count table: {name}")
                cells = physical_counts.get(name, coords.shape[0])
                if cells > coords.shape[0]:
                    raise FimUnsupportedError(f"physical cell count exceeds compiled centers: {name}")
                if cells:
                    meshes.append(name)
            if any(count and name not in meshes for name, count in physical_counts.items()):
                raise FimUnsupportedError("physical cell count table contains a mesh without compiled centers")

        rivers = count("Geometry/River Centerlines")
        sections = count("Geometry/Cross Sections")
        storage_group = group_at("Geometry/Storage Areas")
        storage = ()
        if storage_group is not None:
            attrs = storage_group.get("Attributes")
            if attrs is None:
                if len(storage_group):
                    raise FimUnsupportedError("storage geometry lacks name attributes")
            elif (not isinstance(attrs, h5py.Dataset) or attrs.ndim != 1
                  or not attrs.dtype.names or "Name" not in attrs.dtype.names):
                raise FimUnsupportedError("malformed storage-area name attributes")
            else:
                storage = tuple(_name(row["Name"]) for row in read_typed(attrs))
                if any(not name for name in storage) or len(set(storage)) != len(storage):
                    raise FimUnsupportedError("storage-area names must be unique and non-empty")
        if geom_path is None:
            if path.name.lower().endswith(".hdf") and path.with_suffix("").suffix.lower().startswith(".g"):
                candidate = path.with_suffix("")
            elif "Plan Data/Plan Information" in source:
                name = read_attr(source["Plan Data/Plan Information"], "Geometry Filename", "")
                if isinstance(name, bytes):
                    name = name.decode("utf-8")
                candidate = path.parent / str(name).replace("\\", "/")
            else:
                candidate = None
            if candidate is not None and candidate.is_file():
                geom_path = candidate
    reaches = set()
    text_nodes = 0
    geometry = Path(geom_path).resolve(strict=True) if geom_path is not None else None
    if geometry is not None:
        with geometry.open(encoding="utf-8-sig", errors="replace") as stream:
            for line in stream:
                reach = GeomParser.extract_river_reach(line)
                if reach is not None:
                    reaches.add(reach)
                elif line.strip().startswith(("River Reach=", "Reach=")) and line.split("=", 1)[1].strip(" ,\r\n"):
                    reaches.add(("unparsed reach declaration", line.strip()))
                if line.strip().startswith("Type RM Length L Ch R="):
                    text_nodes += 1
    one_d = bool(rivers or sections or reaches or text_nodes)
    dimension = ("mixed_1d_2d" if one_d else "2d") if meshes else ("1d" if one_d else "storage_only")
    if not meshes and not one_d and not storage:
        raise FimUnsupportedError("model scope has no compiled mesh, river/XS or storage geometry")
    methods = {
        "2d": ("horizontal", "sloping"),
        "1d": ("one_d_clipped_diagnostic",),
        "mixed_1d_2d": ("coupled_storage_diagnostic",) if storage else ("coupled_diagnostic",),
        "storage_only": ("storage",),
    }[dimension]
    return FimModelScope(dimension, tuple(meshes), sections, max(rivers, len(reaches)),
                         storage, methods, rivers, len(reaches), text_nodes, path, geometry)


def inspect_model(hdf_path, geom_path=None):
    """Keep the existing strict 2D-only mapping gate and legacy dict fields."""
    try:
        scope = inspect_model_scope(hdf_path, geom_path)
    except FimUnsupportedError as exc:
        raise FimUnsupportedError(f"FIM mapping is 2D-only: {exc}") from exc
    if not scope.mesh_names:
        raise FimUnsupportedError("FIM mapping is 2D-only: no compiled 2D mesh cells")
    if scope.dimension != "2d":
        raise FimUnsupportedError(
            "FIM mapping is 2D-only; models containing 1D river centerlines/reaches "
            f"or cross sections are rejected (centerline records={scope.river_centerline_records}, "
            f"cross-section records={scope.cross_section_count}, text reaches={scope.text_reaches}, text 1D nodes={scope.text_1d_nodes}). "
            "Selecting a 2D mesh does not bypass this check. Pipe networks are permitted."
        )
    result = scope.to_dict()
    result["dimension"] = "2D-only"
    return result
