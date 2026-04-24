import sys
import types
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

county_module = types.ModuleType("ras_commander.sources.county")
county_module.M3Model = object
sys.modules.setdefault("ras_commander.sources.county", county_module)

import ras_commander
from ras_commander.sources.federal.ebfe_models import RasEbfeModels


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_repair_project_paths_updates_dss_and_rasmap_references(
    monkeypatch,
    tmp_path,
):
    organized_root = tmp_path / "Tickfaw_08070203"
    project_folder = organized_root / "RAS Model" / "Tickfaw"
    spatial_folder = organized_root / "Spatial Data"
    docs_folder = organized_root / "Documentation"

    prj_file = _write_text(
        project_folder / "TickfawRASLSModel.prj",
        (
            "Proj Title=TickfawRASLSModel\n"
            "Current Plan=p13\n"
            "Geom File=g05\n"
            "Unsteady File=u13\n"
            "DSS File=C:\\broken\\TickfawRASLSModel.dss\n"
        ),
    )
    plan_file = _write_text(
        project_folder / "TickfawRASLSModel.p13",
        "Plan Title=1pct\n",
    )
    unsteady_file = _write_text(
        project_folder / "TickfawRASLSModel.u13",
        (
            "Flow Title=1pct\n"
            "DSS File=W:\\broken\\TickfawRASLSModel.dss\n"
            "DSS Filename=..\\Input_DSS\\TickfawRASLSModel.dss\n"
        ),
    )
    _write_text(project_folder / "TickfawRASLSModel.dss", "placeholder")
    _write_text(project_folder / "TickfawRASLSModel.p13.hdf", "placeholder")
    _write_text(project_folder / "projection_file.prj", "projection")
    _write_text(project_folder / "Terrain" / "Terrain_Repaired.hdf", "terrain")
    _write_text(project_folder / "LandCover" / "LandCover.tif", "landcover")
    _write_text(
        spatial_folder / "VectorData" / "Final_Geom_Tickfaw.shp",
        "shape",
    )
    _write_text(docs_folder / "08070203_Hydraulics_metadata.xml", "<xml />")

    rasmap_file = _write_text(
        project_folder / "TickfawRASLSModel.rasmap",
        (
            "<RASMapper>"
            '<RASProjection Filename="W:\\broken\\projection_file.prj" />'
            '<Layer Name="Terrain" Type="TerrainLayer" '
            'Filename="W:\\broken\\Terrain_Repaired.hdf" />'
            '<Layer Name="LandCover" Filename="W:\\broken\\LandCover.tif" />'
            '<Layer Name="Results" Filename="W:\\broken\\TickfawRASLSModel.p13.hdf" />'
            '<Layer Name="Geometry" '
            'Filename="W:\\Louisiana_LSAE\\Figure_Creation\\08070203 - Tickfaw\\Final_Geom_Tickfaw.shp" />'
            "<CurrentSettings><Folders>"
            "<AddDataFolder>..\\..\\GIS\\Louisiana\\Shapefiles\\08070203</AddDataFolder>"
            "<TerrainDestinationFolder>.\\Terrain\\RAS_Terrain</TerrainDestinationFolder>"
            "<TerrainSourceFolder>..\\GIS\\Louisiana\\Terrain\\Tickfaw 08070203 - UPDATED</TerrainSourceFolder>"
            "<LandCoverDestinationFolder>..\\GIS\\Louisiana\\LandUse</LandCoverDestinationFolder>"
            "</Folders></CurrentSettings>"
            "</RASMapper>"
        ),
    )

    class FakeRasPrj:
        pass

    def fake_init_ras_project(
        project_folder_arg,
        ras_version,
        ras_object=None,
        load_results_summary=False,
    ):
        ras_object.project_folder = Path(project_folder_arg)
        ras_object.project_name = "TickfawRASLSModel"
        ras_object.prj_file = prj_file
        ras_object.plan_df = pd.DataFrame([{"full_path": plan_file}])
        ras_object.unsteady_df = pd.DataFrame([{"full_path": unsteady_file}])
        ras_object.flow_df = pd.DataFrame(columns=["full_path"])

    monkeypatch.setattr(ras_commander, "RasPrj", FakeRasPrj)
    monkeypatch.setattr(ras_commander, "init_ras_project", fake_init_ras_project)

    stats = RasEbfeModels.repair_project_paths(
        project_folder=project_folder,
        search_roots=[spatial_folder, docs_folder],
        ras_version="5.0.3",
    )

    assert stats["dss_corrections"] == 3
    assert stats["rasmap_corrections"] == 5
    assert stats["folder_corrections"] == 4
    assert stats["unresolved_paths"] == 0

    prj_text = prj_file.read_text(encoding="utf-8")
    unsteady_text = unsteady_file.read_text(encoding="utf-8")
    assert "DSS File=.\\TickfawRASLSModel.dss" in prj_text
    assert "DSS File=.\\TickfawRASLSModel.dss" in unsteady_text
    assert "DSS Filename=.\\TickfawRASLSModel.dss" in unsteady_text

    rasmap_root = ET.parse(rasmap_file).getroot()
    filenames = {
        element.attrib["Filename"]
        for element in rasmap_root.iter()
        if "Filename" in element.attrib
    }
    assert ".\\projection_file.prj" in filenames
    assert ".\\Terrain\\Terrain_Repaired.hdf" in filenames
    assert ".\\LandCover\\LandCover.tif" in filenames
    assert ".\\TickfawRASLSModel.p13.hdf" in filenames
    assert "..\\..\\Spatial Data\\VectorData\\Final_Geom_Tickfaw.shp" in filenames

    folders = rasmap_root.find(".//CurrentSettings/Folders")
    assert folders is not None
    folder_values = {child.tag: child.text for child in folders}
    assert folder_values["AddDataFolder"] == "..\\..\\Spatial Data\\VectorData"
    assert folder_values["TerrainDestinationFolder"] == ".\\Terrain"
    assert folder_values["TerrainSourceFolder"] == ".\\Terrain"
    assert folder_values["LandCoverDestinationFolder"] == ".\\LandCover"


