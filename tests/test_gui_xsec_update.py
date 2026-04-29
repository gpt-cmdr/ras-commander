"""Unit coverage for RASMapper geometry layer command dispatch."""

import pytest

from ras_commander.gui.workflows.xsec_update import (
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
