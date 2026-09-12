"""Regression tests for explicit ``rasmap_df`` parse provenance."""

import builtins
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ras_commander import RasMap
from ras_commander.RasPrj import RasPrj
from ras_commander._rasmap_schema import (
    RASMAP_COLUMNS,
    RASMAP_LEGACY_COLUMNS,
    create_rasmap_dataframe,
    expected_rasmap_path,
    rasmap_dataframe_is_usable,
)
from ras_commander._rasmap_layer_helper import top_level_map_layers
from ras_commander.schemas import DATAFRAME_SCHEMAS


REPO_ROOT = Path(__file__).resolve().parent.parent
BALD_EAGLE_RASMAP_FIXTURE = (
    REPO_ROOT
    / "tests"
    / "data"
    / "rasmap"
    / "bald_eagle_representative.rasmap"
)


def _path_names(value):
    """Return platform-neutral basenames for one path or a path collection."""
    values = value if isinstance(value, list) else [value]
    return [str(item).replace("\\", "/").rsplit("/", 1)[-1] for item in values]


def test_schema_is_always_one_row_and_preserves_legacy_column_order():
    rasmap_df = create_rasmap_dataframe()

    assert rasmap_df.shape == (1, len(RASMAP_COLUMNS))
    assert list(rasmap_df.columns[: len(RASMAP_LEGACY_COLUMNS)]) == list(
        RASMAP_LEGACY_COLUMNS
    )
    assert rasmap_df.index.tolist() == [0]
    assert [
        column["name"]
        for column in DATAFRAME_SCHEMAS["rasmap_df"]["columns"]
    ] == list(rasmap_df.columns)


def test_schema_uses_fresh_mutable_defaults():
    first = create_rasmap_dataframe()
    second = create_rasmap_dataframe()

    first.at[0, "terrain_hdf_path"].append("terrain.hdf")
    first.at[0, "rasmap_field_errors"]["terrain_hdf_path"] = "broken"

    assert second.at[0, "terrain_hdf_path"] == []
    assert second.at[0, "rasmap_field_errors"] == {}


def test_shared_path_and_health_helpers_preserve_legacy_frames(tmp_path: Path):
    assert expected_rasmap_path(tmp_path, "Project") == tmp_path / "Project.rasmap"
    assert not rasmap_dataframe_is_usable(create_rasmap_dataframe())
    assert rasmap_dataframe_is_usable(
        create_rasmap_dataframe(rasmap_status="parsed")
    )
    assert rasmap_dataframe_is_usable(
        create_rasmap_dataframe(rasmap_status="parsed_with_errors")
    )
    assert rasmap_dataframe_is_usable(
        create_rasmap_dataframe().drop(columns=["rasmap_status"])
    )


def test_top_level_layer_traversal_excludes_nested_layers():
    root = ET.fromstring(
        "<RASMapper><MapLayers><Layer Name='top'><Layer Name='nested' />"
        "</Layer><Layer Name='sibling' /></MapLayers></RASMapper>"
    )

    assert [layer.attrib["Name"] for layer in top_level_map_layers(root)] == [
        "top",
        "sibling",
    ]


@pytest.mark.parametrize(
    ("contents", "expected_error_prefix"),
    [
        (b"", "ParseError:"),
        (b"not xml", "ParseError:"),
        (b"<RASMapper>", "ParseError:"),
        (b"<NotRASMapper />", "ValueError:"),
    ],
)
def test_document_parse_failures_are_explicit(
    tmp_path: Path,
    contents: bytes,
    expected_error_prefix: str,
):
    rasmap_path = tmp_path / "Broken.rasmap"
    rasmap_path.write_bytes(contents)

    rasmap_df = RasMap.parse_rasmap(rasmap_path)

    assert len(rasmap_df) == 1
    assert rasmap_df.at[0, "rasmap_status"] == "failed"
    assert rasmap_df.at[0, "rasmap_error"].startswith(expected_error_prefix)
    assert rasmap_df.at[0, "rasmap_field_errors"] == {}


