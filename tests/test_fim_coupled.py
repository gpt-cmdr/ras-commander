"""Transport/lifecycle guards for receipt-bound coupled preparation."""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ras_commander.fim import RasFim, FimPreparedCoupledModel, FimUnsupportedError
from ras_commander.fim import _coupled, _sloping_inputs
from test_fim_one_d import files as one_d_files  # noqa: F401


@pytest.fixture
def files(one_d_files):
    """Coupled components share an explicitly nodata-tagged terrain."""
    import rasterio
    with rasterio.open(one_d_files[1], "r+") as terrain:
        terrain.nodata = float("nan")
    return one_d_files


@pytest.mark.parametrize("method", [RasFim.prepare_coupled_model, RasFim.map_coupled_profiles])
def test_default_gate_before_engine_or_writes(tmp_path, monkeypatch, method):
    monkeypatch.setattr(_coupled, "_require_engine", lambda *_: pytest.fail("engine lookup before gate"))
    with pytest.raises(FimUnsupportedError, match="unqualified"):
        method("missing.hdf", "missing.tif", tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_reconstructed_preparation_refuses(tmp_path):
    import inspect
    assert list(inspect.signature(FimPreparedCoupledModel).parameters) == ["folder"]
    with pytest.raises(FimUnsupportedError, match="created by prepare"):
        FimPreparedCoupledModel(tmp_path)


@pytest.mark.parametrize("threads,budget", [(65, 64), (True, 64), (1, 0)])
def test_resource_bounds(threads, budget):
    with pytest.raises(ValueError):
        _coupled._resources(threads, budget)


def test_resource_contract_is_independent_of_validation_host_budget():
    assert _coupled._resources(8, 2048) == (8, 2048 * 1024**2)


def test_non_epsg_crs_refuses_at_preparation(files, tmp_path, monkeypatch):
    import h5py
    import rasterio
    from pyproj import CRS
    _prep_environment(tmp_path, monkeypatch)
    crs = CRS.from_proj4("+proj=tmerc +lat_0=29.3 +lon_0=-94.7 +k=0.99971 +x_0=12345 +y_0=9876 +datum=NAD83 +units=us-ft +no_defs")
    assert crs.to_epsg() is None
    with h5py.File(files[0], "a") as source:
        source.attrs["Projection"] = crs.to_wkt()
    with rasterio.open(files[1], "r+") as terrain:
        terrain.crs = crs
    monkeypatch.setattr(_coupled, "_stage_mesh", lambda *args: pytest.fail("staged unsupported CRS"))
    with pytest.raises(FimUnsupportedError, match="EPSG code"):
        RasFim.prepare_coupled_model(*files, tmp_path / "prep", allow_unqualified=True)
    assert not (tmp_path / "prep").exists()


def test_terrain_identity_probe_timeout_is_forwarded(files, monkeypatch):
    import rasterio
    from subprocess import CompletedProcess
    from ras_commander.fim import _engine
    calls = []
    with rasterio.open(files[1]) as terrain:
        info = dict(width=terrain.width, height=terrain.height,
                    geo_transform=list(terrain.transform.to_gdal()), epsg=6588)
    def run(command, label, timeout=None):
        calls.append((command, label, timeout))
        return CompletedProcess(command, 0, json.dumps(info), "")
    monkeypatch.setattr(_engine, "run_engine", run)
    result = _engine.terrain_identity(Path("engine.exe"), files[1], "EPSG:6588", timeout=7.5)
    assert result["epsg"] == 6588
    assert len(calls) == 1 and calls[0][1:] == ("terrain-info", 7.5)


def test_real_scope_still_refuses_xs_only(files):
    with pytest.raises(FimUnsupportedError, match="actual mixed"):
        _coupled._require_mixed(files[0])


@pytest.mark.parametrize("kind", ["dataset_mask", "no_nodata"])
def test_terrain_validity_refuses_before_payload_staging(files, tmp_path, monkeypatch, kind):
    import rasterio
    _prep_environment(tmp_path, monkeypatch)
    terrain = files[1]
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False), rasterio.open(terrain, "r+") as source:
        if kind == "dataset_mask":
            source.write_mask(np.full((source.height, source.width), 255, dtype="u1"))
        else:
            source.nodata = None
    monkeypatch.setattr(_coupled, "_stage_mesh", lambda *a: pytest.fail("payload staging before terrain admission"))
    with pytest.raises(FimUnsupportedError, match="dataset/alpha mask|declare its nodata"):
        RasFim.prepare_coupled_model(*files, tmp_path / "prep", allow_unqualified=True)
    assert not (tmp_path / "prep").exists()


