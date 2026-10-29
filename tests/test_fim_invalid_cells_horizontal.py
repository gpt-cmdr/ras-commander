"""Invalid 2D cell polygons in horizontal, whole-simulation and comparison mapping.

Cell tables come from ``RasFim.get_cells_from_plan_hdf``: strict assembly first,
the ``invalid_cells`` policy only when strict assembly refuses the mesh. The
synthetic meshes are those of ``test_fim_invalid_cells.py`` (a bowtie cell 0
with valid neighbours). Plan results and model-scope checks are stubbed; no
HEC-RAS execution occurs. The real Glaise Creek test is opt-in through
RAS_COMMANDER_FIM_GLAISE_HORIZONTAL_CASE.
"""
import json
import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest
from pyproj import CRS

pytest.importorskip("ras_commander_fast_hdf")
rasterio = pytest.importorskip("rasterio")
shapely = pytest.importorskip("shapely")
from rasterio.transform import from_origin
from shapely.geometry import box

from ras_commander import RasFim
from ras_commander.fim import _invalid_cells
from ras_commander.fim.errors import FimUnsupportedError
from ras_commander.hdf.HdfMesh import MeshCellPolygonError

MESH = "Bowtie Mesh"
BOWTIE_RING = [(0, 0), (10, 10), (0, 10), (10, 0)]
WSE = {0: 3.0, 1: 1.0, 2: 2.0}


def _write_cells(path, rings):
    points, faces, info, values = [], [], [], []
    for ring in rings:
        first_point, first_face = len(points), len(faces)
        points.extend(ring)
        faces.extend((first_point + i, first_point + (i + 1) % len(ring)) for i in range(len(ring)))
        info.append((len(values), len(ring)))
        values.extend((first_face + i, 1) for i in range(len(ring)))
    attributes = np.zeros(1, dtype=[("Name", "S64")])
    attributes["Name"] = MESH.encode()
    with h5py.File(path, "w") as hdf:
        hdf.attrs["Projection"] = np.bytes_(CRS.from_epsg(26915).to_wkt(version="WKT1_ESRI"))
        hdf["Geometry/2D Flow Areas/Attributes"] = attributes
        base = f"Geometry/2D Flow Areas/{MESH}"
        hdf[f"{base}/FacePoints Coordinate"] = np.asarray(points, dtype=float)
        hdf[f"{base}/Faces FacePoint Indexes"] = np.asarray(faces, dtype=np.int32)
        hdf[f"{base}/Faces Perimeter Info"] = np.zeros((len(faces), 2), dtype=np.int32)
        hdf[f"{base}/Faces Perimeter Values"] = np.empty((0, 2), dtype=float)
        hdf[f"{base}/Cells Face and Orientation Info"] = np.asarray(info, dtype=np.int32)
        hdf[f"{base}/Cells Face and Orientation Values"] = np.asarray(values, dtype=np.int32)
    return path


def _ring(shape):
    return list(shape.exterior.coords)[:-1]


@pytest.fixture
def split_mesh(tmp_path):
    """Cell 1 (strip) cuts cell 2 in two; nothing is left for the bowtie (cell 0)."""
    return _write_cells(tmp_path / "split.p01.hdf",
                        [BOWTIE_RING, _ring(box(4, -1, 6, 11)), _ring(box(0, 0, 10, 10))])


@pytest.fixture
def repaired_mesh(tmp_path):
    """Valid neighbours west (1) and east (2) of the bowtie (0), which is repaired."""
    return _write_cells(tmp_path / "repaired.p01.hdf",
                        [BOWTIE_RING, _ring(box(-10, 0, 0, 10)), _ring(box(10, 0, 20, 10))])


@pytest.fixture
def valid_mesh(tmp_path):
    return _write_cells(tmp_path / "valid.p01.hdf",
                        [_ring(box(0, 0, 10, 10)), _ring(box(-10, 0, 0, 10)), _ring(box(10, 0, 20, 10))])


