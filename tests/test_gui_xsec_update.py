"""Unit coverage for RASMapper geometry layer command dispatch."""

import pytest

from ras_commander.gui.workflows.xsec_update import (
    RasMapperBankLineWorkflow,
    RasMapperLayerCommandWorkflow,
    RasMapperXsecUpdateWorkflow,
)


def test_xsec_update_command_aliases_normalize_to_menu_paths():
    workflow = RasMapperXsecUpdateWorkflow

    assert workflow._normalize_command("river stations") == "river_stations_table"
    assert workflow._normalize_command("terrain") == "elevation_profiles_from_terrain"
    assert workflow.UPDATE_COMMANDS["reach_lengths"] == (
        "Update Cross Sections",
        "Reach Lengths",
    )


def test_xsec_update_rejects_unknown_command():
    with pytest.raises(ValueError, match="Unknown cross-section update command"):
        RasMapperXsecUpdateWorkflow._normalize_command("not a mapper command")


def test_generic_layer_command_aliases_cover_structure_and_storage_updates():
    workflow = RasMapperLayerCommandWorkflow

    assert workflow._normalize_target_node("SA/2D Connections") == ["SA/2D Connections"]
    assert workflow._normalize_command_path("storage_area_curves") == [
        "Compute Elevation-Volume Data"
    ]
    assert workflow._normalize_command_path("sa2d_terrain") == [
        "Update SA/2D Connections",
        "Elevation Profiles from Terrain",
    ]
    assert workflow._normalize_command_path("lateral_river_stations") == [
        "Update Lateral Structures",
        "River Stations",
    ]
    assert workflow._normalize_command_path("compute_edge_lines") == [
        "Create Edge Lines at XS Limits"
    ]
    assert workflow._normalize_command_path("blocked_obstructions") == [
        "Update Blocked Obstructions on XSs"
    ]
    assert workflow._normalize_command_path("bank_points") == [
        "Generate Layers",
        "Bank Points on XS",
    ]
    assert workflow._normalize_command_path("create_bank_lines") == [
        "Create Bank Lines from XS Bank Stations"
    ]
    assert workflow._normalize_target_node("river_bank_lines") == [
        "Rivers",
        "Bank Lines",
    ]
    assert workflow._normalize_target_node("flow_paths") == ["Rivers", "Flow Paths"]


def test_generic_layer_command_accepts_explicit_menu_paths():
    assert RasMapperLayerCommandWorkflow._normalize_command_path(
        ["Update Inline Structures", "Elevation Profiles from Terrain"]
    ) == ["Update Inline Structures", "Elevation Profiles from Terrain"]


def test_common_wrapper_step_building_does_not_touch_gui():
    storage_context = {
        "target_path": ["Storage Areas"],
        "menu_path": ["Compute Elevation-Volume Data"],
        "timeout": 600,
        "save_after": True,
        "close_after": True,
    }

    steps = RasMapperLayerCommandWorkflow._build_steps(storage_context)

    assert [step.name for step in steps][:4] == [
        "Verify HEC-RAS is closed",
        "Launch HEC-RAS",
        "Open RASMapper",
        "Wait for RASMapper",
    ]


def test_workflow_classes_are_static_namespaces():
    with pytest.raises(TypeError, match="static namespace"):
        RasMapperLayerCommandWorkflow()

    with pytest.raises(TypeError, match="static namespace"):
        RasMapperXsecUpdateWorkflow()

    with pytest.raises(TypeError, match="static namespace"):
        RasMapperBankLineWorkflow()


def test_bank_line_workflow_exposes_requested_mapper_commands():
    workflow = RasMapperBankLineWorkflow

    assert workflow.XS_GENERATE_LAYER_COMMANDS["intersections_with_rivers"] == (
        "Generate Layers",
        "XS Intersections with Rivers",
    )
    assert workflow.XS_GENERATE_LAYER_COMMANDS["bank_points_on_xs"] == (
        "Generate Layers",
        "Bank Points on XS",
    )
    assert workflow.XS_GENERATE_LAYER_COMMANDS["levee_points_on_xs"] == (
        "Generate Layers",
        "Levee Points on XS",
    )
    assert workflow.XS_GENERATE_LAYER_COMMANDS["encroachment_points_on_xs"] == (
        "Generate Layers",
        "Encroachment Points on XS",
    )
    assert workflow.BANK_LINE_COMMANDS["update_bank_stations_on_xss"] == (
        "Update Bank Stations on XSs",
    )
    assert workflow.BANK_LINE_COMMANDS["create_from_xs_bank_stations"] == (
        "Create Bank Lines from XS Bank Stations",
    )
    assert workflow.BANK_LINE_COMMANDS["pull_to_xs_bank_stations"] == (
        "Pull Bank Lines to XS Bank Stations",
    )


def test_bank_line_wrappers_route_to_generic_layer_workflow(monkeypatch):
    calls = []

    def fake_run_command(**kwargs):
        calls.append(kwargs)
        return "workflow-result"

    monkeypatch.setattr(
        RasMapperLayerCommandWorkflow,
        "run_command",
        staticmethod(fake_run_command),
    )

    result = RasMapperBankLineWorkflow.create_bank_lines_from_xs_bank_stations(
        "01",
        ras_object="fake-ras",
        timeout=123,
    )

    assert result == "workflow-result"
    assert calls == [
        {
            "target_node": "Bank Lines",
            "command": "bank_lines_create_from_xs_bank_stations",
            "geom_number": "01",
            "ras_object": "fake-ras",
            "timeout": 123,
        }
    ]

    RasMapperBankLineWorkflow.generate_xs_intersections_with_rivers("02")
    assert calls[-1]["target_node"] == "Cross Sections"
    assert calls[-1]["command"] == "xs_intersections_with_rivers"


def test_target_node_is_prefixed_with_geometry_when_geom_number_is_given(monkeypatch):
    class FakeRas:
        geom_df = None

        def check_initialized(self):
            return None

    monkeypatch.setattr(
        "ras_commander.gui.workflows.xsec_update.RasMapperLayerCommandWorkflow."
        "_resolve_geometry_tree_node",
        staticmethod(lambda geom_number, ras_object=None: "Muncie Geometry"),
    )

    assert RasMapperLayerCommandWorkflow._normalize_target_node(
        "Storage Areas",
        geom_number="01",
        ras_object=FakeRas(),
    ) == ["Muncie Geometry", "Storage Areas"]

    assert RasMapperLayerCommandWorkflow._normalize_target_node(
        ["Muncie Geometry", "Storage Areas"],
        geom_number="01",
        ras_object=FakeRas(),
    ) == ["Muncie Geometry", "Storage Areas"]
