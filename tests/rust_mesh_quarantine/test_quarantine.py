"""Native mesh quarantine regressions (bridge API_VERSION 11).

Two layers are covered:

* the direct ``ras_commander_fast_hdf.assemble_cells`` binding (strict and
  quarantine policy, structural corruption always fatal, ghosts/empty cells,
  curved/reversed faces, thread determinism); these skip cleanly when the
  optional extension is not installed;
* the ``HdfMesh.get_mesh_cell_polygons`` release contract: auto mode returns
  exactly the Python reference outcome (result or exception), required mode
  (``backend="rust"``) raises instead of falling back, and python mode never
  touches the extension.

Real-model conformance lives in ``qualification.py``. The suite passes with
``RAS_COMMANDER_FAST_HDF`` unset/``auto``, ``0`` and ``required``.
"""
from contextlib import contextmanager
from functools import wraps

import numpy as np
import pytest

API_VERSION = 11
MESH = "Native Quarantine"
REFERENCE_KEYS = {"mesh_name", "cell_id", "face_count", "polygon_count", "status",
                  "reason_code", "face_ids", "missing_face_ids"}


@pytest.fixture
def native():
    try:
        import ras_commander_fast_hdf as module
    except (ImportError, OSError) as exc:  # same policy as fast_hdf._load_native
        pytest.skip(f"optional ras-commander-fast-hdf extension not importable: {exc}")
    assert module.API_VERSION == API_VERSION
    return module


@pytest.fixture
def adapter():
    from ras_commander import fast_hdf
    fast_hdf._reset_native()
    fast_hdf.close_sessions()
    yield fast_hdf
    fast_hdf.close_sessions()
    fast_hdf._reset_native()


@pytest.fixture
def native_adapter(adapter):
    if not adapter.available():
        pytest.skip("optional ras-commander-fast-hdf extension not installed/compatible")
    return adapter


# --------------------------------------------------------------------------
# Synthetic topology: one square cell (or a bow-tie when invalid).
# --------------------------------------------------------------------------

def topology(invalid=False):
    points = [[0, 0], [1, 0], [1, 1], [0, 1]]
    if invalid:
        points = [[0, 0], [1, 1], [0, 1], [1, 0]]
    return [np.array(points, dtype="f8"), np.array([[0, 1], [1, 2], [2, 3], [3, 0]], dtype="i8"),
            np.zeros((4, 2), dtype="i8"), np.empty((0, 2), dtype="f8"),
            np.array([[0, 4]], dtype="i8"), np.array([[0, 1], [1, -1], [2, 1], [3, -1]], dtype="i8")]


def grid_topology(nx=24, ny=17, bowties=()):
    """Regular nx*ny cell grid; cells listed in ``bowties`` get a crossed ring.

    A crossed ring is made by giving the cell's bottom face one perimeter
    sample above the cell's top edge, so that face crosses the top face.
    Shared face/point topology is otherwise untouched (no structural damage).
    """
    def node(i, j):
        return j * (nx + 1) + i
    points = np.array([[i, j] for j in range(ny + 1) for i in range(nx + 1)], dtype="f8")
    faces, index = [], {}
    def face(a, b):
        key = (min(a, b), max(a, b))
        if key not in index:
            index[key] = len(faces)
            faces.append(key)
        return index[key]
    info, values = [], []
    for j in range(ny):
        for i in range(nx):
            ring = [node(i, j), node(i + 1, j), node(i + 1, j + 1), node(i, j + 1)]
            info.append([len(values), 4])
            for a, b in zip(ring, ring[1:] + ring[:1]):
                f = face(a, b)
                values.append([f, 1 if faces[f] == (a, b) else -1])
    perimeter_info = np.zeros((len(faces), 2), dtype="i8")
    perimeter_values = np.empty((0, 2), dtype="f8")
    if bowties:
        samples, offsets = [], {}
        for cell in bowties:
            j, i = divmod(cell, nx)
            # The bottom face gets an interior sample far above the top edge,
            # crossing the cell's own top face: a self-intersecting ring.
            f = index[(node(i, j), node(i + 1, j))]
            offsets[f] = len(samples)
            samples.append([i + 0.5, j + 2.5])
        perimeter_values = np.array(samples, dtype="f8")
        for f, start in offsets.items():
            perimeter_info[f] = [start, 1]
    return [points, np.array(faces, dtype="i8"), perimeter_info, perimeter_values,
            np.array(info, dtype="i8"), np.array(values, dtype="i8")]


