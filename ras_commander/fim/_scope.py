"""Fail-closed dimensional scope checks for model-backed FIM mapping."""

from pathlib import Path

from .errors import FimUnsupportedError


def inspect_model(hdf_path, geom_path=None):
    """Inspect compiled geometry and any available source reach declarations."""
    import h5py
    from ..fast_hdf import read_attr
    from ..geom.GeomParser import GeomParser

    path = Path(hdf_path).resolve(strict=True)
    with h5py.File(path, "r") as source:
        if "Geometry/2D Flow Areas" not in source:
            raise FimUnsupportedError("FIM mapping is 2D-only: no compiled 2D flow areas")
        areas = source["Geometry/2D Flow Areas"]
        meshes = [name for name, group in areas.items()
                  if isinstance(group, h5py.Group) and "Cells Center Coordinate" in group
                  and group["Cells Center Coordinate"].shape[0] > 0]
        if not meshes:
            raise FimUnsupportedError("FIM mapping is 2D-only: no compiled 2D mesh cells")

        def count(group_path):
            if group_path not in source:
                return 0
            group = source[group_path]
            # Pipe/conduit and 2D bridge hydraulic tables may use the Cross
            # Sections group without any river cross-section geometry. Only
            # geometric identity records establish a 1D element here.
            identity = ("Attributes", "Polyline Info", "River Stations", "River Names", "Reach Names")
            sizes = [group[name].shape[0] for name in identity if name in group
                     and isinstance(group[name], h5py.Dataset) and group[name].ndim > 0]
            if any(sizes):
                return max(sizes)
            # Also reject orphaned geometry rather than treating it as absent.
            return group["Polyline Points"].shape[0] if "Polyline Points" in group else 0

        rivers = count("Geometry/River Centerlines")
        sections = count("Geometry/Cross Sections")
        storage = (source["Geometry/Storage Areas/Attributes"].shape[0]
                   if "Geometry/Storage Areas/Attributes" in source else 0)
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
    if geom_path is not None:
        geometry = Path(geom_path).resolve(strict=True)
        with geometry.open(encoding="utf-8-sig", errors="replace") as source:
            for line in source:
                reach = GeomParser.extract_river_reach(line)
                if reach is not None:
                    reaches.add(reach)
                elif line.strip().startswith(("River Reach=", "Reach=")) and line.split("=", 1)[1].strip(" ,\r\n"):
                    reaches.add(("unparsed reach declaration", line.strip()))
                if line.strip().startswith("Type RM Length L Ch R="):
                    text_nodes += 1
    if rivers or sections or reaches or text_nodes:
        raise FimUnsupportedError(
            "FIM mapping is 2D-only; models containing 1D river centerlines/reaches "
            f"or cross sections are rejected (centerline records={rivers}, "
            f"cross-section records={sections}, text reaches={len(reaches)}, text 1D nodes={text_nodes}). "
            "Selecting a 2D mesh does not bypass this check. Pipe networks are permitted."
        )
    return {"dimension": "2D-only", "mesh_names": meshes,
            "river_centerline_records": rivers, "cross_section_records": sections,
            "text_reaches": len(reaches), "storage_areas": storage,
            "text_1d_nodes": text_nodes,
            "hdf_path": str(path), "geometry_path": str(geom_path) if geom_path else None}
