from importlib import import_module
import subprocess

import pytest


ras_terrain_module = import_module("ras_commander.terrain.RasTerrain")
RasTerrain = ras_terrain_module.RasTerrain
h5py = pytest.importorskip("h5py")


def test_create_terrain_hdf_passes_custom_timeout(monkeypatch, tmp_path):
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

    calls = []

    def fake_run(cmd, capture_output, text, timeout, cwd, env):
        calls.append(
            {
                "cmd": cmd,
                "capture_output": capture_output,
                "text": text,
                "timeout": timeout,
                "cwd": cwd,
                "env_path": env["PATH"],
            }
        )
        with h5py.File(output_hdf, "w") as hdf:
            terrain = hdf.create_group("Terrain")
            terrain.create_dataset("Elevation", data=[1.0])
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(
        RasTerrain,
        "_get_hecras_path",
        staticmethod(lambda version: tmp_path),
    )
    monkeypatch.setattr(ras_terrain_module.subprocess, "run", fake_run)

    result = RasTerrain.create_terrain_hdf(
        input_rasters=[input_raster],
        output_hdf=output_hdf,
        projection_prj=projection_prj,
        hecras_version="7.0",
        timeout_seconds=7200,
    )

    assert result == output_hdf
    assert calls[0]["cmd"] == [
        str(rasprocess),
        "CreateTerrain",
        "units=Feet",
        "stitch=true",
        f"prj={projection_prj}",
        f"out={output_hdf}",
        str(input_raster),
    ]
    assert calls[0]["capture_output"] is True
    assert calls[0]["text"] is True
    assert calls[0]["timeout"] == 7200
    assert calls[0]["cwd"] == str(tmp_path)
    assert str(gdal_bin) in calls[0]["env_path"]


def test_create_terrain_hdf_rejects_non_positive_timeout(tmp_path):
    input_raster = tmp_path / "dem.tif"
    input_raster.write_text("dem", encoding="utf-8")
    projection_prj = tmp_path / "Projection.prj"
    projection_prj.write_text("proj", encoding="utf-8")
    output_hdf = tmp_path / "Terrain.hdf"

    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        RasTerrain.create_terrain_hdf(
            input_rasters=[input_raster],
            output_hdf=output_hdf,
            projection_prj=projection_prj,
            timeout_seconds=0,
        )
