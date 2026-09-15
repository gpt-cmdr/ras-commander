"""Explicit target CRS, resolution, resampling, and nodata for VRT mosaics.

``create_vrt()`` historically passed no georeferencing options to
``gdalbuildvrt``, so a mosaic inherited the first tile's SRS and native cell
size. These tests pin the unchanged default command and the new explicit-grid
command construction. No GDAL executable is launched.
"""

from importlib import import_module
from pathlib import Path
import subprocess

import pytest


usgs_module = import_module("ras_commander.terrain.Usgs3depAws")
Usgs3depAws = usgs_module.Usgs3depAws


@pytest.fixture
def gdal_harness(monkeypatch, tmp_path):
    """Fake HEC-RAS bundled GDAL executables that record their command lines."""
    tile_a = tmp_path / "USGS_1M_14_x01y01_TX_A_2020_A20.tif"
    tile_b = tmp_path / "USGS_1M_15_x01y01_TX_B_2020_A20.tif"
    tile_a.write_text("a", encoding="utf-8")
    tile_b.write_text("b", encoding="utf-8")

    gdalbuildvrt = tmp_path / "gdalbuildvrt.exe"
    gdalwarp = tmp_path / "gdalwarp.exe"
    gdalbuildvrt.write_text("", encoding="utf-8")
    gdalwarp.write_text("", encoding="utf-8")

    commands = []

    def fake_run(cmd, capture_output, text, timeout):
        commands.append(list(cmd))
        # Every GDAL tool used here writes its output as the final argument.
        Path(cmd[-1]).write_text("<VRTDataset />", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(
        Usgs3depAws,
        "_find_gdalbuildvrt_path",
        staticmethod(lambda hecras_version=None: gdalbuildvrt),
    )
    monkeypatch.setattr(
        Usgs3depAws,
        "_find_gdalwarp_path",
        staticmethod(lambda hecras_version=None: gdalwarp),
    )
    monkeypatch.setattr(usgs_module.subprocess, "run", fake_run)

    return {
        "tiles": [tile_a, tile_b],
        "gdalbuildvrt": gdalbuildvrt,
        "gdalwarp": gdalwarp,
        "commands": commands,
        "output_vrt": tmp_path / "terrain.vrt",
    }


def test_create_vrt_default_command_is_unchanged(gdal_harness):
    result = Usgs3depAws.create_vrt(
        gdal_harness["tiles"], gdal_harness["output_vrt"]
    )

    assert result == gdal_harness["output_vrt"]
    assert len(gdal_harness["commands"]) == 1

    cmd = gdal_harness["commands"][0]
    assert cmd[:4] == [str(gdal_harness["gdalbuildvrt"]), "-overwrite", "-r", "bilinear"]
    assert "-t_srs" not in cmd
    assert "-a_srs" not in cmd
    assert "-tr" not in cmd
    assert "-srcnodata" not in cmd
    assert "-vrtnodata" not in cmd


def test_create_vrt_applies_resolution_resampling_and_nodata(gdal_harness):
    Usgs3depAws.create_vrt(
        gdal_harness["tiles"],
        gdal_harness["output_vrt"],
        target_resolution=10,
        resampling_method="cubic",
        src_nodata=-999999,
        vrt_nodata=-9999,
        source_crs="EPSG:26914",
    )

    cmd = gdal_harness["commands"][0]
    assert cmd[2:4] == ["-r", "cubic"]
    assert cmd[cmd.index("-a_srs") + 1] == "EPSG:26914"
    assert cmd[cmd.index("-resolution") + 1] == "user"
    assert cmd[cmd.index("-tr") + 1: cmd.index("-tr") + 3] == ["10.0", "10.0"]
    assert cmd[cmd.index("-srcnodata") + 1] == "-999999"
    assert cmd[cmd.index("-vrtnodata") + 1] == "-9999"


def test_create_vrt_warps_each_tile_to_the_target_crs(gdal_harness):
    """The fim-commander case: EPSG:2277, NAVD88 ftUS, 10-foot cells."""
    output_vrt = gdal_harness["output_vrt"]

    result = Usgs3depAws.create_vrt(
        gdal_harness["tiles"],
        output_vrt,
        target_crs="EPSG:2277",
        target_resolution=10.0,
        src_nodata=-999999,
        vrt_nodata=-9999,
    )

    assert result == output_vrt
    commands = gdal_harness["commands"]
    assert len(commands) == 3  # one warp per tile, then the mosaic

    warped_folder = output_vrt.parent / f"{output_vrt.stem}_warped"
    for warp_cmd, tile in zip(commands[:2], gdal_harness["tiles"]):
        assert warp_cmd[0] == str(gdal_harness["gdalwarp"])
        assert warp_cmd[warp_cmd.index("-of") + 1] == "VRT"
        assert warp_cmd[warp_cmd.index("-t_srs") + 1] == "EPSG:2277"
        assert warp_cmd[warp_cmd.index("-r") + 1] == "bilinear"
        assert warp_cmd[warp_cmd.index("-tr") + 1: warp_cmd.index("-tr") + 3] == [
            "10.0",
            "10.0",
        ]
        # Aligned target pixels keep the warped tiles on one shared grid.
        assert "-tap" in warp_cmd
        assert warp_cmd[warp_cmd.index("-srcnodata") + 1] == "-999999"
        assert warp_cmd[warp_cmd.index("-dstnodata") + 1] == "-9999"
        assert warp_cmd[-2] == str(tile)
        assert warp_cmd[-1] == str(warped_folder / f"{tile.stem}.vrt")

    mosaic_cmd = commands[2]
    assert mosaic_cmd[0] == str(gdal_harness["gdalbuildvrt"])
    # The mosaic step never re-applies -srcnodata; the warped tiles carry it.
    assert "-srcnodata" not in mosaic_cmd
    assert mosaic_cmd[mosaic_cmd.index("-vrtnodata") + 1] == "-9999"
    assert mosaic_cmd[mosaic_cmd.index("-tr") + 1: mosaic_cmd.index("-tr") + 3] == [
        "10.0",
        "10.0",
    ]


def test_create_vrt_mosaics_the_warped_tiles(gdal_harness, monkeypatch):
    output_vrt = gdal_harness["output_vrt"]
    warped_folder = output_vrt.parent / f"{output_vrt.stem}_warped"
    recorded = {}

    def fake_write_input_file_list(tile_paths, output_dir):
        recorded["tile_paths"] = list(tile_paths)
        list_path = output_dir / "input-list.txt"
        list_path.write_text(
            "".join(f"{tile_path}\n" for tile_path in tile_paths),
            encoding="utf-8",
        )
        return list_path

    monkeypatch.setattr(
        Usgs3depAws,
        "_write_gdal_input_file_list",
        staticmethod(fake_write_input_file_list),
    )

    Usgs3depAws.create_vrt(
        gdal_harness["tiles"],
        output_vrt,
        target_crs="EPSG:2277",
    )

    assert recorded["tile_paths"] == [
        warped_folder / f"{tile.stem}.vrt" for tile in gdal_harness["tiles"]
    ]


def test_create_vrt_requires_hecras_gdalwarp_for_reprojection(gdal_harness, monkeypatch):
    monkeypatch.setattr(
        Usgs3depAws,
        "_find_gdalwarp_path",
        staticmethod(
            lambda hecras_version=None: (_ for _ in ()).throw(
                FileNotFoundError("not installed")
            )
        ),
    )

    with pytest.raises(FileNotFoundError, match="requires HEC-RAS bundled gdalwarp.exe"):
        Usgs3depAws.create_vrt(
            gdal_harness["tiles"],
            gdal_harness["output_vrt"],
            target_crs="EPSG:2277",
        )


@pytest.mark.parametrize("target_resolution", [0, -10, (10, 0), "ten", (1, 2, 3)])
def test_create_vrt_rejects_invalid_target_resolution(gdal_harness, target_resolution):
    with pytest.raises(ValueError, match="target_resolution"):
        Usgs3depAws.create_vrt(
            gdal_harness["tiles"],
            gdal_harness["output_vrt"],
            target_resolution=target_resolution,
        )


def test_normalize_target_resolution_accepts_scalars_and_pairs():
    assert Usgs3depAws._normalize_target_resolution(None) is None
    assert Usgs3depAws._normalize_target_resolution(10) == (10.0, 10.0)
    assert Usgs3depAws._normalize_target_resolution((10, 5)) == (10.0, 5.0)


def test_find_gdalwarp_path_uses_the_hecras_gdal_folder(monkeypatch, tmp_path):
    ras_terrain_module = import_module("ras_commander.terrain.RasTerrain")
    RasTerrain = ras_terrain_module.RasTerrain

    install_dir = tmp_path / "6.6"
    gdal_bin = install_dir / "GDAL" / "bin64"
    gdal_bin.mkdir(parents=True)
    gdalwarp = gdal_bin / "gdalwarp.exe"
    gdalwarp.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        RasTerrain,
        "_get_hecras_path",
        staticmethod(lambda version: install_dir if version == "6.6" else None),
    )

    assert Usgs3depAws._find_gdalwarp_path("6.6") == gdalwarp


def test_find_gdalwarp_path_reports_missing_tool(monkeypatch):
    ras_terrain_module = import_module("ras_commander.terrain.RasTerrain")
    RasTerrain = ras_terrain_module.RasTerrain

    monkeypatch.setattr(RasTerrain, "_HECRAS_BASE_PATHS", [])
    monkeypatch.setattr(
        RasTerrain,
        "get_available_versions",
        staticmethod(lambda: []),
    )

    with pytest.raises(FileNotFoundError, match="gdalwarp.exe not found"):
        Usgs3depAws._find_gdalwarp_path()