@pytest.fixture
def terrain(tmp_path):
    path = tmp_path / "terrain.tif"
    with rasterio.open(path, "w", driver="GTiff", width=40, height=30, count=1, dtype="float32",
                       crs="EPSG:26915", transform=from_origin(-15.0, 15.0, 1.0, 1.0),
                       nodata=-9999.0, tiled=True, blockxsize=16, blockysize=16) as dst:
        dst.write(np.zeros((1, 30, 40), dtype=np.float32))
    return path


@pytest.fixture(autouse=True)
def stub_plan(monkeypatch):
    """Maximum results for every cell and a 2D-only model scope."""
    from ras_commander import HdfResultsMesh

    def frame(column):
        def read(path, include_geometry=False):
            return pd.DataFrame({"mesh_name": MESH, "cell_id": list(WSE),
                                 column: list(WSE.values())})
        return staticmethod(read)

    monkeypatch.setattr(HdfResultsMesh, "get_mesh_max_ws", frame("maximum_water_surface"))
    monkeypatch.setattr(HdfResultsMesh, "get_mesh_max_depth", frame("maximum_depth"))
    monkeypatch.setattr(RasFim, "validate_2d_model",
                        staticmethod(lambda *a, **k: {"storage_areas": 0}))


def products(row):
    out = {}
    for column in ("depth_tif", "wse_tif"):
        with rasterio.open(row[column]) as src:
            out[column] = (src.transform, src.read(1, masked=True).filled(np.nan))
    return out


def values_at(frame, point):
    out = {}
    for column, (transform, array) in products(frame.iloc[0]).items():
        row, col = rasterio.transform.rowcol(transform, *point)
        out[column] = float(array[row, col])
    return out


def rust_engine():
    from ras_commander.fim import _engine
    try:
        return _engine.find_engine(None)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def test_valid_mesh_extraction_is_strict_and_unrecorded(valid_mesh, monkeypatch):
    calls = []
    original = _invalid_cells.load_cells
    monkeypatch.setattr(_invalid_cells, "load_cells", lambda *a, **k: calls.append(1) or original(*a, **k))
    from ras_commander import HdfMesh

    cells = RasFim.get_cells_from_plan_hdf(valid_mesh)
    strict = HdfMesh.get_mesh_cell_polygons(valid_mesh, strict=True)
    assert calls == []
    assert "fim_invalid_cells" not in cells.attrs
    assert list(shapely.to_wkb(cells.geometry.values)) == list(shapely.to_wkb(strict.geometry.values))


def test_strict_extraction_still_refuses_without_a_policy_path(split_mesh):
    from ras_commander import HdfMesh

    with pytest.raises(MeshCellPolygonError):
        HdfMesh.get_mesh_cell_polygons(split_mesh, strict=True)


def test_split_cell_is_one_multipolygon_row(split_mesh):
    cells = RasFim.get_cells_from_plan_hdf(split_mesh)
    assert cells["cell_idx"].tolist() == [1, 2]
    assert cells.geom_type.tolist() == ["Polygon", "MultiPolygon"]
    assert sorted(part.area for part in cells.geometry.iloc[1].geoms) == [40.0, 40.0]
    stored = cells.attrs["fim_invalid_cells"]
    assert stored["policy"] == "repair" and stored["split_cell_idx"] == [2]
    actions = {r["cell_id"]: r["action"] for r in stored["records"]}
    assert actions == {0: "omitted", 2: "overlap_trimmed"}


@pytest.mark.parametrize("policy", ["repair", "hull", "omit", "raise"])
def test_extraction_records_the_policy(repaired_mesh, policy):
    cells = RasFim.get_cells_from_plan_hdf(repaired_mesh, invalid_cells=policy)
    stored = cells.attrs["fim_invalid_cells"]
    assert stored["policy"] == policy
    bowtie = next(r for r in stored["records"] if r["cell_id"] == 0)
    expected = {"repair": "repaired", "hull": "convex_hull", "omit": "omitted", "raise": "omitted"}
    assert bowtie["action"] == expected[policy]
    assert (0 in cells["cell_idx"].tolist()) == (policy in ("repair", "hull"))


