"""Max shear stress through the Rust sloping engine (``rasmapper-face-shear-max/1``).

Unit tests use a simulated engine method record and synthetic HDF files; no
engine or HEC-RAS runs. Real-model qualification is opt-in: set
RAS_COMMANDER_FIM_SHEAR_CASE to a JSON document with ``hdf``, ``terrain``,
``engine``, optional ``terrain_hdf``, ``shear_depth`` and ``reference`` (RAS
Mapper's ``Shear Stress (Max)`` GeoTIFF on the same terrain grid).
"""

import inspect
import json
import os
from pathlib import Path

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")
rasterio = pytest.importorskip("rasterio")

from ras_commander.fim import RasFim, _engine, _shear  # noqa: E402
from ras_commander.fim.errors import FimUnsupportedError  # noqa: E402


def _tif(path, width=40, height=30):
    from rasterio.transform import from_origin

    with rasterio.open(
        path, "w", driver="GTiff", width=width, height=height, count=1, dtype="float32",
        crs="EPSG:26915", transform=from_origin(0, height, 1, 1), nodata=-9999,
    ) as dst:
        dst.write(np.zeros((1, height, width), dtype="float32"))
    return path


@pytest.fixture
def model_files(tmp_path, monkeypatch):
    hdf = tmp_path / "m.p01.hdf"
    with h5py.File(hdf, "w") as handle:
        handle.attrs["Units System"] = np.bytes_("US Customary")
    tif = _tif(tmp_path / "t.tif")
    scope = {"storage_areas": 0}
    monkeypatch.setattr(RasFim, "validate_2d_model", staticmethod(lambda *a, **k: dict(scope)))
    monkeypatch.setattr(_engine, "find_engine", lambda path=None: Path(tmp_path / "engine.exe"))
    return hdf, tif, scope


def _method(**extra):
    return {"sloping": {"method_id": "rasmapper-plain-sloping/1", "stream_outputs": True, **extra}}


@pytest.mark.parametrize(
    "kwargs, error, message",
    [
        (dict(shear_stress=1), ValueError, "boolean"),
        (dict(shear_stress=True, shear_depth="max"), ValueError, "shear_depth"),
        (dict(shear_depth="horizontal"), ValueError, "requires shear_stress"),
        (dict(shear_stress=True, render_mode="slopingPretty"), FimUnsupportedError, "plain sloping"),
        (dict(shear_stress=True, profiles={"t3": 3}), FimUnsupportedError, "Max only"),
        (dict(shear_stress=True, profiles={"a": "Max", "b": "Max"}), FimUnsupportedError, "Max only"),
        (dict(shear_stress=True, profiles={"a": "Max", "t": 2}), FimUnsupportedError, "Max only"),
        (dict(shear_stress=True, template_raster="x.tif"), FimUnsupportedError, "template"),
        (dict(shear_stress=True, storage_areas=True), FimUnsupportedError, "storage areas"),
    ],
)
def test_shear_refusals_precede_reads(model_files, tmp_path, kwargs, error, message):
    hdf, tif, _ = model_files
    with pytest.raises(error, match=message):
        RasFim.map_sloping_profiles(hdf, tif, tmp_path / "out", **kwargs)
    assert not (tmp_path / "out").exists()


def test_shear_refuses_supplied_profiles(model_files, tmp_path):
    import pandas as pd

    hdf, tif, _ = model_files
    with pytest.raises(FimUnsupportedError, match="stored time series"):
        RasFim.map_sloping_profiles(hdf, tif, tmp_path / "a", shear_stress=True,
                                    wsel_profiles=pd.DataFrame())


def test_shear_refuses_storage_area_plans(model_files, tmp_path, monkeypatch):
    hdf, tif, scope = model_files
    scope["storage_areas"] = 1
    monkeypatch.setattr(_engine, "engine_method", lambda engine: _method(shear_stress=_shear.METHOD_ID))
    with pytest.raises(FimUnsupportedError, match="storage areas"):
        RasFim.map_sloping_profiles(hdf, tif, tmp_path / "a", shear_stress=True)
    assert not (tmp_path / "a").exists()


