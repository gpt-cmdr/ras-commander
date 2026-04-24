import sys
import types
from pathlib import Path

county_module = types.ModuleType("ras_commander.sources.county")
county_module.M3Model = object
sys.modules.setdefault("ras_commander.sources.county", county_module)

from ras_commander.sources.federal.ebfe_models import RasEbfeModels


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_organize_amite_prefers_matching_crs_assets(monkeypatch, tmp_path):
    downloaded_folder = tmp_path / "downloads"
    output_folder = tmp_path / "organized"

    input_dir = downloaded_folder / "Input_extracted"
    terrain_dir = downloaded_folder / "Terrain_extracted"
    landuse_dir = downloaded_folder / "LandUse_extracted"

    _write_text(downloaded_folder / "2D_Model_Inventory_Amite.xlsx", "inventory")

    _write_text(input_dir / "WA4_Input" / "WA4.prj", "Proj Title=WA4\n")
    _write_text(input_dir / "WA4_Input" / "WA4.rasmap", "<RASMapper />")
    _write_text(input_dir / "WA4_Input" / "WA4.g01.hdf", "wa4")
    _write_text(input_dir / "WA4_Input" / "Input_DSS" / "wa4.dss", "dss")

    _write_text(input_dir / "WA5_Input" / "WA5.prj", "Proj Title=WA5\n")
    _write_text(input_dir / "WA5_Input" / "WA5.rasmap", "<RASMapper />")
    _write_text(input_dir / "WA5_Input" / "WA5.g01.hdf", "wa5")
    _write_text(input_dir / "WA5_Input" / "Input_DSS" / "wa5.dss", "dss")

    _write_text(terrain_dir / "Terrain_North" / "Terrain.hdf", "north terrain")
    _write_text(terrain_dir / "Terrain_South" / "Terrain.hdf", "south terrain")
    _write_text(landuse_dir / "Landcover_North" / "LandCover.tif", "north landcover")
    _write_text(landuse_dir / "Landcover_South" / "LandCover.tif", "south landcover")

    def fake_download_component(url, dest, description=""):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("downloaded", encoding="utf-8")

    def fake_extract_component(zip_path, dest, description=""):
        dest.mkdir(parents=True, exist_ok=True)

    def fake_read_spatial_reference(path):
        if path is None:
            return None
        name = Path(path).name
        full = str(path)
        if "WA4.g01.hdf" in name or "WA5.g01.hdf" in name:
            return "EPSG:3452"
        if "Terrain_North" in full:
            return "EPSG:3451"
        if "Terrain_South" in full:
            return "EPSG:3452"
        if "Landcover_North" in full:
            return "EPSG:3451"
        if "Landcover_South" in full:
            return "EPSG:3452"
        return None

    repair_calls = []

    def fake_repair_project_paths(project_folder, search_roots=None, ras_version=None):
        repair_calls.append((Path(project_folder), ras_version))
        return {
            "dss_corrections": 1,
            "rasmap_corrections": 2,
            "folder_corrections": 3,
            "unresolved_paths": 0,
        }

    monkeypatch.setattr(RasEbfeModels, "_download_component", fake_download_component)
    monkeypatch.setattr(RasEbfeModels, "_extract_component", fake_extract_component)
    monkeypatch.setattr(RasEbfeModels, "_read_spatial_reference", fake_read_spatial_reference)
    monkeypatch.setattr(RasEbfeModels, "repair_project_paths", fake_repair_project_paths)

    organized = RasEbfeModels.organize_amite(
        downloaded_folder=downloaded_folder,
        output_folder=output_folder,
        skip_output=True,
        validate_dss=False,
        ras_version="5.0.3",
    )

    assert organized == output_folder
    assert (output_folder / "RAS Model" / "WA4" / "Terrain_South" / "Terrain.hdf").exists()
    assert (output_folder / "RAS Model" / "WA4" / "Landcover_South" / "LandCover.tif").exists()
    assert (output_folder / "RAS Model" / "WA5" / "Terrain_South" / "Terrain.hdf").exists()
    assert (output_folder / "RAS Model" / "WA5" / "Landcover_South" / "LandCover.tif").exists()
    assert (output_folder / "RAS Model" / "WA4" / "projection_file.prj").exists()
    assert (output_folder / "RAS Model" / "WA5" / "projection_file.prj").exists()
    assert (output_folder / "agent" / "model_log.md").exists()

    model_log = (output_folder / "agent" / "model_log.md").read_text(encoding="utf-8")
    assert "CRS Inventory" in model_log
    assert "WA4" in model_log
    assert "WA5" in model_log
    assert "Manual Terrain Follow-Up Required" in model_log
    assert "Terrain/SOURCE/DEM_10ft.tif" in model_log
    assert "AECOM submittal" in model_log

    assert repair_calls == [
        (output_folder / "RAS Model" / "WA4", "5.0.3"),
        (output_folder / "RAS Model" / "WA5", "5.0.3"),
    ]
