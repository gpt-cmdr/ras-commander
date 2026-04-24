from importlib import import_module
from pathlib import Path
import subprocess


ras_process_module = import_module("ras_commander.RasProcess")
RasProcess = ras_process_module.RasProcess


class _DummyRas:
    def __init__(self, project_folder: Path, project_name: str = "Demo"):
        self.project_folder = project_folder
        self.project_name = project_name
        self.ras_exe_path = project_folder / "hecras" / "Ras.exe"

    def check_initialized(self):
        return None


def test_store_maps_moves_overwritten_outputs_to_custom_path(monkeypatch, tmp_path):
    project_folder = tmp_path
    project_name = "Demo"
    output_dir = project_folder / "PlanShort"
    custom_output_dir = project_folder / "custom_maps"
    rasmap_path = project_folder / f"{project_name}.rasmap"
    plan_hdf_path = project_folder / f"{project_name}.p01.hdf"

    (project_folder / "hecras").mkdir()
    (project_folder / "hecras" / "Ras.exe").write_text("", encoding="utf-8")
    plan_hdf_path.write_text("", encoding="utf-8")
    rasmap_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<RASMapper>
  <Results>
    <Layer Name="PlanShort" Filename="Demo.p01.hdf" />
  </Results>
</RASMapper>
""",
        encoding="utf-8",
    )

    output_dir.mkdir()
    (output_dir / "WSE (Max).tif").write_text("old", encoding="utf-8")

    ras_obj = _DummyRas(project_folder=project_folder, project_name=project_name)

    monkeypatch.setattr(
        ras_process_module.RasMap,
        "get_rasmap_path",
        staticmethod(lambda ras_object=None: rasmap_path),
    )
    monkeypatch.setattr(
        RasProcess,
        "_get_plan_short_id",
        staticmethod(lambda hdf_path: "PlanShort"),
    )
    monkeypatch.setattr(
        RasProcess,
        "_remove_stored_maps_from_rasmap",
        staticmethod(lambda *args, **kwargs: 0),
    )
    monkeypatch.setattr(
        RasProcess,
        "_add_stored_map_to_rasmap",
        staticmethod(lambda *args, **kwargs: True),
    )
    monkeypatch.setattr(
        ras_process_module.RasMap,
        "get_water_surface_render_mode",
        staticmethod(lambda ras_object=None: "horizontal"),
    )

    def fake_run_store_all_maps_helper(**kwargs):
        (output_dir / "WSE (Max).tif").write_text("newer", encoding="utf-8")
        (output_dir / "Depth (Max).tif").write_text("depth-map", encoding="utf-8")
        return subprocess.CompletedProcess(
            args=["RasStoreMapHelper.exe"],
            returncode=0,
            stdout="Maps generated: 2",
            stderr="",
        )

    monkeypatch.setattr(
        ras_process_module,
        "run_store_all_maps_helper",
        fake_run_store_all_maps_helper,
    )

    results = RasProcess.store_maps(
        plan_number="01",
        output_path=custom_output_dir,
        profile="Max",
        wse=True,
        depth=True,
        velocity=False,
        clear_existing=True,
        fix_georef=False,
        ras_object=ras_obj,
    )

    assert results["wse"] == [custom_output_dir / "WSE (Max).tif"]
    assert results["depth"] == [custom_output_dir / "Depth (Max).tif"]
    assert (custom_output_dir / "WSE (Max).tif").read_text(
        encoding="utf-8"
    ) == "newer"
    assert (custom_output_dir / "Depth (Max).tif").read_text(
        encoding="utf-8"
    ) == "depth-map"
    assert not (output_dir / "WSE (Max).tif").exists()
    assert not (output_dir / "Depth (Max).tif").exists()


def test_store_maps_leaves_unchanged_files_in_default_folder(monkeypatch, tmp_path):
    project_folder = tmp_path
    project_name = "Demo"
    output_dir = project_folder / "PlanShort"
    custom_output_dir = project_folder / "custom_maps"
    rasmap_path = project_folder / f"{project_name}.rasmap"
    plan_hdf_path = project_folder / f"{project_name}.p01.hdf"

    (project_folder / "hecras").mkdir()
    (project_folder / "hecras" / "Ras.exe").write_text("", encoding="utf-8")
    plan_hdf_path.write_text("", encoding="utf-8")
    rasmap_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<RASMapper>
  <Results>
    <Layer Name="PlanShort" Filename="Demo.p01.hdf" />
  </Results>
</RASMapper>
""",
        encoding="utf-8",
    )

    output_dir.mkdir()
    benchmark_path = output_dir / "manual_benchmark.tif"
    benchmark_path.write_text("keep-me", encoding="utf-8")

    ras_obj = _DummyRas(project_folder=project_folder, project_name=project_name)

    monkeypatch.setattr(
        ras_process_module.RasMap,
        "get_rasmap_path",
        staticmethod(lambda ras_object=None: rasmap_path),
    )
    monkeypatch.setattr(
        RasProcess,
        "_get_plan_short_id",
        staticmethod(lambda hdf_path: "PlanShort"),
    )
    monkeypatch.setattr(
        RasProcess,
        "_remove_stored_maps_from_rasmap",
        staticmethod(lambda *args, **kwargs: 0),
    )
    monkeypatch.setattr(
        RasProcess,
        "_add_stored_map_to_rasmap",
        staticmethod(lambda *args, **kwargs: True),
    )
    monkeypatch.setattr(
        ras_process_module.RasMap,
        "get_water_surface_render_mode",
        staticmethod(lambda ras_object=None: "horizontal"),
    )

    def fake_run_store_all_maps_helper(**kwargs):
        (output_dir / "Depth (Max).tif").write_text("depth-map", encoding="utf-8")
        return subprocess.CompletedProcess(
            args=["RasStoreMapHelper.exe"],
            returncode=0,
            stdout="Maps generated: 1",
            stderr="",
        )

    monkeypatch.setattr(
        ras_process_module,
        "run_store_all_maps_helper",
        fake_run_store_all_maps_helper,
    )

    results = RasProcess.store_maps(
        plan_number="01",
        output_path=custom_output_dir,
        profile="Max",
        wse=False,
        depth=True,
        velocity=False,
        clear_existing=True,
        fix_georef=False,
        ras_object=ras_obj,
    )

    assert results["depth"] == [custom_output_dir / "Depth (Max).tif"]
    assert benchmark_path.exists()
    assert benchmark_path.read_text(encoding="utf-8") == "keep-me"
    assert not (custom_output_dir / "manual_benchmark.tif").exists()
