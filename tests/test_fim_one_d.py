"""Synthetic file-format tests for canonical 1D staging, no native runtime."""
import json
from pathlib import Path

import h5py
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from ras_commander.fim import RasFim, FimPreparedOneDModel, FimUnsupportedError
from ras_commander.fim._one_d import canonical_arrays, normalize_segment, render_ranks, station_m


def inputs():
    attrs = np.zeros(2, dtype=[("River", "S8"), ("Reach", "S8"), ("RS", "S8"), ("Left Bank", "f8"), ("Right Bank", "f8")] +
                     [(side+" Levee "+v, "f8") for side in ("Left", "Right") for v in ("Sta", "Elev")])
    attrs["River"] = b"Main"
    attrs["Left Bank"], attrs["Right Bank"] = 20, 80
    for side in ("Left", "Right"):
        attrs[side+" Levee Sta"] = np.nan
        attrs[side+" Levee Elev"] = np.nan
    points = np.array([[x, y, z, m] for y, z in ((100., 1.), (0., 0.))
                       for x, m in ((0., -1.), (20., 0.), (100., 1.))])
    return {"Attributes": attrs, "TIN Points": points, "TIN Triangles": np.array([[0, 1, 3], [1, 4, 3], [1, 2, 4], [2, 5, 4]]),
            "TIN Info": np.array([[0, 6, 0, 4]]), "XSIDs": np.array([[0, 1]]),
            "Station Elevation Info": np.array([[0, 2], [2, 2]]),
            "Station Elevation Values": np.array([[0., 0.], [100., 0.]]*2),
            "Polyline Info": np.array([[0, 2, 0, 1], [2, 2, 1, 1]]),
            "Polyline Parts": np.array([[0, 2], [0, 2]]),
            "Polyline Points": np.array([[0., 100.], [100., 100.], [0., 0.], [100., 0.]])}


@pytest.fixture
def files(tmp_path):
    hdf = tmp_path / "model.p01.hdf"
    data = inputs()
    with h5py.File(hdf, "w") as f:
        f.attrs["Units System"] = "US Customary"
        f.attrs["Projection"] = rasterio.crs.CRS.from_epsg(6588).to_wkt()
        f.create_group("Geometry").attrs["SI Units"] = False
        for name, value in data.items():
            base = "Geometry/Cross Section Interpolation Surfaces/" if name.startswith("TIN") or name == "XSIDs" else "Geometry/Cross Sections/"
            f.create_dataset(base+name, data=value)
        base = "Results/Unsteady/Output/Output Blocks/Base Output/"
        result_attrs = np.zeros(2, dtype=[("River", "S8"), ("Reach", "S8"), ("Station", "S8")])
        result_attrs["River"] = b"Main"
        f.create_dataset(base+"Unsteady Time Series/Cross Sections/Cross Section Attributes", data=result_attrs)
        f.create_dataset(base+"Summary Output/Cross Sections/Maximum Water Surface", data=[[10., 20.]])
        f.create_dataset(base+"Unsteady Time Series/Cross Sections/Water Surface", data=[[5., 10.], [10., 20.]])
    terrain = tmp_path / "terrain.tif"
    with rasterio.open(terrain, "w", driver="GTiff", width=512, height=512, count=1, dtype="float32",
                       crs="EPSG:6588", transform=from_origin(0, 256, 1, 1), tiled=True, blockxsize=256, blockysize=256) as dst:
        dst.write(np.zeros((512, 512), dtype="float32"), 1)
    return hdf, terrain


def test_normalized_m_and_no_mutation():
    d = inputs()
    original = d["TIN Points"].copy()
    a, receipts, offsets = canonical_arrays(d)
    np.testing.assert_array_equal(d["TIN Points"], original)
    assert a["normalized_m"][1] != 0
    assert offsets[0]["offsets"] == pytest.approx([-0.6, -0.6])
    assert len(receipts) == 2
    assert station_m(50, 0, 100, 20, 80) == 0
    assert station_m(-1, 0, 100, 20, 80) == -2


