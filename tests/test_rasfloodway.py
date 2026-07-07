import logging
from pathlib import Path

import pandas as pd
import pytest

from ras_commander import RasFloodway
from ras_commander.check import RasCheck

LOGGER_NAME = "ras_commander.RasFloodway"


def _log_messages(caplog, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == level
    ]


def _write_plan(path: Path, encroach_block: str = "") -> Path:
    path.write_text(
        "Plan Title=Floodway\n"
        "Version=Version 6.6\n"
        "Short Identifier=FW\n"
        "Simulation Date=,,,\n"
        "Geom File=g01\n"
        "Flow File=f01\n"
        "Subcritical Flow\n"
        "Global Log Level= 0 \n"
        "CheckData=True\n"
        f"{encroach_block}"
        "Computation Interval=1HOUR\n",
        encoding="utf-8",
    )
    return path


def _write_flow(path: Path) -> Path:
    path.write_text(
        "Flow Title=Base Flood\n"
        "Version=Version 6.6\n"
        "Number of Profiles= 1 \n"
        "Profile Names=Base 100yr\n"
        "River Rch & RM=Clear Creek,Main            ,1020.50\n"
        "   14000\n"
        "River Rch & RM=Clear Creek,Main            ,Bridge US\n"
        "   14000\n"
        "Initial Flow Split=Clear Creek,Main            ,900     ,\n"
        "       0\n"
        "Boundary for River Rch & Prof#=Clear Creek,Main            , 1 \n"
        "Up Type= 0 \n"
        "Dn Type= 1 \n"
        "Dn Known WS=211.8\n"
        "DSS Import StartDate=\n",
        encoding="utf-8",
    )
    return path


def _project_files(tmp_path: Path):
    plan = _write_plan(tmp_path / "Project.p01")
    flow = _write_flow(tmp_path / "Project.f01")
    return plan, flow


def test_parse_method_1_encroachments_with_bridge_sections(tmp_path):
    block = (
        "Encroach Param=-1 ,10,20, 2 \n"
        "Encroach River=Clear Creek\n"
        "Encroach Reach=Main\n"
        "Encroach Node=1020.50\n"
        "       1    4910    5075\n"
        "Encroach Node=Bridge US\n"
        "       1    4900    5085\n"
    )
    plan = _write_plan(tmp_path / "Project.p01", encroach_block=block)

    df = RasFloodway.parse_encroachments(plan)

    assert df["node"].tolist() == ["1020.50", "Bridge US"]
    assert df["method"].tolist() == [1, 1]
    assert df.loc[df["node"] == "Bridge US", "left_station"].iloc[0] == 4900
    assert df.loc[df["node"] == "Bridge US", "right_station"].iloc[0] == 5085
    assert RasFloodway.get_encroach_param(plan)["profile_count"] == 2


def test_parse_incomplete_method_values_preserves_missing_value(tmp_path):
    block = (
        "Encroach Param=-1 ,0,0, 2 \n"
        "Encroach River=Clear Creek\n"
        "Encroach Reach=Main\n"
        "Encroach Node=1020.50\n"
        "       4     0.5\n"
    )
    plan = _write_plan(tmp_path / "Project.p01", encroach_block=block)

    df = RasFloodway.parse_encroachments(plan)

    assert df.loc[0, "method"] == 4
    assert df.loc[0, "value_1"] == 0.5
    assert df.loc[0, "value_2"] is None


def test_set_encroachments_writes_multiple_targets_and_bridge_sections(tmp_path):
    plan = _write_plan(tmp_path / "Project.p01")

    RasFloodway.set_encroachments(
        plan,
        [
            {
                "river": "Clear Creek",
                "reach": "Main",
                "node": "1020.50",
                "profiles": [
                    {"method": 4, "target_surcharge": 0.5},
                    {"method": 4, "target_surcharge": 1.0},
                ],
            },
            {
                "river": "Clear Creek",
                "reach": "Main",
                "node": "Bridge DS",
                "profiles": [
                    {"method": 1, "left_station": 4910, "right_station": 5075},
                    {"method": 1, "left_station": 4900, "right_station": 5085},
                ],
            },
        ],
        encroach_param=(0, 5, 7),
        profile_count=3,
    )

    text = plan.read_text(encoding="utf-8")
    assert "Encroach Param=0 ,5,7, 3 " in text
    assert "Encroach Node=Bridge DS" in text
    assert "       4     0.5       0       4       1       0" in text
    assert "       1    4910    5075       1    4900    5085" in text

    parsed = RasFloodway.parse_encroachments(plan)
    assert len(parsed) == 4
    assert parsed["profile_number"].tolist() == [2, 3, 2, 3]


