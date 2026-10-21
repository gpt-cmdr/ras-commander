"""A registered cloned bundle must remain usable after its temporary directory moves."""

import shutil
import xml.etree.ElementTree as ET

from ras_commander import RasMap


def test_sibling_terrain_registration_survives_bundle_rename(tmp_path):
    partial = tmp_path / "run.partial"
    project = partial / "Input"
    terrain = partial / "Terrain"
    project.mkdir(parents=True)
    terrain.mkdir()
    hdf = terrain / "Packed.hdf"
    hdf.write_bytes(b"caller-owned terrain fixture")
    projection = terrain / "Projection.prj"
    projection.write_text("caller-owned projection")
    mapper = project / "Study.rasmap"
    mapper.write_text("<RASMapper><Version>6.6</Version></RASMapper>")
    RasMap.add_terrain_layer(
        hdf, mapper, layer_name="Packed", projection_prj=projection, relative_paths=True
    )
    final = tmp_path / "run"
    shutil.move(str(partial), str(final))
    mapper = final / "Input/Study.rasmap"
    root = ET.parse(mapper).getroot()
    layer = root.find("./Terrains/Layer")
    filename = layer.get("Filename").replace("\\", "/")
    assert not filename.startswith(str(tmp_path))
    assert (mapper.parent / filename).resolve() == final / "Terrain/Packed.hdf"
    assert (mapper.parent / filename).is_file()
    projection_filename = (
        root.find("RASProjectionFilename").get("Filename").replace("\\", "/")
    )
    assert (
        mapper.parent / projection_filename
    ).resolve() == final / "Terrain/Projection.prj"
    assert (mapper.parent / projection_filename).is_file()
