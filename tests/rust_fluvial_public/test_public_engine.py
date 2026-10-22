"""Public HdfFluvialPluvial engine contract on real computed HEC-RAS fixtures.

Fixtures are immutable local copies named by RAS_FLUVIAL_PUBLIC_FIXTURES:
BaldEagleDamBrk.p07.hdf (stored 6.6, one mesh, 87039 cells),
BaldEagleDamBrk.p18.hdf (stored 7.0, two meshes, 4425 cells) and
BaldEagleDamBrk.p03.hdf (stored 6.6, no peak results). A missing fixture is
reported as skipped (unavailable), never as a pass.

engine="python" is the reference. engine="native" must equal it exactly or
raise; tests count native kernel calls and make the Python classification
loop and dissolve fail so that native results cannot come from a fallback.
"""
import contextlib
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import ras_commander_fast_hdf
from ras_commander.hdf import HdfFluvialNative

# ras_commander.hdf re-exports the class under the module's name; get the module.
module = importlib.import_module("ras_commander.hdf.HdfFluvialPluvial")
from ras_commander.hdf.HdfFluvialPluvial import (
    FluvialNativeUnsupportedError,
    HdfFluvialPluvial,
    _hours_to_ms,
)

FIXTURES = Path(os.environ.get("RAS_FLUVIAL_PUBLIC_FIXTURES", "missing"))
REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "qualify_public", REPO / "scripts/benchmarks/rust_fluvial_public/qualify_public.py")
qualify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qualify)


def fixture(name):
    path = FIXTURES / name
    if not path.exists():
        pytest.skip(f"fixture unavailable: {path}")
    return path


def native_calls():
    return dict(HdfFluvialNative.NATIVE_CALLS)


def delta(before):
    after = native_calls()
    return {k: after[k] - before.get(k, 0) for k in after if after[k] - before.get(k, 0)}


@contextlib.contextmanager
def forbid_python_classification():
    """The Python region-growing loop and the legacy per-cell dissolve must not run."""
    import geopandas

    def fail(*args, **kwargs):
        raise AssertionError("Python classification loop executed under engine='native'")
    original = geopandas.GeoDataFrame.dissolve

    def guarded(self, *args, **kwargs):
        if len(self) > 1000:  # the legacy per-cell dissolve, not the region-level area swap
            raise AssertionError("legacy per-cell dissolve executed under engine='native'")
        return original(self, *args, **kwargs)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module, "tqdm", fail)
        patch.setattr(geopandas.GeoDataFrame, "dissolve", guarded)
        yield


def save(frame, path):
    frame.to_parquet(path)
    return path


def test_native_module_and_package_paths():
    assert Path(module.__file__).resolve().is_relative_to(REPO)
    assert Path(ras_commander_fast_hdf.__file__).exists()
    assert hasattr(ras_commander_fast_hdf.NativeAnalysis, "qualifying_edges")


def test_public_defaults_unchanged():
    polygons = inspect.signature(HdfFluvialPluvial.generate_fluvial_pluvial_polygons)
    boundary = inspect.signature(HdfFluvialPluvial.calculate_fluvial_pluvial_boundary)
    assert polygons.parameters["delta_t"].default == 12
    assert polygons.parameters["temporal_tolerance_hours"].default == 1.0
    assert polygons.parameters["min_polygon_area_acres"].default is None
    assert polygons.parameters["engine"].default == "python"
    assert polygons.parameters["engine"].kind is inspect.Parameter.KEYWORD_ONLY
    assert boundary.parameters["delta_t"].default == 12
    assert boundary.parameters["min_line_length"].default is None
    assert boundary.parameters["engine"].default == "python"


@pytest.mark.parametrize("engine", ["rust", "", None, "Native"])
def test_unknown_engine_rejected(engine):
    hdf = fixture("BaldEagleDamBrk.p18.hdf")  # path validation precedes engine validation
    with pytest.raises(ValueError, match="engine must be one of"):
        HdfFluvialPluvial.generate_fluvial_pluvial_polygons(hdf, engine=engine)
    with pytest.raises(ValueError, match="engine must be one of"):
        HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(hdf, engine=engine)


def test_thresholds_are_exact_milliseconds():
    assert _hours_to_ms(12, "d") == 43_200_000
    assert _hours_to_ms(1.0, "d") == 3_600_000
    assert _hours_to_ms(0.5, "d") == 1_800_000
    assert _hours_to_ms(0, "d") == 0
    for bad in (1e-9, 1 / 3, -1, float("nan"), float("inf"), True, "12"):
        with pytest.raises(FluvialNativeUnsupportedError):
            _hours_to_ms(bad, "d")