def test_organize_tickfaw_builds_standard_layout_without_network(
    monkeypatch,
    tmp_path,
):
    downloaded_folder = tmp_path / "downloads"
    output_folder = tmp_path / "organized"

    extract_dirs = {
        "models": downloaded_folder / "08070203_Models_extracted",
        "vector_data": downloaded_folder / "08070203_VectorData_extracted",
        "documents": downloaded_folder / "08070203_Documents_extracted",
        "depth_01": downloaded_folder / "08070203_Depth01_extracted",
        "depth_002": downloaded_folder / "08070203_Depth002_extracted",
        "elev_01": downloaded_folder / "08070203_Elev01_extracted",
        "elev_002": downloaded_folder / "08070203_Elev002_extracted",
    }

    model_source = (
        extract_dirs["models"]
        / "08070203_Models"
        / "08070203_Tickfaw"
    )
    _write_text(model_source / "TickfawRASLSModel.prj", "Proj Title=Tickfaw\n")
    _write_text(model_source / "TickfawRASLSModel.rasmap", "<RASMapper />")
    _write_text(model_source / "Tickfaw_model_READ_ME.txt", "readme")
    _write_text(
        extract_dirs["models"] / "08070203_Models" / "08070203_Hydraulics_metadata.xml",
        "<xml />",
    )
    _write_text(
        extract_dirs["documents"] / "08070203_Documents" / "LA_BLEReport_Tickfaw.pdf",
        "pdf",
    )
    _write_text(
        extract_dirs["vector_data"]
        / "08070203_VectorData"
        / "Tickfaw_BLE.gdb"
        / "a00000001.gdbtable",
        "gdb",
    )
    _write_text(extract_dirs["depth_01"] / "depth01.txt", "depth")
    _write_text(extract_dirs["depth_002"] / "depth002.txt", "depth")
    _write_text(extract_dirs["elev_01"] / "elev01.txt", "elev")
    _write_text(extract_dirs["elev_002"] / "elev002.txt", "elev")

    def fake_download_component(url, dest, description=""):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("downloaded", encoding="utf-8")

    def fake_extract_component(zip_path, dest, description=""):
        dest.mkdir(parents=True, exist_ok=True)

    repair_calls = []

    def fake_repair_project_paths(project_folder, search_roots=None, ras_version=None):
        repair_calls.append(
            {
                "project_folder": Path(project_folder),
                "search_roots": [Path(root) for root in (search_roots or [])],
                "ras_version": ras_version,
            }
        )
        return {
            "dss_corrections": 1,
            "rasmap_corrections": 2,
            "folder_corrections": 3,
            "unresolved_paths": 0,
        }

    monkeypatch.setattr(RasEbfeModels, "_download_component", fake_download_component)
    monkeypatch.setattr(RasEbfeModels, "_extract_component", fake_extract_component)
    monkeypatch.setattr(RasEbfeModels, "repair_project_paths", fake_repair_project_paths)

    organized = RasEbfeModels.organize_tickfaw(
        downloaded_folder=downloaded_folder,
        output_folder=output_folder,
        include_ble_surfaces=True,
        validate_dss=False,
        ras_version="5.0.3",
    )

    assert organized == output_folder
    assert (output_folder / "RAS Model" / "Tickfaw" / "TickfawRASLSModel.prj").exists()
    assert (output_folder / "Documentation" / "LA_BLEReport_Tickfaw.pdf").exists()
    assert (
        output_folder
        / "Spatial Data"
        / "VectorData"
        / "Tickfaw_BLE.gdb"
        / "a00000001.gdbtable"
    ).exists()

    ble_manifest = (output_folder / "Spatial Data" / "BLE_SURFACES.md").read_text(
        encoding="utf-8"
    )
    assert "Depth01" in ble_manifest
    assert "Depth002" in ble_manifest
    assert "Elev01" in ble_manifest
    assert "Elev002" in ble_manifest

    hms_readme = (output_folder / "HMS Model" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "No separate HEC-HMS project" in hms_readme
    assert (output_folder / "agent" / "model_log.md").exists()

    assert len(repair_calls) == 1
    assert repair_calls[0]["project_folder"] == output_folder / "RAS Model" / "Tickfaw"
    assert repair_calls[0]["ras_version"] == "5.0.3"