def test_unknown_policy_is_rejected(repaired_mesh):
    with pytest.raises(ValueError, match="invalid_cells must be one of"):
        RasFim.get_cells_from_plan_hdf(repaired_mesh, invalid_cells="strict")


# --------------------------------------------------------------------------- #
# Horizontal mapping
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("backend", ["numpy", "rust"])
def test_every_piece_of_a_split_cell_owns_its_wse(split_mesh, terrain, tmp_path, backend):
    if backend == "rust" and rust_engine() is None:
        pytest.skip("Fast-Map engine unavailable")
    cells = RasFim.get_cells_from_plan_hdf(split_mesh)
    out = RasFim.map_horizontal_profiles(cells, terrain, tmp_path / "out", backend=backend)
    assert out.iloc[0].status == "complete"
    assert out.iloc[0].wet_cells == 2
    for point in ((2.0, 5.0), (8.0, 5.0)):  # both pieces of cell 2
        assert values_at(out, point) == {"depth_tif": 2.0, "wse_tif": 2.0}
    assert values_at(out, (5.0, 5.0))["wse_tif"] == 1.0  # the strip
    manifest = json.loads((tmp_path / "out" / "fim_manifest.json").read_text(encoding="utf-8"))
    assert manifest["invalid_cells"] == out.attrs["invalid_cells"]
    record = manifest["invalid_cells"]
    assert record["schema"] == "fim-invalid-cells/1" and record["policy"] == "repair"
    assert {c["cell_id"]: c["pieces"] for c in record["cells"]} == {0: 0, 2: 2}


def test_rust_and_numpy_agree_on_rebuilt_cells(repaired_mesh, terrain, tmp_path):
    if rust_engine() is None:
        pytest.skip("Fast-Map engine unavailable")
    cells = RasFim.get_cells_from_plan_hdf(repaired_mesh)
    reference = products(RasFim.map_horizontal_profiles(
        cells, terrain, tmp_path / "numpy", backend="numpy").iloc[0])
    native = products(RasFim.map_horizontal_profiles(
        cells, terrain, tmp_path / "rust", backend="rust").iloc[0])
    for column in reference:
        assert reference[column][0] == native[column][0]
        assert np.array_equal(reference[column][1].view(np.uint32), native[column][1].view(np.uint32))


@pytest.mark.parametrize("policy, bowtie_wse", [("repair", 3.0), ("hull", 3.0), ("omit", None)])
def test_policies_set_the_bowtie_ownership(repaired_mesh, terrain, tmp_path, policy, bowtie_wse):
    cells = RasFim.get_cells_from_plan_hdf(repaired_mesh, invalid_cells=policy)
    out = RasFim.map_horizontal_profiles(cells, terrain, tmp_path / policy, backend="numpy",
                                         invalid_cells=policy)
    inside = values_at(out, (8.0, 2.0))  # inside the bowtie's main lobe
    if bowtie_wse is None:
        assert np.isnan(inside["wse_tif"])
    else:
        assert inside["wse_tif"] == bowtie_wse
    assert values_at(out, (-5.0, 5.0))["wse_tif"] == 1.0
    assert values_at(out, (15.0, 5.0))["wse_tif"] == 2.0
    assert out.attrs["invalid_cells"]["policy"] == policy


def test_policy_must_match_the_extraction(repaired_mesh, terrain, tmp_path):
    cells = RasFim.get_cells_from_plan_hdf(repaired_mesh, invalid_cells="repair")
    with pytest.raises(ValueError, match="extracted with invalid_cells='repair'"):
        RasFim.map_horizontal_profiles(cells, terrain, tmp_path / "out", backend="numpy",
                                       invalid_cells="omit")
    assert not (tmp_path / "out").exists()


