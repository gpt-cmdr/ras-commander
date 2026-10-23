"""Required-native mode must surface native refusals from broad except handlers.

``fast_hdf.reraise_required`` is the policy: in ``RAS_COMMANDER_FAST_HDF=native``
(legacy ``required``) a :class:`FastHdfError` propagates unchanged; in ``h5py``
and ``auto`` modes each handler keeps its established degraded result. These
handlers used to swallow the refusal in every mode (native-failure triage C1),
and ``_fast_hdf_typed.read`` called the engine on a writable handle before the
safe-file guard (C2).

Every test sets ``RAS_COMMANDER_FAST_HDF`` itself, so the suite is mode-independent.
"""
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import fast_hdf
from ras_commander.fast_hdf import FastHdfError

FALLBACK_MODES = ("h5py", "auto")
REQUIRED_MODES = ("native", "required")

needs_native = pytest.mark.skipif(not fast_hdf.available(), reason="native extension not installed")


def _refuse(*args, **kwargs):
    raise FastHdfError("injected native refusal")


# --- RasPreprocess._missing_land_classification_files (pre-launch guard) ---

def _land_cover_geometry(path: Path, value) -> Path:
    with h5py.File(path, "w") as hdf:
        hdf.create_group("Geometry").attrs["Land Cover Filename"] = value
    return path


@pytest.mark.parametrize("mode", REQUIRED_MODES)
def test_land_classification_guard_propagates_refusal(tmp_path, monkeypatch, mode):
    from ras_commander import _geometry_association
    from ras_commander.RasPreprocess import RasPreprocess

    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    monkeypatch.setattr(_geometry_association, "read_geometry_association", _refuse)
    geom = _land_cover_geometry(tmp_path / "m.g03.hdf", np.bytes_(r".\missing\n.hdf"))
    with pytest.raises(FastHdfError, match="injected"):
        RasPreprocess._missing_land_classification_files(geom)


@pytest.mark.parametrize("mode", FALLBACK_MODES)
def test_land_classification_guard_fallback_unchanged(tmp_path, monkeypatch, mode):
    from ras_commander import _geometry_association
    from ras_commander.RasPreprocess import RasPreprocess

    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    geom = _land_cover_geometry(tmp_path / "m.g03.hdf", r".\missing\n.hdf")  # vlen str
    missing = RasPreprocess._missing_land_classification_files(geom)
    assert len(missing) == 1 and r".\missing\n.hdf" in missing[0]
    # An unreadable association still means "check does not apply".
    monkeypatch.setattr(_geometry_association, "read_geometry_association", _refuse)
    assert RasPreprocess._missing_land_classification_files(geom) == []


@needs_native
def test_land_classification_guard_real_refusal_in_native(tmp_path, monkeypatch):
    from ras_commander.RasPreprocess import RasPreprocess

    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "native")
    # A vlen-string attribute is a genuine engine refusal (metadata encoding).
    geom = _land_cover_geometry(tmp_path / "m.g03.hdf", r".\missing\n.hdf")
    with pytest.raises(FastHdfError):
        RasPreprocess._missing_land_classification_files(geom)


# --- GeomProjection._read_asset_crs (terrain CRS) ---

def _terrain(path: Path, projection) -> Path:
    with h5py.File(path, "w") as hdf:
        hdf.attrs["Projection"] = projection
    return path


@pytest.mark.parametrize("mode", REQUIRED_MODES)
def test_asset_crs_propagates_refusal(tmp_path, monkeypatch, mode):
    from ras_commander.geom.GeomProjection import GeomProjection
    from ras_commander.hdf.HdfBase import HdfBase

    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    monkeypatch.setattr(HdfBase, "get_projection", staticmethod(_refuse))
    with pytest.raises(FastHdfError, match="injected"):
        GeomProjection._read_asset_crs(_terrain(tmp_path / "Terrain.hdf", np.bytes_("x")))


@pytest.mark.parametrize("mode", FALLBACK_MODES)
def test_asset_crs_fallback_unchanged(tmp_path, monkeypatch, mode):
    pyproj = pytest.importorskip("pyproj")
    from ras_commander.geom.GeomProjection import GeomProjection
    from ras_commander.hdf.HdfBase import HdfBase

    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    terrain = _terrain(tmp_path / "Terrain.hdf", pyproj.CRS.from_epsg(5070).to_wkt())
    assert GeomProjection._read_asset_crs(terrain).to_epsg() == 5070
    monkeypatch.setattr(HdfBase, "get_projection", staticmethod(_refuse))
    assert GeomProjection._read_asset_crs(terrain) is None


@needs_native
def test_asset_crs_real_refusal_in_native(tmp_path, monkeypatch):
    pyproj = pytest.importorskip("pyproj")
    from ras_commander.geom.GeomProjection import GeomProjection

    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "native")
    terrain = _terrain(tmp_path / "Terrain.hdf", pyproj.CRS.from_epsg(5070).to_wkt())
    with pytest.raises(FastHdfError):
        GeomProjection._read_asset_crs(terrain)


