"""Portable execution runs any HEC-RAS plan; only validation depends on its type.

The solver path is agnostic to model type: 1D, 2D, and combined models, steady
and unsteady, run through ``execute_request`` identically. The plan's flow file
selects the validator -- ``.f##`` steady, ``.u##`` unsteady -- and anything else
fails the receipt before HEC-RAS is started.
"""

from pathlib import Path

import h5py
import pandas as pd
import pytest

from ras_commander.ComputeResults import ComputeResult
from ras_commander.remote import PortableExecution
from ras_commander.remote.ExecutionContract import PreprocessPolicy, RasExecutionRequest
from ras_commander.remote.RasPortableDocker import RasPortableDocker

OCI = "registry.example/hecras/any@sha256:" + "b" * 64
MAPS = {"terrain_name": "Terrain 1m", "profiles": ["PF 1", 1], "timeout_seconds": 900}

# A 2D inline flow boundary in the layout HEC-RAS writes, as a firehose plan
# authors it: 100 cfs held for one hour.
_BOUNDARY = (
    "Boundary Location=                ,                ,        ,        ,"
    "                ,SLDR_004        ,                ,wb-1                "
    "            ,                                "
)


def _flow_text(
    ordinates=("     100     100",),
    count=2,
    interval="1HOUR",
    precipitation="Disable",
    use_dss="False",
    fixed_start="False",
) -> str:
    return "\n".join(
        [
            "Flow Title=firehose",
            "Program Version=6.60",
            "Use Restart= 0 ",
            _BOUNDARY,
            f"Interval={interval}",
            f"Flow Hydrograph= {count} ",
            *ordinates,
            "Stage Hydrograph TW Check=0",
            "Flow Hydrograph Slope= 0.001 ",
            "DSS File=",
            "DSS Path=",
            f"Use DSS={use_dss}",
            f"Use Fixed Start Time={fixed_start}",
            "Fixed Start Date/Time=,",
            "Is Critical Boundary=False",
            "Critical Boundary Flow=",
            "Met Station Name=x",
            f"Precipitation Mode={precipitation}",
            "",
        ]
    )


def _plan_text(start="01JAN2024,0000", end="01JAN2024,0100") -> str:
    return f"Plan Title=firehose\nSimulation Date={start},{end}\nFlow File=u01\n"


def _result_hdf(path: Path, **overrides) -> Path:
    """A result HDF carrying HEC-RAS's whole-model volume accounting."""
    attributes = {
        "Error": 1.231e-7,
        "Error Percent": 8.127e-7,
        "Total Boundary Flux of Water In": 8.264,
        "Total Boundary Flux of Water Out": 0.0,
        "Volume Starting": 6.887,
        "Volume Ending": 15.15,
        "Vol Accounting in": b"Acre Feet",
    }
    attributes.update(overrides)
    with h5py.File(path, "w") as handle:
        group = handle.create_group("Results/Unsteady/Summary/Volume Accounting")
        for key, value in attributes.items():
            if value is not None:
                group.attrs[key] = value
    return path


def _files(tmp_path: Path, **flow) -> tuple[Path, Path, Path]:
    flow_path = tmp_path / "m.u01"
    flow_path.write_text(_flow_text(**flow))
    plan_path = tmp_path / "m.p01"
    plan_path.write_text(_plan_text())
    return _result_hdf(tmp_path / "m.p01.hdf"), flow_path, plan_path


# --- classification ----------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [("m.f01", "steady"), ("m.F12", "steady"), ("m.u01", "unsteady"), ("m.u99", "unsteady"),
     ("m.q01", None), ("m.p01", None), ("m.f1", None)],
)
def test_flow_type_comes_from_the_exact_flow_file_suffix(name, expected):
    """A quasi-unsteady .q## plan is neither; RasPlan's inference calls it steady."""
    assert PortableExecution._plan_flow_type(Path(name)) == expected


def test_simulation_window_reads_ras_dates_including_2400(tmp_path):
    path = tmp_path / "m.p01"
    path.write_text("Simulation Date=01JAN2024,0000,01JAN2024,2400\n")

    assert PortableExecution._simulation_seconds(path) == 24 * 3600.0


