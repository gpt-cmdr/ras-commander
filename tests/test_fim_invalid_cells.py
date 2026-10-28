"""Invalid 2D cell polygons in sloping mapping: policies, AOI scoping, manifest.

The synthetic mesh reproduces the downstream UPGU1 defect: cell 0 is a square
whose west face has an interior perimeter point that crosses back over its
south face (a bowtie). Cell 1 (west) shares that face, so its valid polygon
contains the bowtie's small lobe, which also lies inside cell 2 (south).
"""
import json
import os
from pathlib import Path

import h5py
import numpy as np
import pytest
from pyproj import CRS

pytest.importorskip("ras_commander_fast_hdf")

MESH = "Bowtie Mesh"
# D -> E -> A crosses A -> B at X = (20/11, 0).
CROSSING_X = 20.0 / 11.0
MAIN_LOBE_AREA = 100.0 - 0.5 * 10.0 * CROSSING_X
SMALL_LOBE_AREA = 0.5 * CROSSING_X * 1.0


def _write_bowtie_mesh(path: Path) -> Path:
    points = np.array(
        [
            [0, 0], [10, 0], [10, 10], [0, 10],  # A B C D (cell 0)
            [-10, 0], [-10, 10],                  # F G (cell 1)
            [10, -10], [0, -10],                  # H I (cell 2)
        ],
        dtype=float,
    )
    faces = np.array(
        [
            [0, 1], [1, 2], [2, 3], [3, 0],  # 0 AB, 1 BC, 2 CD, 3 DA (E inside)
            [0, 4], [4, 5], [5, 3],          # 4 AF, 5 FG, 6 GD
            [1, 6], [6, 7], [7, 0],          # 7 BH, 8 HI, 9 IA
        ],
        dtype=np.int32,
    )
    perimeter_info = np.zeros((len(faces), 2), dtype=np.int32)
    perimeter_info[3] = [0, 1]
    perimeter_values = np.array([[2.0, -1.0]])  # E, south of A -> B
    cell_faces = [[0, 1, 2, 3], [3, 4, 5, 6], [0, 7, 8, 9]]
    info, values = [], []
    for ids in cell_faces:
        info.append([len(values), len(ids)])
        values.extend([face, 1] for face in ids)
    attributes = np.zeros(1, dtype=[("Name", "S64")])
    attributes["Name"] = MESH.encode()
    with h5py.File(path, "w") as hdf:
        hdf.attrs["Projection"] = np.bytes_(CRS.from_epsg(26915).to_wkt(version="WKT1_ESRI"))
        base = f"Geometry/2D Flow Areas/{MESH}"
        hdf["Geometry/2D Flow Areas/Attributes"] = attributes
        hdf[f"{base}/FacePoints Coordinate"] = points
        hdf[f"{base}/Faces FacePoint Indexes"] = faces
        hdf[f"{base}/Faces Perimeter Info"] = perimeter_info
        hdf[f"{base}/Faces Perimeter Values"] = perimeter_values
        hdf[f"{base}/Cells Face and Orientation Info"] = np.asarray(info, dtype=np.int32)
        hdf[f"{base}/Cells Face and Orientation Values"] = np.asarray(values, dtype=np.int32)
    return path


@pytest.fixture
def bowtie(tmp_path):
    return _write_bowtie_mesh(tmp_path / "bowtie.g01.hdf")


def _assert_partition(cells):
    import shapely

    geometries = cells.geometry.to_numpy()
    assert shapely.is_valid(geometries).all()
    assert (shapely.get_type_id(geometries) == 3).all()
    left, right = cells.sindex.query(geometries, predicate="intersects")
    pairs = left < right
    overlap = shapely.area(shapely.intersection(geometries[left[pairs]], geometries[right[pairs]]))
    assert not (overlap > 0).any()


def test_strict_native_assembly_still_refuses_the_bowtie(bowtie):
    from ras_commander.hdf.HdfMesh import HdfMesh, MeshCellPolygonError

    with pytest.raises(MeshCellPolygonError):
        HdfMesh.get_mesh_cell_polygons(bowtie, strict=True, engine="native")


