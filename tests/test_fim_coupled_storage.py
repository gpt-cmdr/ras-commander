"""Coupled 1D/2D mapping of models with storage areas (Fast-Map 0.18.0+).

Synthetic HDF metadata and an inert fake engine exercise the Commander
contract: storage areas are staged, mapped through the standalone storage
transport and composed with coupled schema /2. Physical storage/2D overlap,
the native stored-grid contract and engines older than Fast-Map 0.18.0 refuse.
No native engine or solver runs, and results stay unqualified.
"""
import json
from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from ras_commander import HdfMesh
from ras_commander.fim import FimUnsupportedError, RasFim
from ras_commander.fim import _coupled, _engine
from test_fim_coupled import _complete_engine, _prep_environment, files, one_d_files  # noqa: F401

BASE = "Results/Unsteady/Output/Output Blocks/Base Output/"
STORAGE_SQUARE = [(300., 100.), (340., 100.), (340., 140.), (300., 140.)]


def _add_storage_area(hdf, name="Pond", ring=STORAGE_SQUARE, levels=(1.5, 2.5), maximum=3.0):
    """One storage area with stored Water Surface rows and its Max summary."""
    with h5py.File(hdf, "a") as f:
        attrs = np.zeros(1, dtype=[("Name", "S16")])
        attrs["Name"] = name.encode()
        group = f.create_group("Geometry/Storage Areas")
        group.create_dataset("Attributes", data=attrs)
        group.create_dataset("Polygon Info", data=np.array([[0, len(ring), 0, 1]], dtype="i4"))
        group.create_dataset("Polygon Points", data=np.asarray(ring, dtype="f8"))
        series = f.create_dataset(BASE + "Unsteady Time Series/Storage Areas/Water Surface",
                                  data=np.asarray(levels, dtype="f4").reshape(-1, 1))
        variables = f.create_dataset(
            BASE + f"Unsteady Time Series/Storage Areas/{name}/Storage Area Variables",
            data=np.column_stack([np.asarray(levels, dtype="f4"), np.zeros(len(levels), "f4")]))
        variables.attrs["Variable_Unit"] = np.array([[b"Stage", b"ft"], [b"Volume", b"acre-ft"]])
        f.create_dataset(BASE + "Summary Output/Storage Areas/Maximum Water Surface",
                         data=np.array([[maximum], [0.]], dtype="f4"))
        assert series.shape == (len(levels), 1)


def _capabilities(version="0.18.0", missing=None):
    methods = {key: SimpleNamespace(method_id=method, request_schemas=(schema,), flags={})
               for key, method, schema in (
                   ("coupled_diagnostic", _coupled.METHOD_ID, _coupled.REQUEST_SCHEMA),
                   ("coupled_native_grid_diagnostic", "native", "native"),
                   ("storage", _coupled.STORAGE_METHOD_ID, _coupled.STORAGE_SCHEMA),
                   ("coupled_storage_diagnostic", _coupled.STORAGE_COMPOSITION_METHOD_ID,
                    _coupled.STORAGE_COMPOSITION_SCHEMA))}
    if missing:
        del methods[missing]
    return SimpleNamespace(methods=methods, engine_version=version,
                           raw_record={"engine": {"version": version}})


def _perimeter(monkeypatch, ring):
    import geopandas as gpd
    from shapely.geometry import Polygon
    frame = gpd.GeoDataFrame({"mesh_name": ["mesh"]}, geometry=[Polygon(ring)], crs="EPSG:6588")
    monkeypatch.setattr(HdfMesh, "get_mesh_areas", lambda _: frame)


def _storage_environment(files, tmp_path, monkeypatch, *, caps=None,
                         perimeter=((0., 0.), (100., 0.), (100., 100.), (0., 100.))):
    _add_storage_area(files[0])
    engine = _prep_environment(tmp_path, monkeypatch)
    caps = caps or _capabilities()
    monkeypatch.setattr(_coupled, "_require_engine", lambda *args: (engine.resolve(), caps))
    monkeypatch.setattr(_coupled, "_require_mixed", lambda _: SimpleNamespace(
        storage_area_names=("Pond",),
        to_dict=lambda: {"dimension": "mixed_1d_2d", "storage_area_names": ["Pond"]}))
    _perimeter(monkeypatch, perimeter)
    return engine, caps


