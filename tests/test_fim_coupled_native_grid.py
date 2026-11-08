"""Source/framing separation and transactional mixed-grid API contracts."""
import copy
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ras_commander.fim import RasFim, FimUnsupportedError, FimMappingError
from ras_commander.fim import _coupled, _native_grid, _engine
from test_fim_coupled import files, one_d_files, _prep_environment, _complete_engine  # noqa: F401


def _grid():
    # Synthetic two-tile grid whose rounded extent changes the scale.
    return dict(width=512, height=256, tile_size=256,
                geo_transform=[1000000., 1.1, 0., 10000000., 0., -1.1])


def test_rounded_extent_preserves_source_and_derives_output():
    grid = _grid()
    baseline = copy.deepcopy(grid)
    record = _native_grid.derive(grid)
    assert grid == baseline
    assert record["source_geo_transform"] == grid["geo_transform"]
    assert record["output_geo_transform"][1] != grid["geo_transform"][1]
    assert record["output_geo_transform"][1].hex() == "0x1.1999999999800p+0"
    assert _native_grid.validate(record, grid) == record


def test_last_partial_tile_keeps_full_logical_tile_size():
    grid = _grid()
    grid.update(width=256, height=257)
    record = _native_grid.derive(grid)
    assert record["source_height"] == 257 and record["tile_size"] == 256
    assert record["output_geo_transform"][1].hex() == "0x1.1999999999800p+0"


def test_exact_new_capabilities_are_accepted_without_engine_execution(tmp_path, monkeypatch):
    engine = tmp_path / "engine.exe"
    engine.write_bytes(b"synthetic executable identity")
    caps = _capabilities()
    monkeypatch.setattr(_engine, "find_engine", lambda _: engine)
    monkeypatch.setattr(RasFim, "get_capabilities", lambda _: caps)
    monkeypatch.setattr(_engine, "run_engine", lambda *a: pytest.fail("unexpected engine execution"))
    assert _coupled._require_engine(engine, _native_grid.CONTRACT) == (engine, caps)


@pytest.mark.parametrize("change", ["source", "output", "dimensions", "extra", "signed_zero"])
def test_descriptor_tampering_and_relabelling_refuse(change):
    grid = _grid()
    record = _native_grid.derive(grid)
    if change == "source":
        record["source_geo_transform"] = record["output_geo_transform"]
    elif change == "output":
        record["output_geo_transform"] = record["source_geo_transform"]
    elif change == "dimensions":
        record["source_width"] = True
    elif change == "signed_zero":
        record["source_geo_transform"][2] = -0.0
    else:
        record["unverified"] = 1
    with pytest.raises(FimUnsupportedError, match="descriptor differs"):
        _native_grid.validate(record, grid)


@pytest.mark.parametrize("change", ["overflow", "nan", "rotated", "nonsquare", "center_drift"])
def test_grid_admission_refuses_before_center_work(change):
    grid = _grid()
    if change == "overflow":
        grid["width"] = 2**63
    elif change == "nan":
        grid["geo_transform"][0] = math.nan
    elif change == "rotated":
        grid["geo_transform"][2] = 0.1
    elif change == "nonsquare":
        grid["geo_transform"][5] = -1.2
    elif change == "center_drift":
        grid.update(width=257, height=513, geo_transform=[0., .1, 0., 0., 0., -.1])
    with pytest.raises(FimUnsupportedError, match="unsupported native stored tile grid"):
        _native_grid.derive(grid)


@pytest.mark.parametrize("dimensions, message", [
    ((2**31, 1), "positive source dimensions"),
    ((65536, 65536), "bounded layout scope"),
])
def test_python_admission_matches_engine_dimension_and_work_limits(dimensions, message):
    grid = _grid()
    grid.update(width=dimensions[0], height=dimensions[1])
    with pytest.raises(FimUnsupportedError, match=message):
        _native_grid.derive(grid)


def _capabilities():
    contracts = _coupled._contracts(_native_grid.CONTRACT)
    methods = {}
    for key, method, schema in ((contracts["xs_key"], _coupled.XS_METHOD_ID, contracts["xs_schema"]),
                               (contracts["two_key"], contracts["two_method"], contracts["two_schema"]),
                               (contracts["key"], contracts["method"], contracts["schema"])):
        methods[key] = SimpleNamespace(method_id=method, request_schemas=(schema,),
            flags={"grid_contracts": (_native_grid.CONTRACT,), "native_parity_qualified": False,
                   "export_physical_ownership": True})
    return SimpleNamespace(methods=methods, raw_record={})