def test_p07_polygons_native_equals_python(tmp_path):
    hdf = fixture("BaldEagleDamBrk.p07.hdf")
    before_hash = qualify.sha256(hdf)
    reference = save(_python_polygons(hdf), tmp_path / "python.parquet")
    calls = native_calls()
    with forbid_python_classification():
        native = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(hdf, engine="native")
    used = delta(calls)
    assert native.attrs["fluvial_engine"] == {"requested": "native", "used": "native", "fallback_reason": None}
    assert used["face_graph"] == 1 and used["assemble_rings"] == 1 and used["NativeAnalysis"] == 1
    assert used["NativeAnalysis.classify"] >= 1 and used["NativeAnalysis.polygons"] == 1
    info = native.attrs["fluvial_native"]
    # Set-based seeding (#572): conflicting seeds are ambiguous in both engines; no replay.
    assert info["classification"]["conflicting_seeds"] == 3
    assert "python_seed_tie_breaks" not in info
    result = qualify.compare_polygons(reference, save(native, tmp_path / "native.parquet"))
    assert result["equal"], json.dumps(result, default=str)
    assert all(c["symmetric_difference_area"] == 0 for c in result["classes"].values())
    assert qualify.sha256(hdf) == before_hash


def _python_polygons(hdf, **kwargs):
    calls = native_calls()
    frame = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(hdf, engine="python", **kwargs)
    assert delta(calls) == {}, "python engine must not call fluvial native kernels"
    assert "fluvial_engine" not in frame.attrs
    assert not frame.empty
    return frame


def test_p07_min_area_swap_is_never_native_and_auto_matches_python(tmp_path):
    """Legacy swap keeps union-order-dependent 'first' attributes: native refuses.

    Removal (HdfFluvialNative.Analysis area_filter_policy='remove') is a different
    policy and is never substituted. auto selects the unchanged Python swap.
    """
    hdf = fixture("BaldEagleDamBrk.p07.hdf")
    calls = native_calls()
    with pytest.raises(FluvialNativeUnsupportedError, match="class swapping"):
        HdfFluvialPluvial.generate_fluvial_pluvial_polygons(hdf, min_polygon_area_acres=1000.0, engine="native")
    assert delta(calls) == {}, "rejected before any native work"
    reference = _python_polygons(hdf, min_polygon_area_acres=1000.0)
    unswapped = _python_polygons(hdf)
    parts = lambda frame: sum(len(getattr(g, "geoms", [g])) for g in frame.geometry)
    assert parts(reference) < parts(unswapped)  # the swap actually happened
    # Swapping relabels, never deletes: total area is conserved.
    assert reference.geometry.area.sum() == pytest.approx(unswapped.geometry.area.sum(), rel=1e-12)
    auto = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(hdf, min_polygon_area_acres=1000.0, engine="auto")
    assert auto.attrs["fluvial_engine"]["used"] == "python"
    assert "class swapping" in auto.attrs["fluvial_engine"]["fallback_reason"]
    auto.attrs.clear()
    assert auto.to_wkb().equals(reference.to_wkb())


def test_p07_boundary_native_equals_python(tmp_path):
    hdf = fixture("BaldEagleDamBrk.p07.hdf")
    calls = native_calls()
    reference = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(hdf, engine="python")
    assert delta(calls) == {}
    calls = native_calls()
    with forbid_python_classification():
        native = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(hdf, engine="native")
    used = delta(calls)
    assert used["NativeAnalysis.qualifying_edges"] == 1 and used["face_graph"] == 1
    assert native.attrs["fluvial_native"]["qualifying_edges"] == len(reference) == 4569
    # Every shared face is kept (#572); rows are in the reference's sorted pair order.
    assert "python_segment_tie_breaks" not in native.attrs["fluvial_native"]
    result = qualify.compare_boundary(save(reference, tmp_path / "p.parquet"), save(native, tmp_path / "n.parquet"))
    assert result["equal"], result
    assert all(a.equals_exact(b, 0) for a, b in zip(native.geometry, reference.geometry))
    short = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(hdf, min_line_length=100.0, engine="native")
    expected = reference[reference.length >= 100.0]
    assert 0 < len(short) == len(expected) < len(reference)


def test_p07_auto_selects_native():
    hdf = fixture("BaldEagleDamBrk.p07.hdf")
    frame = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(hdf, engine="auto")
    assert frame.attrs["fluvial_engine"]["used"] == "native"


