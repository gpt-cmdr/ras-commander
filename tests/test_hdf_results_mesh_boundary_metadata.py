"""Boundary-condition metadata coordinate regression tests."""

from __future__ import annotations

import os
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import HdfResultsMesh

BASE_PATH = (
    "Results/Unsteady/Output/Output Blocks/Base Output/"
    "Unsteady Time Series"
)
DEFAULT_DAVIS_PLAN = Path(
    "C:/GH/ras-commander-hydro/testdata/DavisStormSystem.p02.hdf"
)


def _write_boundary_hdf(
    path: Path,
    *,
    include_face_data: bool = False,
    rogue_position: str | None = None,
) -> None:
    previous_track_order = h5py.get_config().track_order
    h5py.get_config().track_order = True
    try:
        with h5py.File(path, "w") as hdf_file:
            plan_information = hdf_file.create_group(
                "Plan Data/Plan Information"
            )
            plan_information.attrs["Simulation Start Time"] = (
                b"18Sep2019 13:00:00"
            )
            hdf_file.create_dataset(
                f"{BASE_PATH}/Time",
                data=np.asarray([0.0, 1.0 / 24.0]),
            )
            boundary = hdf_file.create_dataset(
                f"{BASE_PATH}/Boundary Conditions/Inflow",
                data=np.asarray([[10.0, 100.0], [11.0, 120.0]]),
            )
            boundary.attrs["Columns"] = np.asarray([b"Stage", b"Flow"])
            canonical = [
                ("Stage", b"ft"),
                ("Flow", b"cfs"),
                ("2D Area", b"Mesh"),
            ]
            rogue = [
                ("stage_units", b"rogue stage units"),
                ("flow_units", b"rogue flow units"),
                ("area_2d", b"rogue area"),
            ]
            metadata = canonical
            if rogue_position == "before":
                metadata = rogue + canonical
            elif rogue_position == "after":
                metadata = canonical + rogue
            for key, value in metadata:
                boundary.attrs[key] = value
            boundary.attrs["Model Name"] = b"Fixture model"

            if include_face_data:
                boundary.attrs["Flow per Face"] = b"metadata flow per face"
                boundary.attrs["flow_per_face"] = (
                    b"metadata underscore flow per face"
                )
                boundary.attrs["Time"] = b"metadata time"
                face_data = hdf_file.create_dataset(
                    f"{BASE_PATH}/Boundary Conditions/"
                    "Inflow - Flow per Face",
                    data=np.asarray([[60.0, 40.0], [70.0, 50.0]]),
                )
                face_data.attrs["Faces"] = np.asarray([3, 5])
    finally:
        h5py.get_config().track_order = previous_track_order


def _real_davis_plan() -> Path:
    configured = os.environ.get("RAS_COMMANDER_DAVIS_PIPE_RESULTS")
    return Path(configured) if configured else DEFAULT_DAVIS_PLAN


def test_stage_and_flow_metadata_do_not_replace_hydrographs(tmp_path: Path) -> None:
    hdf_path = tmp_path / "boundaries.p01.hdf"
    _write_boundary_hdf(hdf_path)

    dataset = HdfResultsMesh.get_boundary_conditions_timeseries(hdf_path)

    assert set(dataset.data_vars) == {"stage", "flow"}
    assert "stage" not in dataset.coords
    assert "flow" not in dataset.coords
    assert dataset["stage"].dims == ("time", "bc_name")
    assert dataset["flow"].dims == ("time", "bc_name")
    np.testing.assert_array_equal(
        dataset["stage"].values,
        np.asarray([[10.0], [11.0]]),
    )
    np.testing.assert_array_equal(
        dataset["flow"].values,
        np.asarray([[100.0], [120.0]]),
    )
    assert dataset["stage_units"].values.tolist() == ["ft"]
    assert dataset["flow_units"].values.tolist() == ["cfs"]
    assert dataset["area_2d"].values.tolist() == ["Mesh"]
    assert dataset["2d area"].values.tolist() == ["Mesh"]
    assert dataset["model name"].values.tolist() == ["Fixture model"]


