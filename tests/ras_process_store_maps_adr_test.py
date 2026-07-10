"""Tests for arrival time / duration / percent-inundated stored maps.

These map types are whole-simulation products: RasMapperLib names them by the
ArrivalDepth threshold (e.g. "Arrival Time (0.1ft hrs)") instead of the profile,
always uses the Max profile, and requires the correct MapType XML names
("arrival time", "duration", "fraction inundated") verified against the
RasMapperLib.dll MapTypes table for 6.6 and 7.0.1.
"""

import subprocess
import xml.etree.ElementTree as ET
from importlib import import_module
from pathlib import Path


ras_process_module = import_module("ras_commander.RasProcess")
RasProcess = ras_process_module.RasProcess


class _DummyRas:
    def __init__(self, project_folder: Path, project_name: str = "Demo"):
        self.project_folder = project_folder
        self.project_name = project_name
        self.ras_exe_path = project_folder / "hecras" / "Ras.exe"

    def check_initialized(self):
        return None


def _write_minimal_rasmap(rasmap_path: Path):
    rasmap_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<RASMapper>
  <Results>
    <Layer Name="PlanShort" Type="RASResults" Filename=".\\Demo.p01.hdf" />
  </Results>
</RASMapper>
""",
        encoding="utf-8",
    )


def test_add_stored_map_extra_attrs_set_on_map_parameters(tmp_path):
    rasmap_path = tmp_path / "Demo.rasmap"
    _write_minimal_rasmap(rasmap_path)

    ok = RasProcess._add_stored_map_to_rasmap(
        rasmap_path,
        "Demo.p01.hdf",
        "arrival time",
        "Max",
        "PlanShort",
        2147483647,
        extra_attrs={"ArrivalDepth": "0.25"},
    )
    assert ok

    root = ET.parse(rasmap_path).getroot()
    params = root.findall(".//MapParameters")
    assert len(params) == 1
    assert params[0].get("MapType") == "arrival time"
    assert params[0].get("ArrivalDepth") == "0.25"
    assert params[0].get("ProfileIndex") == "2147483647"


def test_map_types_use_verified_xml_names():
    assert RasProcess.MAP_TYPES["arrival_time"][0] == "arrival time"
    assert RasProcess.MAP_TYPES["duration"][0] == "duration"
    assert RasProcess.MAP_TYPES["percent_inundated"][0] == "fraction inundated"
    # RasMapperLib has no recession MapType; it must not be offered.
    assert "recession" not in RasProcess.MAP_TYPES


def test_store_maps_adr_types_injected_and_collected(monkeypatch, tmp_path):
    project_folder = tmp_path
    project_name = "Demo"
    output_dir = project_folder / "PlanShort"
    rasmap_path = project_folder / f"{project_name}.rasmap"
    plan_hdf_path = project_folder / f"{project_name}.p01.hdf"

    (project_folder / "hecras").mkdir()
    (project_folder / "hecras" / "Ras.exe").write_text("", encoding="utf-8")
    plan_hdf_path.write_text("", encoding="utf-8")
    _write_minimal_rasmap(rasmap_path)
    output_dir.mkdir()

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
        ras_process_module.RasMap,
        "get_water_surface_render_mode",
        staticmethod(lambda ras_object=None: "horizontal"),
    )

    injected_rasmap = {}

    def fake_run_store_all_maps_helper(**kwargs):
        # Capture the rasmap as the helper sees it (before the finally-restore)
        injected_rasmap["xml"] = rasmap_path.read_text(encoding="utf-8")
        (output_dir / "Arrival Time (0.1ft hrs).Terrain.tile.tif").write_text(
            "arrival", encoding="utf-8"
        )
        (output_dir / "Duration (0.1ft hrs).Terrain.tile.tif").write_text(
            "duration", encoding="utf-8"
        )
        (output_dir / "Percent Time Inundated (0.1ft).Terrain.tile.tif").write_text(
            "percent", encoding="utf-8"
        )
        return subprocess.CompletedProcess(
            args=["RasStoreMapHelper.exe"],
            returncode=0,
            stdout="Maps generated: 3",
            stderr="",
        )

    monkeypatch.setattr(
        ras_process_module,
        "run_store_all_maps_helper",
        fake_run_store_all_maps_helper,
    )

    results = RasProcess.store_maps(
        plan_number="01",
        profile="Max",
        wse=False,
        depth=False,
        velocity=False,
        arrival_time=True,
        duration=True,
        percent_inundated=True,
        arrival_depth=0.1,
        clear_existing=False,
        fix_georef=False,
        ras_object=ras_obj,
    )

    # Injected entries carried the verified XML names + threshold, Max profile
    root = ET.fromstring(injected_rasmap["xml"])
    params = root.findall(".//MapParameters")
    map_types = {p.get("MapType") for p in params}
    assert map_types == {"arrival time", "duration", "fraction inundated"}
    assert all(p.get("ArrivalDepth") == "0.1" for p in params)
    assert all(p.get("ProfileIndex") == "2147483647" for p in params)

    # Threshold-labeled outputs collected under the right keys
    assert [p.name for p in results["arrival_time"]] == [
        "Arrival Time (0.1ft hrs).Terrain.tile.tif"
    ]
    assert [p.name for p in results["duration"]] == [
        "Duration (0.1ft hrs).Terrain.tile.tif"
    ]
    assert [p.name for p in results["percent_inundated"]] == [
        "Percent Time Inundated (0.1ft).Terrain.tile.tif"
    ]

    # rasmap restored after the run (backup semantics unchanged)
    restored = ET.parse(rasmap_path).getroot()
    assert restored.findall(".//MapParameters") == []