def test_unbound_mask_sidecar_is_refused_on_prepared_reuse(files, tmp_path, monkeypatch):
    import rasterio
    _prep_environment(tmp_path, monkeypatch)
    prepared = RasFim.prepare_coupled_model(*files, tmp_path / "prep", allow_unqualified=True)
    terrain = Path(files[1])
    before = _coupled.digest(terrain)
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False), rasterio.open(terrain, "r+") as source:
        source.write_mask(np.full((source.height, source.width), 255, dtype="u1"))
    assert _coupled.digest(terrain) == before
    assert Path(str(terrain) + ".msk").is_file()
    with pytest.raises(FimUnsupportedError, match="dataset/alpha mask"):
        prepared.validate()


def test_unbound_auxiliary_metadata_is_refused(files, tmp_path, monkeypatch):
    _prep_environment(tmp_path, monkeypatch)
    prepared = RasFim.prepare_coupled_model(*files, tmp_path / "prep", allow_unqualified=True)
    Path(str(files[1]) + ".aux.xml").write_text("<PAMDataset/>", encoding="utf-8")
    with pytest.raises(FimUnsupportedError, match="auxiliary sidecar"):
        prepared.validate()


def test_preparation_cleanup_preserves_unowned_destination_files(files, tmp_path, monkeypatch):
    _prep_environment(tmp_path, monkeypatch)
    stage = _coupled._stage_mesh
    output = tmp_path / "prep"
    def concurrent_file(*args, **kwargs):
        result = stage(*args, **kwargs)
        (output / "unowned.txt").write_text("preserve this file", encoding="utf-8")
        return result
    monkeypatch.setattr(_coupled, "_stage_mesh", concurrent_file)
    with pytest.raises(FimUnsupportedError, match="destination changed"):
        RasFim.prepare_coupled_model(*files, output, allow_unqualified=True)
    assert [path.name for path in output.iterdir()] == ["unowned.txt"]
    assert (output / "unowned.txt").read_text(encoding="utf-8") == "preserve this file"


def _prep_environment(tmp_path, monkeypatch):
    from ras_commander.fim import _engine
    engine = tmp_path / "engine.exe"
    engine.write_bytes(b"engine identity")
    monkeypatch.setattr(_coupled, "_require_engine", lambda *args: (engine.resolve(), None))
    monkeypatch.setattr(_coupled, "_require_mixed", lambda _: SimpleNamespace(to_dict=lambda: {"dimension": "mixed_1d_2d"}))
    monkeypatch.setattr(_coupled, "_alignment", lambda hdf, profiles: {"profiles": list(profiles)})
    monkeypatch.setattr(_engine, "terrain_identity", lambda *args, **kwargs: {"epsg": 6588, "crs_identity": {"kind": "epsg"}})
    def stage(hdf, folder, selected, budget, threads):
        (folder / "cells.wkb").write_bytes(b"physical polygons")
        np.asarray([1., 2.], dtype="<f4").tofile(folder / "values.bin")
        return {"geometry_file": "cells.wkb", "mesh_files": [],
                "meshes": [{"mesh_name": "mesh", "cell_count": 2}],
                "profiles": [{"id": name, "values_files": ["values.bin"]} for name in selected],
                "owner_cells": [[0, 0]], "physical_cell_count": 1}
    monkeypatch.setattr(_coupled, "_stage_mesh", stage)
    return engine


def test_receipt_binding_and_mesh_hash_coverage(files, tmp_path, monkeypatch):
    _prep_environment(tmp_path, monkeypatch)
    prepared = RasFim.prepare_coupled_model(*files, tmp_path / "prep", profiles={"later": 1, "first": 0},
                                           allow_unqualified=True, max_working_mib=64)
    receipt = prepared.validate()
    assert receipt["qualified"] is False
    assert receipt["method_id"] == _coupled.METHOD_ID
    assert receipt["request_schema"] == _coupled.REQUEST_SCHEMA
    assert receipt["component_contracts"]["xs"]["method_id"] == _coupled.XS_METHOD_ID
    assert receipt["profile_ids"] == ["later", "first"]
    assert receipt["profiles"] == [1, 0]
    assert str(prepared.folder / "two_d/values.bin") in receipt["sha256"]
    (prepared.folder / "two_d/values.bin").write_bytes(b"changed")
    with pytest.raises(FimUnsupportedError, match="changed"):
        prepared.validate()