# --------------------------------------------------------------------------
# Direct binding
# --------------------------------------------------------------------------

def test_api_version_pinned(native):
    assert native.API_VERSION == API_VERSION
    assert issubclass(native.TopologyError, ValueError)


def test_legacy_shape_and_thread_determinism(native):
    args = topology()
    saved = [a.copy() for a in args]
    legacy = native.assemble_cells(*args)
    assert isinstance(legacy, tuple) and len(legacy) == 3
    for threads in (1, 2, 4):
        coordinates, offsets, ids, diagnostics = native.assemble_cells(
            *args, threads=threads, strict=False, return_diagnostics=True)
        np.testing.assert_array_equal(ids, [0])
        np.testing.assert_array_equal(offsets, [0, 5])
        np.testing.assert_array_equal(coordinates, legacy[0])
        assert coordinates.shape == (5, 2) and np.array_equal(coordinates[0], coordinates[-1])
        assert diagnostics == []
        for actual, original in zip(args, saved):
            np.testing.assert_array_equal(actual, original)


def test_all_invalid_and_strict_failure(native):
    args = topology(invalid=True)
    for threads in (1, 2, 4):
        coordinates, offsets, ids, diagnostics = native.assemble_cells(
            *args, threads=threads, strict=False, return_diagnostics=True)
        assert coordinates.shape == (0, 2) and len(ids) == 0
        np.testing.assert_array_equal(offsets, [0])
        assert isinstance(diagnostics, list) and len(diagnostics) == 1
        record = diagnostics[0]
        assert isinstance(record, dict)
        assert record["cell_id"] == 0
        assert record["kind"] == "invalid_geometry"
        assert "intersection" in record["message"]
    for kwargs in ({}, {"strict": True}):
        with pytest.raises(native.TopologyError, match="cell 0") as info:
            native.assemble_cells(*args, **kwargs)
        # Geometric (quarantinable) failure, not structural corruption.
        assert info.value.mesh_structure_error is False


@pytest.mark.parametrize("damage", ["offset", "count", "face", "endpoint", "perimeter", "nan", "columns"])
@pytest.mark.parametrize("strict", [False, True])
def test_corruption_is_always_fatal_even_after_invalid_ring(native, damage, strict):
    args = topology(invalid=True)
    # Put a corrupt late record after geometry that non-strict may omit.
    args[4] = np.array([[0, 4], [0, 4]], dtype="i8")
    if damage == "offset":
        args[4][1, 0] = np.iinfo("i8").max
    elif damage == "count":
        args[4][1, 1] = -1
    elif damage == "face":
        args[5] = np.concatenate([args[5], [[99, 1]]])
        args[4][1] = [4, 1]
    elif damage == "endpoint":
        args[1][3, 1] = 99
    elif damage == "perimeter":
        args[2][3] = [0, 1]
    elif damage == "nan":
        args[0][0, 0] = np.nan
    else:
        args[4] = args[4][:, :1].copy()
    with pytest.raises(native.TopologyError) as info:
        native.assemble_cells(*args, strict=strict, return_diagnostics=True)
    assert info.value.mesh_structure_error is True


