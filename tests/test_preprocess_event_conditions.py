"""Completed event conditions are required even for point-station rainfall."""

import h5py
import numpy as np
import pytest
from test_raspreprocess_gridded_precipitation import (
    _ExitedProcess,
    _patch_launch,
    _RunningProcess,
    _seed_project,
)

from ras_commander.RasApptainer import check_solver_ready
from ras_commander.RasPreprocess import RasPreprocess


def _event_hdf(path, *, complete=True, values=True, mode="Point"):
    with h5py.File(path, "w") as hdf:
        event = hdf.create_group("Event Conditions")
        if complete is not None:
            event.attrs["Completed Successfully"] = complete
        precip = event.create_group("Meteorology/Precipitation")
        precip.attrs["Mode"] = mode
        if values:
            precip.create_dataset("Values", data=[[0.0, 0.1], [0.2, 0.0]])
        # Empty station datasets are not evidence that interpolated rain is missing.
        precip.create_dataset("Station Values", shape=(0,), dtype="f4")
        hdf.create_group("Geometry/GeomPreprocess").create_dataset("Complete", data=[1])


@pytest.mark.parametrize("complete", [False, None, "False", b"False", 0, [True, False]])
def test_apptainer_rejects_incomplete_event_conditions(tmp_path, complete):
    path = tmp_path / "model.p01.tmp.hdf"
    _event_hdf(path, complete=complete)
    assert any("Completed Successfully" in p for p in check_solver_ready(path))


@pytest.mark.parametrize("mode", ["Point", "Gridded"])
@pytest.mark.parametrize("shape", [None, (0, 2), (2, 0), (2,)])
def test_apptainer_requires_materialized_rain_values(tmp_path, mode, shape):
    path = tmp_path / "model.p01.tmp.hdf"
    _event_hdf(path, values=False, mode=mode)
    if shape is not None:
        with h5py.File(path, "a") as hdf:
            hdf["Event Conditions/Meteorology/Precipitation"].create_dataset(
                "Values", shape=shape, dtype="f4"
            )
    assert any("Precipitation/Values" in p for p in check_solver_ready(path))


@pytest.mark.parametrize("complete", [True, 1, "True", np.bytes_("True"), [True]])
def test_completed_point_rain_needs_no_gridded_mapping(tmp_path, complete):
    path = tmp_path / "model.p01.tmp.hdf"
    _event_hdf(path, complete=complete)
    assert check_solver_ready(path) == []


def test_completed_non_rain_plan_needs_no_precipitation(tmp_path):
    path = tmp_path / "model.p01.tmp.hdf"
    _event_hdf(path)
    with h5py.File(path, "a") as hdf:
        del hdf["Event Conditions/Meteorology"]
    assert check_solver_ready(path) == []


def test_uniform_rain_uses_its_own_layout(tmp_path):
    path = tmp_path / "model.p01.tmp.hdf"
    _event_hdf(path, mode="Uniform", values=False)
    assert check_solver_ready(path) == []


def test_missing_event_conditions_is_not_ready(tmp_path):
    path = tmp_path / "model.p01.tmp.hdf"
    _event_hdf(path)
    with h5py.File(path, "a") as hdf:
        del hdf["Event Conditions"]
    assert any("Completed Successfully" in p for p in check_solver_ready(path))


@pytest.mark.parametrize("natural", [False, True])
@pytest.mark.parametrize("complete,values,success", [(False, False, False), (True, False, False), (True, True, True)])
def test_point_preprocessing_validates_after_process_cleanup(
    tmp_path, monkeypatch, natural, complete, values, success
):
    ras = _seed_project(tmp_path)
    (tmp_path / "fixture.u02").write_text(
        "Precipitation Mode=Enable\nMet BC=Precipitation|Mode=Point\n"
    )
    process = _ExitedProcess() if natural else _RunningProcess()
    terminated = []

    class Monitor:
        blocked_reason = None
        signal_source = None if natural else "alternate"

        @staticmethod
        def enable_detailed_logging(_path):
            return True

        def __init__(self, **_kwargs):
            pass

        def monitor_until_signal(self, _process):
            _event_hdf(tmp_path / "fixture.p01.tmp.hdf", complete=complete, values=values)
            (tmp_path / "fixture.b01").write_bytes(b"ready")
            (tmp_path / "fixture.x03").write_bytes(b"ready")
            return not natural

    _patch_launch(monkeypatch, Monitor, process, terminated)
    monkeypatch.setattr(RasPreprocess, "_terminate_exact_preprocess_residue", lambda **_: ((), ()))
    from ras_commander import _preprocess_validation

    validate = _preprocess_validation._event_condition_errors

    def validate_after_cleanup(hdf, mode):
        assert process.poll() is not None
        return validate(hdf, mode)

    monkeypatch.setattr(_preprocess_validation, "_event_condition_errors", validate_after_cleanup)
    result = RasPreprocess.preprocess_plan(
        "01", ras_object=ras, max_wait=2, clear_existing=False, fix_line_endings=False
    )
    assert process.poll() is not None
    assert result.success is success
    if not success:
        assert "Event Conditions" in result.error
        assert result.tmp_hdf_path == tmp_path / "fixture.p01.tmp.hdf"


def test_active_text_point_mode_cannot_be_hidden_by_missing_hdf_group(tmp_path):
    from ras_commander._preprocess_validation import _event_condition_errors

    ras = _seed_project(tmp_path)
    (tmp_path / "fixture.u02").write_text(
        "Precipitation Mode=Enable\nMet BC=Precipitation|Mode=Point\n"
    )
    mode = RasPreprocess._plan_precipitation_mode(
        tmp_path / "fixture.p01", tmp_path, ras.project_name
    )
    assert mode == "point"
    path = tmp_path / "fixture.p01.tmp.hdf"
    _event_hdf(path)
    with h5py.File(path, "a") as hdf:
        del hdf["Event Conditions/Meteorology"]
        assert any("Precipitation/Values" in p for p in _event_condition_errors(hdf, mode))