@pytest.mark.parametrize("existing", [True, False])
def test_partial_mesh_prep_cleans_owned_files_and_can_retry(files, tmp_path, monkeypatch, existing):
    _prep_environment(tmp_path, monkeypatch)
    original = _coupled._stage_mesh
    output = tmp_path / "prep"
    if existing:
        output.mkdir()
    def fail(hdf, folder, *args):
        (folder / "partial.bin").write_bytes(b"partial")
        raise KeyboardInterrupt("original interrupt")
    monkeypatch.setattr(_coupled, "_stage_mesh", fail)
    with pytest.raises(KeyboardInterrupt, match="original interrupt"):
        RasFim.prepare_coupled_model(*files, output, allow_unqualified=True)
    assert not output.exists() or not list(output.iterdir())
    monkeypatch.setattr(_coupled, "_stage_mesh", original)
    assert RasFim.prepare_coupled_model(*files, output, allow_unqualified=True).validate()


def test_strict_mesh_entry_point_retains_guard(monkeypatch):
    monkeypatch.setattr(RasFim, "validate_2d_model", lambda _: (_ for _ in ()).throw(FimUnsupportedError("strict guard")))
    monkeypatch.setattr(_sloping_inputs, "_write_binary_mesh_payloads", lambda *args, **kwargs: pytest.fail("read after guard"))
    with pytest.raises(FimUnsupportedError, match="strict guard"):
        _sloping_inputs.write_binary_mesh_inputs("mixed.hdf", "output")


def test_owner_report_checks_dry_and_nodata_coverage(tmp_path):
    # Ownership remains physical even when the component's products are nodata.
    np.asarray([0, 1, 1], dtype="<u4").tofile(tmp_path / "owners.bin")
    request = {"window": [2, 3, 3, 1], "epsg": 6588, "crs_identity": {"kind": "epsg"},
               "owner_cells": [[0, 0]], "profiles": [{"id": "p"}]}
    ownership = {"kind": "physical_2d", "dtype": "<u4", "count": 3, "path": "owners.bin",
                 "bytes": 12, "width": 3, "height": 1, "window": request["window"],
                 "geo_transform": [2, 1, 0, 4, 0, -1], "epsg": 6588,
                 "crs_identity": request["crs_identity"], "owner_cell_count": 1, "owned_pixels": 2}
    report = {"schema": "ras-commander-sloping-report/1", "status": "complete",
              "method": {"method_id": _coupled.TWO_D_METHOD}, "window": request["window"],
              "profiles": [{"id": "p", "status": "complete"}], "physical_ownership": ownership}
    _coupled._validate_two_d_report(report, request, ownership["geo_transform"], tmp_path)
    report["physical_ownership"]["owned_pixels"] = 1
    with pytest.raises(_coupled.FimEngineError, match="coverage count"):
        _coupled._validate_two_d_report(report, request, ownership["geo_transform"], tmp_path)

@pytest.mark.parametrize("failure", [OSError("engine failed"), KeyboardInterrupt("original interruption")])
@pytest.mark.parametrize("raise_on_failure", [False, True])
def test_map_failure_manifest_and_interrupt_preservation(files, tmp_path, monkeypatch, failure, raise_on_failure):
    from ras_commander.fim import FimMappingError, _engine
    engine = _prep_environment(tmp_path, monkeypatch)
    prepared = RasFim.prepare_coupled_model(*files, tmp_path / "prep", profiles={"p": 0},
                                           allow_unqualified=True, max_working_mib=64)
    caps = SimpleNamespace(methods={key: SimpleNamespace(flags={}) for key in
                                   ("coupled_diagnostic", "coupled_native_grid_diagnostic")}, raw_record={})
    monkeypatch.setattr(_coupled, "_require_engine", lambda *args: (engine.resolve(), caps))
    def fail(*args):
        raise failure
    monkeypatch.setattr(_engine, "run_engine", fail)
    output = tmp_path / "products"
    if isinstance(failure, KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt, match="original interruption"):
            prepared.map_profiles(output, bbox=(0, 0, 100, 100), allow_unqualified=True,
                                  max_working_mib=64, raise_on_failure=raise_on_failure)
    elif raise_on_failure:
        with pytest.raises(FimMappingError) as error:
            prepared.map_profiles(output, bbox=(0, 0, 100, 100), allow_unqualified=True,
                                  max_working_mib=64, raise_on_failure=True)
        assert error.value.manifest.iloc[0].status == "failed"
    else:
        manifest = prepared.map_profiles(output, bbox=(0, 0, 100, 100), allow_unqualified=True,
                                         max_working_mib=64, raise_on_failure=False)
        assert manifest.iloc[0].status == "failed"
    assert json.loads((output / "fim_manifest.json").read_text())["status"] == "failed"
    assert not list(output.glob("*.tif*"))


