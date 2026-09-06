import json
from datetime import datetime
from pathlib import Path
import sys
import types

import h5py

county_module = types.ModuleType("ras_commander.sources.county")
county_module.M3Model = object
sys.modules.setdefault("ras_commander.sources.county", county_module)

from ras_commander import RasMap
from ras_commander.sources.federal.ebfe_models import RasEbfeModels


PROJECTS = RasEbfeModels._SAN_GABRIEL_PROJECTS


def _write(path: Path, content: str = "data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _build_delivery(tmp_path: Path) -> Path:
    delivery = tmp_path / "12070205_Models"
    engineering = delivery / "Engineering Models"
    hydraulic = engineering / "Hydraulic Models"
    ras_submission = hydraulic / "RAS_Submittal"

    _write(hydraulic / "2D_Model_Inventory_LBSG.xlsx", "inventory")
    _write(
        engineering / "Hydrologic Models" / "HMS Models" / "HMS 4.10"
        / "LBSG.hms",
        "hms",
    )
    _write(
        ras_submission / "Terrain Submittal" / "Task_Documentation"
        / "999999_Terrain_metadata.xml",
        "<metadata />",
    )
    _write(
        ras_submission / "Terrain Submittal" / "Correspondence"
        / "Terrain_QAQC_Checklist.docx",
        "checklist",
    )
    for index in range(1, 4):
        _write(
            ras_submission / "Terrain Submittal" / "Final" / "hdem"
            / f"HDEM_{index}.tif",
            f"hdem-{index}",
        )
    _write(
        ras_submission / "Terrain Submittal" / "Spatial_Files"
        / "terrain_boundary.shp",
        "boundary",
    )
    _write(
        ras_submission / "Terrain Submittal" / "Supplemental_Data"
        / "very" / "deep" / "lidar" / "report.pdf",
        "supplemental",
    )

    dss_locations = {
        "LBSG_501": Path("Simulation/100.dss"),
        "LBSG_502": Path("Simulations/100.dss"),
        "LBSG_503": Path("Simulations/100.dss"),
        "LBSG_504": Path("Simulation/100.dss"),
    }
    for model_name, smoke in PROJECTS.items():
        model_number = model_name[-3:]
        source_project = ras_submission / model_name
        input_folder = source_project / "Input"
        project_stem = f"BLE_LBSG_{model_number}"
        _write(input_folder / f"{project_stem}.prj", f"Proj Title={model_name}\n")
        _write(
            input_folder / f"{project_stem}.rasmap",
            """<RASMapper>
<Terrains>
  <Layer Name="Terrain" Type="TerrainLayer" Filename=".\\Terrain\\old.hdf">
    <Layer Name="Modifications" Type="ElevationModificationGroup" Filename="C:\\old\\Terrain.hdf">
      <Layer Name="Hwy-Road Crossings (Channel)" Type="GroundLineModificationLayer" Filename=".\\old-1.hdf">
        <Layer Name="Control Points" Type="ElevationControlPointLayer" Filename=".\\old-2.hdf" />
      </Layer>
      <Layer Name="Hwy-Road Crossings" Type="GroundLineModificationLayer" Filename=".\\old-3.hdf">
        <Layer Name="Control Points" Type="ElevationControlPointLayer" Filename=".\\old-4.hdf" />
      </Layer>
      <Layer Name="Lake Georgetown" Type="PolygonElevationModificationLayer" Filename=".\\old-5.hdf">
        <Layer Name="Control Points" Type="ElevationControlPointLayer" Filename=".\\old-6.hdf" />
      </Layer>
    </Layer>
  </Layer>
</Terrains>
<TerrainDestinationFolder>.\\Terrain</TerrainDestinationFolder>
<TerrainSourceFolder>..\\..\\GIS\\DEM</TerrainSourceFolder>
</RASMapper>
""",
        )
        _write(
            input_folder / f"{project_stem}.p{smoke['plan']}",
            "Run HTab= -1\nUNET Use Existing IB Tables= -1\n",
        )
        _write(
            source_project / "Output" / f"{project_stem}.p{smoke['plan']}.hdf",
            f"result-{model_number}",
        )
        _write(source_project / "Land Cover" / "classification.txt", model_name)
        if model_name in dss_locations:
            _write(
                input_folder / dss_locations[model_name],
                f"upstream-{model_number}",
            )

    input_505 = ras_submission / "LBSG_505" / "Input"
    _write(input_505 / "HMS DSS" / "100.dss", "local-505")
    _write(
        input_505 / "BLE_LBSG_505.u02",
        r"""DSS File=.\HMS DSS\100.dss
DSS File=..\..\501 - RAS 6.3\Input\Simulation\100.dss
DSS File=..\..\502 - RAS 6.3\Input\Simulations\100.dss
DSS File=..\..\503 - RAS 6.3\Input\Simulations\100.dss
DSS File=..\..\504 - RAS 6.3\Input\Simulation\100.dss
""",
    )
    return delivery


def test_san_gabriel_registry_aliases_and_metadata():
    assert RasEbfeModels.normalize_model_key("San Gabriel") == "san-gabriel"
    assert RasEbfeModels.normalize_model_key("sangabriel") == "san-gabriel"
    assert RasEbfeModels.normalize_model_key("12070205") == "san-gabriel"

    metadata = next(
        item
        for item in RasEbfeModels.list_models()
        if item.source_id == "san-gabriel"
    )
    assert metadata.hecras_version == "6.3"
    assert metadata.url == RasEbfeModels._SAN_GABRIEL_SOURCE_URL
    assert metadata.extra["project_count"] == 5
    assert metadata.extra["validation_level"] == "unsteady_start"
    assert "Terrain.hdf" in " ".join(metadata.extra["known_deficiencies"])


def test_organize_model_dispatches_san_gabriel(monkeypatch, tmp_path):
    expected = tmp_path / "organized"
    observed = {}

    def fake_organizer(**kwargs):
        observed.update(kwargs)
        return expected

    monkeypatch.setattr(
        RasEbfeModels,
        "organize_san_gabriel",
        staticmethod(fake_organizer),
    )
    result = RasEbfeModels.organize_model(
        "12070205",
        downloaded_folder=tmp_path / "raw",
        output_folder=expected,
    )

    assert result == expected
    assert observed["downloaded_folder"] == tmp_path / "raw"
    assert observed["output_folder"] == expected


def test_organize_san_gabriel_preserves_bundle_and_repairs_exact_dss_paths(
    monkeypatch,
    tmp_path,
):
    source = _build_delivery(tmp_path / "source")
    destination = tmp_path / "organized"
    flag_calls = []

    monkeypatch.setattr(
        RasEbfeModels,
        "_restore_san_gabriel_association_timestamps",
        staticmethod(lambda project_folder, geometry_number: 3),
    )
    monkeypatch.setattr(
        RasEbfeModels,
        "_set_san_gabriel_smoke_plan_flags",
        staticmethod(
            lambda project_folder, plan_number: flag_calls.append(
                (Path(project_folder).parent.name, plan_number)
            )
        ),
    )

    organized = RasEbfeModels.organize_san_gabriel(
        downloaded_folder=source,
        output_folder=destination,
        validate_dss=False,
    )

    assert organized == destination
    assert flag_calls == [
        (model_name, settings["plan"])
        for model_name, settings in PROJECTS.items()
    ]
    for model_name, smoke in PROJECTS.items():
        model_number = model_name[-3:]
        project_folder = destination / "RAS Model" / model_name / "Input"
        assert (project_folder / f"BLE_LBSG_{model_number}.prj").is_file()
        assert (
            project_folder / f"BLE_LBSG_{model_number}.p{smoke['plan']}.hdf"
        ).read_text(encoding="utf-8") == f"result-{model_number}"
        assert (
            destination / "RAS Model" / model_name / "Land Cover"
            / "classification.txt"
        ).read_text(encoding="utf-8") == model_name

    unsteady_text = (
        destination / "RAS Model" / "LBSG_505" / "Input"
        / "BLE_LBSG_505.u02"
    ).read_text(encoding="utf-8")
    assert "DSS File=.\\HMS DSS\\100.dss" in unsteady_text
    assert "501 - RAS 6.3" not in unsteady_text
    assert "502 - RAS 6.3" not in unsteady_text
    assert "503 - RAS 6.3" not in unsteady_text
    assert "504 - RAS 6.3" not in unsteady_text
    for model_number in ("501", "502", "503", "504"):
        assert f"..\\..\\LBSG_{model_number}\\Input\\" in unsteady_text

    assert (
        destination / "RAS Model" / "LBSG_501" / "Input"
        / "Simulation" / "100.dss"
    ).read_text(encoding="utf-8") == "upstream-501"
    assert (
        destination / "RAS Model" / "LBSG_502" / "Input"
        / "Simulations" / "100.dss"
    ).read_text(encoding="utf-8") == "upstream-502"
    assert (
        destination / "RAS Model" / "LBSG_505" / "Input"
        / "HMS DSS" / "100.dss"
    ).read_text(encoding="utf-8") == "local-505"

    assert not (destination / "RAS Model" / "Terrain" / "Terrain.hdf").exists()
    terrain_notice = (
        destination / "RAS Model" / "Terrain" / "README.md"
    ).read_text(encoding="utf-8")
    assert "not present" in terrain_notice
    assert "does not automatically rebuild" in terrain_notice
    assert "HDEM-only reconstruction" in terrain_notice
    for index in range(1, 4):
        assert (
            destination / "RAS Model" / "Terrain Submittal" / "Final"
            / "hdem" / f"HDEM_{index}.tif"
        ).is_file()
    assert (
        destination / "RAS Model" / "Terrain Submittal" / "Spatial_Files"
        / "terrain_boundary.shp"
    ).is_file()
    assert not (
        destination / "RAS Model" / "Terrain Submittal"
        / "Supplemental_Data"
    ).exists()
    for model_name in PROJECTS:
        model_number = model_name[-3:]
        rasmap_file = (
            destination / "RAS Model" / model_name / "Input"
            / f"BLE_LBSG_{model_number}.rasmap"
        )
        rasmap_text = rasmap_file.read_text(encoding="utf-8")
        assert rasmap_text.count('Filename="..\\..\\Terrain\\Terrain.hdf"') == 8
        assert (
            "<TerrainDestinationFolder>..\\..\\Terrain"
            "</TerrainDestinationFolder>"
        ) in rasmap_text
        assert (
            "<TerrainSourceFolder>..\\..\\Terrain Submittal\\Final\\hdem"
            "</TerrainSourceFolder>"
        ) in rasmap_text
        parsed_terrain_paths = RasMap.parse_rasmap(rasmap_file).iloc[0][
            "terrain_hdf_path"
        ]
        assert parsed_terrain_paths == [
            str(destination / "RAS Model" / "Terrain" / "Terrain.hdf")
        ]
    assert (destination / "HMS Model" / "HMS 4.10" / "LBSG.hms").is_file()

    manifest = json.loads(
        (destination / "agent" / "san_gabriel_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["terrain_status"] == "Not Provided in Source"
    assert manifest["terrain_path_normalization"] == {
        "rasmap_files": 5,
        "terrain_hdf_references": 40,
        "terrain_hdf_corrections": 40,
        "folder_corrections": 10,
    }
    assert manifest["dss_path_rewrites"] == 4
    assert manifest["validation_level"] == "unsteady_start"

    rod_path = destination / "agent" / "record_of_deficiencies.md"
    rod_text = rod_path.read_text(encoding="utf-8")
    assert "San Gabriel Record of Deficiencies" in rod_text
    assert "SG-001" in rod_text
    assert "SG-005" in rod_text
    assert "all 40 terrain references across 5 projects" in rod_text
    assert "No reconstruction is performed automatically" in rod_text

    # Reorganization must preserve subsequently recorded build provenance.
    rod_path.write_text(rod_text + "\nAuthorized build record.\n", encoding="utf-8")

    # Reorganization is deterministic and does not accumulate path rewrites.
    RasEbfeModels.organize_san_gabriel(
        downloaded_folder=source,
        output_folder=destination,
        validate_dss=False,
    )
    repeated = json.loads(
        (destination / "agent" / "san_gabriel_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert repeated["dss_path_rewrites"] == 4
    assert "Authorized build record." in rod_path.read_text(encoding="utf-8")


def test_san_gabriel_smoke_flags_do_not_require_project_initialization(tmp_path):
    project_folder = tmp_path / "Input"
    _write(project_folder / "BLE_LBSG_501.prj", "Proj Title=LBSG_501\n")
    plan_file = _write(
        project_folder / "BLE_LBSG_501.p01",
        "Run HTab= -1\nUNET Use Existing IB Tables= -1\n",
    )

    RasEbfeModels._set_san_gabriel_smoke_plan_flags(project_folder, "01")

    text = plan_file.read_text(encoding="utf-8")
    assert "Run HTab= 0" in text
    assert "UNET Use Existing IB Tables= 0" in text


def test_resolve_model_reference_accepts_windows_separators(tmp_path):
    base_folder = tmp_path / "LBSG_505" / "Input"
    target = tmp_path / "LBSG_501" / "Input" / "Simulation" / "100.dss"
    _write(target, "upstream")

    resolved = RasEbfeModels._resolve_model_reference(
        base_folder,
        r"..\..\LBSG_501\Input\Simulation\100.dss",
    )

    assert resolved == target.resolve()


def test_san_gabriel_association_times_follow_geometry_hdf(tmp_path):
    project_folder = tmp_path / "LBSG_502" / "Input"
    _write(project_folder / "BLE_LBSG_502.prj", "Proj Title=LBSG_502\n")
    land_cover = _write(
        project_folder.parent / "Land Cover" / "NLCD19.hdf",
        "land-cover",
    )
    land_cover_tif = _write(
        project_folder.parent / "Land Cover" / "NLCD19.tif",
        "land-cover-raster",
    )
    soils = _write(
        project_folder.parent / "Land Cover" / "Soils.hdf",
        "soils",
    )
    geometry_hdf = project_folder / "BLE_LBSG_502.g03.hdf"
    geometry_hdf.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(geometry_hdf, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        geometry.attrs["Land Cover Filename"] = b"..\\Land Cover\\NLCD19.hdf"
        geometry.attrs["Land Cover File Date"] = b"31AUG2022 21:11:43"
        geometry.attrs["Infiltration Filename"] = b"..\\Land Cover\\Soils.hdf"
        geometry.attrs["Infiltration File Date"] = b"28FEB2022 16:48:16"

    restored = RasEbfeModels._restore_san_gabriel_association_timestamps(
        project_folder,
        "03",
    )

    assert restored == 3
    assert datetime.fromtimestamp(land_cover.stat().st_mtime) == datetime(
        2022, 8, 31, 21, 11, 43
    )
    assert datetime.fromtimestamp(land_cover_tif.stat().st_mtime) == datetime(
        2022, 8, 31, 21, 11, 43
    )
    assert datetime.fromtimestamp(soils.stat().st_mtime) == datetime(
        2022, 2, 28, 16, 48, 16
    )