def test_hydrograph_integration_is_linear_and_truncates_at_the_window():
    # Constant 100 cfs for one hour.
    assert PortableExecution._integrate_hydrograph([100, 100], 3600, 3600) == 360000.0
    # A step from 0 to 100 over one hour ramps linearly: half the rectangle.
    assert PortableExecution._integrate_hydrograph([0, 100], 3600, 3600) == 180000.0
    # Truncated halfway through a ramp from 0 to 100: area to t=1800 s.
    assert PortableExecution._integrate_hydrograph([0, 100], 3600, 1800) == 45000.0
    # Ordinates that end before the run cannot be integrated as authored.
    assert PortableExecution._integrate_hydrograph([100, 100], 3600, 7200) is None


# --- the unsteady validator --------------------------------------------------


def test_unsteady_result_passes_and_reconciles_the_authored_inflow(tmp_path):
    """The Salt Draw firehose probe: 100 cfs x 1 h = 8.2645 acre-ft vs 8.264 reported."""
    summary = PortableExecution.validate_unsteady_results(*_files(tmp_path))

    assert summary["passed"], summary["reason_codes"]
    assert summary["flow_type"] == "unsteady"
    assert summary["volume_units"] == "Acre Feet"
    reconciliation = summary["inflow_reconciliation"]
    assert reconciliation["status"] == "passed"
    assert reconciliation["hydrographs_integrated"] == 1
    assert reconciliation["authored_inflow_volume"] == pytest.approx(360000.0 / 43560.0)
    assert reconciliation["relative_difference"] < 1e-4


def test_excess_volume_error_fails(tmp_path):
    hdf, flow, plan = _files(tmp_path)
    _result_hdf(hdf, **{"Error Percent": 2.5})

    summary = PortableExecution.validate_unsteady_results(hdf, flow, plan)

    assert not summary["passed"]
    assert summary["reason_codes"] == ["UNSTEADY_VOLUME_ERROR_EXCEEDED"]


def test_negative_volume_error_is_judged_by_magnitude(tmp_path):
    hdf, flow, plan = _files(tmp_path)
    _result_hdf(hdf, **{"Error Percent": -1.5})

    assert "UNSTEADY_VOLUME_ERROR_EXCEEDED" in (
        PortableExecution.validate_unsteady_results(hdf, flow, plan)["reason_codes"]
    )


def test_injected_volume_that_disagrees_with_the_hydrograph_fails(tmp_path):
    """A boundary that injected the wrong volume must not pass on volume error alone."""
    hdf, flow, plan = _files(tmp_path)
    _result_hdf(hdf, **{"Total Boundary Flux of Water In": 16.5})

    summary = PortableExecution.validate_unsteady_results(hdf, flow, plan)

    assert not summary["passed"]
    assert summary["reason_codes"] == ["UNSTEADY_INFLOW_MISMATCH"]
    assert summary["inflow_reconciliation"]["status"] == "failed"


def test_missing_volume_accounting_fails_closed(tmp_path):
    hdf, flow, plan = _files(tmp_path)
    with h5py.File(hdf, "w") as handle:
        handle.create_group("Results/Unsteady/Summary")

    summary = PortableExecution.validate_unsteady_results(hdf, flow, plan)

    assert not summary["passed"]
    assert summary["reason_codes"] == ["UNSTEADY_VOLUME_ACCOUNTING_MISSING"]


def test_a_partial_volume_accounting_block_names_what_is_missing(tmp_path):
    hdf, flow, plan = _files(tmp_path)
    _result_hdf(hdf, **{"Volume Ending": None})

    summary = PortableExecution.validate_unsteady_results(hdf, flow, plan)

    assert summary["reason_codes"] == ["UNSTEADY_VOLUME_ACCOUNTING_MISSING"]
    assert summary["missing_attributes"] == ["Volume Ending"]


def test_nonfinite_volume_fails_closed(tmp_path):
    hdf, flow, plan = _files(tmp_path)
    _result_hdf(hdf, **{"Error Percent": float("nan")})

    assert PortableExecution.validate_unsteady_results(hdf, flow, plan)["reason_codes"] == [
        "UNSTEADY_NONFINITE_VOLUME"
    ]


def test_an_unreadable_result_fails_closed(tmp_path):
    _, flow, plan = _files(tmp_path)
    bogus = tmp_path / "not.hdf"
    bogus.write_bytes(b"not an hdf5 file")

    summary = PortableExecution.validate_unsteady_results(bogus, flow, plan)

    assert summary["reason_codes"] == ["UNSTEADY_RESULTS_UNREADABLE"]
    assert "error" in summary


