import json
import importlib.util
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from ras_commander import RasMap, init_ras_project

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    ROOT / "scripts" / "benchmarks" / "fixtures" / "spring_river_store_maps.json"
)


def _fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_spring_river_large_watershed_fixture_contract():
    fixture = _fixture()

    assert fixture["schema"] == "ras-commander.store-maps-fixture/1"
    assert fixture["id"] == "spring-river-large-watershed"
    assert fixture["default_plan_number"] == "02"
    assert fixture["benchmark_maps"] == ["wse", "depth", "velocity"]
    assert fixture["terrain"]["source_count"] == 1
    assert fixture["terrain"]["width"] * fixture["terrain"]["height"] > 750_000_000
    assert fixture["model"]["mesh_cells"] > 400_000
    assert fixture["model"]["mesh_faces"] > 900_000
    assert fixture["viewer_manifest_url"].startswith("https://rascommander.info/")


def test_store_maps_benchmark_accepts_automatic_worker_selection():
    script_path = ROOT / "scripts" / "benchmarks" / "benchmark_store_maps_memory.py"
    spec = importlib.util.spec_from_file_location("store_maps_benchmark", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._parse_max_workers("auto") is None
    assert module._parse_max_workers("2") == 2


@pytest.mark.skipif(
    not os.environ.get("RAS_COMMANDER_SPRING_RIVER_FIXTURE"),
    reason="Set RAS_COMMANDER_SPRING_RIVER_FIXTURE for the local 7 GB fixture",
)
def test_spring_river_local_fixture_matches_declared_terrain():
    fixture = _fixture()
    project_folder = Path(os.environ["RAS_COMMANDER_SPRING_RIVER_FIXTURE"])
    ras = init_ras_project(project_folder, fixture["mapping_ras_version"])
    terrain = fixture["terrain"]

    terrain_layers = RasMap.list_terrain_layers(project_folder, ras_object=ras)
    assert terrain_layers["name"].tolist() == [terrain["name"]]

    vrt_path = project_folder / terrain["vrt"]
    root = ET.parse(vrt_path).getroot()
    sources = root.findall(".//SourceFilename")
    assert len(sources) == terrain["source_count"]
    assert sources[0].text == Path(terrain["source_raster"]).name
    assert int(root.attrib["rasterXSize"]) == terrain["width"]
    assert int(root.attrib["rasterYSize"]) == terrain["height"]