def test_normalized_metadata_names_cannot_claim_structural_names(
    tmp_path: Path,
) -> None:
    hdf_path = tmp_path / "boundary-face-data.p01.hdf"
    _write_boundary_hdf(hdf_path, include_face_data=True)

    dataset = HdfResultsMesh.get_boundary_conditions_timeseries(hdf_path)

    assert "flow_per_face" in dataset.data_vars
    assert dataset["flow_per_face"].dims == ("time", "bc_name", "face_id")
    np.testing.assert_array_equal(
        dataset["flow_per_face"].values,
        np.asarray([[[60.0, 40.0]], [[70.0, 50.0]]]),
    )
    assert dataset["flow per face"].values.tolist() == [
        "metadata flow per face"
    ]
    assert dataset["bc_flow_per_face"].values.tolist() == [
        "metadata underscore flow per face"
    ]
    assert dataset["bc_time"].values.tolist() == ["metadata time"]
    assert dataset["time"].dims == ("time",)


@pytest.mark.parametrize("rogue_position", ["before", "after"])
def test_canonical_metadata_ownership_is_attribute_order_independent(
    tmp_path: Path,
    rogue_position: str,
) -> None:
    hdf_path = tmp_path / f"boundary-order-{rogue_position}.p01.hdf"
    _write_boundary_hdf(hdf_path, rogue_position=rogue_position)

    dataset = HdfResultsMesh.get_boundary_conditions_timeseries(hdf_path)

    assert dataset["stage_units"].values.tolist() == ["ft"]
    assert dataset["flow_units"].values.tolist() == ["cfs"]
    assert dataset["area_2d"].values.tolist() == ["Mesh"]
    assert dataset["2d area"].values.tolist() == ["Mesh"]
    assert dataset["bc_stage_units"].values.tolist() == [
        "rogue stage units"
    ]
    assert dataset["bc_flow_units"].values.tolist() == [
        "rogue flow units"
    ]
    assert dataset["bc_area_2d"].values.tolist() == ["rogue area"]


@pytest.mark.integration
def test_real_davis_boundary_hydrographs_remain_data_variables() -> None:
    hdf_path = _real_davis_plan()
    if not hdf_path.exists():
        pytest.skip(f"Davis completed plan HDF not staged: {hdf_path}")

    boundary_path = f"{BASE_PATH}/Boundary Conditions/DS Normal"
    with h5py.File(hdf_path, "r") as hdf_file:
        source = hdf_file[boundary_path]
        source_values = source[:]
        columns = [value.decode("utf-8") for value in source.attrs["Columns"]]
        stage_index = columns.index("Stage")
        flow_index = columns.index("Flow")

    dataset = HdfResultsMesh.get_boundary_conditions_timeseries(hdf_path)

    assert "stage" in dataset.data_vars
    assert "flow" in dataset.data_vars
    assert "stage" not in dataset.coords
    assert "flow" not in dataset.coords
    assert dataset["stage"].dims == ("time", "bc_name")
    assert dataset["flow"].dims == ("time", "bc_name")
    np.testing.assert_array_equal(
        dataset["stage"].sel(bc_name="DS Normal").values,
        source_values[:, stage_index],
    )
    np.testing.assert_array_equal(
        dataset["flow"].sel(bc_name="DS Normal").values,
        source_values[:, flow_index],
    )
    assert dataset["stage_units"].sel(bc_name="DS Normal").item() == "ft"
    assert dataset["flow_units"].sel(bc_name="DS Normal").item() == "cfs"
    assert dataset["area_2d"].sel(bc_name="DS Normal").item() == "DS Channel"
    assert dataset["2d area"].sel(bc_name="DS Normal").item() == "DS Channel"
