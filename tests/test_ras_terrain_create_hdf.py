from importlib import import_module
from pathlib import Path
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
    resolved_paths = []

    def fake_run(cmd, capture_output, text, timeout, cwd, env):
        calls.append(
            {
                "cmd": cmd,
                "capture_output": capture_output,
                "text": text,
                "timeout": timeout,
                "cwd": cwd,
                "env_path": env["PATH"],
                "gdal_num_threads": env.get("GDAL_NUM_THREADS"),
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
    monkeypatch.setattr(
        ras_terrain_module.RasUtils,
        "safe_resolve",
        staticmethod(
            lambda path: resolved_paths.append(Path(path)) or Path(path).absolute()
        ),
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
    assert calls[0]["gdal_num_threads"] is None
    assert {input_raster, projection_prj, output_hdf} <= set(resolved_paths)


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


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1, "1"), (4, "4"), ("all_cpus", "ALL_CPUS"), (None, None)],
)
def test_build_hecras_terrain_env_controls_gdal_threads(
    monkeypatch,
    tmp_path,
    value,
    expected,
):
    gdal_bin = tmp_path / "GDAL" / "bin64"
    gdal_bin.mkdir(parents=True)
    (gdal_bin / "gdal_translate.exe").write_text("", encoding="utf-8")
    monkeypatch.setenv("GDAL_NUM_THREADS", "inherited")

    env = RasTerrain._build_hecras_terrain_env(
        tmp_path,
        gdal_num_threads=value,
    )

    assert env.get("GDAL_NUM_THREADS") == expected


@pytest.mark.parametrize("value", [0, -1, "many"])
def test_create_terrain_hdf_rejects_invalid_gdal_threads(tmp_path, value):
    input_raster = tmp_path / "dem.tif"
    input_raster.write_text("dem", encoding="utf-8")
    projection_prj = tmp_path / "Projection.prj"
    projection_prj.write_text("proj", encoding="utf-8")

    with pytest.raises(ValueError, match="gdal_num_threads"):
        RasTerrain.create_terrain_hdf(
            input_rasters=[input_raster],
            output_hdf=tmp_path / "Terrain.hdf",
            projection_prj=projection_prj,
            gdal_num_threads=value,
        )


@pytest.fixture
def terrain_failure_inputs(tmp_path, monkeypatch):
    install = tmp_path / "Program Files" / "HEC-RAS"
    install.mkdir(parents=True)
    (install / "RasProcess.exe").write_bytes(b"not executed")
    gdal = install / "GDAL" / "bin64"
    gdal.mkdir(parents=True)
    (gdal / "gdal_translate.exe").write_bytes(b"not executed")
    raster = tmp_path / "input terrain.tif"
    raster.write_bytes(b"intercepted process input")
    projection = tmp_path / "Projection File.prj"
    projection.write_text("intercepted process input", encoding="utf-8")
    output = tmp_path / "Terrain" / "Terrain.hdf"
    monkeypatch.setattr(RasTerrain, "_get_hecras_path", staticmethod(lambda _: install))
    return raster, output, projection


def test_create_terrain_hdf_reports_process_timeout(terrain_failure_inputs, monkeypatch):
    def timed_out(command, **kwargs):
        assert kwargs["timeout"] == 3
        raise subprocess.TimeoutExpired(command, 3)

    monkeypatch.setattr(ras_terrain_module.subprocess, "run", timed_out)
    raster, output, projection = terrain_failure_inputs
    with pytest.raises(RuntimeError, match="timed out after 3 seconds"):
        RasTerrain.create_terrain_hdf([raster], output, projection, timeout_seconds=3)
    assert not output.exists()


def test_create_terrain_hdf_rejects_failed_process_with_readable_output(
    terrain_failure_inputs, monkeypatch
):
    raster, output, projection = terrain_failure_inputs

    def failed_run(command, **kwargs):
        with h5py.File(output, "w") as hdf:
            hdf.create_dataset("Terrain/Elevation", data=[1.0])
        return subprocess.CompletedProcess(command, 17, "Final Processing", "controlled failure")

    monkeypatch.setattr(ras_terrain_module.subprocess, "run", failed_run)
    with pytest.raises(RuntimeError, match="Return code: 17"):
        RasTerrain.create_terrain_hdf([raster], output, projection)
    with h5py.File(output, "r") as hdf:
        assert hdf["Terrain/Elevation"][0] == 1.0