def test_raise_is_scoped_to_the_aoi(repaired_mesh, terrain, tmp_path):
    cells = RasFim.get_cells_from_plan_hdf(repaired_mesh, invalid_cells="raise")
    with pytest.raises(MeshCellPolygonError, match="Bowtie Mesh cell 0"):
        RasFim.map_horizontal_profiles(cells, terrain, tmp_path / "all", backend="numpy",
                                       invalid_cells="raise")
    with pytest.raises(MeshCellPolygonError):
        RasFim.map_horizontal_profiles(cells, terrain, tmp_path / "hit", backend="numpy",
                                       bbox=(1, 1, 3, 3), invalid_cells="raise")
    away = RasFim.map_horizontal_profiles(cells, terrain, tmp_path / "away", backend="numpy",
                                          bbox=(-9, 1, -2, 9), invalid_cells="raise")
    assert away.iloc[0].status == "complete"
    assert {c["intersects_aoi"] for c in away.attrs["invalid_cells"]["cells"]} == {False}


def test_tables_without_a_record_stay_strict(valid_mesh, terrain, tmp_path):
    cells = RasFim.get_cells_from_plan_hdf(valid_mesh)
    out = RasFim.map_horizontal_profiles(cells, terrain, tmp_path / "out", backend="numpy",
                                         invalid_cells="raise")
    assert out.attrs["invalid_cells"] == {"schema": "fim-invalid-cells/1", "policy": "raise",
                                          "count": 0, "cells": []}
    # A MultiPolygon the extraction did not record is still refused.
    merged = cells.copy()
    merged.loc[0, "geometry"] = shapely.MultiPolygon([box(0, 0, 4, 10), box(6, 0, 10, 10)])
    with pytest.raises(FimUnsupportedError, match="valid, non-empty cell Polygons"):
        RasFim.map_horizontal_profiles(merged, terrain, tmp_path / "multi", backend="numpy")


def test_step05_refuses_rebuilt_tables(repaired_mesh, tmp_path):
    cells = RasFim.get_cells_from_plan_hdf(repaired_mesh)
    with pytest.raises(FimUnsupportedError, match="map_profiles requires valid cell polygons"):
        RasFim.map_profiles(cells, tmp_path / "missing.tif", tmp_path / "out", hdf_path=repaired_mesh)
    with pytest.raises(FimUnsupportedError, match="prepare_profile requires valid cell polygons"):
        RasFim.prepare_profile(cells, None, "wsel_max", 1.0)


def test_explode_split_keeps_row_order():
    import geopandas as gpd

    frame = gpd.GeoDataFrame(
        {"cell_idx": [1, 2, 3], "wsel": [1.0, 2.0, 3.0]},
        geometry=[box(0, 0, 1, 1), shapely.MultiPolygon([box(1, 0, 2, 1), box(3, 0, 4, 1)]),
                  box(2, 0, 3, 1)], crs=26915)
    exploded = _invalid_cells.explode_split(frame, frozenset({2}))
    assert exploded["cell_idx"].tolist() == [1, 2, 2, 3]
    assert exploded["wsel"].tolist() == [1.0, 2.0, 2.0, 3.0]
    assert exploded.geom_type.tolist() == ["Polygon"] * 4
    assert _invalid_cells.explode_split(frame, frozenset()) is frame


# --------------------------------------------------------------------------- #
# Whole simulation
# --------------------------------------------------------------------------- #
@pytest.fixture
def whole_stubs(monkeypatch, tmp_path):
    from ras_commander.fim import _engine, _whole_simulation

    engine = tmp_path / "engine.exe"
    engine.write_bytes(b"")
    monkeypatch.setattr(_engine, "find_engine", lambda *a, **k: engine)
    monkeypatch.setattr(_engine, "engine_method", lambda *a, **k: {})
    monkeypatch.setattr(_whole_simulation, "_require_methods", lambda method: ({}, {}))
    stamps = [pd.Timestamp("2000-01-01"), pd.Timestamp("2000-01-01 01:00")]
    monkeypatch.setattr(_whole_simulation, "output_hours",
                        lambda hdf: ([0.0, 1.0], stamps[0], stamps))
    seen = {}
    monkeypatch.setattr(_whole_simulation, "_run", lambda *args, **kw: seen.update(cells=args[3]))
    return seen


def test_whole_simulation_raise_refuses_any_affected_cell(repaired_mesh, terrain, tmp_path, whole_stubs):
    with pytest.raises(MeshCellPolygonError):
        RasFim.map_whole_simulation(repaired_mesh, terrain, tmp_path / "out", threshold=0.5,
                                    invalid_cells="raise")
    assert "cells" not in whole_stubs