@contextlib.contextmanager
def single_mesh_inputs(hdf, mesh_name):
    """Python restricted to one mesh's rows: an independent per-mesh oracle."""
    from ras_commander.hdf import HdfMesh, HdfResultsMesh
    polygons = HdfMesh.get_mesh_cell_polygons(hdf)
    max_ws = HdfResultsMesh.get_mesh_max_ws(hdf)
    polygons = polygons[polygons["mesh_name"] == mesh_name].copy()
    max_ws = max_ws[max_ws["mesh_name"] == mesh_name].copy()
    assert polygons["cell_id"].is_unique and max_ws["cell_id"].is_unique
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module.HdfMesh, "get_mesh_cell_polygons", staticmethod(lambda *a, **k: polygons.copy()))
        patch.setattr(module.HdfResultsMesh, "get_mesh_max_ws", staticmethod(lambda *a, **k: max_ws.copy()))
        yield len(polygons)


def test_p18_two_meshes_auto_native_equals_mesh_scoped_python(tmp_path):
    """Python keys cells by (mesh_name, cell_id) (#564), so two meshes are defined.

    engine='auto' now selects the native composite analysis and returns the
    Python reference's polygons and lines.
    """
    hdf = fixture("BaldEagleDamBrk.p18.hdf")
    reference = _python_polygons(hdf)
    assert reference["mesh_name"].nunique() == 2
    auto = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(hdf, engine="auto")
    assert auto.attrs["fluvial_engine"] == {"requested": "auto", "used": "native", "fallback_reason": None}
    assert list(auto.columns) == list(reference.columns)
    assert list(zip(auto["mesh_name"], auto["classification"])) == list(
        zip(reference["mesh_name"], reference["classification"]))
    for name in sorted(set(reference["mesh_name"])):
        result = qualify.compare_polygons(
            save(reference[reference["mesh_name"] == name].reset_index(drop=True), tmp_path / f"{name}-p.parquet"),
            save(auto[auto["mesh_name"] == name].reset_index(drop=True), tmp_path / f"{name}-a.parquet"))
        assert result["equal"], json.dumps(result, default=str)
    lines = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(hdf, engine="auto")
    assert lines.attrs["fluvial_engine"]["used"] == "native"
    python_lines = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(hdf, engine="python")
    assert not python_lines.empty
    result = qualify.compare_boundary(save(python_lines, tmp_path / "pl.parquet"),
                                      save(lines, tmp_path / "al.parquet"))
    assert result["equal"], result


def test_p18_two_meshes_native_composite_equals_per_mesh_python(tmp_path):
    hdf = fixture("BaldEagleDamBrk.p18.hdf")
    before_hash = qualify.sha256(hdf)
    analysis = HdfFluvialNative.Analysis.from_hdf(hdf, wet_policy="all")
    meshes = analysis.meshes
    assert len(meshes) == 2 and len(analysis.keys) == 4425
    # Composite identities: unique, and their union is every physical cell.
    identities = [(meshes[m], row) for m, row in analysis.sources]
    assert len(set(identities)) == len(identities) == 4425
    per_mesh = {name: sum(1 for m, _ in analysis.sources if meshes[m] == name) for name in meshes}
    repeated = {row for m, row in analysis.sources if m == 0} & {row for m, row in analysis.sources if m == 1}
    assert repeated, "fixture must exercise repeated local cell IDs"
    # The native face graph never joins cells of different meshes.
    for i in range(len(analysis.keys)):
        for j in analysis.neighbors[analysis.offsets[i]:analysis.offsets[i + 1]]:
            assert analysis.sources[i][0] == analysis.sources[j][0]

    calls = native_calls()
    with forbid_python_classification():
        native = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(hdf, engine="native")
    used = delta(calls)
    assert native.attrs["fluvial_engine"] == {"requested": "native", "used": "native", "fallback_reason": None}
    assert used["face_graph"] == 1 and used["assemble_rings"] == 2 and used["NativeAnalysis"] == 1
    assert used["NativeAnalysis.polygons"] == 1
    info = native.attrs["fluvial_native"]
    assert "python_seed_tie_breaks" not in info
    assert set(native["mesh_name"]) == set(meshes)
    assert not native.duplicated(["mesh_name", "classification"]).any()

    calls = native_calls()
    with forbid_python_classification():
        native_lines = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(hdf, engine="native")
    assert delta(calls)["NativeAnalysis.qualifying_edges"] == 1
    native_lines = native_lines.assign(_n=range(len(native_lines)))

    oracle_lines = []
    for name in meshes:
        with single_mesh_inputs(hdf, name) as cells:
            assert cells == per_mesh[name]
            reference = _python_polygons(hdf)
            oracle_lines.append(HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(hdf, engine="python"))
        mine = native[native["mesh_name"] == name].reset_index(drop=True)
        assert set(reference["mesh_name"]) == {name}
        result = qualify.compare_polygons(save(reference, tmp_path / f"{name}-p.parquet"),
                                          save(mine, tmp_path / f"{name}-n.parquet"))
        assert result["equal"], json.dumps(result, default=str)
        assert sorted(reference["classification"]) == sorted(mine["classification"])
        first = dict(zip(reference["classification"], reference["cell_id"]))
        assert first == dict(zip(mine["classification"], mine["cell_id"]))
    oracle = pandas_concat(oracle_lines)
    assert len(native_lines) == len(oracle) == info_edges(native_lines)
    result = qualify.compare_boundary(save(oracle, tmp_path / "op.parquet"),
                                      save(native_lines.drop(columns="_n"), tmp_path / "on.parquet"))
    assert result["equal"], result
    assert qualify.sha256(hdf) == before_hash