def _complete_engine(monkeypatch, tmp_path, engine, fail_profile=None):
    from ras_commander.fim import _engine
    from affine import Affine
    from subprocess import CompletedProcess
    caps = SimpleNamespace(methods={key: SimpleNamespace(flags={}) for key in
                                   ("coupled_diagnostic", "coupled_native_grid_diagnostic")}, raw_record={})
    monkeypatch.setattr(_coupled, "_require_engine", lambda *args: (engine.resolve(), caps))
    monkeypatch.setattr(_engine, "terrain_identity", lambda *args, **kwargs: {"epsg": 6588, "crs_identity": {"kind": "epsg"}})
    calls = []
    def run(args, what, timeout=None):
        request = json.loads(Path(args[2]).read_text())
        command, out = args[1], Path(args[3])
        calls.append((command, request))
        descriptor = request.get("grid_contract")
        contracts = _coupled._contracts(descriptor["id"] if descriptor else None)
        if command == "one-d-diagnostic":
            w = request["window"]
            full = descriptor["output_geo_transform"] if descriptor else request["geo_transform"]
            gt = list((Affine.from_gdal(*full) @ Affine.translation(w["col"], w["row"])).to_gdal())
            report = {"schema": contracts["xs_schema"], "status": "complete", "method": {"method_id": _coupled.XS_METHOD_ID},
                "width": w["width"], "height": w["height"], "source_width": request["width"], "source_height": request["height"],
                "source_geo_transform": request["geo_transform"], "source_col": w["col"], "source_row": w["row"],
                "geo_transform": gt, "tile_size": 256, "scope": request["scope"], "clipping_scope": request["clipping_scope"],
                "depth_file": "depth.bin", "wse_file": "wse.bin", "dtype": "little-endian float32", "nodata": "NaN", "valid_pixels": w["width"]*w["height"]}
            product_out = out
            width, height = w["width"], w["height"]
        elif command == "sloping":
            window = request["window"]
            name = request["profiles"][0]["id"]
            if name == fail_profile:
                raise OSError("second profile failed")
            full = descriptor["output_geo_transform"] if descriptor else request["terrain_transform"]
            gt = list((Affine.from_gdal(*full) @ Affine.translation(window[0], window[1])).to_gdal())
            width, height = window[2:]
            report = {"schema": contracts["two_report"], "status": "complete", "method": {"method_id": contracts["two_method"]},
                      "window": window, "profiles": [{"id": name, "status": "complete"}],
                      "physical_ownership": {"kind": "physical_2d", "dtype": "<u4", "count": width*height,
                        "path": "owners.bin", "bytes": width*height*4, "width": width, "height": height,
                        "window": window, "geo_transform": gt, "epsg": 6588, "crs_identity": {"kind": "epsg"},
                        "owner_cell_count": 1, "owned_pixels": width*height}}
            if descriptor:
                report.update(source_geo_transform=request["terrain_transform"],
                              output_geo_transform=full, geo_transform=gt)
            out.mkdir()
            np.ones(width*height, dtype="<u4").tofile(out / "owners.bin")
            product_out = out / name
        else:
            component = request["xs"]
            width, height = component["width"], component["height"]
            report = {"schema": contracts["schema"], "status": "complete", "method": {"method_id": contracts["method"]},
                      **{key: component[key] for key in ("profile_id", "crs", "width", "height", "geo_transform")},
                      "counts": {"valid_pixels": width*height, "two_d_owned_pixels": width*height,
                                 "dry_two_d_suppressed_wet_xs": 0}}
            product_out = out
        if descriptor:
            report["grid_contract"] = descriptor
            if command == "one-d-diagnostic":
                report["output_geo_transform"] = descriptor["output_geo_transform"]
        product_out.mkdir(parents=True, exist_ok=True)
        for product in ("depth", "wse"):
            np.ones(width*height, dtype="<f4").tofile(product_out / (product+".bin"))
        (out / "report.json").write_text(json.dumps(report))
        return CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(_engine, "run_engine", run)
    return calls


