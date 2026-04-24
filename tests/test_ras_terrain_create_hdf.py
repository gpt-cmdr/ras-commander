from importlib import import_module
import subprocess

import pytest


ras_terrain_module = import_module("ras_commander.terrain.RasTerrain")
RasTerrain = ras_terrain_module.RasTerrain


def test_create_terrain_hdf_passes_custom_timeout(monkeypatch, tmp_path):
    input_raster = tmp_path / "dem.tif"
    input_raster.write_text("dem", encoding="utf-8")
    projection_prj = tmp_path / "Projection.prj"
    projection_prj.write_text("proj", encoding="utf-8")
    output_hdf = tmp_path / "Terrain.hdf"

    rasprocess = tmp_path / "RasProcess.exe"
    rasprocess.write_text("", encoding="utf-8")

    calls = []

    def fake_run(cmd_str, shell, capture_output, text, timeout):
        calls.append(
            {
                "cmd_str": cmd_str,
                "shell": shell,
                "capture_output": capture_output,
                "text": text,
                "timeout": timeout,
            }
        )
        output_hdf.write_text("hdf", encoding="utf-8")
        return subprocess.CompletedProcess(cmd_str, 0, stdout="", stderr="")

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
    assert calls == [
        {
            "cmd_str": (
                f'"{rasprocess}" CreateTerrain '
                f'units=Feet stitch=true '
                f'prj="{projection_prj}" '
                f'out="{output_hdf}" '
                f'"{input_raster}"'
            ),
            "shell": True,
            "capture_output": True,
            "text": True,
            "timeout": 7200,
        }
    ]


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