# --- GeomMetadata.get_geometry_counts (provenance) ---

def _metadata_inputs(tmp_path):
    geom = tmp_path / "m.g01"
    geom.write_text("Geom Title=fixture\n", encoding="utf-8")
    hdf = tmp_path / "m.g01.hdf"
    with h5py.File(hdf, "w") as handle:
        handle.create_group("Geometry")
    return geom, hdf


@pytest.mark.parametrize("mode", REQUIRED_MODES)
def test_geometry_counts_propagate_refusal(tmp_path, monkeypatch, mode):
    from ras_commander.geom.GeomMetadata import GeomMetadata

    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    monkeypatch.setattr(GeomMetadata, "_get_counts_from_hdf", staticmethod(_refuse))
    with pytest.raises(FastHdfError, match="injected"):
        GeomMetadata.get_geometry_counts(*_metadata_inputs(tmp_path))


@pytest.mark.parametrize("mode", FALLBACK_MODES)
def test_geometry_counts_fallback_unchanged(tmp_path, monkeypatch, mode):
    from ras_commander.geom.GeomMetadata import GeomMetadata

    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    monkeypatch.setattr(GeomMetadata, "_get_counts_from_hdf", staticmethod(_refuse))
    counts = GeomMetadata.get_geometry_counts(*_metadata_inputs(tmp_path))
    assert counts["geometry_metadata_source"] == "text"
    assert "HDF inspection failed: injected native refusal" in (counts["geometry_metadata_error"] or "")


# --- RasMap.list/validate_geometry_associations and the land-cover diagnostic ---

class _Project:
    def __init__(self, folder: Path, geom: Path):
        self.project_folder = folder
        self.project_name = "Project"
        self.geom_df = pd.DataFrame({"geom_number": ["01"], "full_path": [str(geom)],
                                     "hdf_path": [str(geom) + ".hdf"], "has_2d_mesh": [True]})
        self.plan_df = pd.DataFrame({"plan_number": ["01"], "geometry_number": ["01"]})

    def check_initialized(self):
        return None


def _association_project(tmp_path: Path) -> _Project:
    terrain = tmp_path / "Terrain" / "Terrain.hdf"
    terrain.parent.mkdir()
    terrain.write_text("artifact", encoding="utf-8")
    geom = tmp_path / "Project.g01"
    geom.write_text("Geom Title=Default\n", encoding="utf-8")
    with h5py.File(str(geom) + ".hdf", "w") as hdf:
        g = hdf.create_group("Geometry")
        g.attrs["Terrain Filename"] = np.bytes_(r".\Terrain\Terrain.hdf")
        g.attrs["Terrain Layername"] = np.bytes_("Terrain")
    return _Project(tmp_path, geom)


@pytest.mark.parametrize("mode", REQUIRED_MODES)
def test_geometry_association_validation_propagates_refusal(tmp_path, monkeypatch, mode):
    from ras_commander import RasMap, _geometry_association

    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    monkeypatch.setattr(_geometry_association, "read_geometry_association", _refuse)
    project = _association_project(tmp_path)
    with pytest.raises(FastHdfError, match="injected"):
        RasMap.list_geometry_associations(ras_object=project)
    with pytest.raises(FastHdfError, match="injected"):
        RasMap.validate_geometry_associations(required_layers=("terrain",),
                                              raise_on_failure=False, ras_object=project)


@pytest.mark.parametrize("mode", FALLBACK_MODES)
def test_geometry_association_validation_fallback_unchanged(tmp_path, monkeypatch, mode):
    from ras_commander import RasMap, _geometry_association

    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    project = _association_project(tmp_path)
    ok = RasMap.validate_geometry_associations(required_layers=("terrain",),
                                               raise_on_failure=False, ras_object=project).iloc[0]
    assert bool(ok["passed"]) and ok["missing_required_layers"] == ()
    monkeypatch.setattr(_geometry_association, "read_geometry_association", _refuse)
    row = RasMap.list_geometry_associations(ras_object=project).iloc[0]
    assert row["inspection_status"] == "failed"
    assert row["inspection_error"] == "injected native refusal"
    assert not bool(row["terrain_associated"])


@pytest.mark.parametrize("mode", FALLBACK_MODES + REQUIRED_MODES)
def test_landcover_diagnostic_policy(tmp_path, monkeypatch, mode):
    from ras_commander import _geometry_association

    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    monkeypatch.setattr(_geometry_association, "read_geometry_association", _refuse)
    hdf = tmp_path / "m.g01.hdf"
    with h5py.File(hdf, "w") as handle:
        handle.create_group("Geometry")
    if mode in REQUIRED_MODES:
        with pytest.raises(FastHdfError, match="injected"):
            _geometry_association.landcover_association_diagnostic(hdf)
    else:
        text = _geometry_association.landcover_association_diagnostic(hdf)
        assert text.startswith("Could not inspect the land-cover association")


# --- Additional handlers found by the audit (same pattern) ---