def test_empty_and_ghosts(native):
    args = topology()
    args[4] = np.empty((0, 2), dtype="i8")
    coordinates, offsets, ids, diagnostics = native.assemble_cells(
        *args, strict=False, return_diagnostics=True)
    assert ids.size == 0 and coordinates.shape == (0, 2) and diagnostics == []
    np.testing.assert_array_equal(offsets, [0])
    args[4] = np.array([[0, 0], [0, 1], [0, 4]], dtype="i8")
    for strict in (False, True):
        result = native.assemble_cells(*args, strict=strict, return_diagnostics=True)
        np.testing.assert_array_equal(result[2], [2])
        # Ghosts/empty records are expected non-polygons, never invalid rings.
        assert result[3] == []


def test_curved_reversed_faces_preserve_samples(native):
    args = topology()
    args[1][0] = [1, 0]
    args[2][0] = [0, 1]
    args[3] = np.array([[0.5, -0.2]], dtype="f8")
    coords, offsets, ids = native.assemble_cells(*args)
    assert any(np.array_equal(p, [0.5, -0.2]) for p in coords)
    assert len(coords) == 6 and ids.tolist() == [0]
    np.testing.assert_array_equal(offsets, [0, 6])


def test_disconnected_topology_remains_fatal(native):
    args = topology()
    args[5][3, 0] = 2
    for strict in (False, True):
        with pytest.raises(native.TopologyError) as info:
            native.assemble_cells(*args, strict=strict)
        assert info.value.mesh_structure_error is True


def test_grid_thread_determinism_with_quarantine(native):
    nx = 24
    bowties = (5, 77, 300, 407)
    args = grid_topology(nx=nx, bowties=bowties)
    saved = [a.copy() for a in args]
    cells = len(args[4])
    baseline = None
    for threads in (1, 2, 3, 4, 8):
        coordinates, offsets, ids, diagnostics = native.assemble_cells(
            *args, threads=threads, strict=False, return_diagnostics=True)
        assert sorted(d["cell_id"] for d in diagnostics) == sorted(bowties)
        assert all(d["kind"] == "invalid_geometry" for d in diagnostics)
        assert ids.tolist() == [c for c in range(cells) if c not in bowties]
        assert len(offsets) == len(ids) + 1 and offsets[-1] == len(coordinates)
        current = (coordinates, offsets, ids, [sorted(d.items()) for d in diagnostics])
        if baseline is None:
            baseline = current
        else:
            np.testing.assert_array_equal(current[0], baseline[0])
            np.testing.assert_array_equal(current[1], baseline[1])
            np.testing.assert_array_equal(current[2], baseline[2])
            assert current[3] == baseline[3]
        with pytest.raises(native.TopologyError, match=f"cell {bowties[0]}:") as info:
            native.assemble_cells(*args, threads=threads, strict=True)
        assert info.value.mesh_structure_error is False
    for actual, original in zip(args, saved):
        np.testing.assert_array_equal(actual, original)
    valid = native.assemble_cells(*grid_topology(nx=nx), threads=4)
    assert valid[2].tolist() == list(range(cells))


# --------------------------------------------------------------------------
# High-level adapter: the release contract
# --------------------------------------------------------------------------

NAMES = ("FacePoints Coordinate", "Faces FacePoint Indexes", "Faces Perimeter Info",
         "Faces Perimeter Values", "Cells Face and Orientation Info",
         "Cells Face and Orientation Values")
CASES = ("valid", "invalid", "corrupt_late", "grid_bowties")


def write_hdf(path, case):
    import h5py
    from pyproj import CRS
    if case == "grid_bowties":
        args = grid_topology(nx=12, ny=9, bowties=(3, 50))
    else:
        args = topology(invalid=case != "valid")
        if case == "corrupt_late":
            args[4] = np.array([[0, 4], [99999, 4]], dtype="i8")
    with h5py.File(path, "w") as hdf:
        # Fixed-length ASCII ESRI WKT, as HEC-RAS writes it (h5py would default
        # to a vlen string, and WKT2 carries non-ASCII degree signs).
        hdf.attrs["Projection"] = np.bytes_(CRS.from_epsg(26915).to_wkt("WKT1_ESRI").encode("ascii"))
        attributes = np.zeros(1, dtype=[("Name", "S64")])
        attributes["Name"] = MESH.encode()
        hdf["Geometry/2D Flow Areas/Attributes"] = attributes
        for name, values in zip(NAMES, args):
            hdf[f"Geometry/2D Flow Areas/{MESH}/{name}"] = values
    return path