def test_whole_simulation_maps_rebuilt_cells_and_records_them(split_mesh, terrain, tmp_path, whole_stubs):
    out = RasFim.map_whole_simulation(split_mesh, terrain, tmp_path / "out", threshold=0.5)
    staged = whole_stubs["cells"]
    assert staged["cell_id"].tolist() == [1, 2, 2]  # one ownership row per piece
    assert staged.geom_type.tolist() == ["Polygon"] * 3
    manifest = json.loads((tmp_path / "out" / "fim_manifest.json").read_text(encoding="utf-8"))
    assert manifest["invalid_cells"] == out.attrs["invalid_cells"]
    assert {c["cell_id"]: c["action"] for c in manifest["invalid_cells"]["cells"]} == {
        0: "omitted", 2: "overlap_trimmed"}


def test_whole_simulation_valid_mesh_uses_strict_cells(valid_mesh, terrain, tmp_path, whole_stubs, monkeypatch):
    monkeypatch.setattr(_invalid_cells, "load_cells",
                        lambda *a, **k: pytest.fail("non-strict assembly ran on a valid mesh"))
    out = RasFim.map_whole_simulation(valid_mesh, terrain, tmp_path / "out", threshold=0.5)
    assert out.attrs["invalid_cells"]["count"] == 0
    assert whole_stubs["cells"]["cell_id"].tolist() == [0, 1, 2]


# --------------------------------------------------------------------------- #
# Real model (opt-in): Glaise Creek p01 against RAS Mapper 7.0.1 horizontal maps
# --------------------------------------------------------------------------- #
@pytest.fixture
def glaise_case(stub_plan):
    filename = os.environ.get("RAS_COMMANDER_FIM_GLAISE_HORIZONTAL_CASE")
    if not filename:
        pytest.skip("set RAS_COMMANDER_FIM_GLAISE_HORIZONTAL_CASE for the real horizontal test")
    return json.loads(Path(filename).read_text(encoding="utf-8"))


def test_real_glaise_horizontal_repair_matches_rasmapper(glaise_case, tmp_path, monkeypatch):
    """Repair reproduces native depth on every window pixel. Native WSE differs only
    where native depth is nodata (RAS Mapper writes WSE at a bowtie crossing pixel
    whose depth it leaves dry)."""
    monkeypatch.undo()  # real plan results and scope checks
    cells = RasFim.get_cells_from_plan_hdf(glaise_case["hdf"])
    record = {r["cell_id"]: r["action"] for r in cells.attrs["fim_invalid_cells"]["records"]}
    assert {k: record[k] for k in (36699, 457262, 497876)} == dict.fromkeys(
        (36699, 457262, 497876), "repaired")
    for window in glaise_case["windows"]:
        out = RasFim.map_horizontal_profiles(cells, window["terrain"], tmp_path / Path(window["terrain"]).stem,
                                             threads=4, max_working_mib=8192)
        row = out.iloc[0]
        for column, key in (("depth_tif", "depth"), ("wse_tif", "wse")):
            with rasterio.open(window[key]) as ref, rasterio.open(row[column]) as cand:
                expected = ref.read(1, masked=True).filled(np.nan)
                actual = np.full(expected.shape, np.nan, dtype=np.float32)
                r0 = round((cand.transform.f - ref.transform.f) / ref.transform.e)
                c0 = round((cand.transform.c - ref.transform.c) / ref.transform.a)
                actual[r0:r0 + cand.height, c0:c0 + cand.width] = cand.read(1, masked=True).filled(np.nan)
            same = (np.isnan(actual) & np.isnan(expected)) | (actual.view(np.uint32) == expected.view(np.uint32))
            if key == "depth":
                assert same.all(), f"{window['terrain']}: {int((~same).sum())} depth pixels differ"
                depth_nodata = np.isnan(expected)
            else:
                assert (same | depth_nodata).all()
                assert int((~same).sum()) <= window.get("wse_only_native_pixels", 0)
