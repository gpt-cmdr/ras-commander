import logging
from types import SimpleNamespace

import h5py
import pandas as pd

from ras_commander.RasCurrency import RasCurrency
from ras_commander.hdf.HdfResultsPlan import HdfResultsPlan


def _ras_object(tmp_path, plan_path, geom_path, flow_path):
    return SimpleNamespace(
        project_folder=tmp_path,
        project_name="Demo",
        plan_df=pd.DataFrame(
            [
                {
                    "plan_number": "01",
                    "full_path": plan_path,
                    "Geom Path": geom_path,
                    "Flow Path": flow_path,
                }
            ]
        ),
    )


def test_missing_expected_input_marks_plan_stale_with_concise_reason(
    tmp_path,
    caplog,
):
    hdf_path = tmp_path / "Demo.p01.hdf"
    plan_path = tmp_path / "Demo.p01"
    geom_path = tmp_path / "Demo.g01"
    flow_path = tmp_path / "Demo.u01"

    hdf_path.touch()
    plan_path.touch()
    flow_path.touch()
    ras_object = _ras_object(tmp_path, plan_path, geom_path, flow_path)

    caplog.set_level(logging.WARNING, logger="ras_commander.RasCurrency")

    is_current, reason = RasCurrency.are_plan_results_current(
        "01",
        ras_object,
        check_complete=False,
    )

    assert is_current is False
    assert reason == "Plan 01 stale: missing input files: geom: Demo.g01"
    assert str(tmp_path) not in reason

    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.name == "ras_commander.RasCurrency"
        and record.levelno == logging.WARNING
    ]
    assert warnings == [
        f"Plan 01 expected geom input file not found: {geom_path}"
    ]


def test_unreadable_input_mtime_logs_one_contextual_warning(
    tmp_path,
    monkeypatch,
    caplog,
):
    hdf_path = tmp_path / "Demo.p01.hdf"
    plan_path = tmp_path / "Demo.p01"
    geom_path = tmp_path / "Demo.g01"
    flow_path = tmp_path / "Demo.u01"

    for path in (hdf_path, plan_path, geom_path, flow_path):
        path.touch()

    ras_object = _ras_object(tmp_path, plan_path, geom_path, flow_path)
    real_get_file_mtime = RasCurrency.get_file_mtime

    def fake_get_file_mtime(file_path, warn_on_error=True):
        if file_path == geom_path:
            return None
        return real_get_file_mtime(file_path, warn_on_error=warn_on_error)

    monkeypatch.setattr(
        RasCurrency,
        "get_file_mtime",
        staticmethod(fake_get_file_mtime),
    )

    caplog.set_level(logging.WARNING, logger="ras_commander.RasCurrency")

    is_current, reason = RasCurrency.are_plan_results_current(
        "01",
        ras_object,
        check_complete=False,
    )

    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.name == "ras_commander.RasCurrency"
        and record.levelno == logging.WARNING
    ]

    assert is_current is False
    assert reason == "Plan 01 stale: unreadable input mtimes: geom: Demo.g01"
    assert str(tmp_path) not in reason
    assert warnings == [
        f"Plan 01 cannot get mtime for geom input file {geom_path}; assuming stale"
    ]


def test_incomplete_hdf_reason_identifies_missing_plan_information(
    tmp_path,
    monkeypatch,
    caplog,
):
    hdf_path = tmp_path / "Demo.p01.hdf"
    with h5py.File(hdf_path, "w"):
        pass

    ras_object = SimpleNamespace(
        project_folder=tmp_path,
        project_name="Demo",
        plan_df=pd.DataFrame(),
    )
    monkeypatch.setattr(
        HdfResultsPlan,
        "get_compute_messages",
        staticmethod(lambda _hdf_path: "Complete Process"),
    )

    caplog.set_level(logging.DEBUG, logger="ras_commander.RasCurrency")

    assert RasCurrency.check_plan_hdf_complete(hdf_path) is False

    is_current, reason = RasCurrency.are_plan_results_current(
        "01",
        ras_object,
    )

    assert is_current is False
    assert reason == (
        "Plan 01 HDF exists but incomplete "
        "(missing '/Plan Data/Plan Information')"
    )
    assert f"Plan HDF missing '/Plan Data/Plan Information': {hdf_path}" in caplog.text
