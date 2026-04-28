from pathlib import Path
import sys

import h5py
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ras_commander import RasMap


def _make_project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "AssocProject"
    project_dir.mkdir()
    (project_dir / "AssocProject.prj").write_text(
        "Proj Title=Association Project\nCurrent Plan=\n",
        encoding="utf-8",
    )
    return project_dir


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("artifact", encoding="utf-8")
    return path


def _make_geometry_hdf(path: Path) -> Path:
    with h5py.File(path, "w") as hdf_file:
        hdf_file.create_group("Geometry")
    return path


def test_rasmap_associate_geometry_layers_writes_hdf_attrs_with_layer_names(tmp_path):
    project_dir = _make_project(tmp_path)
    terrain = _touch(project_dir / "Terrain" / "TerrainA.hdf")
    landcover = _touch(project_dir / "Land" / "cover.hdf")
    soils = _touch(project_dir / "Soils Data" / "Hydrologic Soil Groups.hdf")
    infiltration = _touch(project_dir / "Soils Data" / "infiltration.hdf")
    sediment = _touch(project_dir / "Sediment" / "bed_material.hdf")
    geom_hdf = _make_geometry_hdf(project_dir / "AssocProject.g01.hdf")

    (project_dir / "AssocProject.rasmap").write_text(
        (
            "<RASMapper>\n"
            "  <MapLayers>\n"
            '    <Layer Name="Custom Land" Type="LandCoverLayer" '
            'Filename=".\\Land\\cover.hdf" '
            'SelectedParameterForSurfaceFillLabel="ManningsN" />\n'
            '    <Layer Name="Custom Soils" Type="LandCoverLayer" '
            'Filename=".\\Soils Data\\Hydrologic Soil Groups.hdf" '
            'SelectedParameterForSurfaceFillLabel="ID" />\n'
            '    <Layer Name="Custom Infiltration" Type="LandCoverLayer" '
            'Filename=".\\Soils Data\\infiltration.hdf" '
            'SelectedParameterForSurfaceFillLabel="ID" />\n'
            "  </MapLayers>\n"
            "  <Terrains>\n"
            '    <Layer Name="Custom Terrain" Type="TerrainLayer" Checked="True" '
            'Filename=".\\Terrain\\TerrainA.hdf">\n'
            "      <ResampleMethod>near</ResampleMethod>\n"
            '      <Surface On="True" />\n'
            "    </Layer>\n"
            "  </Terrains>\n"
            "</RASMapper>\n"
        ),
        encoding="utf-8",
    )

    result = RasMap.associate_geometry_layers(
        project_dir,
        geom_hdf,
        terrain_hdf_path=terrain,
        landcover_hdf_path=landcover,
        soil_layer_path=soils,
        infiltration_hdf_path=infiltration,
        sediment_soils_hdf_path=sediment,
    )

    assert result == geom_hdf
    association = RasMap.get_hdf_geometry_association(geom_hdf)
    assert Path(association["terrain_hdf_path"]) == terrain
    assert Path(association["landcover_hdf_path"]) == landcover
    assert Path(association["infiltration_hdf_path"]) == infiltration
    assert Path(association["sediment_soils_hdf_path"]) == sediment
    assert association["terrain_layer_name"] == "Custom Terrain"
    assert association["landcover_layer_name"] == "Custom Land"
    assert association["infiltration_layer_name"] == "Custom Infiltration"
    assert association["sediment_soils_layer_name"] == "bed_material"
    assert association["hdf_attrs"]["Terrain Filename"] == ".\\Terrain\\TerrainA.hdf"
    assert association["hdf_attrs"]["Land Cover File Date"] is not None
    assert association["hdf_attrs"]["Land Cover Date Last Modified"] is not None


def test_soil_layer_path_does_not_write_sediment_soils_attr(tmp_path):
    project_dir = _make_project(tmp_path)
    soils = _touch(project_dir / "Soils Data" / "Hydrologic Soil Groups.hdf")
    landcover = _touch(project_dir / "Land" / "LandCover.hdf")
    geom_hdf = _make_geometry_hdf(project_dir / "AssocProject.g01.hdf")
    (project_dir / "AssocProject.rasmap").write_text(
        (
            "<RASMapper>\n"
            "  <MapLayers>\n"
            '    <Layer Name="Land" Type="LandCoverLayer" '
            'Filename=".\\Land\\LandCover.hdf" '
            'SelectedParameterForSurfaceFillLabel="ManningsN" />\n'
            '    <Layer Name="Hydrologic Soil Groups" Type="LandCoverLayer" '
            'Filename=".\\Soils Data\\Hydrologic Soil Groups.hdf" '
            'SelectedParameterForSurfaceFillLabel="ID" />\n'
            "  </MapLayers>\n"
            "</RASMapper>\n"
        ),
        encoding="utf-8",
    )

    RasMap.associate_geometry_layers(
        project_dir,
        geom_hdf,
        landcover_hdf_path=landcover,
        soil_layer_path=soils,
    )

    association = RasMap.get_hdf_geometry_association(geom_hdf)
    assert Path(association["landcover_hdf_path"]) == landcover
    assert association["sediment_soils_hdf_path"] is None
    assert association["sediment_soils_layer_name"] is None


def test_get_hdf_geometry_association_reads_plan_hdf_without_mutation(tmp_path):
    project_dir = tmp_path / "PlanProject"
    project_dir.mkdir()
    terrain = _touch(project_dir / "Terrain" / "PlanTerrain.hdf")
    plan_hdf = project_dir / "PlanProject.p01.hdf"
    with h5py.File(plan_hdf, "w") as hdf_file:
        geometry = hdf_file.create_group("Geometry")
        geometry.attrs["Terrain Filename"] = b".\\Terrain\\PlanTerrain.hdf"
        geometry.attrs["Terrain Layername"] = b"Plan Terrain"
        geometry.attrs["Terrain File Date"] = b"01JAN2025 00:00:00"
        area = hdf_file.create_group("Geometry/2D Flow Areas/Main")
        area.attrs["Terrain Filename"] = b".\\Terrain\\PlanTerrain.hdf"
        area.attrs["Terrain File Date"] = b"01JAN2025 00:00:00"

    association = RasMap.get_hdf_geometry_association(plan_hdf)

    assert Path(association["terrain_hdf_path"]) == terrain
    assert association["terrain_layer_name"] == "Plan Terrain"
    assert association["terrain_file_date"] == "01JAN2025 00:00:00"
    assert association["two_d_area_terrain_associations"] == [
        {
            "flow_area": "Main",
            "terrain_raw_filename": ".\\Terrain\\PlanTerrain.hdf",
            "terrain_layer_name": None,
            "terrain_file_date": "01JAN2025 00:00:00",
            "terrain_hdf_path": str(terrain),
        }
    ]


def test_missing_geometry_group_rejected_for_read(tmp_path):
    hdf_path = tmp_path / "empty.g01.hdf"
    with h5py.File(hdf_path, "w"):
        pass

    with pytest.raises(RuntimeError, match="/Geometry"):
        RasMap.get_hdf_geometry_association(hdf_path)