def test_native_end_selection_not_profile_inequality():
    d = inputs()
    d["Obstruction Info"] = np.array([[0, 1], [1, 0]])
    d["Obstruction Blocks"] = np.array([(0., 30., 20.)], dtype=[("Left Sta", "f8"), ("Right Sta", "f8"), ("Elevation", "f8")])
    a, r, _ = canonical_arrays(d)
    assert r[0]["selected_left"] == 0
    assert a["xs_clip"][0, 4] == station_m(30, 0, 100, 20, 80)
    d["Obstruction Blocks"]["Left Sta"] = -10
    _, receipt, _ = canonical_arrays(d)
    assert receipt[0]["selected_left"] is None
    assert "ignored" in receipt[0]["ordered_blocks"][0]["selection"]


def test_render_order():
    ids = np.array([[0, 2], [1, 2], [2, 3]])
    assert render_ranks(ids, ["Trib", "Main", "Main", "Main"]).tolist() == [1, 0, 2]


def test_degenerate_refusal():
    d = inputs()
    d["TIN Triangles"][0] = [0, 0, 1]
    with pytest.raises(FimUnsupportedError, match="degenerate"):
        canonical_arrays(d)


def test_prepare_receipt_and_default_gate(files, tmp_path):
    hdf, terrain = files
    target = tmp_path / "prepared"
    with pytest.raises(FimUnsupportedError, match="unqualified"):
        RasFim.prepare_one_d_model(hdf, terrain, target)
    assert not target.exists()
    prepared = RasFim.prepare_one_d_model(str(hdf), str(terrain), target, profiles=[1, "Max", 1], allow_unqualified=True, max_working_mib=64)
    assert isinstance(prepared, FimPreparedOneDModel)
    r = prepared.validate()
    assert r["profiles"] == [1, "Max", 1]
    assert r["qualified"] is False
    assert r["normalized_changed_points"] == 2
    Path(r["files"]["normalized_m"]).write_bytes(b"changed")
    with pytest.raises(FimUnsupportedError, match="changed"):
        prepared.validate()


@pytest.mark.parametrize("feature", ["Geometry/Blocked Obstructions", "Plan Data/Fixed Encroachments", "Geometry/Storage Areas/Attributes", "Geometry/2D Flow Areas/Attributes"])
def test_unsupported_before_writes(files, tmp_path, feature):
    hdf, terrain = files
    with h5py.File(hdf, "a") as f:
        f.create_dataset(feature, data=[1])
    with pytest.raises(FimUnsupportedError, match="unsupported"):
        RasFim.prepare_one_d_model(hdf, terrain, tmp_path / "out", allow_unqualified=True)
    assert not (tmp_path / "out").exists()


def test_real_engine_synthetic_mapping(files, tmp_path):
    import os
    engine = os.environ.get("RAS_COMMANDER_FIM_ENGINE")
    if not engine:
        pytest.skip("explicit opt-in engine")
    hdf, terrain = files
    result = RasFim.map_one_d_profiles(hdf, terrain, tmp_path / "map", profiles=["Max", 0],
                                      bbox=(0, 0, 100, 100), allow_unqualified=True,
                                      threads=4, max_working_mib=64, engine_path=engine)
    assert result.status.tolist() == ["complete", "complete"]
    assert result.attrs["qualified"] is False
    assert isinstance(result.iloc[0]["transform"], tuple)
    assert result.iloc[0].depth_finite_pixels > 0
    document = json.loads((tmp_path / "map" / "fim_manifest.json").read_text())
    assert document["schema"] == "ras-commander-fim-manifest/1"
    assert document["request_schema"] == "fast-map-one-d-diagnostic/3"
    assert document["profiles"][0]["profile"] == result.iloc[0].profile
    assert document["engine"]["package"] == "ras-commander-fast-map"
    with rasterio.open(result.iloc[0].wse_tif) as src:
        values = src.read(1)
        assert values.shape == (100, 100)
        assert np.isfinite(values).any()




