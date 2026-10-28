"""ROUTE-NONHDF cases: ras_commander/geom and gui/workflows/mesh_regeneration.

Arguments (mesh names, spacings, features) are derived from the fixture here with
h5py; these harness reads are exempt from the required-mode gate. Public GeomMesh
methods that resolve a geometry text file and ensure a compiled HDF run with
``_resolve_geom_text_path``/``_ensure_hdf`` patched to the fixture itself, so only
their HDF read logic is exercised (no RAS Mapper call, no write).
"""
from contextlib import contextmanager
import importlib
from dataclasses import asdict, is_dataclass
from pathlib import Path
from unittest import mock

import h5py
import pytest

from ._case import Case

GEOM = {"geom", "plan"}


def _gm():
    return importlib.import_module("ras_commander.geom.GeomMesh")


def _mesh():
    return _gm().GeomMesh


def _names(path):
    with h5py.File(path, "r") as f:
        key = "Geometry/2D Flow Areas/Attributes"
        if key not in f:
            return []
        return [bytes(v).rstrip(b"\x00").decode("utf-8", "replace").strip() for v in f[key][()]["Name"]]


def _first_mesh(path):
    names = _names(path)
    if not names:
        pytest.skip("fixture has no 2D flow areas")
    return names[0]


def _spacing(path, mesh):
    with h5py.File(path, "r") as f:
        rows = f["Geometry/2D Flow Areas/Attributes"][()]
    for row in rows:
        if bytes(row["Name"]).rstrip(b"\x00").decode("utf-8", "replace").strip() == mesh:
            return float(row["Spacing dx"])
    pytest.skip("no spacing for mesh")