def test_missing_file_is_absent_and_retains_requested_path(tmp_path: Path):
    rasmap_path = tmp_path / "Missing.rasmap"

    rasmap_df = RasMap.parse_rasmap(rasmap_path)

    assert len(rasmap_df) == 1
    assert rasmap_df.at[0, "rasmap_status"] == "absent"
    assert rasmap_df.at[0, "rasmap_path"] == str(rasmap_path)
    assert rasmap_df.at[0, "rasmap_error"] is None


def test_valid_minimal_and_utf8_bom_files_are_parsed(tmp_path: Path):
    rasmap_path = tmp_path / "Minimal.rasmap"
    rasmap_path.write_bytes(b"\xef\xbb\xbf<RASMapper />")

    rasmap_df = RasMap.parse_rasmap(rasmap_path)

    assert rasmap_df.at[0, "rasmap_status"] == "parsed"
    assert rasmap_df.at[0, "rasmap_error"] is None
    assert rasmap_df.at[0, "rasmap_field_errors"] == {}


def test_helper_import_failure_returns_failed_summary(monkeypatch, tmp_path: Path):
    rasmap_path = tmp_path / "ImportFailure.rasmap"
    rasmap_path.write_text("<RASMapper />", encoding="utf-8")
    original_import = builtins.__import__

    def fail_land_helper(name, globals=None, locals=None, fromlist=(), level=0):
        if "_land_classification_helper" in fromlist:
            raise ImportError("injected helper import failure")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fail_land_helper)

    rasmap_df = RasMap.parse_rasmap(rasmap_path)

    assert len(rasmap_df) == 1
    assert rasmap_df.at[0, "rasmap_status"] == "failed"
    assert rasmap_df.at[0, "rasmap_error"] == (
        "ImportError: injected helper import failure"
    )
    assert rasmap_df.at[0, "terrain_hdf_path"] == []


def test_four_public_lifecycle_states_are_mutually_distinguishable(
    tmp_path: Path,
):
    paths = {
        "absent": tmp_path / "Absent.rasmap",
        "failed": tmp_path / "Failed.rasmap",
        "valid": tmp_path / "Valid.rasmap",
        "partial": tmp_path / "Partial.rasmap",
    }
    paths["failed"].write_text("<RASMapper>", encoding="utf-8")
    paths["valid"].write_text("<RASMapper />", encoding="utf-8")
    paths["partial"].write_text(
        '<RASMapper><Terrains><Layer Type="TerrainLayer" /></Terrains></RASMapper>',
        encoding="utf-8",
    )

    statuses = {
        name: RasMap.parse_rasmap(path).at[0, "rasmap_status"]
        for name, path in paths.items()
    }

    assert statuses == {
        "absent": "absent",
        "failed": "failed",
        "valid": "parsed",
        "partial": "parsed_with_errors",
    }


def test_bald_eagle_fixture_preserves_happy_path_values():
    rasmap_df = RasMap.parse_rasmap(BALD_EAGLE_RASMAP_FIXTURE)

    assert rasmap_df.at[0, "rasmap_status"] == "parsed"
    assert rasmap_df.at[0, "rasmap_field_errors"] == {}
    assert _path_names(rasmap_df.at[0, "projection_path"]) == ["Projection.prj"]
    assert _path_names(rasmap_df.at[0, "profile_lines_path"]) == [
        "Profile Lines.shp"
    ]
    assert _path_names(rasmap_df.at[0, "soil_layer_path"]) == [
        "Hydrologic Soil Groups.hdf"
    ]
    assert _path_names(rasmap_df.at[0, "infiltration_hdf_path"]) == [
        "Infiltration.hdf"
    ]
    assert _path_names(rasmap_df.at[0, "landcover_hdf_path"]) == ["LandCover.hdf"]
    assert _path_names(rasmap_df.at[0, "terrain_hdf_path"]) == ["Terrain50.hdf"]
    assert rasmap_df.at[0, "reference_map_layer_names"] == ["Inspection Line"]
    assert _path_names(rasmap_df.at[0, "reference_map_layer_path"]) == [
        "Inspection Line.shp"
    ]
    assert rasmap_df.at[0, "basemap_layer_names"] == ["USGS Topo"]
    assert _path_names(rasmap_df.at[0, "basemap_layer_path"]) == ["USGS Topo.xml"]
    assert rasmap_df.at[0, "current_settings"] == {
        "ProjectIsMetric": "False",
        "TerrainFolder": "Terrain",
    }