def _storage_engine(monkeypatch, tmp_path, engine, caps, composed_storage_pixels=3):
    """Fake engine: the existing XS/2D components plus storage and schema /2."""
    calls = _complete_engine(monkeypatch, tmp_path, engine)
    monkeypatch.setattr(_coupled, "_require_engine", lambda *args: (engine.resolve(), caps))
    component_run = _engine.run_engine

    def run(args, what, timeout=None):
        command, request, out = args[1], json.loads(Path(args[2]).read_text()), Path(args[3])
        if command == "storage":
            calls.append((command, request))
            out.mkdir()
            count = request["width"] * request["height"]
            owners = np.zeros(count, dtype="<u4")
            owners[:3] = 1
            owners.tofile(out / "owners.bin")
            depth = np.full(count, np.nan, dtype="<f4")
            depth[:2] = 0.5
            depth.tofile(out / "depth.bin")
            (depth + np.float32(1)).tofile(out / "wse.bin")
            report = {"schema": request["schema"], "status": "complete",
                      "method": {"method_id": _coupled.STORAGE_METHOD_ID},
                      "width": request["width"], "height": request["height"],
                      "geo_transform": request["geo_transform"], "storage_owned_pixels": 3,
                      "valid_pixels": 2, "owners_file": "owners.bin",
                      "depth_file": "depth.bin", "wse_file": "wse.bin"}
            (out / "report.json").write_text(json.dumps(report))
            return CompletedProcess(args, 0, "", "")
        if command == "coupled-diagnostic" and "storage" in request:
            calls.append((command, request))
            xs = request["xs"]
            count = xs["width"] * xs["height"]
            out.mkdir()
            for product in ("depth", "wse"):
                np.ones(count, dtype="<f4").tofile(out / (product + ".bin"))
            report = {"schema": request["schema"], "status": "complete",
                      "method": {"method_id": _coupled.STORAGE_COMPOSITION_METHOD_ID},
                      **{key: xs[key] for key in ("profile_id", "crs", "width", "height", "geo_transform")},
                      "counts": {"valid_pixels": count, "two_d_owned_pixels": count,
                                 "dry_two_d_suppressed_wet_xs": 0,
                                 "storage_owned_pixels": composed_storage_pixels,
                                 "dry_storage_suppressed_wet_xs": 1}}
            (out / "report.json").write_text(json.dumps(report))
            return CompletedProcess(args, 0, "", "")
        return component_run(args, what, timeout)

    monkeypatch.setattr(_engine, "run_engine", run)
    return calls


def test_mixed_scope_with_storage_areas_is_admitted(monkeypatch):
    scope = SimpleNamespace(dimension="mixed_1d_2d", mesh_names=("mesh",), cross_section_count=3,
                            storage_area_names=("Pond",))
    monkeypatch.setattr(RasFim, "inspect_model_scope", lambda _: scope)
    assert _coupled._require_mixed("model.p01.hdf") is scope