def test_engine_capability_gates_shear(model_files, tmp_path, monkeypatch):
    hdf, tif, _ = model_files
    monkeypatch.setattr(_engine, "engine_method", lambda engine: _method())
    with pytest.raises(FimUnsupportedError, match=_shear.METHOD_ID):
        RasFim.map_sloping_profiles(hdf, tif, tmp_path / "a", shear_stress=True)
    monkeypatch.setattr(_engine, "engine_method", lambda engine: _method(
        shear_stress=_shear.METHOD_ID, shear_stress_depth=["rendered"]))
    with pytest.raises(FimUnsupportedError, match="shear_stress_depth"):
        RasFim.map_sloping_profiles(hdf, tif, tmp_path / "b", shear_stress=True,
                                    shear_depth="horizontal")
    assert not any((tmp_path / n).exists() for n in "ab")


def test_supports_shear_stress(monkeypatch):
    from types import SimpleNamespace

    def capabilities(flags):
        return SimpleNamespace(methods={"sloping": SimpleNamespace(flags=flags)})

    monkeypatch.setattr(RasFim, "get_capabilities",
                        staticmethod(lambda path=None: capabilities({"shear_stress": _shear.METHOD_ID})))
    assert RasFim.supports_shear_stress() is True
    monkeypatch.setattr(RasFim, "get_capabilities", staticmethod(lambda path=None: capabilities({})))
    assert RasFim.supports_shear_stress() is False

    def missing(path=None):
        raise FileNotFoundError("no engine")

    monkeypatch.setattr(RasFim, "get_capabilities", staticmethod(missing))
    assert RasFim.supports_shear_stress() is False
    assert RasFim.SHEAR_STRESS_METHOD == _shear.METHOD_ID


def test_units_follow_the_plan(tmp_path):
    for units in _shear.UNITS:
        path = tmp_path / f"{units[:2]}.hdf"
        with h5py.File(path, "w") as handle:
            handle.attrs["Units System"] = np.bytes_(units)
        assert _shear.units(path) == units
    with h5py.File(tmp_path / "x.hdf", "w"):
        pass
    with pytest.raises(FimUnsupportedError, match="unit system"):
        _shear.units(tmp_path / "x.hdf")


def _plan(path, *, empty_table=False, velocity_times=3):
    geometry = "Geometry/2D Flow Areas/A/"
    series = _shear._SERIES + "/A/"
    with h5py.File(path, "w") as h:
        h.attrs["Units System"] = np.bytes_("SI Units")
        h[geometry + "Faces NormalUnitVector and Length"] = np.array(
            [[1, 0, 2], [0, 1, 3]], dtype="f4")
        h[geometry + "FacePoints Coordinate"] = np.array([[0, 0], [2, 0], [2, 3]], dtype="f8")
        h[geometry + "Faces FacePoint Indexes"] = np.array([[0, 1], [1, 2]], dtype="i4")
        h[geometry + "Faces Perimeter Info"] = np.zeros((2, 2), dtype="i4")
        h[geometry + "Faces Perimeter Values"] = np.zeros((0, 2), dtype="f8")
        h[geometry + "Faces Area Elevation Info"] = np.array(
            [[0, 2], [2, 0 if empty_table else 1]], dtype="i4")
        h[geometry + "Faces Area Elevation Values"] = np.array(
            [[1, 0, 0, 0.03], [2, 4, 5, 0.04], [0, 0, 0, 0.05]], dtype="f4")
        base = _shear._SERIES.rsplit("/", 1)[0]
        h[base + "/Time"] = np.arange(3, dtype="f8")
        h[base + "/Time Date Stamp"] = np.array(
            [b"01JAN2000 00:00:00", b"02JAN2000 00:00:00", b"03JAN2000 00:00:00"])
        h[series + "Water Surface"] = np.arange(12, dtype="f4").reshape(3, 4)
        h[series + "Face Velocity"] = np.arange(velocity_times * 2, dtype="f4").reshape(velocity_times, 2)
    return path


