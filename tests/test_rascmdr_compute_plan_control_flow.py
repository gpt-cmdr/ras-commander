"""Focused control-flow regression tests for ``RasCmdr.compute_plan()``."""

import pytest

from ras_commander.ComputeResults import ComputeResult
from ras_commander.RasCmdr import RasCmdr


class _DummyRas:
    """Minimal ras-like object for compute_plan control-flow tests."""

    def __init__(self, init_exception=None):
        self.project_folder = r"C:\fake_project"
        self.prj_file = r"C:\fake_project\test.prj"
        self.ras_exe_path = r"C:\Program Files\HEC-RAS\Ras.exe"
        self.init_exception = init_exception
        self.refresh_calls = []
        self.plan_df = None
        self.geom_df = None
        self.flow_df = None
        self.unsteady_df = None

    def check_initialized(self):
        if self.init_exception is not None:
            raise self.init_exception

    def get_plan_entries(self):
        self.refresh_calls.append("plan")
        return "plan_df"

    def get_geom_entries(self):
        self.refresh_calls.append("geom")
        return "geom_df"

    def get_flow_entries(self):
        self.refresh_calls.append("flow")
        return "flow_df"

    def get_unsteady_entries(self):
        self.refresh_calls.append("unsteady")
        return "unsteady_df"


def test_compute_plan_returns_failed_result_for_regular_exception():
    """Regular Exception paths should stay bool-compatible and non-raising."""
    ras_obj = _DummyRas(init_exception=RuntimeError("boom"))

    result = RasCmdr.compute_plan("01", ras_object=ras_obj)

    assert isinstance(result, ComputeResult)
    assert result.success is False
    assert result.results_df_row is None
    assert ras_obj.refresh_calls == ["plan", "geom", "flow", "unsteady"]


def test_compute_plan_does_not_swallow_keyboard_interrupt():
    """
    Non-Exception exits must propagate after cleanup.

    This guards against returning from a finally block, which would suppress
    ``KeyboardInterrupt`` and similar BaseException subclasses.
    """
    ras_obj = _DummyRas(init_exception=KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        RasCmdr.compute_plan("01", ras_object=ras_obj)

    assert ras_obj.refresh_calls == ["plan", "geom", "flow", "unsteady"]
