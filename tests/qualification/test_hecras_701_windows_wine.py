"""Fail-closed acceptance tests for real HEC-RAS 7.0.1 qualification evidence.

These tests consume receipts produced on the private native-Windows and Wine
runners.  Local test runs opt out explicitly; an enabled private runner fails
instead of skipping when evidence or configuration is absent.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import h5py
import numpy as np
import pytest
from pyproj import CRS

from ras_commander import ExecutorProfile, RasQualification


RUN_ENV = "RAS_COMMANDER_RUN_HECRAS_QUALIFICATION"
NATIVE_RECEIPT_ENV = "RAS_COMMANDER_NATIVE_701_RECEIPT"
WINE_RECEIPT_ENV = "RAS_COMMANDER_WINE_701_RECEIPT"
TOLERANCES_ENV = "RAS_COMMANDER_701_PARITY_TOLERANCES"
BALD_EAGLE_SOURCE_ENV = "RAS_COMMANDER_BALD_EAGLE_701_SOURCE"
QUALIFICATION_ENABLED = os.environ.get(RUN_ENV, "").strip() == "1"
FIXTURE_SPEC_PATH = Path(__file__).parent / "fixtures" / "bald_eagle_701.json"

pytestmark = [
    pytest.mark.hecras_qualification,
    pytest.mark.qualification_critical,
    pytest.mark.skipif(
        not QUALIFICATION_ENABLED,
        reason=f"set {RUN_ENV}=1 only on a configured private HEC-RAS runner",
    ),
]


def _required_json_path(variable: str) -> Path:
    raw_value = os.environ.get(variable, "").strip()
    if not raw_value:
        pytest.fail(f"{variable} is required when {RUN_ENV}=1", pytrace=False)
    path = Path(raw_value).expanduser()
    if not path.is_file():
        pytest.fail(f"{variable} does not name a file: {path}", pytrace=False)
    return path


def _required_directory(variable: str) -> Path:
    raw_value = os.environ.get(variable, "").strip()
    if not raw_value:
        pytest.fail(f"{variable} is required when {RUN_ENV}=1", pytrace=False)
    path = Path(raw_value).expanduser()
    if not path.is_dir():
        pytest.fail(f"{variable} does not name a directory: {path}", pytrace=False)
    return path


@pytest.fixture(scope="module")
def native_receipt():
    return RasQualification.read_receipt(_required_json_path(NATIVE_RECEIPT_ENV))


@pytest.fixture(scope="module")
def wine_receipt():
    return RasQualification.read_receipt(_required_json_path(WINE_RECEIPT_ENV))


@pytest.fixture(scope="module")
def tolerances():
    path = _required_json_path(TOLERANCES_ENV)
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bald_eagle_spec():
    return json.loads(FIXTURE_SPEC_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bald_eagle_source():
    return _required_directory(BALD_EAGLE_SOURCE_ENV)


def _assert_valid(receipt, profile: ExecutorProfile) -> None:
    validation = RasQualification.validate_run_receipt(
        receipt,
        expected_profile=profile,
        expected_version="7.0.1",
    )
    assert validation["passed"], json.dumps(validation, indent=2, sort_keys=True)


def test_native_windows_receipt_has_all_critical_content(native_receipt):
    _assert_valid(native_receipt, ExecutorProfile.WINDOWS_NATIVE)


def test_wine_receipt_has_all_critical_content(wine_receipt):
    _assert_valid(wine_receipt, ExecutorProfile.LINUX_WINE_WINDOWS_RAS)


def test_native_windows_and_wine_outputs_meet_approved_tolerances(
    native_receipt,
    wine_receipt,
    tolerances,
):
    comparison = RasQualification.compare_run_receipts(
        native_receipt,
        wine_receipt,
        tolerances,
    )
    assert comparison["passed"], json.dumps(comparison, indent=2, sort_keys=True)


def test_bald_eagle_source_fixture_matches_pinned_content(
    bald_eagle_spec,
    bald_eagle_source,
):
    expected = bald_eagle_spec["source"]
    assert RasQualification.project_tree_fingerprint(bald_eagle_source) == expected[
        "tree_sha256"
    ]
    for relative, digest in expected["files"].items():
        path = bald_eagle_source / relative
        assert path.is_file(), f"missing pinned fixture file: {relative}"
        assert RasQualification.file_sha256(path) == digest, relative


def test_bald_eagle_plan_projection_and_geometry_match_pinned_content(
    bald_eagle_spec,
    bald_eagle_source,
):
    plan = bald_eagle_spec["plan"]
    plan_text = (bald_eagle_source / "BaldEagleDamBrk.p06").read_text(
        encoding="utf-8"
    )
    required_lines = {
        f"Plan Title={plan['title']}",
        f"Program Version={plan['source_program_version']}",
        f"Simulation Date={plan['simulation_date']}",
        f"Geom File=g{plan['geometry_number']}",
        f"Flow File=u{plan['unsteady_number']}",
        f"Computation Interval={plan['computation_interval']}",
    }
    normalized_lines = {line.rstrip() for line in plan_text.splitlines()}
    assert required_lines.issubset(normalized_lines)
    values = {
        name.strip(): value.strip()
        for line in plan_text.splitlines()
        if "=" in line
        for name, value in [line.split("=", 1)]
    }
    for name, value in plan["required_flags"].items():
        assert values[name] == value

    projection_path = bald_eagle_source / "Terrain" / "Projection.prj"
    assert CRS.from_wkt(projection_path.read_text()).to_epsg() == 2271
    rasmap_text = (bald_eagle_source / "BaldEagleDamBrk.rasmap").read_text(
        encoding="utf-8"
    )
    assert bald_eagle_spec["projection"]["rasmap_reference"] in rasmap_text

    geometry_path = bald_eagle_source / "BaldEagleDamBrk.g09.hdf"
    receipt = RasQualification.geometry_receipt(geometry_path)
    expected_geometry = bald_eagle_spec["source_geometry"]
    area = receipt["areas"][expected_geometry["mesh_name"]]
    assert area["cell_count"] == expected_geometry["cell_count"]
    assert area["face_count"] == expected_geometry["face_count"]
    assert area["mesh_topology"]["fingerprint"] == expected_geometry[
        "topology_fingerprint"
    ]
    assert receipt["geometry_fingerprint"] == expected_geometry[
        "geometry_fingerprint"
    ]
    assert receipt["boundary_assignments"] == expected_geometry[
        "boundary_assignments"
    ]
    assert area["cell_property_complete"] is True
    assert area["face_property_complete"] is True
    assert area["quality"]["invalid_cell_count"] == 0
    with h5py.File(geometry_path, "r") as hdf:
        perimeter = np.asarray(
            hdf["Geometry/2D Flow Areas/BaldEagleCr/Perimeter"][:],
            dtype=float,
        )
    bounds = [
        float(perimeter[:, 0].min()),
        float(perimeter[:, 1].min()),
        float(perimeter[:, 0].max()),
        float(perimeter[:, 1].max()),
    ]
    assert bounds == expected_geometry["perimeter_bounds"]