def test_stage_writes_tables_and_series_in_hdf_order(tmp_path):
    hdf = _plan(tmp_path / "p.hdf")
    root = tmp_path / "stage"
    root.mkdir()
    fields = _shear.stage(hdf, root, [{"mesh_name": "A", "cell_count": 4}],
                          shear_depth="horizontal", chunk_bytes=16)
    block = fields["shear_stress"]
    assert block["units"] == "SI Units" and block["depth"] == "horizontal"
    (mesh,) = block["meshes"]
    assert mesh["times"] == 3 and mesh["table_rows"] == 3
    normals = np.fromfile(root / mesh["normals_file"], dtype="<f4").reshape(-1, 3)
    np.testing.assert_array_equal(normals, [[1, 0, 2], [0, 1, 3]])
    np.testing.assert_array_equal(
        np.fromfile(root / mesh["tables_info_file"], dtype="<i4").reshape(-1, 2), [[0, 2], [2, 1]])
    np.testing.assert_array_equal(
        np.fromfile(root / mesh["tables_values_file"], dtype="<f4").reshape(-1, 4)[1],
        np.array([2, 4, 5, 0.04], dtype="f4"))
    np.testing.assert_array_equal(
        np.fromfile(root / mesh["water_surface_file"], dtype="<f4"), np.arange(12, dtype="f4"))
    np.testing.assert_array_equal(
        np.fromfile(root / mesh["face_velocity_file"], dtype="<f4"), np.arange(6, dtype="f4"))
    assert not list(root.glob("*.partial"))


def test_stage_refuses_empty_tables_and_mismatched_series(tmp_path):
    root = tmp_path / "stage"
    root.mkdir()
    meshes = [{"mesh_name": "A", "cell_count": 4}]
    with pytest.raises(FimUnsupportedError, match="Faces Area Elevation table"):
        _shear.stage(_plan(tmp_path / "a.hdf", empty_table=True), root, meshes)
    # A series that disagrees with the plan's time axis never reaches the engine.
    from ras_commander.fast_hdf import FastHdfError

    with pytest.raises((FimUnsupportedError, FastHdfError)):
        _shear.stage(_plan(tmp_path / "b.hdf", velocity_times=2), root, meshes)
    with pytest.raises(FimUnsupportedError, match="dimensions"):
        _shear.stage(_plan(tmp_path / "c.hdf"), root, [{"mesh_name": "A", "cell_count": 5}])
    with pytest.raises(ValueError, match="shear_depth"):
        _shear.stage(_plan(tmp_path / "d.hdf"), root, meshes, shear_depth="max")


def test_manifest_and_signature():
    from ras_commander.schemas import DATAFRAME_SCHEMAS

    assert "shear_stress_tif" in RasFim.MANIFEST_COLUMNS
    declared = [c["name"] for c in DATAFRAME_SCHEMAS["fim_product_manifest"]["columns"]]
    assert declared == list(RasFim.MANIFEST_COLUMNS)
    parameters = inspect.signature(RasFim.map_sloping_profiles).parameters
    assert parameters["shear_stress"].default is False
    assert parameters["shear_depth"].default == "rendered"
    assert isinstance(RasFim.__dict__["supports_shear_stress"], staticmethod)
    assert _shear.shear_path(Path("o"), "Max") == Path("o") / "15_Max_shear_stress.tif"


# ---------------------------------------------------------------------------
# Opt-in real-model qualification against RAS Mapper's Shear Stress (Max).
# ---------------------------------------------------------------------------

@pytest.fixture
def shear_case():
    filename = os.environ.get("RAS_COMMANDER_FIM_SHEAR_CASE")
    if not filename:
        pytest.skip("set RAS_COMMANDER_FIM_SHEAR_CASE for real native qualification")
    return json.loads(Path(filename).read_text(encoding="utf-8"))


def test_real_shear_matches_native(shear_case, tmp_path):
    from rasterio.windows import from_bounds

    frame = RasFim.map_sloping_profiles(
        shear_case["hdf"], shear_case["terrain"], tmp_path / "out",
        engine_path=shear_case["engine"], terrain_hdf=shear_case.get("terrain_hdf"),
        shear_stress=True, shear_depth=shear_case.get("shear_depth", "rendered"),
        threads=4, max_working_mib=4096,
    )
    with rasterio.open(frame.loc[0, "shear_stress_tif"]) as ours, \
            rasterio.open(shear_case["reference"]) as ref:
        window = from_bounds(*ours.bounds, transform=ref.transform)
        reference = ref.read(1, window=window, boundless=True, fill_value=ref.nodata)
        mine = ours.read(1)
        ref_valid = reference != ref.nodata
        my_valid = np.isfinite(mine)
        assert ref_valid.sum() > 0
        assert (ref_valid != my_valid).sum() == 0
        assert np.array_equal(mine[my_valid].view("u4"), reference[ref_valid].astype("f4").view("u4"))