def test_batched_workers_match_sequential_single_profile_bits(files, tmp_path, monkeypatch):
    """Multi-profile engine calls and render workers never change product pixels."""
    import os
    from ras_commander.fim import _one_d
    engine = os.environ.get("RAS_COMMANDER_FIM_ENGINE")
    if not engine:
        pytest.skip("explicit opt-in engine")
    flags = RasFim.get_capabilities(engine).methods["one_d_clipped_diagnostic"].flags
    if _one_d._xs_batch_limit(flags) < 2 or not flags.get("render_workers"):
        pytest.skip("engine lacks multi_profile/render_workers")
    hdf, terrain = files
    kwargs = dict(profiles=["Max", 0, 1], allow_unqualified=True, max_working_mib=64, engine_path=engine)
    batched = RasFim.map_one_d_profiles(hdf, terrain, tmp_path / "batched", threads=4, **kwargs)
    assert batched.attrs["xs_render_workers"] > 1
    assert batched.attrs["xs_profiles_per_request"] > 1
    monkeypatch.setattr(_one_d, "_xs_batch_limit", lambda flags: 1)
    monkeypatch.setattr(_one_d, "_xs_render_workers", lambda *args: 1)
    single = RasFim.map_one_d_profiles(hdf, terrain, tmp_path / "single", threads=1, **kwargs)
    assert single.attrs["xs_render_workers"] == 1
    for a, b in zip(batched.itertuples(), single.itertuples()):
        assert a.status == b.status == "complete"
        for column in ("depth_tif", "wse_tif"):
            with rasterio.open(getattr(a, column)) as x, rasterio.open(getattr(b, column)) as y:
                assert x.transform == y.transform and x.crs == y.crs
                np.testing.assert_array_equal(x.read(1).view("<u4"), y.read(1).view("<u4"))


def test_xs_worker_and_batch_flags_are_parsed_conservatively():
    from ras_commander.fim._one_d import _xs_batch_limit, _xs_render_workers
    receipt, grid = {"triangle_count": 1000}, {"tile_size": 256}
    workers = {"render_workers": {"control": "threads", "max": 64}}
    assert _xs_batch_limit({}) == 1
    assert _xs_batch_limit({"multi_profile": {"control": "levels_files", "max": 256}}) == 256
    assert _xs_batch_limit({"multi_profile": {"control": "other", "max": 256}}) == 1
    assert _xs_batch_limit({"multi_profile": {"control": "levels_files", "max": True}}) == 1
    assert _xs_render_workers({}, 8, 10**9, receipt, grid, 0) == 1
    assert _xs_render_workers(workers, 8, 10**9, receipt, grid, 0) == 8
    assert _xs_render_workers({"render_workers": {"control": "threads", "max": 2}}, 8, 10**9, receipt, grid, 0) == 2
    scratch = 256 * 256 + 1000 * 8
    assert _xs_render_workers(workers, 8, 100 + 2 * scratch, receipt, grid, 100) == 3
    assert _xs_render_workers(workers, 8, 100, receipt, grid, 100) == 1

