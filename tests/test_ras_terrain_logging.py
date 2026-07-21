import logging
import subprocess
from importlib import import_module

import pytest


ras_terrain_module = import_module("ras_commander.terrain.RasTerrain")
RasTerrain = ras_terrain_module.RasTerrain
h5py = pytest.importorskip("h5py")


def _messages(caplog, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == ras_terrain_module.logger.name and record.levelno == level
    ]


def _text(caplog, level):
    return "\n".join(_messages(caplog, level))


def test_create_terrain_hdf_info_is_concise_and_debug_keeps_command(
    monkeypatch, tmp_path, caplog
):
    input_raster = tmp_path / "dem.tif"
    input_raster.write_text("dem", encoding="utf-8")
    projection_prj = tmp_path / "Projection.prj"
    projection_prj.write_text("proj", encoding="utf-8")
    output_hdf = tmp_path / "Terrain.hdf"

    rasprocess = tmp_path / "RasProcess.exe"
    rasprocess.write_text("", encoding="utf-8")
    gdal_bin = tmp_path / "GDAL" / "bin64"
    gdal_bin.mkdir(parents=True)
    (gdal_bin / "gdal_translate.exe").write_text("", encoding="utf-8")

    def fake_run(cmd, capture_output, text, timeout, cwd, env):
        with h5py.File(output_hdf, "w") as hdf:
            terrain = hdf.create_group("Terrain")
            terrain.create_dataset("Elevation", data=[1.0])
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="terrain stdout details",
            stderr="terrain stderr details",
        )

    monkeypatch.setattr(
        RasTerrain,
        "_get_hecras_path",
        staticmethod(lambda version: tmp_path),
    )
    monkeypatch.setattr(ras_terrain_module.subprocess, "run", fake_run)
    caplog.set_level(logging.DEBUG, logger=ras_terrain_module.logger.name)

    result = RasTerrain.create_terrain_hdf(
        input_rasters=[input_raster],
        output_hdf=output_hdf,
        projection_prj=projection_prj,
        hecras_version="7.0",
        timeout_seconds=7200,
    )

    assert result == output_hdf
    info_text = _text(caplog, logging.INFO)
    warning_text = _text(caplog, logging.WARNING)
    debug_text = _text(caplog, logging.DEBUG)

    assert "Terrain HDF created: Terrain.hdf" in info_text
    assert str(tmp_path) not in info_text
    assert "CreateTerrain" not in info_text
    assert "RasProcess.exe" not in info_text
    assert "completed with stderr" in warning_text
    assert "terrain stderr details" not in warning_text
    assert str(output_hdf) in debug_text
    assert str(input_raster) in debug_text
    assert "CreateTerrain" in debug_text
    assert "terrain stderr details" in debug_text


def test_vrt_to_tiff_info_uses_filenames_and_debug_keeps_paths(
    monkeypatch, tmp_path, caplog
):
    vrt_path = tmp_path / "input.vrt"
    vrt_path.write_text("<VRTDataset />", encoding="utf-8")
    output_path = tmp_path / "output.tif"

    gdal_bin = tmp_path / "GDAL" / "bin64"
    gdal_bin.mkdir(parents=True)
    gdal_translate = gdal_bin / "gdal_translate.exe"
    gdaladdo = gdal_bin / "gdaladdo.exe"
    gdal_translate.write_text("", encoding="utf-8")
    gdaladdo.write_text("", encoding="utf-8")

    commands = []

    def fake_run(cmd, capture_output, text, timeout, cwd, env):
        commands.append((cmd, cwd, env))
        if cmd[0] == str(gdal_translate):
            output_path.write_bytes(b"tiff")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(
            cmd,
            1,
            stdout="overview stdout details",
            stderr="overview stderr details",
        )

    monkeypatch.setattr(
        RasTerrain,
        "_get_hecras_gdal_path",
        staticmethod(lambda version: gdal_bin),
    )
    monkeypatch.setattr(ras_terrain_module.subprocess, "run", fake_run)
    caplog.set_level(logging.DEBUG, logger=ras_terrain_module.logger.name)

    result = RasTerrain.vrt_to_tiff(
        vrt_path=vrt_path,
        output_path=output_path,
        create_overviews=True,
        overview_levels=[2, 4],
        hecras_version="7.0",
    )

    assert result == output_path
    assert not any(item.startswith("NUM_THREADS=") for item in commands[0][0])
    assert "GDAL_NUM_THREADS" not in commands[0][2]
    assert commands[0][1] == str(tmp_path)
    info_text = _text(caplog, logging.INFO)
    warning_text = _text(caplog, logging.WARNING)
    debug_text = _text(caplog, logging.DEBUG)

    assert "Converting VRT to TIFF: input.vrt -> output.tif" in info_text
    assert "Adding pyramid overviews: [2, 4]" in info_text
    assert "VRT to TIFF conversion complete: output.tif" in info_text
    assert str(tmp_path) not in info_text
    assert str(gdal_translate) not in info_text
    assert "gdaladdo failed with code 1" in warning_text
    assert "overview stderr details" not in warning_text
    assert str(vrt_path) in debug_text
    assert str(output_path) in debug_text
    assert str(gdal_translate) in debug_text
    assert "overview stderr details" in debug_text