def _plain(value):
    """Dataclasses and tuples of them into dicts; everything else unchanged."""
    if is_dataclass(value) and not isinstance(value, type):
        return {"__type__": type(value).__name__, **{k: _plain(v) for k, v in asdict(value).items()}}
    if isinstance(value, (list, tuple)):
        return type(value)(_plain(v) for v in value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


@contextmanager
def _patched_hdf(path):
    gm = _gm()
    with mock.patch.object(gm, "_resolve_geom_text_path", lambda *a, **k: Path(path)), \
            mock.patch.object(gm, "_ensure_hdf", lambda *a, **k: Path(path)):
        yield gm.GeomMesh


def _refinement_names(path):
    with _patched_hdf(path) as gm:
        return gm.get_refinement_region_names(path)


def _refinement_regions(path):
    with _patched_hdf(path) as gm:
        return gm.get_refinement_regions(path)


def _clip_refinement(path):
    from shapely.geometry import box
    with h5py.File(path, "r") as f:
        key = "Geometry/2D Flow Area Refinement Regions/Polygon Points"
        if key not in f:
            pytest.skip("fixture has no refinement regions")
        pts = f[key][()]
    x0, y0 = pts[:, 0].min(), pts[:, 1].min()
    x1, y1 = pts[:, 0].max(), pts[:, 1].max()
    mask = box(x0, y0, (x0 + x1) / 2, y1)
    with _patched_hdf(path) as gm:
        regions, report = gm.clip_refinement_regions(path, mask, invalid_regions="drop")
    return regions, report


def _grid_anchor(path):
    _first_mesh(path)
    return _plain(_gm()._grid_anchor_from_hdf(path))


def _audit(path):
    mesh = _first_mesh(path)
    return _plain(_gm()._audit_domain_containment_hdf(Path(path), mesh, _spacing(path, mesh)))


def _features(path, group, polygon=False):
    gm = _gm()
    with h5py.File(path, "r") as f:
        if polygon:
            return gm._hdf_polygon_features(f, group)
        if group == "Geometry/Structures":
            return gm._hdf_polyline_features(f, group, info_name="Centerline Info",
                                             parts_name="Centerline Parts", points_name="Centerline Points")
        return gm._hdf_polyline_features(f, group)


def _detect_bc(path):
    _first_mesh(path)
    return _plain(_mesh().detect_bc_conflicts(path, 10.0))


def _preprocessor():
    from ras_commander.geom.GeomPreprocessor import GeomPreprocessor
    return GeomPreprocessor


def _legacy_recovery(path):
    with h5py.File(path, "r") as f:
        version = f.attrs.get("File Version", b"")
    version = version.decode() if isinstance(version, bytes) else str(version)
    with h5py.File(path, "r") as f:
        return _preprocessor()._validate_legacy_geometry_hdf_recovery(f, Path(path), version)


def _contract():
    from ras_commander.geom import _preprocess_contract
    return _preprocess_contract


def _text_path(path):
    text = Path(str(path)[:-4])
    if not text.is_file():
        pytest.skip("geometry text file not next to the fixture")
    return text


def _layer_type(hdf_path):
    """Harness copy of HdfInfiltration._native_infiltration_layer_type (same rule, same errors).

    That helper lives in ras_commander/hdf (owned by the parallel HDF routing task) and
    still reads the sidecar ``LC Type`` attribute through h5py; snapshot() only consumes
    its token. The copy keeps that out-of-scope read in the harness so the gate checks
    the _preprocess_contract reads themselves.
    """
    import numpy as np
    hdf_path = Path(hdf_path)
    with h5py.File(hdf_path, "r") as hdf_file:
        raw_value = hdf_file.attrs.get("LC Type")
    if isinstance(raw_value, (bytes, np.bytes_)):
        value = raw_value.decode("utf-8", errors="replace")
    else:
        value = str(raw_value or "")
    lookup = {
        "InfiltrationSCSCurveNumber": "infiltration_scs",
        "InfiltrationDeficitConstantLoss": "infiltration_deficit_constant",
        "InfiltrationGreenAmpt": "infiltration_green_ampt",
    }
    if value not in lookup:
        raise ValueError(
            f"{hdf_path} is not a recognized HEC-RAS infiltration sidecar "
            f"(LC Type={value!r})."
        )
    return lookup[value]


@contextmanager
def _harness_layer_type():
    from ras_commander.hdf.HdfInfiltration import HdfInfiltration
    with mock.patch.object(HdfInfiltration, "_native_infiltration_layer_type", staticmethod(_layer_type)):
        yield


def _snapshot(path):
    with _harness_layer_type():
        return _contract().snapshot(_text_path(path), Path(path), require_complete_products=False)


def _validate(path):
    text = _text_path(path)
    contract = _contract()
    with _harness_layer_type():
        expected = contract.snapshot(text, Path(path), require_complete_products=False)
    return contract.validate(text, Path(path), expected, 0.0)


def _area_groups(path):
    with h5py.File(path, "r") as f:
        root = f.get("Geometry/2D Flow Areas")
        if root is None:
            pytest.skip("fixture has no 2D flow areas")
        return [name for name, obj in root.items() if isinstance(obj, h5py.Group)]


def _topology(path):
    out = {}
    for name in _area_groups(path):
        with h5py.File(path, "r") as f:
            out[name] = _contract()._topology_issues(f[f"Geometry/2D Flow Areas/{name}"])
    return out


def _binding(path):
    import numpy as np
    out = {}
    for name in _area_groups(path):
        with h5py.File(path, "r") as f:
            area = f[f"Geometry/2D Flow Areas/{name}"]
            if "Cells Center Coordinate" not in area or "Perimeter" not in area:
                continue
            seeds = area["Cells Center Coordinate"][()][: max(0, len(area["Cells Center Coordinate"]) // 2)]
            ring = np.asarray(area["Perimeter"][()], dtype=float)
        with h5py.File(path, "r") as f:
            out[name] = _contract()._mesh_binding_issues(f[f"Geometry/2D Flow Areas/{name}"], seeds, ring)
    return out


def _feature_issues(path, group):
    """Features rebuilt from the file itself: every compared read runs, no issues expected."""
    import numpy as np
    with h5py.File(path, "r") as f:
        if group not in f or "Attributes" not in f[group]:
            pytest.skip(f"fixture has no {group}")
        g = f[group]
        rows, info, points = g["Attributes"][()], g["Polyline Info"][()], g["Polyline Points"][()]
        features = [
            {"name": bytes(rows["Name"][i]).rstrip(b"\x00").decode("utf-8").rstrip(),
             "coordinates": np.asarray(points[int(info[i, 0]): int(info[i, 0]) + int(info[i, 1])]),
             "storage_area": ""}
            for i in range(len(rows))
        ]
    with h5py.File(path, "r") as f:
        return _contract()._feature_issues(f, group, features)


def _regen():
    from ras_commander.gui.workflows import mesh_regeneration
    return mesh_regeneration


def _flow_area_polygon(path):
    return _regen()._read_hdf_flow_area_polygon(Path(path), _first_mesh(path))


CASES = {
    "GeomMesh._grid_anchor_from_hdf": Case(_grid_anchor, kinds=GEOM),
    "GeomMesh._screening_inset": Case(lambda p: _gm()._screening_inset(p), kinds=GEOM),
    "GeomMesh._read_mesh_metadata_from_hdf": Case(lambda p: _gm()._read_mesh_metadata_from_hdf(Path(p)), kinds=GEOM),
    "GeomMesh._read_cell_size_from_hdf": Case(lambda p: _gm()._read_cell_size_from_hdf(Path(p), _first_mesh(p)), kinds=GEOM),
    "GeomMesh._read_cell_size_from_hdf[any]": Case(lambda p: _gm()._read_cell_size_from_hdf(Path(p)), kinds=GEOM),
    "GeomMesh._hdf_flow_area_perimeter": Case(lambda p: _gm()._hdf_flow_area_perimeter(Path(p), _first_mesh(p)), kinds=GEOM),
    "GeomMesh._audit_domain_containment_hdf": Case(_audit, kinds=GEOM, max_mb=400, note="shapely containment audit"),
    "GeomMesh._hdf_polyline_features[breaklines]": Case(lambda p: _features(p, "Geometry/2D Flow Area Break Lines"), kinds=GEOM),
    "GeomMesh._hdf_polyline_features[structures]": Case(lambda p: _features(p, "Geometry/Structures"), kinds=GEOM),
    "GeomMesh._hdf_polygon_features[refinement]": Case(lambda p: _features(p, "Geometry/2D Flow Area Refinement Regions", True), kinds=GEOM),
    "GeomMesh.detect_bc_conflicts": Case(_detect_bc, kinds=GEOM, max_mb=400, note="per-face shapely distance loop"),
    "GeomMesh.get_refinement_region_names": Case(_refinement_names, kinds=GEOM),
    "GeomMesh.get_refinement_regions": Case(_refinement_regions, kinds=GEOM),
    "GeomMesh.clip_refinement_regions": Case(_clip_refinement, kinds=GEOM),
    "GeomMetadata._get_counts_from_hdf": Case(
        lambda p: importlib.import_module("ras_commander.geom.GeomMetadata").GeomMetadata._get_counts_from_hdf(Path(p), {}),
        kinds=GEOM),
    "GeomPreprocessor._geometry_hdf_readiness": Case(lambda p: _preprocessor()._geometry_hdf_readiness(Path(p)), kinds=GEOM),
    "GeomPreprocessor._geometry_hdf_readiness[2D]": Case(lambda p: _preprocessor()._geometry_hdf_readiness(Path(p), "2D"), kinds=GEOM),
    "GeomPreprocessor._validate_legacy_geometry_hdf_recovery": Case(_legacy_recovery, kinds={"geom"},
                                                                     helper="GeomPreprocessor.invalidate_legacy_geometry_hdf_preprocessor_cache"),
    "GeomProjection._inspect_compiled_geometry_hdfs": Case(
        lambda p: importlib.import_module("ras_commander.geom.GeomProjection").GeomProjection._inspect_compiled_geometry_hdfs([Path(str(p)[:-4])]),
        kinds={"geom"}),
    "_preprocess_contract.snapshot": Case(_snapshot, kinds={"geom"}, helper="GeomMesh.regenerate_mesh (completion contract)"),
    "_preprocess_contract.validate": Case(_validate, kinds={"geom"}, helper="GeomMesh.regenerate_mesh (completion contract)",
                                          max_mb=400, note="full topology/binding validation"),
    "_preprocess_contract._topology_issues": Case(_topology, kinds=GEOM, max_mb=400, note="full topology validation"),
    "_preprocess_contract._mesh_binding_issues": Case(_binding, kinds=GEOM, max_mb=400, note="shapely coverage of every face"),
    "_preprocess_contract._feature_issues[breaklines]": Case(lambda p: _feature_issues(p, "Geometry/2D Flow Area Break Lines"), kinds=GEOM),
    "_preprocess_contract._feature_issues[bc_lines]": Case(lambda p: _feature_issues(p, "Geometry/Boundary Condition Lines"), kinds=GEOM),
    "mesh_regeneration._check_mesh_valid": Case(lambda p: _regen()._check_mesh_valid(Path(p)), kinds=GEOM,
                                                helper="gui mesh regeneration workflow"),
    "mesh_regeneration._read_hdf_flow_area_polygon": Case(_flow_area_polygon, kinds=GEOM,
                                                          helper="gui mesh regeneration workflow"),
}