@pytest.mark.parametrize("breakage", ["missing_xs", "schema", "method", "grid_flag", "ownership"])
def test_exact_capability_admission_before_source_reads(tmp_path, monkeypatch, breakage):
    engine = tmp_path / "engine.exe"
    engine.write_bytes(b"synthetic executable identity")
    caps = _capabilities()
    if breakage == "missing_xs":
        caps.methods.pop("one_d_clipped_native_grid_diagnostic")
    elif breakage == "schema":
        caps.methods["sloping_native_grid"].request_schemas = ("ras-commander-sloping-request/1",)
    elif breakage == "method":
        caps.methods["sloping_native_grid"].method_id = _coupled.TWO_D_METHOD
    elif breakage == "grid_flag":
        caps.methods["coupled_native_grid_diagnostic"].flags["grid_contracts"] = _native_grid.CONTRACT
    else:
        caps.methods["sloping_native_grid"].flags["export_physical_ownership"] = False
    monkeypatch.setattr(_engine, "find_engine", lambda _: engine)
    monkeypatch.setattr(RasFim, "get_capabilities", lambda _: caps)
    with pytest.raises(FimUnsupportedError, match="contract|capability"):
        RasFim.prepare_coupled_model("missing.hdf", "missing.tif", tmp_path / "prep",
            allow_unqualified=True, grid_contract=_native_grid.CONTRACT)
    assert not (tmp_path / "prep").exists()


@pytest.mark.parametrize("value", [True, "unknown-grid/1", {}, 1])
def test_unknown_option_refuses_before_engine_or_folder(tmp_path, monkeypatch, value):
    monkeypatch.setattr(_coupled, "_require_engine", lambda *args: pytest.fail("engine lookup before option validation"))
    for method in (RasFim.prepare_coupled_model, RasFim.map_coupled_profiles):
        with pytest.raises(FimUnsupportedError, match="grid_contract"):
            method("missing.hdf", "missing.tif", tmp_path / "out",
                   allow_unqualified=True, grid_contract=value)
    assert not (tmp_path / "out").exists()


def _native_terrain(files):
    import rasterio
    grid = _grid()
    with rasterio.open(files[1], "w", driver="GTiff", width=grid["width"], height=grid["height"],
            count=1, dtype="float32", crs="EPSG:6588",
            transform=rasterio.Affine.from_gdal(*grid["geo_transform"]),
            tiled=True, blockxsize=256, blockysize=256, nodata=float("nan")) as target:
        target.write(np.zeros((grid["height"], grid["width"]), dtype="<f4"), 1)
    return grid


def test_prepared_and_path_routes_preserve_raw_identity_and_native_grid(files, tmp_path, monkeypatch):
    import rasterio
    engine = _prep_environment(tmp_path, monkeypatch)
    source_grid = _native_terrain(files)
    original_hash = _coupled.digest(files[1])
    prepared = RasFim.prepare_coupled_model(*files, tmp_path / "prep", profiles={"p": 0},
        allow_unqualified=True, grid_contract=_native_grid.CONTRACT, max_working_mib=64)
    receipt = prepared.validate()
    assert receipt["schema"] == "ras-commander-coupled-preparation/2"
    assert receipt["grid"]["geo_transform"] == source_grid["geo_transform"]
    calls = _complete_engine(monkeypatch, tmp_path, engine)
    record = receipt["grid_contract"]
    gt = record["output_geo_transform"]
    bbox = (gt[0]+3*gt[1], gt[3]-8*gt[1], gt[0]+8*gt[1], gt[3]-3*gt[1])
    outputs = []
    for source, terrain, folder, extra in ((prepared, None, "prepared-maps", {}),
            (*files, "path-maps", {"grid_contract": _native_grid.CONTRACT, "profiles": {"p": 0}})):
        outputs.append(RasFim.map_coupled_profiles(source, terrain, tmp_path / folder,
            bbox=bbox, allow_unqualified=True, max_working_mib=64, **extra))
    for manifest in outputs:
        assert manifest.status.tolist() == ["complete"]
        assert manifest.attrs["grid_contract"] == record
        assert manifest.attrs["qualified"] is False
        with rasterio.open(manifest.iloc[0].depth_tif) as product:
            assert product.transform.a == gt[1] != source_grid["geo_transform"][1]
    assert _coupled.digest(files[1]) == original_hash
    assert [c for c, _ in calls] == ["one-d-diagnostic", "sloping", "coupled-diagnostic"]*2
    for command, request in calls:
        assert request["grid_contract"] == record
        if command == "one-d-diagnostic":
            assert request["geo_transform"] == source_grid["geo_transform"]
            assert request["schema"] == "fast-map-one-d-diagnostic/4"
        elif command == "sloping":
            assert request["terrain_transform"] == source_grid["geo_transform"]
            assert request["schema"] == "ras-commander-sloping-request/2"
        else:
            assert request["schema"] == "fast-map-coupled-diagnostic/3"
            assert request["xs"]["grid_contract"] == request["two_d"]["grid_contract"] == record
    assert outputs[0].iloc[0]["transform"] == outputs[1].iloc[0]["transform"]
    with pytest.raises(ValueError, match="already bind grid_contract"):
        RasFim.map_coupled_profiles(prepared, None, tmp_path / "override", allow_unqualified=True,
                                   grid_contract=_native_grid.CONTRACT)
    assert not (tmp_path / "override").exists()


