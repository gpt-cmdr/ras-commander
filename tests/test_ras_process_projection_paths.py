"""Metadata-only tests for ``RasProcess._get_projection_info`` path handling.

RASMapper writes Windows-style relative paths (``.\\Terrain\\Terrain.hdf``) into
``.rasmap`` files. On POSIX hosts ``\\`` is an ordinary filename character, so
these references must be split on the Windows separators rather than stripped.
The tests use real ``.rasmap`` XML and empty placeholder files; no HDF or raster
data is read.
"""

from importlib import import_module
from pathlib import Path

import pytest

ras_process_module = import_module("ras_commander.RasProcess")
RasProcess = ras_process_module.RasProcess


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def _write_rasmap(path: Path, projection: str, layers: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<RASMapper>
  <RASProjectionFilename Filename="{projection}" />
  <Terrains>
{layers}
  </Terrains>
</RASMapper>
""",
        encoding="utf-8",
    )
    return path


def test_backslash_nested_paths_resolve_projection_and_terrain(tmp_path):
    prj = _touch(tmp_path / "Terrain" / "Projection.prj")
    _touch(tmp_path / "Terrain" / "Terrain.hdf")
    tif = _touch(tmp_path / "Terrain" / "Terrain.tif")
    rasmap = _write_rasmap(
        tmp_path / "Demo.rasmap",
        ".\\Terrain\\Projection.prj",
        '    <Layer Name="Terrain" Filename=".\\Terrain\\Terrain.hdf" />',
    )

    info = RasProcess._get_projection_info(rasmap)

    assert info.prj_path == prj
    assert info.terrain_path == tif
    assert info.terrain_paths == (tif,)


def test_backslash_deeply_nested_terrain_path(tmp_path):
    _touch(tmp_path / "Data" / "Terrain" / "Base.hdf")
    tif = _touch(tmp_path / "Data" / "Terrain" / "Base.tif")
    rasmap = _write_rasmap(
        tmp_path / "Demo.rasmap",
        "",
        '    <Layer Name="Base" Filename=".\\Data\\Terrain\\Base.hdf" />',
    )

    info = RasProcess._get_projection_info(rasmap)

    assert info.prj_path is None
    assert info.terrain_paths == (tif,)


def test_parent_relative_backslash_paths_resolve_outside_rasmap_folder(tmp_path):
    shared = tmp_path / "Shared"
    prj = _touch(shared / "Terrain" / "Projection.prj")
    _touch(shared / "Terrain" / "T.hdf")
    tif = _touch(shared / "Terrain" / "T.tif")
    rasmap = _write_rasmap(
        tmp_path / "Project" / "Demo.rasmap",
        "..\\Shared\\Terrain\\Projection.prj",
        '    <Layer Name="T" Filename="..\\Shared\\Terrain\\T.hdf" />',
    )

    info = RasProcess._get_projection_info(rasmap)

    assert info.prj_path == prj
    assert info.terrain_paths == (tif,)


def test_forward_slash_paths_remain_compatible(tmp_path):
    prj = _touch(tmp_path / "Terrain" / "Projection.prj")
    _touch(tmp_path / "Terrain" / "Terrain.hdf")
    tif = _touch(tmp_path / "Terrain" / "Terrain.tif")
    rasmap = _write_rasmap(
        tmp_path / "Demo.rasmap",
        "./Terrain/Projection.prj",
        '    <Layer Name="Terrain" Filename="./Terrain/Terrain.hdf" />',
    )

    info = RasProcess._get_projection_info(rasmap)

    assert info.prj_path == prj
    assert info.terrain_paths == (tif,)


def test_checked_false_backslash_layer_is_skipped_and_selection_preserved(tmp_path):
    _touch(tmp_path / "Terrain" / "Active.hdf")
    active_tif = _touch(tmp_path / "Terrain" / "Active.Source.tif")
    _touch(tmp_path / "Terrain" / "Inactive.hdf")
    _touch(tmp_path / "Terrain" / "Inactive.Source.tif")
    rasmap = _write_rasmap(
        tmp_path / "Demo.rasmap",
        "",
        '    <Layer Name="Inactive" Checked="False"'
        ' Filename=".\\Terrain\\Inactive.hdf" />\n'
        '    <Layer Name="Active" Checked="True"'
        ' Filename=".\\Terrain\\Active.hdf" />',
    )

    info = RasProcess._get_projection_info(rasmap)

    assert info.terrain_path == active_tif
    assert info.terrain_paths == (active_tif,)


def test_missing_targets_yield_empty_projection_info(tmp_path):
    rasmap = _write_rasmap(
        tmp_path / "Demo.rasmap",
        ".\\Terrain\\Projection.prj",
        '    <Layer Name="Terrain" Filename=".\\Terrain\\Terrain.hdf" />',
    )

    info = RasProcess._get_projection_info(rasmap)

    assert info.prj_path is None
    assert info.terrain_path is None
    assert info.terrain_paths == ()


@pytest.mark.parametrize("separator", ["\\", "/"])
def test_terrain_hdf_with_spaces_uses_its_stem_for_tif_discovery(tmp_path, separator):
    _touch(tmp_path / "Terrain" / "Composite Terrain.hdf")
    east = _touch(tmp_path / "Terrain" / "Composite Terrain.East.tif")
    _touch(tmp_path / "Terrain" / "Unrelated.tif")
    filename = separator.join([".", "Terrain", "Composite Terrain.hdf"])
    rasmap = _write_rasmap(
        tmp_path / "Demo.rasmap",
        "",
        f'    <Layer Name="Composite" Filename="{filename}" />',
    )

    info = RasProcess._get_projection_info(rasmap)

    assert info.terrain_paths == (east,)
