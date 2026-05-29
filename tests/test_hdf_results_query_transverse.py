"""Integration tests for transverse velocity profile extraction."""

import os
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import HdfResultsQuery


EXPECTED_COLUMNS = [
    "station",
    "distance_from_seed",
    "x",
    "y",
    "cell_id",
    "mesh_name",
    "velocity",
    "velocity_x",
    "velocity_y",
    "side",
    "step",
    "entry_face_id",
]


def _candidate_bald_eagle_result_dirs():
    env_path = os.environ.get("RAS_COMMANDER_BALD_EAGLE_RESULTS")
    if env_path:
        yield Path(env_path)

    repo_root = Path(__file__).resolve().parents[1]
    for root in (
        repo_root,
        Path("C:/GH/ras-commander"),
        Path("G:/GH/ras-commander"),
    ):
        yield root / "example_projects" / "BaldEagleCrkMulti2D_velocity"
        yield (
            root
            / "examples"
            / "example_projects"
            / "BaldEagleCrkMulti2D_AORC_2020_901"
        )


def _find_bald_eagle_plan_hdf() -> Path:
    for result_dir in _candidate_bald_eagle_result_dirs():
        if not result_dir.exists():
            continue

        for plan_hdf in sorted(result_dir.glob("BaldEagleDamBrk.p*.hdf")):
            try:
                with h5py.File(plan_hdf, "r") as hdf_file:
                    meshes = [
                        name
                        for name in hdf_file["Geometry/2D Flow Areas"].keys()
                        if name != "Attributes"
                    ]
                    if not meshes:
                        continue
                    mesh_name = meshes[0]
                    face_velocity_path = (
                        "Results/Unsteady/Output/Output Blocks/Base Output/"
                        "Unsteady Time Series/2D Flow Areas/"
                        f"{mesh_name}/Face Velocity"
                    )
                    if face_velocity_path in hdf_file:
                        return plan_hdf
            except Exception:
                continue

    pytest.skip(
        "Bald Eagle Creek 2D result HDF with Face Velocity output is not "
        "available. Set RAS_COMMANDER_BALD_EAGLE_RESULTS to a result folder."
    )


def _peak_face_velocity_seed(plan_hdf: Path):
    with h5py.File(plan_hdf, "r") as hdf_file:
        mesh_name = [
            name
            for name in hdf_file["Geometry/2D Flow Areas"].keys()
            if name != "Attributes"
        ][0]
        base_path = f"Geometry/2D Flow Areas/{mesh_name}"
        face_velocity_path = (
            "Results/Unsteady/Output/Output Blocks/Base Output/"
            "Unsteady Time Series/2D Flow Areas/"
            f"{mesh_name}/Face Velocity"
        )
        face_velocity = np.asarray(hdf_file[face_velocity_path][()])
        time_index = int(np.nanargmax(np.nanmax(np.abs(face_velocity), axis=1)))
        face_id = int(np.nanargmax(np.abs(face_velocity[time_index])))
        face_cells = np.asarray(hdf_file[f"{base_path}/Faces Cell Indexes"][face_id])
        cell_id = int(face_cells[face_cells >= 0][0])
        x, y = hdf_file[f"{base_path}/Cells Center Coordinate"][cell_id]

        return {
            "mesh_name": mesh_name,
            "time_index": time_index,
            "face_id": face_id,
            "cell_id": cell_id,
            "x": float(x),
            "y": float(y),
        }


@pytest.fixture(scope="module")
def bald_eagle_plan_hdf() -> Path:
    return _find_bald_eagle_plan_hdf()


@pytest.fixture(scope="module")
def peak_seed(bald_eagle_plan_hdf):
    return _peak_face_velocity_seed(bald_eagle_plan_hdf)


def test_query_transverse_profile_orders_bald_eagle_cells(
    bald_eagle_plan_hdf,
    peak_seed,
):
    profile = HdfResultsQuery.query_transverse_profile(
        bald_eagle_plan_hdf,
        peak_seed["x"],
        peak_seed["y"],
        time_index=peak_seed["time_index"],
        max_steps=6,
        min_velocity=0.0,
    )

    assert list(profile.columns) == EXPECTED_COLUMNS
    assert len(profile) >= 3
    assert profile["station"].is_monotonic_increasing
    assert np.isclose(profile["station"], 0.0).any()
    assert profile.loc[profile["side"] == "seed", "cell_id"].iloc[0] == peak_seed[
        "cell_id"
    ]
    assert profile["cell_id"].is_unique
    assert {"left", "seed", "right"}.issubset(set(profile["side"]))


def test_query_transverse_profile_reconstructs_components_from_face_velocity(
    bald_eagle_plan_hdf,
    peak_seed,
):
    with h5py.File(bald_eagle_plan_hdf, "r") as hdf_file:
        base_path = (
            "Results/Unsteady/Output/Output Blocks/Base Output/"
            "Unsteady Time Series/2D Flow Areas/"
            f"{peak_seed['mesh_name']}"
        )
        assert f"{base_path}/Face Velocity" in hdf_file
        assert f"{base_path}/Velocity X" not in hdf_file
        assert f"{base_path}/Velocity Y" not in hdf_file

    profile = HdfResultsQuery.query_transverse_profile(
        bald_eagle_plan_hdf,
        peak_seed["x"],
        peak_seed["y"],
        time_index=peak_seed["time_index"],
        max_steps=3,
        min_velocity=0.0,
    )

    seed = profile.loc[profile["side"] == "seed"].iloc[0]
    assert np.isfinite(seed["velocity_x"])
    assert np.isfinite(seed["velocity_y"])
    assert seed["velocity"] == pytest.approx(
        float(np.hypot(seed["velocity_x"], seed["velocity_y"]))
    )


def test_query_transverse_profile_respects_max_steps(
    bald_eagle_plan_hdf,
    peak_seed,
):
    profile = HdfResultsQuery.query_transverse_profile(
        bald_eagle_plan_hdf,
        peak_seed["x"],
        peak_seed["y"],
        time_index=peak_seed["time_index"],
        max_steps=1,
        min_velocity=0.0,
    )

    assert len(profile) <= 3
    assert profile["step"].abs().max() <= 1


def test_query_transverse_profile_rejects_max_envelope_time_index(
    bald_eagle_plan_hdf,
    peak_seed,
):
    with pytest.raises(ValueError, match="requires a signed time_index"):
        HdfResultsQuery.query_transverse_profile(
            bald_eagle_plan_hdf,
            peak_seed["x"],
            peak_seed["y"],
            time_index="max",
        )


def test_query_transverse_profile_rejects_seed_below_min_velocity(
    bald_eagle_plan_hdf,
    peak_seed,
):
    with pytest.raises(ValueError, match="below min_velocity"):
        HdfResultsQuery.query_transverse_profile(
            bald_eagle_plan_hdf,
            peak_seed["x"],
            peak_seed["y"],
            time_index=peak_seed["time_index"],
            min_velocity=1.0e6,
        )