def outcome(backend, path, strict, **kwargs):
    """Comparable outcome of get_mesh_cell_polygons: normalized frame or exception."""
    import shapely
    from ras_commander.hdf.HdfMesh import HdfMesh
    try:
        frame = HdfMesh.get_mesh_cell_polygons(path, backend=backend, strict=strict, **kwargs)
    except Exception as exc:  # noqa: BLE001 - the exception is the outcome
        return ("raised", type(exc), str(exc))
    if frame.empty:
        rows = ()
    else:
        order = np.lexsort((frame.cell_id.to_numpy(), frame.mesh_name.to_numpy()))
        geometries = shapely.normalize(frame.geometry.to_numpy()[order])
        rows = tuple(zip(frame.mesh_name.to_numpy()[order].tolist(),
                         frame.cell_id.to_numpy()[order].astype("i8").tolist(),
                         shapely.to_wkb(geometries).tolist()))
    crs = frame.crs.to_wkt() if getattr(frame, "crs", None) is not None else None
    return ("returned", tuple(frame.columns), rows, crs, dict(frame.attrs))


@contextmanager
def python_polygonize_forbidden():
    """Fail loudly if a required-native call reaches the Python polygonizer."""
    import shapely.ops
    original = shapely.ops.polygonize
    def forbidden(*args, **kwargs):
        raise AssertionError("required native mesh polygons fell back to Python polygonize")
    shapely.ops.polygonize = forbidden
    try:
        yield
    finally:
        shapely.ops.polygonize = original


@pytest.fixture
def assemble_calls(monkeypatch):
    """Count calls into the extension's assemble_cells (when it is installed)."""
    calls = []
    try:
        import ras_commander_fast_hdf as module
    except (ImportError, OSError):
        return calls
    original = module.assemble_cells

    @wraps(original)
    def counted(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "assemble_cells", counted)
    return calls


def test_python_reference_schema_and_outcomes(tmp_path, adapter):
    """Pin the reference outcomes the native paths are held to."""
    from ras_commander.hdf.HdfMesh import MeshCellPolygonError
    path = write_hdf(tmp_path / "invalid.g01.hdf", "invalid")
    reference = outcome("python", path, strict=False)
    assert reference[0] == "returned" and reference[2] == ()
    diagnostics = reference[4]["cell_polygon_diagnostics"]
    assert len(diagnostics) == 1
    record = diagnostics[0]
    assert set(record) == REFERENCE_KEYS
    assert (record["mesh_name"], record["cell_id"], record["status"]) == (MESH, 0, "omitted")
    assert record["reason_code"] == "no_polygon" and record["face_ids"] == (0, 1, 2, 3)
    strict = outcome("python", path, strict=True)
    assert strict[0] == "raised" and strict[1] is MeshCellPolygonError


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("case", CASES)
def test_auto_returns_exactly_the_python_outcome(tmp_path, adapter, monkeypatch, assemble_calls,
                                                 case, strict):
    path = write_hdf(tmp_path / f"{case}.g01.hdf", case)
    reference = outcome("python", path, strict=strict)
    assert not assemble_calls, "python backend must not call the extension"
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
    actual = outcome("auto", path, strict=strict)
    assert actual == reference
    if adapter.available():
        assert assemble_calls, "auto mode with the extension installed must try native first"


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("case", CASES)
def test_env_default_backend_follows_policy(tmp_path, adapter, case, strict):
    """backend="auto" honours RAS_COMMANDER_FAST_HDF as set for this run."""
    path = write_hdf(tmp_path / f"{case}.g01.hdf", case)
    policy = adapter._mode("auto")
    actual = outcome("auto", path, strict=strict)
    expected = outcome("rust" if policy == "rust" else "python", path, strict=strict)
    assert actual == expected


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("case", ["valid", "invalid", "grid_bowties"])
def test_required_native_matches_reference_without_fallback(
        tmp_path, native_adapter, assemble_calls, case, strict):
    from ras_commander.hdf.HdfMesh import MeshCellPolygonError
    path = write_hdf(tmp_path / f"{case}.g01.hdf", case)
    reference = outcome("python", path, strict=strict)
    with python_polygonize_forbidden():
        actual = outcome("rust", path, strict=strict)
    assert assemble_calls and all(call.get("strict") is strict for call in assemble_calls)
    if case != "valid" and strict:
        # Strict native assembly fails on the first invalid source cell with the
        # documented strict error, naming the original cell identity.
        assert actual[0] == "raised" and actual[1] is MeshCellPolygonError, actual
        first = 0 if case == "invalid" else 3
        assert f"cell {first}:" in actual[2]
        return
    assert actual[0] == "returned", actual
    assert actual == reference
    for record in actual[4]["cell_polygon_diagnostics"]:
        # Native detail is logged at debug only; records keep the reference schema.
        assert set(record) == REFERENCE_KEYS


