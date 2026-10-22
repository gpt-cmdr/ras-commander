"""Explicit core requests must work on native plans omitting core controls."""

import os
from pathlib import Path
import shutil

import pytest

from ras_commander import RasPlan


class _Ready:
    def check_initialized(self):
        pass


def _cores(path):
    return [line for line in path.read_text().splitlines() if line.startswith((
        "UNET D1 Cores=", "UNET D2 Cores=", "PS Cores=",
    ))]


@pytest.mark.parametrize("cores", [0, 2])
def test_missing_core_controls_are_upserted_on_real_minimal_plan(tmp_path, cores):
    source = Path(os.environ.get(
        "RAS_COMMANDER_MINIMAL_CORE_PLAN",
        "tests/data/external/EtherHollow.p01",
    ))
    if not source.is_file():
        pytest.skip("Set RAS_COMMANDER_MINIMAL_CORE_PLAN to immutable minimal EtherHollow plan")
    before = source.read_bytes()
    assert _cores(source) == []
    copy = tmp_path / "EtherHollow.p01"
    shutil.copy2(source, copy)
    RasPlan.set_num_cores(copy, cores, ras_object=_Ready(), refresh_dataframes=False)
    assert _cores(copy) == [f"{key}= {cores}" for key in ("UNET D1 Cores", "UNET D2 Cores", "PS Cores")]
    for line in before.decode().splitlines():
        assert line in copy.read_text().splitlines()
    once = copy.read_bytes()
    RasPlan.set_num_cores(copy, cores, ras_object=_Ready(), refresh_dataframes=False)
    assert copy.read_bytes() == once
    assert source.read_bytes() == before


def test_existing_duplicate_and_mesh_core_controls_all_update(tmp_path):
    plan = tmp_path / "Model.p01"
    plan.write_text(
        "Plan Title=Core contract\nUNET D1 Cores= 4\nUNET D1 Cores= 6\n"
        "UNET D2 Name=Area A\nUNET D2 Cores= 8\nUNET D2 Name=Area B\nUNET D2 Cores= 3\n"
    )
    RasPlan.set_num_cores(plan, 2, ras_object=_Ready(), refresh_dataframes=False)
    assert _cores(plan) == ["UNET D1 Cores= 2", "UNET D1 Cores= 2", "UNET D2 Cores= 2", "PS Cores= 2",
                            "UNET D2 Cores= 2", "UNET D2 Cores= 2"]
    assert plan.read_text().index("UNET D2 Cores=") < plan.read_text().index("UNET D2 Name=")
    assert plan.read_text().index("PS Cores=") < plan.read_text().index("UNET D2 Name=")


def test_missing_default_d2_precedes_first_named_area(tmp_path):
    plan = tmp_path / "Model.p01"
    plan.write_text("Plan Title=Core contract\nUNET D2 Name=Area A\nUNET D2 Equation= 1\nUNET D2 Name=Area B")
    RasPlan.set_num_cores(plan, 2, ras_object=_Ready(), refresh_dataframes=False)
    text = plan.read_text()
    assert text.index("UNET D2 Cores=") < text.index("UNET D2 Name=Area A")
    assert len(_cores(plan)) == 3


def test_description_core_text_is_not_changed_or_used_as_a_control(tmp_path):
    plan = tmp_path / "Model.p01"
    plan.write_text("Plan Title=Core contract\nBegin DESCRIPTION:\nUNET D2 Cores=8\nEND DESCRIPTION:\n")
    RasPlan.set_num_cores(plan, 2, ras_object=_Ready(), refresh_dataframes=False)
    assert "Begin DESCRIPTION:\nUNET D2 Cores=8\nEND DESCRIPTION:\n" in plan.read_text()
    assert plan.read_text().splitlines()[-3:] == ["UNET D1 Cores= 2", "UNET D2 Cores= 2", "PS Cores= 2"]


def test_default_refresh_still_runs_and_false_does_not_require_refresh_methods(tmp_path):
    class Refreshing(_Ready):
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            if name.startswith("get_") and name.endswith("_entries"):
                def entries():
                    self.calls.append(name)
                    return name
                return entries
            raise AttributeError(name)

    plan = tmp_path / "Model.p01"
    plan.write_text("Plan Title=Core contract\n")
    ras = Refreshing()
    RasPlan.set_num_cores(plan, 2, ras_object=ras)
    assert ras.calls == ["get_plan_entries", "get_geom_entries", "get_flow_entries", "get_unsteady_entries"]
    assert ras.plan_df == "get_plan_entries"


@pytest.mark.parametrize("cores", [-1, 1.5, True, float("nan"), float("inf")])
def test_invalid_core_request_preserves_plan(tmp_path, cores):
    plan = tmp_path / "Model.p01"
    plan.write_text("Plan Title=Core contract\n")
    before = plan.read_bytes()
    with pytest.raises(ValueError, match="nonnegative integer"):
        RasPlan.set_num_cores(plan, cores, ras_object=_Ready(), refresh_dataframes=False)
    assert plan.read_bytes() == before