def _regions_cases(tmp_path, monkeypatch):
    from ras_commander.geom.ManningsFromLandCover import ManningsFromLandCover
    from ras_commander.hdf.HdfLandCover import HdfLandCover

    for name in ("get_classification_polygons", "get_landcover_raster_map",
                 "get_mannings_calibration_table", "get_mannings_region_polygons"):
        monkeypatch.setattr(HdfLandCover, name, staticmethod(_refuse))
    sidecar = tmp_path / "LandCover.hdf"
    sidecar.write_bytes(b"")
    geom = tmp_path / "m.g01"
    Path(str(geom) + ".hdf").write_bytes(b"")
    return [
        lambda: ManningsFromLandCover._load_land_cover_sidecar_regions(sidecar, None, {}, {}),
        lambda: ManningsFromLandCover._load_geometry_hdf_regions(geom, None, {}, {}),
    ]


@pytest.mark.parametrize("mode", FALLBACK_MODES + REQUIRED_MODES)
def test_mannings_region_loaders_policy(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    for call in _regions_cases(tmp_path, monkeypatch):
        if mode in REQUIRED_MODES:
            with pytest.raises(FastHdfError, match="injected"):
                call()
        else:
            assert call() == []


@pytest.mark.parametrize("mode", FALLBACK_MODES + REQUIRED_MODES)
def test_permutation_max_wse_policy(tmp_path, monkeypatch, mode):
    from ras_commander.RasPermutation import RasPermutation
    from ras_commander.hdf import HdfChannelCapacity, HdfResultsMesh

    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    monkeypatch.setattr(HdfChannelCapacity, "extract_max_wse", staticmethod(_refuse))
    monkeypatch.setattr(HdfResultsMesh, "get_mesh_max_ws", staticmethod(_refuse))
    if mode in REQUIRED_MODES:
        with pytest.raises(FastHdfError, match="injected"):
            RasPermutation._extract_max_wse(tmp_path / "x.p01.hdf")
    else:
        assert np.isnan(RasPermutation._extract_max_wse(tmp_path / "x.p01.hdf"))


@pytest.mark.parametrize("mode", FALLBACK_MODES + REQUIRED_MODES)
def test_preprocessor_compute_messages_policy(tmp_path, monkeypatch, mode):
    from ras_commander.geom.GeomPreprocessor import GeomPreprocessor
    from ras_commander.hdf.HdfResultsPlan import HdfResultsPlan

    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    monkeypatch.setattr(HdfResultsPlan, "get_compute_messages_hdf_only", staticmethod(_refuse))
    hdf = tmp_path / "m.p01.hdf"
    hdf.write_bytes(b"x")
    if mode in REQUIRED_MODES:
        with pytest.raises(FastHdfError, match="injected"):
            GeomPreprocessor._read_compute_messages([], hdf)
    else:
        assert GeomPreprocessor._read_compute_messages([], hdf) == ([], "")


# --- C2: safe-file guard before the typed-inventory engine call ---

def _break_lines(handle):
    g = handle.create_group("Geometry/2D Flow Area Break Lines")
    g["Attributes"] = np.array([(b"BL1",)], dtype=[("Name", "S16")])
    g["Polyline Info"] = np.array([[0, 2, 0, 1]], dtype=np.int32)
    g["Polyline Parts"] = np.array([[0, 2]], dtype=np.int32)
    g["Polyline Points"] = np.array([[0.0, 0.0], [1.0, 1.0]])


@needs_native
@pytest.mark.parametrize("mode", FALLBACK_MODES + REQUIRED_MODES)
def test_typed_inventory_refuses_writable_handle_before_engine(tmp_path, monkeypatch, mode):
    from ras_commander import _fast_hdf_typed

    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    path = tmp_path / "lines.hdf"
    with h5py.File(path, "w") as handle:
        _break_lines(handle)
    expected = [[0.0, 0.0], [1.0, 1.0]]

    member_calls = []
    real_member = _fast_hdf_typed._member

    def spy(*args, **kwargs):
        member_calls.append(args[1:])
        return real_member(*args, **kwargs)

    monkeypatch.setattr(_fast_hdf_typed, "_member", spy)
    with h5py.File(path, "r+") as handle:
        ds = handle["Geometry/2D Flow Area Break Lines/Polyline Points"]
        assert not fast_hdf._safe_file(ds)
        if mode in REQUIRED_MODES:
            with pytest.raises(FastHdfError, match="file cannot be reopened safely") as info:
                fast_hdf.read_typed(ds)
            assert "os error" not in str(info.value)
        else:
            with fast_hdf.trace_reads() as trace:
                assert fast_hdf.read_typed(ds).tolist() == expected
            if mode == "auto":
                assert trace[-1]["backend"] == "h5py-fallback"
    # The engine never opened the file for the writable handle.
    assert member_calls == []
    # A read-only handle still uses the engine inventory.
    with h5py.File(path, "r") as handle:
        assert fast_hdf.read_typed(handle["Geometry/2D Flow Area Break Lines/Polyline Points"]).tolist() == expected
    if mode != "h5py":
        assert member_calls