def test_crs_identity_refused_before_writes(files, tmp_path):
    hdf, terrain = files
    with rasterio.open(terrain, 'r+') as dst:
        dst.crs = 'EPSG:2278'
    with pytest.raises(FimUnsupportedError, match='CRS differ'):
        RasFim.prepare_one_d_model(hdf, terrain, tmp_path / 'out', allow_unqualified=True)
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize("shift", [0, 1.25])
def test_bound_source_crs_prepares_and_preserves_unapplied_binding(files, tmp_path, shift):
    from ras_commander.fim._one_d import digest
    from pyproj import CRS
    from pyproj.crs import BoundCRS
    from pyproj.crs.coordinate_operation import ToWGS84Transformation
    projected = CRS.from_epsg(6588)
    bound = BoundCRS(source_crs=projected, target_crs=CRS.from_epsg(4326),
        transformation=ToWGS84Transformation(projected.geodetic_crs,
            x_axis_translation=shift, y_axis_translation=2 * shift, z_axis_translation=3 * shift))
    with h5py.File(files[0], "a") as hdf:
        hdf.attrs["Projection"] = bound.to_wkt()
    source_sha = digest(files[0])
    terrain_sha = digest(files[1])
    prepared = RasFim.prepare_one_d_model(*files, tmp_path / "prepared", profiles={"max": "Max"},
        allow_unqualified=True, max_working_mib=64)
    receipt = prepared.validate()
    assert receipt["schema"] == "ras-commander-one-d-preparation/1" and receipt["qualified"] is False
    assert CRS.from_wkt(receipt["grid"]["crs"]) == projected
    provenance = receipt["crs_provenance"]
    assert provenance["policy"] == "bound-source-identity/1"
    assert CRS.from_wkt(provenance["model"]["original_wkt"]) == bound
    assert provenance["model"]["binding_operation"] == CRS.from_wkt(bound.to_wkt()).coordinate_operation.to_json_dict()
    assert provenance["terrain"]["is_bound"] is False
    assert receipt["sha256"][str(files[0])] == source_sha
    assert receipt["sha256"][str(files[1])] == terrain_sha


@pytest.mark.parametrize("datum", [2278, 6587])
def test_bound_model_still_refuses_different_terrain_datum_or_units(files, tmp_path, datum):
    from pyproj import CRS
    from pyproj.crs import BoundCRS
    from pyproj.crs.coordinate_operation import ToWGS84Transformation
    projected = CRS.from_epsg(6588)
    bound = BoundCRS(source_crs=projected, target_crs=CRS.from_epsg(4326),
        transformation=ToWGS84Transformation(projected.geodetic_crs, x_axis_translation=1))
    with h5py.File(files[0], "a") as hdf:
        hdf.attrs["Projection"] = bound.to_wkt()
    with rasterio.open(files[1], "r+") as terrain:
        terrain.crs = CRS.from_epsg(datum)
    with pytest.raises(FimUnsupportedError, match="CRS differ"):
        RasFim.prepare_one_d_model(*files, tmp_path / "prepared", allow_unqualified=True)
    assert not (tmp_path / "prepared").exists()


def test_bad_result_order_before_writes(files, tmp_path):
    hdf, terrain = files
    with h5py.File(hdf, 'a') as f:
        ds = f['Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Cross Sections/Cross Section Attributes']
        rows = ds[:]
        rows['River'][0] = b'Other'
        ds[:] = rows
    with pytest.raises(FimUnsupportedError, match='identity/order'):
        RasFim.prepare_one_d_model(hdf, terrain, tmp_path / 'out', allow_unqualified=True)
    assert not (tmp_path / 'out').exists()


def test_source_immutability(files, tmp_path):
    from ras_commander.fim._one_d import digest
    hdf, terrain = files
    before = [digest(hdf), digest(terrain)]
    prepared = RasFim.prepare_one_d_model(hdf, terrain, tmp_path / 'out', allow_unqualified=True)
    assert before == [digest(hdf), digest(terrain)]
    with hdf.open('ab') as stream:
        stream.write(b'changed')
    with pytest.raises(FimUnsupportedError, match='changed'):
        prepared.validate()


def test_input_budget_before_payload_reads(files):
    from ras_commander import HdfXsec
    with pytest.raises(ValueError, match='admission'):
        HdfXsec.get_one_d_mapping_inputs(files[0], max_bytes=1)