def test_malformed_terrain_is_partial_failure_without_hiding_other_fields(
    tmp_path: Path,
):
    rasmap_path = tmp_path / "Partial.rasmap"
    contents = BALD_EAGLE_RASMAP_FIXTURE.read_text(encoding="utf-8")
    contents = contents.replace(
        ' Filename=".\\Terrain\\Terrain50.hdf"',
        "",
        1,
    )
    rasmap_path.write_text(contents, encoding="utf-8")

    rasmap_df = RasMap.parse_rasmap(rasmap_path)

    assert rasmap_df.at[0, "rasmap_status"] == "parsed_with_errors"
    assert rasmap_df.at[0, "rasmap_error"] is None
    assert rasmap_df.at[0, "terrain_hdf_path"] == []
    assert "terrain_hdf_path" in rasmap_df.at[0, "rasmap_field_errors"]
    assert Path(rasmap_df.at[0, "projection_path"]).name == "Projection.prj"
    assert len(rasmap_df.at[0, "landcover_hdf_path"]) == 1


def test_malformed_layer_declarations_preserve_valid_siblings(tmp_path: Path):
    rasmap_path = tmp_path / "Mixed.rasmap"
    contents = BALD_EAGLE_RASMAP_FIXTURE.read_text(encoding="utf-8")
    contents = contents.replace(
        "  </MapLayers>",
        """    <Layer Name="Broken Land" Type="LandCoverLayer" />
    <Layer Name="Broken Reference" Type="PolylineFeatureLayer" />
    <Layer Name="Broken Basemap" Type="WMSLayer" />
  </MapLayers>""",
    )
    contents = contents.replace(
        "  </Terrains>",
        """    <Layer Name="Broken Terrain" Type="TerrainLayer" />
  </Terrains>""",
    )
    rasmap_path.write_text(contents, encoding="utf-8")

    rasmap_df = RasMap.parse_rasmap(rasmap_path)
    errors = rasmap_df.at[0, "rasmap_field_errors"]

    assert rasmap_df.at[0, "rasmap_status"] == "parsed_with_errors"
    assert _path_names(rasmap_df.at[0, "landcover_hdf_path"]) == ["LandCover.hdf"]
    assert _path_names(rasmap_df.at[0, "soil_layer_path"]) == [
        "Hydrologic Soil Groups.hdf"
    ]
    assert _path_names(rasmap_df.at[0, "infiltration_hdf_path"]) == [
        "Infiltration.hdf"
    ]
    assert _path_names(rasmap_df.at[0, "terrain_hdf_path"]) == ["Terrain50.hdf"]
    assert "Inspection Line" in rasmap_df.at[0, "reference_map_layer_names"]
    assert _path_names(rasmap_df.at[0, "reference_map_layer_path"]) == [
        "Inspection Line.shp"
    ]
    assert "USGS Topo" in rasmap_df.at[0, "basemap_layer_names"]
    assert _path_names(rasmap_df.at[0, "basemap_layer_path"]) == ["USGS Topo.xml"]
    assert {
        "soil_layer_path",
        "infiltration_hdf_path",
        "landcover_hdf_path",
        "terrain_hdf_path",
        "reference_map_layer_path",
        "basemap_layer_path",
    }.issubset(errors)


def test_legacy_and_modern_landcover_layers_share_one_parse_path(tmp_path: Path):
    rasmap_path = tmp_path / "LegacyAndModern.rasmap"
    contents = BALD_EAGLE_RASMAP_FIXTURE.read_text(encoding="utf-8")
    contents = contents.replace(
        'Type="LandCoverLayer"',
        'Type="LandCover"',
        1,
    )
    rasmap_path.write_text(contents, encoding="utf-8")

    rasmap_df = RasMap.parse_rasmap(rasmap_path)

    assert rasmap_df.at[0, "rasmap_status"] == "parsed"
    assert _path_names(rasmap_df.at[0, "landcover_hdf_path"]) == [
        "LandCover.hdf"
    ]
    (tmp_path / "LegacyAndModern.prj").write_text(
        "Proj Title=Legacy and Modern\n",
        encoding="utf-8",
    )
    layers = RasMap.list_map_layers(rasmap_path)
    assert "land_classification" in layers["category"].tolist()


