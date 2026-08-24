import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from ras_commander.RasExamples import RasExamples
from ras_commander.RasPlan import RasPlan
from ras_commander.RasPrj import RasPrj


pytestmark = pytest.mark.integration

MANIFEST_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "plan_classification"
    / "rasexamples_7_0.json"
)


def _load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_project_file(project_folder: Path) -> Path:
    candidates = []
    for path in project_folder.rglob("*.prj"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "Plan File=" in text:
            candidates.append(path)
    assert len(candidates) == 1, (
        f"Expected one plan-bearing project in {project_folder}, found {candidates}"
    )
    return candidates[0]


def _load_project(project_folder: Path) -> RasPrj:
    prj_path = _find_project_file(project_folder)
    project = RasPrj()
    project.initialized = True
    project.prj_file = prj_path
    project.project_folder = prj_path.parent
    project.project_name = prj_path.stem
    project.suppress_logging = True
    project.geom_df = project.get_geom_entries()
    project.plan_df = project.get_plan_entries()
    return project


def _fixture_database_path() -> Path:
    database_override = os.environ.get("RAS_COMMANDER_CLB_FIXTURE_DB")
    return (
        Path(database_override)
        if database_override
        else Path("feature_dev_notes")
        / "Database of Project Fixtures"
        / "project_fixtures.sqlite3"
    )


def _project_path_from_database(database_path: Path, project_id: int) -> Path:
    connection = sqlite3.connect(
        f"file:{database_path.as_posix()}?mode=ro",
        uri=True,
    )
    try:
        row = connection.execute(
            "SELECT prj_file FROM projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise LookupError(f"Fixture database has no project_id={project_id}")
    return Path(row[0])


@pytest.fixture(scope="module")
def real_projects(tmp_path_factory):
    manifest = _load_manifest()
    archive_meta = manifest["archive"]
    archive_override = os.environ.get("RAS_COMMANDER_EXAMPLE_ARCHIVE")
    archive_path = (
        Path(archive_override)
        if archive_override
        else RasExamples._user_data_dir / archive_meta["filename"]
    )
    if not archive_path.is_file():
        pytest.skip(
            "Pinned HEC-RAS 7.0 example archive is not cached; set "
            "RAS_COMMANDER_EXAMPLE_ARCHIVE to run real classification fixtures"
        )

    assert archive_path.stat().st_size == archive_meta["size_bytes"]
    assert _sha256(archive_path) == archive_meta["sha256"]

    previous_archive = RasExamples._zip_file_path
    previous_folders = RasExamples._folder_df
    RasExamples._zip_file_path = archive_path
    RasExamples._folder_df = None
    RasExamples._extract_folder_structure()

    project_names = list(manifest["projects"])
    output_path = tmp_path_factory.mktemp("plan_classification_examples")
    try:
        extracted = RasExamples.extract_project(
            project_names,
            output_path=output_path,
            suffix="plan_classification",
        )
        yield dict(zip(project_names, extracted))
    finally:
        RasExamples._zip_file_path = previous_archive
        RasExamples._folder_df = previous_folders


def test_portable_real_fixture_matrix(real_projects):
    manifest = _load_manifest()

    for project_name, expected_plans in manifest["projects"].items():
        project = _load_project(real_projects[project_name])
        rows = project.plan_df.set_index("plan_number")
        for plan_number, expected_type in expected_plans.items():
            assert rows.loc[plan_number, "plan_type"] == expected_type
            assert bool(rows.loc[plan_number, "plan_classification_valid"])

    chippewa = _load_project(real_projects["Chippewa_2D"])
    chippewa_row = chippewa.plan_df.set_index("plan_number").loc["02"]
    assert chippewa_row["flow_file_prefix"] == "u"
    assert chippewa_row["Sediment File"] == "01"

    bstem = _load_project(real_projects["BSTEM - Simple Example"])
    bstem_row = bstem.plan_df.set_index("plan_number").loc["02"]
    assert bstem_row["flow_file_prefix"] == "q"
    assert bstem_row["Sediment File"] == "02"


def test_muncie_and_chippewa_text_only_2d_detection(real_projects, tmp_path):
    muncie_copy = tmp_path / "muncie_text"
    shutil.copytree(real_projects["Muncie"], muncie_copy)
    (muncie_copy / "Muncie.g02.hdf").unlink()
    muncie = _load_project(muncie_copy)
    muncie_row = muncie.plan_df.set_index("plan_number").loc["03"]
    assert muncie_row["plan_type"] == "unsteady_1d_2d"
    assert muncie_row["geometry_metadata_source"] == "text"
    assert pd.isna(muncie_row["mesh_cell_count"])
    assert muncie_row["mesh_area_names"] == ["2D Interior Area"]

    chippewa_copy = tmp_path / "chippewa_text"
    shutil.copytree(real_projects["Chippewa_2D"], chippewa_copy)
    (chippewa_copy / "Chippewa_2D.g01.hdf").unlink()
    chippewa = _load_project(chippewa_copy)
    chippewa_row = chippewa.plan_df.set_index("plan_number").loc["02"]
    assert chippewa_row["plan_type"] == "unsteady_2d"
    assert chippewa_row["geometry_metadata_source"] == "text"
    assert pd.isna(chippewa_row["mesh_cell_count"])


def test_missing_and_corrupt_geometry_hdf_fail_or_fallback(real_projects, tmp_path):
    missing_copy = tmp_path / "muncie_missing"
    shutil.copytree(real_projects["Muncie"], missing_copy)
    (missing_copy / "Muncie.g02.hdf").unlink()
    (missing_copy / "Muncie.g02").unlink()
    missing = _load_project(missing_copy)
    missing_row = missing.plan_df.set_index("plan_number").loc["03"]
    assert missing_row["plan_type"] == "unknown"
    assert not bool(missing_row["plan_classification_valid"])
    assert missing_row["geometry_metadata_source"] == "unavailable"

    corrupt_copy = tmp_path / "muncie_corrupt"
    shutil.copytree(real_projects["Muncie"], corrupt_copy)
    (corrupt_copy / "Muncie.g02.hdf").write_bytes(b"not an hdf file")
    corrupt = _load_project(corrupt_copy)
    corrupt_row = corrupt.plan_df.set_index("plan_number").loc["03"]
    assert corrupt_row["plan_type"] == "unsteady_1d_2d"
    assert corrupt_row["geometry_metadata_source"] == "text"
    assert "HDF inspection failed" in corrupt_row["geometry_metadata_error"]


def test_real_mutations_refresh_classification_and_refuse_steady_2d(
    real_projects,
    tmp_path,
):
    muncie_copy = tmp_path / "muncie_mutation"
    shutil.copytree(real_projects["Muncie"], muncie_copy)
    muncie = _load_project(muncie_copy)
    RasPlan.set_steady("03", "01", muncie)
    row = muncie.plan_df.set_index("plan_number").loc["03"]
    assert row["flow_type"] == "Steady"
    assert row["geometry_type"] == "1D/2D"
    assert row["plan_type"] == "unknown"
    assert "steady solver" in row["plan_classification_reason"]

    wailupe_copy = tmp_path / "wailupe_mutation"
    shutil.copytree(real_projects["Wailupe GeoRAS"], wailupe_copy)
    wailupe = _load_project(wailupe_copy)
    before = wailupe.plan_df.set_index("plan_number").loc["01"]
    assert before["num_cross_sections"] == 47
    RasPlan.set_geom("01", "02", wailupe)
    after = wailupe.plan_df.set_index("plan_number").loc["01"]
    assert after["geometry_number"] == "02"
    assert after["num_cross_sections"] == 209
    assert after["plan_type"] == "steady_1d"
    assert after["geometry_metadata_source"] == "text"


@pytest.mark.qualification_critical
def test_clb_1106_text_only_631_2d_regression():
    database_path = _fixture_database_path()
    if not database_path.is_file():
        pytest.skip("CLB fixture database is not available")

    project_path = _project_path_from_database(database_path, 1106)
    if not project_path.is_file():
        pytest.skip("CLB fixture 1106 is not mounted")

    project = _load_project(project_path.parent)
    plan = project.plan_df.set_index("plan_number").loc["01"]
    assert plan["Program Version"] == "6.31"
    assert plan["flow_type"] == "Unsteady"
    assert plan["geometry_type"] == "2D"
    assert plan["plan_type"] == "unsteady_2d"
    assert plan["geometry_metadata_source"] == "text"
    assert plan["mesh_area_names"] == ["Perimeter 1"]
    assert pd.isna(plan["mesh_cell_count"])


@pytest.mark.qualification_critical
def test_clb_670_and_700_geometry_hdf_schema_regressions():
    database_path = _fixture_database_path()
    if not database_path.is_file():
        pytest.skip("CLB fixture database is not available")

    expected = {
        21: {
            "version": "6.70",
            "plans": {"01", "03"},
            "plan_type": "unsteady_2d",
        },
        1514: {
            "version": "7.00",
            "plans": {"03", "17"},
            "plan_type": "unsteady_1d",
        },
    }
    for project_id, contract in expected.items():
        project_path = _project_path_from_database(database_path, project_id)
        if not project_path.is_file():
            pytest.skip(f"CLB fixture {project_id} is not mounted")
        project = _load_project(project_path.parent)
        rows = project.plan_df[
            project.plan_df["plan_number"].isin(contract["plans"])
        ]
        assert set(rows["plan_number"]) == contract["plans"]
        assert set(rows["Program Version"]) == {contract["version"]}
        assert set(rows["plan_type"]) == {contract["plan_type"]}
        assert set(rows["geometry_metadata_source"]) == {"hdf"}
        assert rows["plan_classification_valid"].all()