def test_set_encroachments_logs_concise_info_and_debug_path(tmp_path, caplog):
    plan = _write_plan(tmp_path / "Project.p01")
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    RasFloodway.set_encroachments(
        plan,
        [
            {
                "river": "Clear Creek",
                "reach": "Main",
                "node": "1020.50",
                "profiles": [
                    {"method": 4, "target_surcharge": 0.5},
                    {"method": 4, "target_surcharge": 1.0},
                ],
            },
            {
                "river": "Clear Creek",
                "reach": "Main",
                "node": "Bridge DS",
                "profiles": [
                    {"method": 1, "left_station": 4910, "right_station": 5075},
                    {"method": 1, "left_station": 4900, "right_station": 5085},
                ],
            },
        ],
        profile_count=3,
    )

    info_messages = _log_messages(caplog, logging.INFO)
    assert (
        "Updated floodway encroachments in Project.p01: "
        "4 records across 2 nodes, profiles 2-3, methods 1, 4"
    ) in info_messages
    assert info_messages.count(
        "Updated floodway encroachments in Project.p01: "
        "4 records across 2 nodes, profiles 2-3, methods 1, 4"
    ) == 1
    assert all(str(tmp_path) not in message for message in info_messages)
    assert f"Full floodway plan path: {plan}" in _log_messages(caplog, logging.DEBUG)


def test_set_encroachments_accepts_method_2_and_3_named_targets(tmp_path):
    plan = _write_plan(tmp_path / "Project.p01")

    RasFloodway.set_encroachments(
        plan,
        [
            {
                "river": "Clear Creek",
                "reach": "Main",
                "node": "1020.50",
                "profiles": [
                    {"method": 2, "fixed_top_width": 850},
                    {"method": 3, "conveyance_reduction_percent": 25},
                ],
            },
        ],
        profile_count=3,
    )

    text = plan.read_text(encoding="utf-8")
    assert "       2     850       0       3      25       0" in text

    parsed = RasFloodway.parse_encroachments(plan)
    assert parsed["method"].tolist() == [2, 3]
    assert parsed.loc[0, "target_top_width"] == 850
    assert pd.isna(parsed.loc[1, "target_top_width"])
    assert pd.isna(parsed.loc[0, "conveyance_reduction_percent"])
    assert parsed.loc[1, "conveyance_reduction_percent"] == 25


def test_set_encroachments_requires_method_specific_values(tmp_path):
    plan = _write_plan(tmp_path / "Project.p01")

    with pytest.raises(ValueError, match="Method 1"):
        RasFloodway.set_encroachments(
            plan,
            [{
                "river": "Clear Creek",
                "reach": "Main",
                "node": "Bridge US",
                "method": 1,
                "left_station": 4910,
            }],
        )

    with pytest.raises(ValueError, match="Method 4"):
        RasFloodway.set_encroachments(
            plan,
            [{
                "river": "Clear Creek",
                "reach": "Main",
                "node": "1020.50",
                "method": 4,
            }],
        )


def test_create_method_4_trial_profiles_duplicates_flows_and_starting_wse(tmp_path):
    plan, flow = _project_files(tmp_path)

    result = RasFloodway.create_method_4_trial_profiles(
        plan,
        targets=[0.5, 1.0],
        profile_names=["FW 0.5 ft", "FW 1 ft"],
        locations=[
            {"river": "Clear Creek", "reach": "Main", "node": "1020.50"},
            {"river": "Clear Creek", "reach": "Main", "node": "Bridge US"},
        ],
        starting_wse_deltas=[0.5, 1.0],
    )

    flow_text = flow.read_text(encoding="utf-8")
    assert result["new_profile_numbers"] == [2, 3]
    assert "Number of Profiles= 3 " in flow_text
    assert "Profile Names=Base 100yr, FW 0.5 ft, FW 1 ft" in flow_text
    assert "   14000   14000   14000" in flow_text
    assert "       0       0       0" in flow_text
    assert "Boundary for River Rch & Prof#=Clear Creek,Main            , 2 " in flow_text
    assert "Dn Known WS=212.3" in flow_text
    assert "Dn Known WS=212.8" in flow_text

    plan_text = plan.read_text(encoding="utf-8")
    assert "       4     0.5       0       4       1       0" in plan_text
    assert "Floodway Trial Metadata\nmethod: 4\ntargets: 0.5, 1" in plan_text
    assert "flow_file: Project.f01" in plan_text
    assert "base_profile: 1" in plan_text