@pytest.mark.parametrize(
    ("flow", "reason"),
    [
        ({"precipitation": "Enable"}, "UNSTEADY_INFLOW_PRECIPITATION_ENABLED"),
        ({"use_dss": "True"}, "UNSTEADY_INFLOW_FROM_DSS"),
        ({"fixed_start": "True"}, "UNSTEADY_INFLOW_FIXED_START_TIME"),
        ({"interval": "1MON"}, "UNSTEADY_INFLOW_INTERVAL_UNSUPPORTED"),
    ],
)
def test_undeterminable_inflow_is_recorded_never_assumed(tmp_path, flow, reason):
    """Volume error still gates; the reconciliation says why it did not run."""
    summary = PortableExecution.validate_unsteady_results(*_files(tmp_path, **flow))

    assert summary["passed"]
    assert summary["inflow_reconciliation"]["status"] == "not_applicable"
    assert reason in summary["inflow_reconciliation"]["reasons"]


def test_a_hydrograph_shorter_than_the_run_is_not_reconciled(tmp_path):
    hdf, flow, plan = _files(tmp_path)
    plan.write_text(_plan_text(end="01JAN2024,0300"))

    summary = PortableExecution.validate_unsteady_results(hdf, flow, plan)

    assert summary["inflow_reconciliation"]["status"] == "not_applicable"
    assert summary["inflow_reconciliation"]["reasons"] == [
        "UNSTEADY_INFLOW_HYDROGRAPH_SHORTER_THAN_RUN"
    ]


def test_si_volume_units_are_not_reconciled_against_cfs(tmp_path):
    hdf, flow, plan = _files(tmp_path)
    _result_hdf(hdf, **{"Vol Accounting in": b"1000 m3"})

    summary = PortableExecution.validate_unsteady_results(hdf, flow, plan)

    assert "UNSTEADY_INFLOW_UNITS_UNSUPPORTED" in summary["inflow_reconciliation"]["reasons"]


# --- the executor: one path, validator by plan type ---------------------------


def _bundle(tmp_path: Path, flow_suffix: str, stored_maps=None) -> Path:
    bundle = tmp_path / "bundle"
    source = bundle / "input" / "sample.prj"
    source.parent.mkdir(parents=True)
    source.write_text("Proj Title=sample\nCurrent Plan=p01\nPlan File=p01\n")
    (source.parent / "sample.p01").write_text(
        f"Plan Title=portable\nGeom File=g01\nFlow File={flow_suffix}\n"
        "Simulation Date=01JAN2024,0000,01JAN2024,0100\n"
    )
    (source.parent / "sample.g01").write_text("Geom Title=sample\n")
    (source.parent / f"sample.{flow_suffix}").write_text(_flow_text())
    request = RasExecutionRequest.create(
        execution_id="sample-001",
        request_directory=bundle,
        source_project_path="input/sample.prj",
        plan_number="1",
        output_directory="output/sample-001",
        ras_executable="/opt/hec-ras/Ras.exe",
        container_identity=OCI,
        preprocess_policy=PreprocessPolicy.REBUILD,
        timeout_seconds=60,
        stored_maps=stored_maps,
    )
    return request.write(bundle / "request.json")


def _patch_run(monkeypatch, flow_suffix: str, calls: dict) -> None:
    def initialize(self, project_folder, ras_exe_path, **kwargs):
        self.project_folder = Path(project_folder)
        self.project_name = "sample"
        self.prj_file = self.project_folder / "sample.prj"
        self.initialized = True
        self.plan_df = pd.DataFrame(
            [{"plan_number": "01", "Flow Path": self.project_folder / f"sample.{flow_suffix}"}]
        )

    def compute(plan_number, **kwargs):
        calls["compute"] = calls.get("compute", 0) + 1
        project = kwargs["ras_object"].project_folder
        # A rebuild must leave fresh preprocessing output, as HEC-RAS would.
        (project / "sample.c01").write_bytes(b"fresh-c")
        (project / "sample.p01.hdf").write_bytes(b"hdf")
        return ComputeResult(success=True)

    def steady(*args, **kwargs):
        calls["steady"] = calls.get("steady", 0) + 1
        return {"passed": True, "reason_codes": []}

    def unsteady(*args, **kwargs):
        calls["unsteady"] = calls.get("unsteady", 0) + 1
        return {"passed": True, "reason_codes": [], "flow_type": "unsteady"}

    monkeypatch.setattr(PortableExecution.RasPrj, "initialize", initialize)
    monkeypatch.setattr(PortableExecution.RasCmdr, "compute_plan", compute)
    monkeypatch.setattr(
        PortableExecution.HdfResultsPlan,
        "get_compute_messages_hdf_only",
        lambda path: "Complete Process",
    )
    monkeypatch.setattr(PortableExecution, "validate_steady_results", steady)
    monkeypatch.setattr(PortableExecution, "validate_unsteady_results", unsteady)