@pytest.mark.parametrize("method", [RasFim.prepare_coupled_model, RasFim.map_coupled_profiles])
def test_native_option_keeps_default_qualification_gate(tmp_path, monkeypatch, method):
    monkeypatch.setattr(_coupled, "_require_engine", lambda *args: pytest.fail("engine before qualification gate"))
    with pytest.raises(FimUnsupportedError, match="unqualified"):
        method("missing.hdf", "missing.tif", tmp_path / "output", grid_contract=_native_grid.CONTRACT)
    assert not (tmp_path / "output").exists()


def test_resealed_forged_descriptor_still_refuses_before_payload_checks(files, tmp_path, monkeypatch):
    _prep_environment(tmp_path, monkeypatch)
    prepared = RasFim.prepare_coupled_model(*files, tmp_path / "prep", profiles={"p": 0},
        allow_unqualified=True, grid_contract=_native_grid.CONTRACT)
    receipt = prepared.receipt
    receipt["grid_contract"]["output_geo_transform"][1] = 2.
    path = prepared.folder / "coupled_preparation.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    forged = _coupled.FimPreparedCoupledModel._from_preparation(prepared.folder, _coupled.digest(path))
    monkeypatch.setattr(_coupled, "digest", lambda *args: pytest.fail("payload hashing before descriptor refusal"))
    with pytest.raises(FimUnsupportedError, match="descriptor differs"):
        forged.validate()


def test_native_polygon_masks_final_products_only_and_rolls_back(files, tmp_path, monkeypatch):
    from shapely.geometry import Polygon
    import rasterio
    engine = _prep_environment(tmp_path, monkeypatch)
    prepared = RasFim.prepare_coupled_model(*files, tmp_path / "prep", profiles={"a": 0, "b": 1},
        allow_unqualified=True, grid_contract=_native_grid.CONTRACT)
    calls = _complete_engine(monkeypatch, tmp_path, engine)
    manifest = prepared.map_profiles(tmp_path / "maps", profiles=["b", "a"],
        polygon=Polygon([(0, 0), (5, 0), (0, 5)]), aoi_crs="EPSG:6588",
        allow_unqualified=True, max_working_mib=64)
    assert manifest.profile.tolist() == ["b", "a"]
    with rasterio.open(manifest.iloc[0].depth_tif) as source:
        values = source.read(1, masked=True)
        assert 0 < values.count() < values.size
    assert all("aoi_file" not in request for _, request in calls)
    _complete_engine(monkeypatch, tmp_path, engine, fail_profile="b")
    failed = prepared.map_profiles(tmp_path / "failed", bbox=(0, 0, 5, 5),
        allow_unqualified=True, max_working_mib=64, raise_on_failure=False)
    assert failed.status.tolist() == ["failed", "failed"]
    assert not list((tmp_path / "failed").glob("*.tif*"))


@pytest.mark.parametrize("component", ["one-d-diagnostic", "sloping", "coupled-diagnostic"])
def test_native_report_framing_mismatch_fails_atomically(files, tmp_path, monkeypatch, component):
    engine = _prep_environment(tmp_path, monkeypatch)
    prepared = RasFim.prepare_coupled_model(*files, tmp_path / "prep", profiles={"p": 0},
        allow_unqualified=True, grid_contract=_native_grid.CONTRACT)
    _complete_engine(monkeypatch, tmp_path, engine)
    run = _engine.run_engine
    def corrupt(args, what, timeout=None):
        result = run(args, what, timeout)
        if args[1] == component:
            path = Path(args[3]) / "report.json"
            report = json.loads(path.read_text())
            report["grid_contract"]["output_geo_transform"][1] = 2.
            path.write_text(json.dumps(report))
        return result
    monkeypatch.setattr(_engine, "run_engine", corrupt)
    output = tmp_path / "maps"
    with pytest.raises(FimMappingError, match="mismatched"):
        prepared.map_profiles(output, bbox=(0, 0, 5, 5), allow_unqualified=True, max_working_mib=64)
    assert not list(output.glob("*.tif*"))
    assert json.loads((output / "fim_manifest.json").read_text())["status"] == "failed"