def pandas_concat(frames):
    import geopandas
    import pandas
    return geopandas.GeoDataFrame(pandas.concat(frames, ignore_index=True), crs=frames[0].crs)


def info_edges(lines):
    return lines.attrs["fluvial_native"]["qualifying_edges"]


def test_inexact_threshold_native_rejects_auto_falls_back():
    hdf = fixture("BaldEagleDamBrk.p07.hdf")
    with pytest.raises(FluvialNativeUnsupportedError, match="exact integer number of milliseconds"):
        HdfFluvialPluvial.generate_fluvial_pluvial_polygons(hdf, delta_t=1 / 3, engine="native")
    with pytest.raises(FluvialNativeUnsupportedError, match="delta_t=0"):
        HdfFluvialPluvial.generate_fluvial_pluvial_polygons(hdf, delta_t=0, engine="native")
    with pytest.raises(FluvialNativeUnsupportedError, match="negative"):
        HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(hdf, delta_t=-1, engine="native")


def test_uncomputed_results_are_fatal_not_empty():
    """p03 has geometry but no peak results: Python logs and returns empty; native raises."""
    hdf = fixture("BaldEagleDamBrk.p03.hdf")
    assert HdfFluvialPluvial.generate_fluvial_pluvial_polygons(hdf).empty
    for engine in ("native", "auto"):
        with pytest.raises(ValueError, match="empty peak table"):
            HdfFluvialPluvial.generate_fluvial_pluvial_polygons(hdf, engine=engine)


def test_corrupt_hdf_is_fatal_for_native_and_auto(tmp_path):
    source = fixture("BaldEagleDamBrk.p18.hdf")
    broken = tmp_path / "Broken.p18.hdf"
    with open(source, "rb") as handle:
        broken.write_bytes(handle.read(4096))
    for engine in ("native", "auto"):
        with pytest.raises(Exception) as caught:
            HdfFluvialPluvial.generate_fluvial_pluvial_polygons(broken, engine=engine)
        assert not isinstance(caught.value, FluvialNativeUnsupportedError)
    # The legacy reference keeps its documented log-and-return-empty behavior.
    assert HdfFluvialPluvial.generate_fluvial_pluvial_polygons(broken).empty


def _hash_native_polygons(hdf, threads):
    code = ("import sys,hashlib;from pathlib import Path;"
            "from ras_commander.hdf.HdfFluvialPluvial import HdfFluvialPluvial as F;"
            "f=F.generate_fluvial_pluvial_polygons(Path(sys.argv[1]),engine='native');"
            "print(hashlib.sha256(b''.join(g.wkb for g in f.geometry)+repr(f.drop(columns='geometry').values.tolist()).encode()).hexdigest())")
    env = dict(os.environ, RAYON_NUM_THREADS=str(threads))
    out = subprocess.run([sys.executable, "-c", code, str(hdf)], env=env, capture_output=True, text=True, check=True)
    return out.stdout.strip().splitlines()[-1]


def test_native_output_identical_at_1_and_4_threads():
    hdf = fixture("BaldEagleDamBrk.p07.hdf")
    assert _hash_native_polygons(hdf, 1) == _hash_native_polygons(hdf, 4)


def test_d601_invalid_source_cells_native_refuses():
    """Stored 5.0.7 D601 p04: 2 genuinely invalid source cells (crossing boundaries).

    Python keeps them in its stored-topology adjacency and GEOS dissolve, which
    native polygon assembly cannot reproduce without guessing; it refuses, and
    auto uses Python. Nothing is repaired. Explicit audited quarantine remains available
    through HdfFluvialNative.Analysis(invalid_geometry='quarantine').
    """
    hdf = fixture("JUL2020_D100RAS.p04.hdf")
    before = qualify.sha256(hdf)
    calls = native_calls()
    with pytest.raises(FluvialNativeUnsupportedError, match="2 cell\(s\) have invalid source geometry"):
        HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(hdf, engine="native")
    used = delta(calls)
    assert used["validate_geometry"] == 1 and used.get("NativeAnalysis.qualifying_edges", 0) == 0
    assert qualify.sha256(hdf) == before