def test_initialize_without_rasmap_returns_expected_path(tmp_path: Path):
    class ProjectStub:
        project_folder = tmp_path
        project_name = "NoMap"

        @staticmethod
        def check_initialized():
            return None

    rasmap_df = RasMap.initialize_rasmap_df(ProjectStub())

    assert len(rasmap_df) == 1
    assert rasmap_df.at[0, "rasmap_status"] == "absent"
    assert rasmap_df.at[0, "rasmap_path"] == str(tmp_path / "NoMap.rasmap")


def test_rasprj_initialization_fallback_is_one_row(monkeypatch, tmp_path: Path):
    prj_path = tmp_path / "Fallback.prj"
    prj_path.write_text("Proj Title=Fallback\nCurrent Plan=\n", encoding="utf-8")
    project = RasPrj()

    monkeypatch.setattr(project, "_load_project_data", lambda: None)
    monkeypatch.setattr(project, "get_boundary_conditions", lambda: None)
    monkeypatch.setattr(project, "refresh_project_crs", lambda: None)

    def fail_initialization(*args, **kwargs):
        raise RuntimeError("injected initialization failure")

    monkeypatch.setattr(RasMap, "initialize_rasmap_df", fail_initialization)

    project.initialize(
        tmp_path,
        ras_exe_path="Ras.exe",
        suppress_logging=True,
        prj_file=prj_path,
        load_results_summary=False,
    )

    assert len(project.rasmap_df) == 1
    assert project.rasmap_df.at[0, "rasmap_status"] == "failed"
    assert project.rasmap_df.at[0, "rasmap_error"] == (
        "RuntimeError: injected initialization failure"
    )


def test_rasprj_import_fallback_is_one_row(monkeypatch, tmp_path: Path):
    prj_path = tmp_path / "ImportFallback.prj"
    prj_path.write_text(
        "Proj Title=Import Fallback\nCurrent Plan=\n",
        encoding="utf-8",
    )
    project = RasPrj()

    monkeypatch.setattr(project, "_load_project_data", lambda: None)
    monkeypatch.setattr(project, "get_boundary_conditions", lambda: None)
    monkeypatch.setattr(project, "refresh_project_crs", lambda: None)
    monkeypatch.setitem(sys.modules, "ras_commander.RasMap", None)

    project.initialize(
        tmp_path,
        ras_exe_path="Ras.exe",
        suppress_logging=True,
        prj_file=prj_path,
        load_results_summary=False,
    )

    assert len(project.rasmap_df) == 1
    assert project.rasmap_df.at[0, "rasmap_status"] == "failed"
    assert project.rasmap_df.at[0, "rasmap_error"].startswith("ImportError:")


def test_rasprj_initialization_importerror_preserves_real_error(
    monkeypatch,
    tmp_path: Path,
):
    prj_path = tmp_path / "DependencyFailure.prj"
    prj_path.write_text(
        "Proj Title=Dependency Failure\nCurrent Plan=\n",
        encoding="utf-8",
    )
    project = RasPrj()

    monkeypatch.setattr(project, "_load_project_data", lambda: None)
    monkeypatch.setattr(project, "get_boundary_conditions", lambda: None)
    monkeypatch.setattr(project, "refresh_project_crs", lambda: None)

    def fail_initialization(*args, **kwargs):
        raise ImportError("optional parser dependency is unavailable")

    monkeypatch.setattr(RasMap, "initialize_rasmap_df", fail_initialization)

    project.initialize(
        tmp_path,
        ras_exe_path="Ras.exe",
        suppress_logging=True,
        prj_file=prj_path,
        load_results_summary=False,
    )

    assert len(project.rasmap_df) == 1
    assert project.rasmap_df.at[0, "rasmap_status"] == "failed"
    assert project.rasmap_df.at[0, "rasmap_error"] == (
        "ImportError: optional parser dependency is unavailable"
    )
