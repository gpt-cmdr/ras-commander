from pathlib import Path
import subprocess
import sys

import h5py

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ras_commander import RasProcess
from ras_commander._geometry_association import write_geometry_association


def _make_geometry_hdf(path: Path) -> Path:
    with h5py.File(path, "w") as hdf_file:
        hdf_file.create_group("Geometry")
    return path


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("artifact", encoding="utf-8")
    return path


def test_validate_geometry_association_cli_reports_native_mutation(
    monkeypatch,
    tmp_path,
):
    geom_hdf = _make_geometry_hdf(tmp_path / "Model.g01.hdf")
    terrain = _touch(tmp_path / "Terrain" / "Terrain50.hdf")
    fake_exe = _touch(tmp_path / "RasProcess.exe")
    captured = {}

    def fake_run(rasprocess_path, args, timeout=600, working_dir=None):
        captured["rasprocess_path"] = rasprocess_path
        captured["args"] = args
        captured["timeout"] = timeout
        captured["working_dir"] = working_dir
        arg_map = dict(arg.split("=", 1) for arg in args[1:])
        write_geometry_association(
            arg_map["GeometryFilename"],
            terrain_hdf_path=arg_map["TerrainFilename"],
            project_folder=Path(arg_map["GeometryFilename"]).parent,
            validate=False,
        )
        return subprocess.CompletedProcess(args, 0, "terrain set\n", "")

    monkeypatch.setattr(
        RasProcess,
        "find_rasprocess",
        staticmethod(lambda ras_version=None: fake_exe),
    )
    monkeypatch.setattr(RasProcess, "_run_rasprocess", staticmethod(fake_run))

    result = RasProcess.validate_geometry_association_cli(
        geom_hdf,
        terrain_hdf_path=terrain,
        ras_version="6.6",
        timeout=42,
    )

    assert result["passed"] is True
    assert result["mismatches"] == []
    assert result["return_code"] == 0
    assert result["stdout"] == "terrain set\n"
    assert result["before"]["terrain_hdf_path"] is None
    assert Path(result["after"]["terrain_hdf_path"]) == terrain
    assert result["command_args"][0] == "SetGeometryAssociation"
    assert result["command_args"][1] == f"GeometryFilename={geom_hdf}"
    assert result["command_args"][2] == f"TerrainFilename={terrain}"
    assert captured["rasprocess_path"] == fake_exe
    assert captured["timeout"] == 42
    assert captured["working_dir"] == geom_hdf.parent


def test_validate_geometry_association_cli_reports_mismatches(
    monkeypatch,
    tmp_path,
):
    geom_hdf = _make_geometry_hdf(tmp_path / "Model.g01.hdf")
    terrain = _touch(tmp_path / "Terrain" / "Terrain50.hdf")
    fake_exe = _touch(tmp_path / "RasProcess.exe")

    def fake_run(rasprocess_path, args, timeout=600, working_dir=None):
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(
        RasProcess,
        "find_rasprocess",
        staticmethod(lambda ras_version=None: fake_exe),
    )
    monkeypatch.setattr(RasProcess, "_run_rasprocess", staticmethod(fake_run))

    result = RasProcess.validate_geometry_association_cli(
        geom_hdf,
        terrain_hdf_path=terrain,
    )

    assert result["passed"] is False
    assert result["return_code"] == 0
    assert result["mismatches"]
    assert result["mismatches"][0]["attribute"] == "Terrain Filename"