@pytest.mark.parametrize("strict", [False, True])
def test_required_native_late_corruption_raises(tmp_path, native_adapter, assemble_calls, strict):
    from ras_commander.fast_hdf import FastHdfError
    from ras_commander.hdf.HdfMesh import MeshCellPolygonError
    path = write_hdf(tmp_path / "corrupt.g01.hdf", "corrupt_late")
    # Python quarantines the corrupt span; required native must refuse instead.
    reference = outcome("python", path, strict=False)
    assert reference[0] == "returned"
    assert [r["reason_code"] for r in reference[4]["cell_polygon_diagnostics"]] == [
        "no_polygon", "invalid_face_span"]
    # Non-strict: FastHdfError. Strict: every TopologyError (structural ones
    # included) is reported as the documented strict MeshCellPolygonError.
    from ras_commander.hdf.HdfMesh import HdfMesh
    expected = MeshCellPolygonError if strict else FastHdfError
    with python_polygonize_forbidden(), pytest.raises(expected, match="cell 1") as info:
        HdfMesh.get_mesh_cell_polygons(path, backend="rust", strict=strict)
    assert getattr(info.value.__cause__, "mesh_structure_error", None) is True
    assert assemble_calls


def test_required_mode_without_extension_raises(tmp_path, adapter, monkeypatch):
    from ras_commander.fast_hdf import FastHdfError
    path = write_hdf(tmp_path / "valid.g01.hdf", "valid")
    monkeypatch.setattr(adapter, "_native_state",
                        (None, "The optional ras-commander-fast-hdf extension is unavailable", None))
    from ras_commander.hdf.HdfMesh import HdfMesh
    with pytest.raises(FastHdfError, match="unavailable"):
        HdfMesh.get_mesh_cell_polygons(path, backend="rust", strict=False)
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
    assert outcome("auto", path, strict=False) == outcome("python", path, strict=False)


@pytest.mark.parametrize("case", CASES)
def test_python_mode_never_touches_native(tmp_path, adapter, monkeypatch, case):
    path = write_hdf(tmp_path / f"{case}.g01.hdf", case)
    expected = outcome("python", path, strict=False)
    def forbidden():
        raise AssertionError("python mode loaded the native extension")
    monkeypatch.setattr(adapter, "_load_native", forbidden)
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "0")
    assert outcome("auto", path, strict=False) == expected
    assert outcome("python", path, strict=False) == expected