def test_an_unsteady_plan_runs_and_is_validated_as_unsteady(tmp_path, monkeypatch):
    """The gate that refused every non-steady plan is gone."""
    calls: dict = {}
    _patch_run(monkeypatch, "u01", calls)

    receipt = PortableExecution.execute_request(_bundle(tmp_path, "u01"))

    assert receipt.success, receipt.error
    assert receipt.solver_verified and receipt.hydraulic_validated
    assert calls == {"compute": 1, "unsteady": 1}
    assert receipt.compute_diagnostics["plan"] == {
        "flow_type": "unsteady",
        "flow_file": "sample.u01",
        "validator": "validate_unsteady_results",
    }


def test_a_steady_plan_still_runs_the_steady_validator(tmp_path, monkeypatch):
    calls: dict = {}
    _patch_run(monkeypatch, "f01", calls)

    receipt = PortableExecution.execute_request(_bundle(tmp_path, "f01"))

    assert receipt.success, receipt.error
    assert calls == {"compute": 1, "steady": 1}
    assert receipt.compute_diagnostics["plan"]["flow_type"] == "steady"
    assert receipt.compute_diagnostics["plan"]["validator"] == "validate_steady_results"


def test_an_unsupported_flow_file_fails_without_starting_the_solver(tmp_path, monkeypatch):
    calls: dict = {}
    _patch_run(monkeypatch, "q01", calls)

    receipt = PortableExecution.execute_request(_bundle(tmp_path, "q01"))

    assert not receipt.success
    assert "compute" not in calls
    assert "only steady (.f##) and unsteady (.u##)" in receipt.error
    assert receipt.compute_diagnostics["plan"]["flow_file"] == "sample.q01"


def test_stored_maps_on_an_unsteady_plan_are_refused_before_any_solve(tmp_path, monkeypatch):
    """Maps are generated at steady profiles; spending a solve first would waste it."""
    calls: dict = {}
    _patch_run(monkeypatch, "u01", calls)

    receipt = PortableExecution.execute_request(_bundle(tmp_path, "u01", stored_maps=MAPS))

    assert not receipt.success
    assert "compute" not in calls
    assert "Stored maps are supported only for steady plans" in receipt.error


def test_a_failed_unsteady_validation_names_the_plan_type(tmp_path, monkeypatch):
    calls: dict = {}
    _patch_run(monkeypatch, "u01", calls)
    monkeypatch.setattr(
        PortableExecution,
        "validate_unsteady_results",
        lambda *a, **k: {"passed": False, "reason_codes": ["UNSTEADY_VOLUME_ERROR_EXCEEDED"]},
    )

    receipt = PortableExecution.execute_request(_bundle(tmp_path, "u01"))

    assert not receipt.success
    assert receipt.solver_verified and not receipt.hydraulic_validated
    assert receipt.error.startswith("Unsteady results failed hydraulic validation")


# --- the Docker launcher ------------------------------------------------------


def test_docker_names_the_entrypoint_and_passes_security_options(tmp_path):
    """An image's own ENTRYPOINT would otherwise be prepended to the executor.

    Wine inside the image also needs AppArmor relaxed on some hosts; the
    launcher has to be able to say so.
    """
    path = _bundle(tmp_path, "u01")
    command = RasPortableDocker.build_execute_command(
        path, security_options=("apparmor=unconfined",)
    )

    image = "registry.example/hecras/any@sha256:" + "b" * 64
    assert command[command.index("--security-opt") + 1] == "apparmor=unconfined"
    entry = command.index("--entrypoint")
    assert command[entry + 1] == "python"
    assert command[entry + 2] == image
    assert command[entry + 3 : entry + 5] == ("-m", "ras_commander.remote.execute_request")
    assert command[-2:] == ("execute-request", "/job/request.json")


def test_docker_rejects_an_empty_security_option(tmp_path):
    with pytest.raises(ValueError, match="security options"):
        RasPortableDocker.build_execute_command(
            _bundle(tmp_path, "u01"), security_options=(" ",)
        )
