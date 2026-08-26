"""Qualification checks against immutable, externally mounted steady HDFs."""

import hashlib
import os
from pathlib import Path
import sqlite3

import h5py
import numpy as np
import pytest

from ras_commander.hdf import HdfResultsPlan


pytestmark = [pytest.mark.integration, pytest.mark.qualification_critical]

EXPECTED_631_SHA256 = (
    "9f42e4313fa530cda0f11fce7d3e3c849b267e71cc1627c2bc988555f94ad744"
)
REGRESSION_FIXTURES = [
    pytest.param(
        570,
        "02",
        "7.0",
        8,
        178,
        "ad2cdb4c0485505e6cc48991c1873191e48a325a8d585761709f493bef429b9a",
        id="hecras-7.0-bald-eagle",
    ),
    pytest.param(
        1498,
        "01",
        "6.4.1",
        8,
        180,
        "d6452ee8306553f550a2749dd036da7cd49145a6f3082b84ed3ba26a7c1f5891",
        id="hecras-6.4.1-siletz",
    ),
    pytest.param(
        74,
        "05",
        "6.6",
        2,
        12,
        "9d929783e40d5a2ed22286bbde8b18e18a63a415619de32530fef8c86d100fc7",
        id="hecras-6.6-floodway",
    ),
    pytest.param(
        96,
        "01",
        "6.0.0",
        75,
        12,
        "597dd4ce66c8c73fa1718eec5664a373213f718d84cb5b9283f7de5b7f5bc76a",
        id="hecras-6.0-ras2fim-si",
    ),
]
STEADY_BASE = (
    "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fixture_database_path() -> Path:
    override = os.environ.get("RAS_COMMANDER_CLB_FIXTURE_DB")
    return (
        Path(override)
        if override
        else Path("feature_dev_notes")
        / "Database of Project Fixtures"
        / "project_fixtures.sqlite3"
    )


def _clb_project_path(database_path: Path, project_id: int) -> Path:
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
        pytest.skip(f"CLB fixture database has no project_id={project_id}")
    return Path(row[0])


def test_hecras_631_steady_depth_and_channel_length_semantics_are_exact():
    database_path = _fixture_database_path()
    if not database_path.is_file():
        pytest.skip("CLB fixture database is not available")

    project_path = _clb_project_path(database_path, 616)
    hdf_path = project_path.with_name(f"{project_path.stem}.p07.hdf")
    if not hdf_path.is_file():
        pytest.skip("Immutable HEC-RAS 6.3.1 steady result fixture is not mounted")

    before_hash = _sha256(hdf_path)
    assert before_hash == EXPECTED_631_SHA256

    results = HdfResultsPlan.get_steady_results(hdf_path)

    with h5py.File(hdf_path, "r") as hdf:
        file_version = hdf.attrs["File Version"]
        if isinstance(file_version, bytes):
            file_version = file_version.decode("utf-8", errors="replace")
        expected_maximum_depth = hdf[
            f"{STEADY_BASE}/Cross Sections/Additional Variables/Maximum Depth Total"
        ][()].reshape(-1)
        hydraulic_depth = hdf[
            f"{STEADY_BASE}/Cross Sections/Additional Variables/Hydraulic Depth Channel"
        ][()].reshape(-1)

    assert "6.3.1" in str(file_version)
    assert len(results) == 8 * 178
    np.testing.assert_array_equal(
        results["max_depth"].to_numpy(),
        expected_maximum_depth,
    )
    assert np.max(np.abs(expected_maximum_depth - hydraulic_depth)) > 29.0
    assert np.isfinite(results["channel_length"]).all()
    assert results.attrs["max_depth_source"] == "Maximum Depth Total"
    assert results.attrs["channel_length_source"].endswith("Len Channel")
    assert _sha256(hdf_path) == before_hash


@pytest.mark.parametrize(
    "project_id,plan_number,version,profile_count,xs_count,expected_hash",
    REGRESSION_FIXTURES,
)
def test_steady_result_semantics_across_real_hecras_versions(
    project_id,
    plan_number,
    version,
    profile_count,
    xs_count,
    expected_hash,
):
    database_path = _fixture_database_path()
    if not database_path.is_file():
        pytest.skip("CLB fixture database is not available")

    project_path = _clb_project_path(database_path, project_id)
    hdf_path = project_path.with_name(
        f"{project_path.stem}.p{plan_number}.hdf"
    )
    if not hdf_path.is_file():
        pytest.skip(f"Steady result fixture {project_id} is not mounted")

    before_hash = _sha256(hdf_path)
    assert before_hash == expected_hash
    results = HdfResultsPlan.get_steady_results(hdf_path)

    with h5py.File(hdf_path, "r") as hdf:
        file_version = hdf.attrs["File Version"]
        if isinstance(file_version, bytes):
            file_version = file_version.decode("utf-8", errors="replace")
        expected_maximum_depth = hdf[
            f"{STEADY_BASE}/Cross Sections/Additional Variables/Maximum Depth Total"
        ][()].reshape(-1)
        raw_lengths = np.asarray(
            hdf["Geometry/Cross Sections/Attributes"]["Len Channel"],
            dtype=float,
        )
        root_file_type = hdf.attrs.get("File Type", "")
        if isinstance(root_file_type, bytes):
            root_file_type = root_file_type.decode("utf-8", errors="replace")

    assert version in str(file_version)
    assert len(results) == profile_count * xs_count
    np.testing.assert_array_equal(
        results["max_depth"].to_numpy(),
        expected_maximum_depth,
    )
    assert np.isfinite(results["channel_length"]).all()
    assert results.attrs["max_depth_source"] == "Maximum Depth Total"
    if project_id == 1498:
        assert np.count_nonzero(~np.isfinite(raw_lengths) | (np.abs(raw_lengths) > 1e20)) == 1
    if project_id == 74:
        assert any("*" in station for station in results["node_id"].unique())
    if project_id == 96:
        assert "Geometry" in str(root_file_type)
    assert _sha256(hdf_path) == before_hash
