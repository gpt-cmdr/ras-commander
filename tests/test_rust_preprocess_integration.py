"""Integration tests for the experimental Rust preprocessor and its equivalence harness.

They run the real ``ras-preprocess`` engine and native HEC-RAS 7.0.1 (through
RAS Commander only) on ``RasExamples`` projects, and skip cleanly when either
is absent. The engine is not distributed with RAS Commander: point
``RAS_COMMANDER_PREPROCESS_EXE`` at a build of it.

Cases:
- Bald Eagle g09 (19,597 cells, SCS infiltration and impervious): equivalent.
- Muncie g02 with a SetValue polygon modification crossing 195 faces: equivalent.
- Muncie g02 with a rotated ellipse modification: refused, naming the layer.
- compute_rust_experimental() into a copy equals native bitwise, source untouched,
  with Property Tables Last Computed restamped and the LC hash kept.
- Muncie g02: a RasCmdr plan compute on the Rust tables reports them current and
  does not recompute the geometry.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import warnings
from pathlib import Path

import pytest

from ras_commander import ExperimentalWarning, GeomPreprocessor
from ras_commander.RasExamples import RasExamples
from ras_commander.geom import _rust_preprocess as rp

pytestmark = [
    pytest.mark.integration,
    pytest.mark.real_ras,
    pytest.mark.destructive_copy,
    pytest.mark.slow,
    pytest.mark.filterwarnings("ignore::ras_commander.geom._rust_preprocess.ExperimentalWarning"),
]


@pytest.fixture(scope="module")
def engine() -> Path:
    exe = os.environ.get(rp.ENGINE_ENV_VAR)
    if not exe or not Path(exe).is_file():
        pytest.skip(f"{rp.ENGINE_ENV_VAR} does not point at a ras-preprocess executable")
    return Path(exe)


@pytest.fixture(scope="module")
def hecras_701():
    if sys.platform != "win32":
        pytest.skip("native HEC-RAS 7.0.1 preprocessing requires Windows")
    from ras_commander.dotnet.clr_bootstrap import find_hecras_install

    try:
        install = find_hecras_install("7.0.1")
    except FileNotFoundError:
        pytest.skip("HEC-RAS 7.0.1 is not installed")
    if not (install / "Ras.exe").exists():
        pytest.skip("HEC-RAS 7.0.1 Ras.exe is not installed")
    return install


def _tree_sha(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def be09_report(engine, hecras_701, tmp_path_factory):
    root = tmp_path_factory.mktemp("rust_be09")
    src = RasExamples.extract_project("BaldEagleCrkMulti2D", output_path=root / "src")
    before = _tree_sha(src)
    report = GeomPreprocessor.validate_rust_equivalence(
        src, "09", work_dir=root / "work", engine_exe=engine, native_repeats=2)
    return src, before, report


def test_bald_eagle_g09_equivalent(be09_report):
    src, before, report = be09_report
    assert report.verdict == "equivalent", report.to_markdown()
    df = report.to_dataframe()
    products = df[df.category == "product"]
    assert len(products) >= 12
    assert set(products.status) == {"bitwise"}
    assert {"Faces Profile Values", "Cells Volume Elevation Values", "Infiltration/Curve Number"} <= set(products.dataset)
    assert (df[df.category == "input"].status == "bitwise").all()
    assert report.native_runs == 2 and report.native_nondeterminism == []
    assert report.engine.sha256 and report.engine.version.startswith("ras-preprocess")
    # Stage 2 coverage is stated: --compare does not cover these arrays yet.
    cov = report.stage2_coverage["BaldEagleCr"]
    assert "Infiltration/Curve Number" in cov["compared"]
    assert "Percent Impervious/Percent Impervious" in cov["compared"]
    assert set(cov["present"]) == set(cov["compared"]) | set(cov["not_compared"])
    md = report.report_markdown.read_text(encoding="utf-8")
    assert "Stage 2 infiltration and impervious coverage" in md and "workstream P" in md
    assert report.options["restamp_currency"] is True
    assert report.report_json.is_file() and report.report_markdown.is_file()
    # The source project is never written.
    assert _tree_sha(src) == before


def test_compute_rust_experimental_matches_native(be09_report, engine, tmp_path):
    _, _, report = be09_report
    native_live = report.work_dir / "native" / report.geometry  # inside a project copy: layers resolve
    source_sha = hashlib.sha256(native_live.read_bytes()).hexdigest()
    out = tmp_path / "rust" / report.geometry
    with pytest.warns(ExperimentalWarning):
        result = GeomPreprocessor.compute_rust_experimental(native_live, out_path=out, engine_exe=engine)
    assert result.geometry_hdf == out and not result.in_place
    assert result.source_sha256 == source_sha == hashlib.sha256(native_live.read_bytes()).hexdigest()
    assert result.options["mode"] == "native"
    assert result.engine.sha256 == report.engine.sha256
    assert result.writeback["datasets_written"] >= 12
    # Currency: Last Computed restamped in native's format; the LC hash kept and reported.
    assert result.options["restamp_currency"] is True
    cur = result.currency
    assert cur["areas"]["BaldEagleCr"][rp.LAST_COMPUTED_ATTR]["status"] == "restamped"
    assert cur["attributes_changed"] == [f"{rp.AREAS}/BaldEagleCr@{rp.LAST_COMPUTED_ATTR}"]
    assert rp.LC_HASH_ATTR in cur["not_restamped"]["BaldEagleCr"]
    assert len(cur["stamp"]) == 18 and cur["stamp"][2:5].isupper()
    comparisons, _ = rp.compare_geometry_hdfs(report.native_geometry_hdfs[0], out)
    assert all(c.bitwise for c in comparisons)


@pytest.fixture(scope="module")
def muncie_factory(engine, hecras_701, tmp_path_factory):
    from ras_commander.terrain.RasTerrainModWriter import RasTerrainModWriter

    def make(tag: str, add):
        root = tmp_path_factory.mktemp(f"rust_{tag}")
        src = RasExamples.extract_project("Muncie", output_path=root / "src")
        add(RasTerrainModWriter, src / "Terrain" / "Terrain.hdf", src / "Muncie.rasmap")
        return GeomPreprocessor.validate_rust_equivalence(src, "02", work_dir=root / "work", engine_exe=engine)

    return make


def test_muncie_polygon_modification_crossing_faces_equivalent(muncie_factory):
    square = [[407800.0, 1802800.0], [408300.0, 1802800.0], [408300.0, 1803300.0], [407800.0, 1803300.0]]
    report = muncie_factory("muncie_pad", lambda W, terrain, rasmap: W.add_modification_polygon(
        terrain, rasmap_path=rasmap, name="PadSet", elevation=945.37, mode="set_value", polygon_coords=square))
    assert report.verdict == "equivalent", report.to_markdown()
    assert all(c.bitwise for c in report.comparisons)


def test_muncie_rotated_ellipse_is_refused(muncie_factory):
    report = muncie_factory("muncie_ellipse", lambda W, terrain, rasmap: W.add_ellipse_modification(
        terrain, rasmap, name="Basin", mode="set_value",
        ellipses=[{"center": (408050.0, 1803000.0), "radius_x": 200.0, "radius_y": 80.0,
                   "rotation": 30.0, "elevation": 930.0}]))
    assert report.verdict == "refused"
    assert "Basin" in report.refusal and "rotated ellipse" in report.refusal
    assert report.comparisons == [] and report.report_markdown.is_file()


def test_muncie_plan_compute_accepts_rust_tables(engine, hecras_701, tmp_path):
    """A ras-commander plan compute treats the Rust tables as current and completes."""
    from datetime import datetime, timedelta

    import h5py

    from ras_commander import RasCmdr, RasPlan, init_ras_project
    from ras_commander.RasCurrency import RasCurrency
    from ras_commander.RasPrj import RasPrj
    from ras_commander.hdf import HdfResultsPlan

    src = RasExamples.extract_project("Muncie", output_path=tmp_path / "src")
    ras = init_ras_project(src, "7.0.1", ras_object=RasPrj(), load_results_summary=False, hide_intro=True)
    plan = "03"
    start = datetime(1900, 1, 2)
    RasPlan.update_simulation_date(plan, start, start + timedelta(hours=2), ras_object=ras)
    phdf = src / "Muncie.p03.hdf"
    # Native first, as the harness stages a model: convert the geometry to 7.0.1, then
    # plan-compute twice. The first plan compute rebuilds the tables whatever they hold;
    # the second is the control, native accepting its own state.
    assert GeomPreprocessor.run_geometry_preprocessor(plan, ras_object=ras).success
    for _ in range(2):
        assert RasCmdr.compute_plan(plan, ras_object=ras, force_rerun=True)
    native_msgs = HdfResultsPlan.get_compute_messages(phdf)
    assert "Mesh property tables are current" in native_msgs, native_msgs
    ghdf = src / "Muncie.g02.hdf"
    result = GeomPreprocessor.compute_rust_experimental(ghdf, in_place=True, engine_exe=engine)
    Path(result.writeback["backup"]).unlink(missing_ok=True)
    assert result.currency["areas"]["2D Interior Area"][rp.LAST_COMPUTED_ATTR]["status"] == "restamped"
    assert RasCurrency.is_geom_preprocessing_current(plan, ras)[0]
    datasets, attrs = rp._dataset_hashes(ghdf), rp._attribute_snapshot(ghdf)

    assert RasCmdr.compute_plan(plan, ras_object=ras, force_rerun=True)
    msgs = HdfResultsPlan.get_compute_messages(phdf)
    assert "Mesh property tables are current" in msgs, msgs
    assert "Property tables do not exist" not in msgs and "Finished Unsteady Flow Simulation" in msgs
    # The geometry's tables and attributes (the restamp included) are what the Rust write left.
    assert rp._dataset_hashes(ghdf) == datasets
    assert rp._attribute_snapshot(ghdf) == attrs
    with h5py.File(ghdf, "r") as fg, h5py.File(phdf, "r") as fp:
        k = f"{rp.AREAS}/2D Interior Area/Cells Volume Elevation Values"
        assert fp[k][()].tobytes() == fg[k][()].tobytes()