def test_create_trial_profiles_logs_concise_info_and_debug_paths(tmp_path, caplog):
    plan, flow = _project_files(tmp_path)
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    RasFloodway.create_method_4_trial_profiles(
        plan,
        targets=[0.5, 1.0],
        profile_names=["FW 0.5 ft", "FW 1 ft"],
        locations=[
            {"river": "Clear Creek", "reach": "Main", "node": "1020.50"},
            {"river": "Clear Creek", "reach": "Main", "node": "Bridge US"},
        ],
    )

    info_messages = _log_messages(caplog, logging.INFO)
    expected_info = (
        "Created Method 4 floodway trial profiles in Project.p01 using Project.f01: "
        "2 profiles, 2 targets, 2 locations"
    )
    assert info_messages == [expected_info]
    assert all(str(tmp_path) not in message for message in info_messages)

    debug_messages = _log_messages(caplog, logging.DEBUG)
    assert f"Full floodway trial plan path: {plan}" in debug_messages
    assert f"Full floodway trial flow path: {flow}" in debug_messages


def test_create_method_5_trial_profiles_writes_energy_targets_and_metadata(tmp_path):
    plan, flow = _project_files(tmp_path)

    RasFloodway.create_method_5_trial_profiles(
        plan,
        targets=[0.5, 1.0],
        profile_names=["M5 Low", "M5 High"],
        locations=[
            {"river": "Clear Creek", "reach": "Main", "node": "1020.50"},
            {"river": "Clear Creek", "reach": "Main", "node": "Bridge US"},
        ],
        energy_targets=[0.1, 0.2],
        metadata={"source": "unit-test"},
    )

    flow_text = flow.read_text(encoding="utf-8")
    assert "Profile Names=Base 100yr, M5 Low, M5 High" in flow_text
    assert flow_text.count("Dn Known WS=211.8") == 3

    plan_text = plan.read_text(encoding="utf-8")
    assert "       5     0.5     0.1       5       1     0.2" in plan_text
    assert "method: 5" in plan_text
    assert "source: unit-test" in plan_text


def test_missing_flow_from_plan_reports_expected_path(tmp_path):
    plan = _write_plan(tmp_path / "Project.p01")
    expected_flow = tmp_path / "Project.f01"

    with pytest.raises(FileNotFoundError) as excinfo:
        RasFloodway.create_method_4_trial_profiles(plan, targets=[0.5])

    message = str(excinfo.value)
    assert "Plan references Flow File=f01" in message
    assert str(expected_flow) in message


def test_missing_plan_number_reports_project_context_and_available_plans(tmp_path):
    class FakeRasObject:
        project_name = "Project"
        project_folder = tmp_path
        plan_df = pd.DataFrame({
            "plan_number": ["01"],
            "full_path": [str(tmp_path / "Project.p01")],
        })

        def check_initialized(self):
            return None

        def get_plan_entries(self):
            return self.plan_df

    with pytest.raises(FileNotFoundError) as excinfo:
        RasFloodway.parse_encroachments("02", ras_object=FakeRasObject())

    message = str(excinfo.value)
    assert "Plan file not found: 02" in message
    assert f"Project: Project in {tmp_path}" in message
    assert "Available plans: 01" in message


def test_refresh_ras_object_failure_warns_and_keeps_traceback_debug(caplog):
    class BrokenRasObject:
        def get_plan_entries(self):
            raise RuntimeError("refresh failed")

    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    RasFloodway._refresh_ras_object(BrokenRasObject())

    assert (
        "Could not refresh ras_object.plan_df using get_plan_entries; "
        "in-memory project tables may be stale"
    ) in _log_messages(caplog, logging.WARNING)
    assert "Could not refresh plan_df on ras_object" in _log_messages(caplog, logging.DEBUG)


def test_check_floodway_delegates_to_rascheck(monkeypatch):
    calls = {}

    def fake_check(plan_hdf, geom_hdf, base_profile, floodway_profile, surcharge, thresholds):
        calls["args"] = (plan_hdf, geom_hdf, base_profile, floodway_profile, surcharge, thresholds)
        return "delegated"

    monkeypatch.setattr(RasCheck, "check_floodways", staticmethod(fake_check))

    result = RasFloodway.check_floodway(
        "plan.p01.hdf",
        "geom.g01.hdf",
        "Base",
        "Floodway",
        surcharge_limit=0.5,
        thresholds={"x": 1},
    )

    assert result == "delegated"
    assert calls["args"] == ("plan.p01.hdf", "geom.g01.hdf", "Base", "Floodway", 0.5, {"x": 1})