def test_digest_without_python311_file_digest(tmp_path, monkeypatch):
    import hashlib
    from ras_commander.fim._one_d import digest
    monkeypatch.delattr(hashlib, "file_digest", raising=False)
    path = tmp_path / "payload"
    path.write_bytes(b"test" * 400000)
    assert digest(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_named_profile_selection_and_prepared_mapping(files, tmp_path, monkeypatch):
    from ras_commander.fim import _one_d
    prepared = RasFim.prepare_one_d_model(*files, tmp_path / "prepared",
                                         profiles={"peak": "Max", "early": 0}, allow_unqualified=True)
    assert prepared.validate()["profiles"] == ["Max", 0]
    assert prepared.validate()["profile_ids"] == ["peak", "early"]
    _fake_engine(monkeypatch, tmp_path)
    result = prepared.map_profiles(tmp_path / "mapped", profiles=["early", "peak"],
                                   bbox=(0, 0, 10, 10), allow_unqualified=True)
    assert result.profile.tolist() == ["early", "peak"]
    assert result.status.tolist() == ["complete", "complete"]


def test_native_float32_station_threshold_and_full_width_left_precedence():
    data = inputs()
    data["Obstruction Info"] = np.array([[0, 1], [1, 0]])
    data["Obstruction Blocks"] = np.array([(0.0100000001, 100., 20.)],
        dtype=[("Left Sta", "f8"), ("Right Sta", "f8"), ("Elevation", "f8")])
    _, receipt, _ = canonical_arrays(data)
    assert receipt[0]["selected_left"] == 0
    assert receipt[0]["selected_right"] is None
    assert receipt[0]["ordered_blocks"][0]["left"] > .01
    assert receipt[0]["ordered_blocks"][0]["native_left"] < .01


@pytest.mark.parametrize("mutate", [
    lambda r: r["grid"].update(crs="EPSG:2278"),
    lambda r: r.update(point_count=r["point_count"] + 1),
    lambda r: r["sha256"].pop(r["files"]["points"]),
    lambda r: r["levels"].pop(),
    lambda r: r["crs_provenance"]["model"].update(binding_operation={"changed": True}),
])
def test_prepared_receipt_tampering_refused(files, tmp_path, mutate):
    prepared = RasFim.prepare_one_d_model(*files, tmp_path / "prepared", allow_unqualified=True)
    path = prepared.folder / "one_d_preparation.json"
    receipt = prepared.receipt
    mutate(receipt)
    path.write_text(json.dumps(receipt))
    with pytest.raises(FimUnsupportedError, match="receipt changed"):
        prepared.validate()


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(schema="incorrect/1"),
    lambda r: r["grid"].update(crs="EPSG:2278"),
    lambda r: r["grid"].update(width=r["grid"]["width"] + 1),
    lambda r: r["grid"]["geo_transform"].__setitem__(0, 10.0),
    lambda r: r["units"].update(unit_system="SI"),
    lambda r: r.update(point_count=r["point_count"] + 1),
    lambda r: r["sha256"].pop(r["files"]["points"]),
    lambda r: r["levels"].pop(),
])
def test_reconstructed_receipt_requires_complete_hash_and_shape_bindings(files, tmp_path, mutate):
    prepared = RasFim.prepare_one_d_model(*files, tmp_path / "prepared", allow_unqualified=True)
    receipt = prepared.receipt
    mutate(receipt)
    (prepared.folder / "one_d_preparation.json").write_text(json.dumps(receipt))
    reconstructed = FimPreparedOneDModel(prepared.folder)
    with pytest.raises(FimUnsupportedError):
        reconstructed.validate()


def test_legacy_receipt_without_optional_crs_provenance_still_validates(files, tmp_path):
    prepared = RasFim.prepare_one_d_model(*files, tmp_path / "prepared", allow_unqualified=True)
    receipt = prepared.receipt
    receipt.pop("crs_provenance")
    (prepared.folder / "one_d_preparation.json").write_text(json.dumps(receipt))
    assert FimPreparedOneDModel(prepared.folder).validate()["qualified"] is False