def test_storage_preparation_and_mapping_compose_schema_2_unqualified(files, tmp_path, monkeypatch):
    engine, caps = _storage_environment(files, tmp_path, monkeypatch)
    prepared = RasFim.prepare_coupled_model(*files, tmp_path / "prep", profiles={"max": "Max", "t1": 1},
                                           allow_unqualified=True, max_working_mib=64)
    receipt = prepared.validate()
    storage = receipt["storage"]
    assert receipt["qualified"] is False
    assert storage["names"] == ["Pond"] and storage["count"] == 1
    assert storage["method_id"] == _coupled.STORAGE_METHOD_ID
    assert storage["composition"]["request_schema"] == "fast-map-coupled-diagnostic/2"
    assert np.fromfile(storage["levels"][0], "<f4").tolist() == [3.0]
    assert np.fromfile(storage["levels"][1], "<f4").tolist() == [2.5]
    assert storage["polygons"] in receipt["sha256"]

    calls = _storage_engine(monkeypatch, tmp_path, engine, caps)
    manifest = prepared.map_profiles(tmp_path / "maps", bbox=(0, 0, 50, 50), allow_unqualified=True,
                                     threads=8, max_working_mib=64)
    assert manifest.status.tolist() == ["complete", "complete"]
    assert manifest.attrs["qualified"] is False
    assert manifest.attrs["method_id"] == "one-d-two-d-storage-coverage-first-diagnostic/1"
    assert manifest.attrs["request_schema"] == "fast-map-coupled-diagnostic/2"
    assert manifest.attrs["component_contracts"]["storage"]["request_schema"] == "fast-map-storage/1"
    assert manifest.attrs["threads_by_component"]["storage"] == 4
    commands = [command for command, _ in calls]
    assert commands == ["one-d-diagnostic", "sloping", "storage", "coupled-diagnostic"] * 2
    pools = [request for command, request in calls if command == "storage"]
    assert [p["levels_file"] for p in pools] == storage["levels"]
    composed = [request for command, request in calls if command == "coupled-diagnostic"]
    assert all(r["schema"] == "fast-map-coupled-diagnostic/2" and r["storage"]["area_count"] == 1
               and r["two_d_cell_count"] == 1 for r in composed)
    on_disk = json.loads((tmp_path / "maps" / "fim_manifest.json").read_text())
    assert on_disk["qualified"] is False and on_disk["status"] == "complete"
    composition_counts = [r["counts"] for r in on_disk["reports"]
                          if r.get("schema") == "fast-map-coupled-diagnostic/2"]
    assert composition_counts and all(c["storage_owned_pixels"] == 3
                                      and c["dry_storage_suppressed_wet_xs"] == 1
                                      for c in composition_counts)
    storage_reports = [r for r in on_disk["reports"] if r.get("schema") == "fast-map-storage/1"]
    assert [r["storage_owned_pixels"] for r in storage_reports] == [3, 3]


def test_composition_storage_counts_must_match_the_storage_component(files, tmp_path, monkeypatch):
    from ras_commander.fim import FimMappingError
    engine, caps = _storage_environment(files, tmp_path, monkeypatch)
    prepared = RasFim.prepare_coupled_model(*files, tmp_path / "prep", allow_unqualified=True)
    _storage_engine(monkeypatch, tmp_path, engine, caps, composed_storage_pixels=4)
    with pytest.raises(FimMappingError, match="storage composition coverage counts differ"):
        prepared.map_profiles(tmp_path / "maps", bbox=(0, 0, 50, 50), allow_unqualified=True,
                              max_working_mib=64)
    assert not list((tmp_path / "maps").glob("*.tif*"))


def test_unreadable_2d_perimeters_refuse_storage_before_writes(files, tmp_path, monkeypatch):
    import geopandas as gpd
    _storage_environment(files, tmp_path, monkeypatch)
    monkeypatch.setattr(HdfMesh, "get_mesh_areas", lambda _: gpd.GeoDataFrame())
    with pytest.raises(FimUnsupportedError, match="perimeters are unreadable"):
        RasFim.prepare_coupled_model(*files, tmp_path / "prep", allow_unqualified=True)
    assert not (tmp_path / "prep").exists()


def test_storage_mapping_still_requires_allow_unqualified(files, tmp_path, monkeypatch):
    _storage_environment(files, tmp_path, monkeypatch)
    with pytest.raises(FimUnsupportedError, match="unqualified"):
        RasFim.map_coupled_profiles(*files, tmp_path / "maps")
    assert not (tmp_path / "maps").exists()


def test_physical_storage_2d_overlap_refuses_before_writes(files, tmp_path, monkeypatch):
    _storage_environment(files, tmp_path, monkeypatch,
                         perimeter=((290., 90.), (320., 90.), (320., 120.), (290., 120.)))
    with pytest.raises(FimUnsupportedError, match="'Pond' physically overlaps 2D flow area 'mesh'"):
        RasFim.prepare_coupled_model(*files, tmp_path / "prep", allow_unqualified=True)
    assert not (tmp_path / "prep").exists()