def test_prepared_order_and_final_polygon_mask(files, tmp_path, monkeypatch):
    import rasterio
    from shapely.geometry import Polygon
    engine = _prep_environment(tmp_path, monkeypatch)
    prepared = RasFim.prepare_coupled_model(*files, tmp_path / "prep", profiles={"first": 0, "second": 1}, allow_unqualified=True)
    calls = _complete_engine(monkeypatch, tmp_path, engine)
    manifest = prepared.map_profiles(tmp_path / "maps", profiles=["second", "first"],
        polygon=Polygon([(0, 0), (5, 0), (0, 5)]), aoi_crs="EPSG:6588", allow_unqualified=True, max_working_mib=64)
    assert manifest.profile.tolist() == ["second", "first"]
    assert manifest.status.tolist() == ["complete", "complete"]
    assert manifest.attrs["qualified"] is False
    assert manifest.attrs["aoi_mask"] == "global-terrain-lattice/1"
    assert [r["profiles"][0]["id"] for cmd, r in calls if cmd == "sloping"] == ["second", "first"]
    assert all("aoi_file" not in r and "terrain_scope" not in r for cmd, r in calls if cmd == "sloping")
    with rasterio.open(manifest.iloc[0].depth_tif) as src:
        values = src.read(1, masked=True)
        assert 0 < values.count() < values.size
        assert np.all(values.compressed() == 1)


def test_terrain_identity_checked_once_before_profiles(files, tmp_path, monkeypatch):
    from ras_commander.fim import _engine
    engine = _prep_environment(tmp_path, monkeypatch)
    prepared = RasFim.prepare_coupled_model(*files, tmp_path / "prep", profiles={"a": 0, "b": 1}, allow_unqualified=True)
    renders = _complete_engine(monkeypatch, tmp_path, engine)
    probes = []
    def identity(*args, timeout=None):
        assert not renders, "terrain identity was checked after rendering began"
        probes.append(timeout)
        return {"epsg": 6588, "crs_identity": {"kind": "epsg"}}
    monkeypatch.setattr(_engine, "terrain_identity", identity)
    manifest = prepared.map_profiles(tmp_path / "maps", bbox=(0, 0, 5, 5),
        allow_unqualified=True, threads=3, max_working_mib=64, timeout=7.5)
    assert probes == [7.5]
    assert manifest.attrs["threads_by_component"] == {"xs": 1, "two_d": 3, "composition": 1}
    assert manifest.attrs["threads_effective"] == 3
    assert manifest.attrs["preparation_receipt"]["ephemeral"] is False


def test_whole_batch_rollback_after_first_profile(files, tmp_path, monkeypatch):
    engine = _prep_environment(tmp_path, monkeypatch)
    prepared = RasFim.prepare_coupled_model(*files, tmp_path / "prep", profiles={"first": 0, "second": 1}, allow_unqualified=True)
    _complete_engine(monkeypatch, tmp_path, engine, fail_profile="second")
    output = tmp_path / "maps"
    manifest = prepared.map_profiles(output, bbox=(0, 0, 5, 5), allow_unqualified=True,
                                     max_working_mib=64, raise_on_failure=False)
    assert manifest.status.tolist() == ["failed", "failed"]
    assert not list(output.glob("*.tif*"))
    assert json.loads((output / "fim_manifest.json").read_text())["status"] == "failed"


def test_edited_receipt_refuses(files, tmp_path, monkeypatch):
    _prep_environment(tmp_path, monkeypatch)
    prepared = RasFim.prepare_coupled_model(*files, tmp_path / "prep", allow_unqualified=True)
    path = prepared.folder / "coupled_preparation.json"
    receipt = prepared.receipt
    receipt["sha256"] = {}
    path.write_text(json.dumps(receipt))
    with pytest.raises(FimUnsupportedError, match="receipt changed"):
        prepared.validate()


@pytest.mark.parametrize("mesh_rows", [1, 2])
def test_timestamp_axis_identity_and_mismatch(files, monkeypatch, mesh_rows):
    import h5py
    from ras_commander import HdfMesh, HdfResultsMesh
    prefix = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/"
    with h5py.File(files[0], "a") as handle:
        handle.create_dataset(prefix+"Time Date Stamp", data=np.array([b"01JAN2000 00:00:00", b"01JAN2000 01:00:00"]))
        handle.create_dataset(prefix+"2D Flow Areas/m/Water Surface", data=np.ones((mesh_rows, 2)))
    monkeypatch.setattr(HdfMesh, "get_mesh_area_names", lambda _: ["m"])
    monkeypatch.setattr(HdfResultsMesh, "get_mesh_timeseries", lambda *args, **kwargs: SimpleNamespace(dataset_path=prefix+"2D Flow Areas/m/Water Surface"))
    if mesh_rows == 1:
        with pytest.raises(FimUnsupportedError, match="shared Base Output"):
            _coupled._alignment(files[0], [0])
    else:
        alignment = _coupled._alignment(files[0], [1, 0, 1])
        assert alignment["selected"] == ["01JAN2000 01:00:00", "01JAN2000 00:00:00", "01JAN2000 01:00:00"]
        assert alignment["components"]["m"]["shape"] == [2, 2]

