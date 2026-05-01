"""Tests for 2D unsteady computation option helpers."""

from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander.RasPlan import RasPlan
from ras_commander.RasUnsteady import RasUnsteady
from ras_commander.hdf.HdfPlan import HdfPlan


class _DummyRas:
    def check_initialized(self):
        return None


def _write_plan(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "Plan Title=2D Options",
                "Program Version=6.60",
                "Short Identifier=2DOpts",
                "Simulation Date=01JAN1999,1200,04JAN1999,1200",
                "Geom File=g01",
                "Flow File=u01",
                "Computation Interval=10SEC",
                "Output Interval=1MIN",
                "Instantaneous Interval=1HOUR",
                "Mapping Interval=5MIN",
                "Computation Time Step Use Courant=        0",
                "Computation Time Step Use Time Series=    0",
                "Computation Time Step Max Courant=",
                "Computation Time Step Min Courant=",
                "Run HTab= 1 ",
                "Run UNet= 1 ",
                "UNET D2 Coriolis=0",
                "UNET D2 Cores= 0 ",
                "UNET D2 Theta= 1 ",
                "UNET D2 Theta Warmup= 1 ",
                "UNET D2 Z Tol= 0.01 ",
                "UNET D2 Volume Tol= 0.01 ",
                "UNET D2 Max Iterations= 20 ",
                "UNET D2 Equation= 0 ",
                "UNET D2 TotalICTime=",
                "UNET D2 RampUpFraction=0.5",
                "UNET D2 TimeSlices= 1 ",
                "UNET D2 Eddy Viscosity=",
                "UNET D2 BCVolumeCheck=0",
                "UNET D2 Name=BaldEagleCr     ",
                "UNET D2 Theta= 1 ",
                "UNET D2 Theta Warmup= 1 ",
                "UNET D2 Z Tol= 0.01 ",
                "UNET D2 Volume Tol= 0.01 ",
                "UNET D2 Max Iterations= 20 ",
                "UNET D2 Equation= 0 ",
                "UNET D2 TotalICTime=2",
                "UNET D2 RampUpFraction=0.1",
                "UNET D2 TimeSlices= 1 ",
                "UNET D2 Eddy Viscosity=0",
                "UNET D2 BCVolumeCheck=0",
                "UNET D2 Cores=12",
                "UNET D1D2 ZTol=0.02",
                "DSS File=dss",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_get_2d_flow_options_parses_default_and_named_area(tmp_path):
    plan_path = tmp_path / "Project.p01"
    _write_plan(plan_path)

    options = RasPlan.get_2d_flow_options(plan_path, ras_object=_DummyRas())

    assert options["program_version"] == "6.60"
    assert options["plan"]["computation_interval"] == "10SEC"
    assert options["plan"]["time_step_use_courant"] is False
    assert options["default"]["equation_set"] == "DWE"
    assert options["areas"][0]["name"] == "BaldEagleCr"
    assert options["areas"][0]["initial_conditions_time_hours"] == 2.0
    assert options["areas"][0]["cores"] == 12


def test_set_2d_equation_set_round_trips_named_area(tmp_path):
    plan_path = tmp_path / "Project.p01"
    _write_plan(plan_path)

    assert RasPlan.set_2d_equation_set(
        plan_path,
        "SWE-ELM",
        mesh_name="BaldEagleCr",
        computation_interval="20SEC",
        initial_conditions_time_hours=3,
        ras_object=_DummyRas(),
    )

    options = RasPlan.get_2d_flow_options(plan_path, ras_object=_DummyRas())

    assert options["plan"]["computation_interval"] == "20SEC"
    assert options["default"]["equation_set"] == "DWE"
    assert options["areas"][0]["equation_set"] == "SWE-ELM"
    assert options["areas"][0]["initial_conditions_time_hours"] == 3.0


def test_set_2d_flow_options_validates_option_names(tmp_path):
    plan_path = tmp_path / "Project.p01"
    _write_plan(plan_path)

    with pytest.raises(ValueError, match="Unknown 2D flow option"):
        RasPlan.set_2d_flow_options(
            plan_path,
            options={"not_a_real_option": 1},
            ras_object=_DummyRas(),
        )


def test_hdfplan_get_2d_flow_options_parses_hdf_attrs(tmp_path):
    hdf_path = tmp_path / "Project.p01.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        plan_data = hdf.create_group("Plan Data")
        info = plan_data.create_group("Plan Information")
        info.attrs["Program Version"] = np.bytes_("6.60")
        params = plan_data.create_group("Plan Parameters")
        params.attrs["2D Names"] = np.array([b"Area A", b"Area B"])
        params.attrs["2D Equation Set"] = np.array([b"Diffusion Wave", b"Shallow Water"])
        params.attrs["2D Initial Conditions Ramp Up Time (hrs)"] = np.array([0.0, 2.0])
        params.attrs["2D Water Surface Tolerance"] = np.array([0.01, 0.02])
        params.attrs["2D Boundary Condition Volume Check"] = np.array([b"False", b"True"])
        params.attrs["2D Cores (per mesh)"] = np.array([4, 8])

    options = HdfPlan.get_2d_flow_options(hdf_path)

    assert options["program_version"] == "6.60"
    assert options["areas"][0]["equation_set"] == "DWE"
    assert options["areas"][1]["equation_set"] == "SWE-ELM"
    assert options["areas"][1]["initial_conditions_time_hours"] == 2.0
    assert options["areas"][1]["boundary_condition_volume_check"] is True
    assert options["areas"][1]["cores"] == 8


def test_rasunsteady_initial_condition_wrappers_round_trip(tmp_path):
    unsteady_path = tmp_path / "Project.u01"
    unsteady_path.write_text(
        "\n".join(
            [
                "Flow Title=Initial Conditions",
                "Program Version=6.60",
                "Use Restart= 0",
                "Boundary Location=Downstream",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    RasUnsteady.set_initial_conditions(
        unsteady_path,
        [
            {
                "type": "storage",
                "area_name": "BaldEagleCr",
                "value": 700.5,
            }
        ],
    )

    ic_df = RasUnsteady.get_initial_conditions(unsteady_path)

    assert len(ic_df) == 1
    assert ic_df.iloc[0]["type"] == "storage"
    assert ic_df.iloc[0]["area_name"] == "BaldEagleCr"
    assert ic_df.iloc[0]["value"] == 700.5