def _fake_engine(monkeypatch, tmp_path, mutation=None):
    import subprocess
    from ras_commander.fim import _engine, _one_d
    engine = tmp_path / "fake-engine.exe"
    engine.write_bytes(b"immutable engine")
    monkeypatch.setattr(_engine, "find_engine", lambda path=None: engine)
    monkeypatch.setattr(_engine, "engine_method", lambda path: {"one_d_clipped_diagnostic": {"method_id": _one_d.METHOD_ID}})
    def run(args, what, timeout=None):
        request = json.loads(Path(args[2]).read_text())
        out = Path(args[3])
        out.mkdir()
        (out / "report.json").write_text(json.dumps({"status": "complete", "method": {"method_id": _one_d.METHOD_ID}}))
        window = request["window"]
        for product in ("depth", "wse"):
            np.ones(window["width"] * window["height"], dtype="<f4").tofile(out / (product + ".bin"))
        if mutation:
            mutation(engine)
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(_engine, "run_engine", run)
    return engine


@pytest.mark.parametrize("kind", ["source", "payload", "receipt", "engine"])
def test_changed_inputs_during_mapping_cannot_publish_success(files, tmp_path, monkeypatch, kind):
    from ras_commander.fim.errors import FimMappingError
    prepared = RasFim.prepare_one_d_model(*files, tmp_path / "prepared", allow_unqualified=True)
    receipt = prepared.receipt
    target = {"source": Path(receipt["source_hdf"]), "payload": Path(receipt["files"]["points"]),
              "receipt": prepared.folder / "one_d_preparation.json"}.get(kind)
    def change(engine):
        with (engine if kind == "engine" else target).open("ab") as stream:
            stream.write(b"changed")
    _fake_engine(monkeypatch, tmp_path, change)
    output = tmp_path / "mapped"
    with pytest.raises(FimMappingError) as error:
        prepared.map_profiles(output, bbox=(0, 0, 10, 10), allow_unqualified=True)
    assert error.value.manifest.status.tolist() == ["failed"]
    assert not list(output.glob("*.tif"))
    assert not list(output.glob("*.partial"))
    result = json.loads((output / "fim_manifest.json").read_text())
    assert result["status"] == "failed"
    assert result["profiles"][0]["depth_tif"] is None


def test_second_product_write_failure_is_atomic(files, tmp_path, monkeypatch):
    from ras_commander.fim.errors import FimMappingError
    prepared = RasFim.prepare_one_d_model(*files, tmp_path / "prepared", allow_unqualified=True)
    _fake_engine(monkeypatch, tmp_path)
    original = rasterio.open
    def open_raster(path, *args, **kwargs):
        if str(path).endswith("_wsel_nudge.tif.partial") and args and args[0] == "w":
            raise OSError("injected second-product failure")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(rasterio, "open", open_raster)
    output = tmp_path / "mapped"
    with pytest.raises(FimMappingError, match="second-product") as error:
        prepared.map_profiles(output, bbox=(0, 0, 10, 10), allow_unqualified=True)
    assert error.value.manifest.status.tolist() == ["failed"]
    assert not list(output.glob("*.tif"))
    assert not list(output.glob("*.partial"))
    assert json.loads((output / "fim_manifest.json").read_text())["status"] == "failed"


def test_integrity_failure_after_publication_removes_batch_products(files, tmp_path, monkeypatch):
    from ras_commander.fim.errors import FimMappingError
    prepared = RasFim.prepare_one_d_model(*files, tmp_path / "prepared", allow_unqualified=True)
    payload = Path(prepared.receipt["files"]["points"])
    _fake_engine(monkeypatch, tmp_path)
    original = FimPreparedOneDModel.validate
    calls = 0
    def validate(self):
        nonlocal calls
        calls += 1
        if calls == 3:
            with payload.open("ab") as stream:
                stream.write(b"changed after TIFF publication")
        return original(self)
    monkeypatch.setattr(FimPreparedOneDModel, "validate", validate)
    output = tmp_path / "mapped"
    with pytest.raises(FimMappingError, match="changed") as error:
        prepared.map_profiles(output, bbox=(0, 0, 10, 10), allow_unqualified=True)
    assert calls == 3
    assert error.value.manifest.status.tolist() == ["failed"]
    assert not list(output.glob("*.tif"))
    assert not list(output.glob("*.partial"))
    assert json.loads((output / "fim_manifest.json").read_text())["status"] == "failed"