def test_storage_sharing_an_edge_with_2d_is_admitted(files, tmp_path, monkeypatch):
    _storage_environment(files, tmp_path, monkeypatch,
                         perimeter=((260., 100.), (300., 100.), (300., 140.), (260., 140.)))
    prepared = RasFim.prepare_coupled_model(*files, tmp_path / "prep", allow_unqualified=True)
    assert prepared.validate()["storage"]["names"] == ["Pond"]


@pytest.mark.parametrize("version", ["0.17.0", "0.13.2", None, "unknown"])
def test_engine_older_than_fast_map_0_18_refuses_storage(files, tmp_path, monkeypatch, version):
    _storage_environment(files, tmp_path, monkeypatch, caps=_capabilities(version))
    with pytest.raises(FimUnsupportedError, match=r"ras-commander-fast-map >= 0\.18\.0"):
        RasFim.prepare_coupled_model(*files, tmp_path / "prep", allow_unqualified=True)
    assert not (tmp_path / "prep").exists()


@pytest.mark.parametrize("missing", ["storage", "coupled_storage_diagnostic"])
def test_engine_without_storage_contracts_refuses(missing):
    with pytest.raises(FimUnsupportedError, match="engine contract " + missing):
        _coupled._require_storage_engine(_capabilities(missing=missing))


def test_native_stored_grid_contract_refuses_storage():
    with pytest.raises(FimUnsupportedError, match="schema /3 excludes storage"):
        _coupled._require_storage_engine(_capabilities(), "rasmapper-stored-tile-grid/1")


def test_storage_receipt_tampering_refuses(files, tmp_path, monkeypatch):
    _storage_environment(files, tmp_path, monkeypatch)
    prepared = RasFim.prepare_coupled_model(*files, tmp_path / "prep", allow_unqualified=True)
    Path(prepared.receipt["storage"]["levels"][0]).write_bytes(np.float32(9).tobytes())
    with pytest.raises(FimUnsupportedError, match="changed"):
        prepared.validate()


def test_storage_series_binds_shared_timestamp_axis(files, monkeypatch):
    from ras_commander import HdfResultsMesh
    prefix = BASE + "Unsteady Time Series/"
    _add_storage_area(files[0])
    with h5py.File(files[0], "a") as handle:
        handle.create_dataset(prefix + "Time Date Stamp",
                              data=np.array([b"01JAN2000 00:00:00", b"01JAN2000 01:00:00"]))
        handle.create_dataset(prefix + "2D Flow Areas/m/Water Surface", data=np.ones((2, 2)))
    monkeypatch.setattr(HdfMesh, "get_mesh_area_names", lambda _: ["m"])
    monkeypatch.setattr(HdfResultsMesh, "get_mesh_timeseries",
                        lambda *a, **k: SimpleNamespace(dataset_path=prefix + "2D Flow Areas/m/Water Surface"))
    alignment = _coupled._alignment(files[0], [1])
    assert alignment["storage"]["shape"] == [2, 1]
    with h5py.File(files[0], "a") as handle:
        del handle[prefix + "Storage Areas/Water Surface"]
        handle.create_dataset(prefix + "Storage Areas/Water Surface", data=np.ones((3, 1)))
    with pytest.raises(FimUnsupportedError, match="storage-area output does not bind"):
        _coupled._alignment(files[0], [1])


def test_installed_engine_advertises_coupled_storage_contracts():
    from ras_commander.fim import FimEngineNotFoundError
    try:
        caps = RasFim.get_capabilities()
    except FimEngineNotFoundError:
        pytest.skip("ras-commander-fast-map is not installed")
    pool, composition = _coupled._require_storage_engine(caps)
    assert composition.flags.get("native_parity_qualified") is False
    assert pool.method_id == "storage-area-level-pool/1"
