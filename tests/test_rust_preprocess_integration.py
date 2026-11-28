"""Integration tests for the experimental Rust preprocessor and its equivalence harness.

They run the real ``ras-preprocess`` engine and native HEC-RAS 7.0.1 (through
RAS Commander only) on ``RasExamples`` projects, and skip cleanly when either
is absent. The engine is not distributed with RAS Commander: point
``RAS_COMMANDER_PREPROCESS_EXE`` at a build of it.

Cases:
- Bald Eagle g09 (19,597 cells, SCS infiltration and impervious): equivalent.
- Muncie g02 with a SetValue polygon modification crossing 195 faces: equivalent.
- Muncie g02 with a rotated ellipse modification: refused, naming the layer.
- compute_rust_experimental() into a copy equals native bitwise, source untouched.
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
