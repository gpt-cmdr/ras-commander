"""Isolated native terrain sampling and finalized portable association evidence."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import h5py

from ras_commander._terrain_registration import (
    audit_terrain_associations,
    create_terrain_sampling_map,
    relocate_rasmap_assets,
)


def test_sampling_keeps_flags_and_repairs_stale_terrain_directory(tmp_path):
    terrain = tmp_path / "Terrain.hdf"
    projection = tmp_path / "Projection.prj"
    terrain.write_bytes(b"native fixture")
    projection.write_text("projection")
    mapper = tmp_path / "source.rasmap"
    mapper.write_text("""<RASMapper><Version>2</Version><Terrains>
      <Layer Name="Terrain" Filename="old/RAS_Terrain/Terrain.hdf" Enabled="True">
      <Layer Name="Channels" Filename="old/Terrain.hdf" Checked="True" /></Layer>
      </Terrains><Results><Layer Name="parent" /></Results></RASMapper>""")
    before = mapper.read_bytes()
    out = tmp_path / "sampling.rasmap"
    assert create_terrain_sampling_map(mapper, terrain, projection, out) == "Terrain"
    root = ET.parse(out).getroot()
    assert root.find("Results") is None
    assert root.find("./Terrains/Layer").get("Enabled") == "True"
    assert root.find("./Terrains/Layer/Layer").get("Checked") == "True"
    assert root.find("./Terrains/Layer/Layer").get("Filename") == str(terrain.resolve())
    assert mapper.read_bytes() == before
    with pytest.raises(ValueError):
        create_terrain_sampling_map(mapper, terrain, projection, out)


def test_sampling_rejects_ambiguous_basenames_before_writing(tmp_path):
    terrain, projection = tmp_path / "Terrain.hdf", tmp_path / "Projection.prj"
    terrain.touch()
    projection.touch()
    mapper = tmp_path / "source.rasmap"
    mapper.write_text(
        '<RASMapper><Terrains><Layer Filename="a/Terrain.hdf" />'
        '<Layer Filename="b/Terrain.hdf" /></Terrains></RASMapper>'
    )
    out = tmp_path / "sampling.rasmap"
    with pytest.raises(ValueError):
        create_terrain_sampling_map(mapper, terrain, projection, out)
    assert not out.exists()


def test_relocation_preserves_result_map_semantics_and_relative_paths(tmp_path):
    model = tmp_path / "Input"
    model.mkdir()
    asset = tmp_path / "LandCover" / "LandCover.hdf"
    asset.parent.mkdir()
    asset.touch()
    mapper = model / "test.rasmap"
    mapper.write_text(
        '<RASMapper><LandCover><Layer Filename="Land Classification/LandCover.hdf" />'
        '</LandCover><Results><Layer><MapParameters Terrain="ChildTerrain" Profile="100yr" />'
        "</Layer></Results></RASMapper>"
    )
    changes = relocate_rasmap_assets(mapper, [asset])
    assert len(changes) == 1
    root = ET.parse(mapper).getroot()
    filename = root.find("./LandCover/Layer").get("Filename")
    assert (model / Path(filename.replace("\\", "/"))).resolve() == asset.resolve()
    assert root.find("./Results/Layer/MapParameters").get("Profile") == "100yr"


def test_duplicate_relocation_basenames_leave_mapper_unchanged(tmp_path):
    first, second = tmp_path / "a" / "asset.hdf", tmp_path / "b" / "asset.hdf"
    for path in (first, second):
        path.parent.mkdir()
        path.touch()
    mapper = tmp_path / "test.rasmap"
    mapper.write_text('<RASMapper><Layer Filename="old/asset.hdf" /></RASMapper>')
    before = mapper.read_bytes()
    with pytest.raises(ValueError):
        relocate_rasmap_assets(mapper, [first, second])
    assert mapper.read_bytes() == before


def test_audit_detects_stale_names_missing_paths_and_absolute_paths(tmp_path):
    terrain = tmp_path / "ChildTerrain.hdf"
    terrain.touch()
    mapper = tmp_path / "test.rasmap"
    mapper.write_text(
        '<RASMapper><Terrains><Layer Name="ChildTerrain" Filename="ChildTerrain.hdf" />'
        '</Terrains><RASProjectionFilename Filename="missing.prj" /><Results><Layer Name="p01">'
        '<MapParameters Terrain="parent" /></Layer></Results></RASMapper>'
    )
    result = audit_terrain_associations(mapper, [])
    assert result["status"] == "hold"
    assert len(result["problems"]) == 2
    assert result["stale_result_terrains"] == [{"plan_name": "p01", "terrain_name": "parent"}]
    mapper.write_text(
        f'<RASMapper><Terrains><Layer Name="ChildTerrain" Filename="{terrain}" />'
        "</Terrains></RASMapper>"
    )
    assert audit_terrain_associations(mapper, [])["status"] == "hold"


@pytest.mark.synthetic_hdf_layout
def test_finalized_bundle_rename_preserves_associations(tmp_path):
    partial = tmp_path / "attempt.partial"
    partial.mkdir()
    (partial / "Terrain").mkdir()
    (partial / "Terrain" / "ChildTerrain.hdf").touch()
    (partial / "Projection.prj").touch()
    mapper = partial / "test.rasmap"
    mapper.write_text(
        '<RASMapper><Terrains><Layer Name="ChildTerrain" Filename="Terrain/ChildTerrain.hdf" />'
        '</Terrains><RASProjectionFilename Filename="Projection.prj" />'
        '<Results><Layer><MapParameters Terrain="ChildTerrain" /></Layer></Results></RASMapper>'
    )
    final = tmp_path / "completed"
    with h5py.File(partial / "sample.g01.hdf", "w") as hdf:
        hdf.create_group("Geometry").attrs["Terrain Filename"] = "Terrain/ChildTerrain.hdf"
    partial.rename(final)
    assert (
        audit_terrain_associations(final / mapper.name, [final / "sample.g01.hdf"])["status"]
        == "pass"
    )


@pytest.mark.synthetic_hdf_layout(
    "other.hdf",
)
@pytest.mark.parametrize("association", [None, "other.hdf"])
def test_audit_holds_missing_or_wrong_existing_geometry_terrain(tmp_path, association):
    (tmp_path / "ChildTerrain.hdf").touch()
    (tmp_path / "other.hdf").touch()
    mapper = tmp_path / "test.rasmap"
    mapper.write_text(
        '<RASMapper><Terrains><Layer Name="ChildTerrain" Filename="ChildTerrain.hdf" /></Terrains></RASMapper>'
    )
    geometry = tmp_path / "sample.g01.hdf"
    with h5py.File(geometry, "w") as hdf:
        group = hdf.create_group("Geometry")
        if association:
            group.attrs["Terrain Filename"] = association
    assert audit_terrain_associations(mapper, [geometry])["status"] == "hold"


def test_sampling_map_registers_explicit_geometry_copy(tmp_path):
    terrain, projection, geometry = [
        tmp_path / name for name in ("Terrain.hdf", "Projection.prj", "sample.g01.hdf")
    ]
    for item in (terrain, projection, geometry):
        item.touch()
    mapper = tmp_path / "source.rasmap"
    mapper.write_text(
        '<RASMapper><Terrains><Layer Name="Parent" Filename="Terrain.hdf" /></Terrains></RASMapper>'
    )
    output = tmp_path / "sample.rasmap"
    create_terrain_sampling_map(mapper, terrain, projection, output, geometry_hdf=geometry)
    assert ET.parse(output).getroot().find("./Geometries/Layer").get("Filename") == str(
        geometry.resolve()
    )