@pytest.mark.parametrize("policy, action", [("repair", "repaired"), ("hull", "convex_hull")])
def test_fallback_policies_own_only_unclaimed_area(bowtie, policy, action):
    from ras_commander.fim import _invalid_cells

    cells, records = _invalid_cells.load_cells(bowtie, policy=policy, threads=1)
    assert cells["cell_id"].tolist() == [0, 1, 2]
    _assert_partition(cells)
    bowtie_record, trimmed = records
    assert bowtie_record["cell_id"] == 0 and bowtie_record["action"] == action
    assert bowtie_record["reason"].startswith("no_polygon: Self-intersection")
    assert bowtie_record["original_area"] == pytest.approx(MAIN_LOBE_AREA + SMALL_LOBE_AREA)
    # Valid neighbours keep the small lobe and the D-X-A wedge.
    assert bowtie_record["fallback_area"] == pytest.approx(MAIN_LOBE_AREA)
    assert cells.geometry.iloc[0].area == pytest.approx(MAIN_LOBE_AREA)
    # Cells 1 and 2 both contain the small lobe; the lower cell ID keeps it.
    assert trimmed["cell_id"] == 2 and trimmed["action"] == "overlap_trimmed"
    assert trimmed["overlap_with"] == [1]
    assert trimmed["original_area"] - trimmed["fallback_area"] == pytest.approx(SMALL_LOBE_AREA)


def test_omit_leaves_the_cell_unowned(bowtie):
    from ras_commander.fim import _invalid_cells

    cells, records = _invalid_cells.load_cells(bowtie, policy="omit", threads=1)
    assert cells["cell_id"].tolist() == [1, 2]
    _assert_partition(cells)
    assert [(r["cell_id"], r["action"], r["fallback_area"]) for r in records] == [
        (0, "omitted", None), (2, "overlap_trimmed", pytest.approx(100 - SMALL_LOBE_AREA)),
    ]


def test_raise_refuses_only_when_the_output_can_include_the_cell(bowtie):
    from shapely.geometry import box

    from ras_commander.fim import _invalid_cells
    from ras_commander.hdf.HdfMesh import MeshCellPolygonError

    cells, records = _invalid_cells.load_cells(bowtie, policy="raise", threads=1)
    assert 0 not in cells["cell_id"].tolist()
    with pytest.raises(MeshCellPolygonError, match="Bowtie Mesh cell 0"):
        _invalid_cells.check_scope(records, "raise", None)
    with pytest.raises(MeshCellPolygonError):
        _invalid_cells.check_scope(records, "raise", box(5, 5, 6, 6))
    # An AOI clear of every invalid and trimmed cell never fails.
    _invalid_cells.check_scope(records, "raise", box(50, 50, 60, 60))
    for policy in ("repair", "hull", "omit"):
        _invalid_cells.check_scope(records, policy, None)


def test_clean_mesh_has_no_records(tmp_path):
    from ras_commander.fim import _invalid_cells

    path = _write_bowtie_mesh(tmp_path / "clean.g01.hdf")
    with h5py.File(path, "a") as hdf:
        del hdf[f"Geometry/2D Flow Areas/{MESH}/Faces Perimeter Info"]
        hdf[f"Geometry/2D Flow Areas/{MESH}/Faces Perimeter Info"] = np.zeros((10, 2), dtype=np.int32)
    cells, records = _invalid_cells.load_cells(path, policy="raise", threads=1)
    assert cells["cell_id"].tolist() == [0, 1, 2] and records == []
    _invalid_cells.check_scope(records, "raise", None)
    assert _invalid_cells.describe(records, "raise", None) == dict(
        schema="fim-invalid-cells/1", policy="raise", count=0, cells=[])


def test_manifest_record_is_json_and_reports_aoi_intersection(bowtie):
    from shapely.geometry import box

    from ras_commander.fim import _invalid_cells

    _, records = _invalid_cells.load_cells(bowtie, policy="repair", threads=1)
    document = json.loads(json.dumps(_invalid_cells.describe(records, "repair", box(4, 4, 5, 5))))
    assert document["schema"] == "fim-invalid-cells/1"
    assert document["policy"] == "repair" and document["count"] == 2
    first = document["cells"][0]
    assert set(first) == {"mesh", "cell_id", "reason", "action", "original_area",
                          "fallback_area", "overlap_with", "intersects_aoi"}
    assert (first["mesh"], first["cell_id"], first["intersects_aoi"]) == (MESH, 0, True)
    assert document["cells"][1]["intersects_aoi"] is False
    assert _invalid_cells.describe(records, "repair", None)["cells"][0]["intersects_aoi"] is None


@pytest.mark.parametrize("value", ["fallback_hull", "strict", True, 0])
def test_unknown_policy_is_rejected_before_inputs_are_read(tmp_path, value):
    from ras_commander import RasFim

    with pytest.raises(ValueError, match="invalid_cells"):
        RasFim.map_sloping_profiles(tmp_path / "absent.hdf", tmp_path / "absent.tif",
                                    tmp_path / "out", invalid_cells=value)
    with pytest.raises(ValueError, match="invalid_cells"):
        RasFim.prepare_sloping_model(tmp_path / "absent.hdf", tmp_path / "absent.tif",
                                     invalid_cells=value)


@pytest.fixture
def glaise_case():
    filename = os.environ.get("RAS_COMMANDER_FIM_INVALID_CELL_CASE")
    if not filename:
        pytest.skip("set RAS_COMMANDER_FIM_INVALID_CELL_CASE for the real invalid-cell model")
    return json.loads(Path(filename).read_text(encoding="utf-8"))


def test_real_invalid_cells_map_and_match_omission_elsewhere(glaise_case, tmp_path):
    """Glaise Creek p01: three self-intersecting cells in 'default geometry'.

    The case JSON names ``hdf``, a ``terrain`` window containing an invalid
    cell, ``cell_id`` and optional ``max_working_mib``. Repair must succeed,
    differ from omission only inside affected cells, and record them.
    """
    import rasterio
    import shapely

    from ras_commander import RasFim
    from ras_commander.fim import _invalid_cells
    from ras_commander.hdf.HdfMesh import MeshCellPolygonError

    common = dict(threads=4, max_working_mib=glaise_case.get("max_working_mib", 8192))
    products = {}
    for policy in ("repair", "omit"):
        manifest = RasFim.map_sloping_profiles(
            glaise_case["hdf"], glaise_case["terrain"], tmp_path / policy,
            invalid_cells=policy, **common)
        assert manifest.status.tolist() == ["complete"]
        document = json.loads((tmp_path / policy / "fim_manifest.json").read_text())
        assert document["invalid_cells"] == json.loads(json.dumps(manifest.attrs["invalid_cells"]))
        listed = {c["cell_id"]: c for c in document["invalid_cells"]["cells"]}
        assert listed[glaise_case["cell_id"]]["action"] == ("repaired" if policy == "repair" else "omitted")
        with rasterio.open(manifest.iloc[0].wse_tif) as source:
            products[policy] = (source.read(1, masked=True).filled(np.nan), source.transform)
    (repaired, transform), (omitted, other) = products["repair"], products["omit"]
    assert transform == other and repaired.shape == omitted.shape
    _, records = _invalid_cells.load_cells(glaise_case["hdf"], policy="repair", threads=4)
    affected = shapely.union_all([r["extent"] for r in records])
    rows, cols = np.indices(repaired.shape)
    outside = ~shapely.contains_xy(affected, transform.c + (cols + 0.5) * transform.a,
                                   transform.f + (rows + 0.5) * transform.e)
    same = np.isnan(repaired) == np.isnan(omitted)
    same &= np.isnan(repaired) | (repaired.view(np.uint32) == omitted.view(np.uint32))
    assert same[outside].all()
    with pytest.raises(MeshCellPolygonError):
        RasFim.map_sloping_profiles(glaise_case["hdf"], glaise_case["terrain"],
                                    tmp_path / "raise", invalid_cells="raise", **common)
    with rasterio.open(glaise_case["terrain"]) as source:
        left, bottom = source.bounds.left, source.bounds.bottom
    corner = (left, bottom, left + 500.0, bottom + 500.0)
    assert not affected.intersects(shapely.box(*corner))
    manifest = RasFim.map_sloping_profiles(
        glaise_case["hdf"], glaise_case["terrain"], tmp_path / "raise-clear",
        invalid_cells="raise", bbox=corner, **common)
    assert manifest.attrs["invalid_cells"]["policy"] == "raise"
