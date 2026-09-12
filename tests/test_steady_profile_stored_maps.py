from contextlib import contextmanager
from importlib import import_module
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
import json
import subprocess
import xml.etree.ElementTree as ET

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import RasMap, RasProcess
from ras_commander.schemas import DATAFRAME_SCHEMAS


ras_process_module = import_module("ras_commander.RasProcess")


class _DummyRas:
    def __init__(self, project_folder: Path):
        self.project_folder = project_folder
        self.project_name = "Demo"
        self.ras_exe_path = project_folder / "HEC-RAS" / "Ras.exe"
        self.ras_version = "6.6"
        self.plan_df = pd.DataFrame(
            [{"plan_number": "01", "Short Identifier": "PlanShort"}]
        )

    def check_initialized(self):
        return None


def _write_steady_project(tmp_path: Path, profile_names=("P1", "P2", "P3")):
    rasmap_path = tmp_path / "Demo.rasmap"
    rasmap_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<RASMapper>
  <Geometries />
  <Results>
    <Layer Name="PlanShort" Type="RASResults" Filename=".\\Demo.p01.hdf">
      <Layer Name="Old" Type="RASResultsMap" Filename=".\\PlanShort\\Old.vrt">
        <MapParameters MapType="depth" OutputMode="Stored Current Terrain"
          StoredFilename=".\\PlanShort\\Old.vrt" ProfileIndex="0" ProfileName="Old" />
      </Layer>
    </Layer>
  </Results>
</RASMapper>
""",
        encoding="utf-8",
    )
    hdf_path = tmp_path / "Demo.p01.hdf"
    with h5py.File(hdf_path, "w") as hdf_file:
        plan_info = hdf_file.require_group("Plan Data/Plan Information")
        plan_info.attrs["Plan ShortID"] = np.bytes_("PlanShort")
        profile_group = hdf_file.require_group(
            "Results/Steady/Output/Output Blocks/Base Output/"
            "Steady Profiles"
        )
        profile_group.create_dataset(
            "Profile Names",
            data=np.asarray([name.encode("utf-8") for name in profile_names]),
        )
    (tmp_path / "HEC-RAS").mkdir()
    return _DummyRas(tmp_path), rasmap_path, hdf_path


def _configure_engine(monkeypatch, tmp_path, profile_names=("P1", "P2", "P3")):
    ras_obj, rasmap_path, hdf_path = _write_steady_project(
        tmp_path,
        profile_names=profile_names,
    )
    monkeypatch.setattr(
        ras_process_module.RasMap,
        "get_rasmap_path",
        staticmethod(lambda _ras_object=None: rasmap_path),
    )
    monkeypatch.setattr(
        ras_process_module.RasMap,
        "get_water_surface_render_mode",
        staticmethod(lambda ras_object=None: "horizontal"),
    )
    monkeypatch.setattr(
        ras_process_module,
        "store_maps_runtime_provenance",
        lambda _hecras_dir: {"helper": "test-double"},
    )

    @contextmanager
    def compatible_hdf(path, _version):
        yield path

    monkeypatch.setattr(
        RasProcess,
        "_mapper_compatible_result_hdf",
        staticmethod(compatible_hdf),
    )
    return ras_obj, rasmap_path, hdf_path


def _write_configured_outputs(rasmap_path: Path, output_dir: Path) -> None:
    tree = ET.parse(rasmap_path)
    for parameters in tree.findall(".//MapParameters"):
        stored_filename = parameters.get("StoredFilename", "")
        filename = PureWindowsPath(stored_filename).name
        if not filename or filename == "Old.vrt":
            continue
        target = output_dir / filename
        target.write_text("primary", encoding="utf-8")
        if "Polygon" in parameters.get("OutputMode", ""):
            target.with_suffix(".dbf").write_text("dbf", encoding="utf-8")
            target.with_suffix(".shx").write_text("shx", encoding="utf-8")
        else:
            (output_dir / f"{target.stem}.Terrain.tif").write_text(
                "tile",
                encoding="utf-8",
            )


def test_steady_profile_engine_bulk_configures_and_launches_once(
    monkeypatch,
    tmp_path,
):
    ras_obj, rasmap_path, hdf_path = _configure_engine(monkeypatch, tmp_path)
    original_rasmap = rasmap_path.read_bytes()
    output_dir = tmp_path / "PlanShort"
    helper_calls = []
    xml_writes = []
    original_write = ET.ElementTree.write

    def counted_write(self, *args, **kwargs):
        xml_writes.append(args[0])
        return original_write(self, *args, **kwargs)

    monkeypatch.setattr(ET.ElementTree, "write", counted_write)

    def fake_helper(**kwargs):
        helper_calls.append(kwargs)
        _write_configured_outputs(rasmap_path, output_dir)
        return subprocess.CompletedProcess(
            args=["RasStoreMapHelper.exe"],
            returncode=0,
            stdout="Maps generated: 5",
            stderr="",
        )

    monkeypatch.setattr(
        ras_process_module,
        "run_store_all_maps_helper",
        fake_helper,
    )
    destination = tmp_path / "published"

    frame = RasProcess.store_maps_at_steady_profiles(
        "01",
        profiles=[2, "P1"],
        output_path=destination,
        map_types=("depth", "velocity"),
        fix_georef=False,
        ras_object=ras_obj,
    )

    assert len(helper_calls) == 1
    assert len(xml_writes) == 1
    assert rasmap_path.read_bytes() == original_rasmap
    assert frame[["profile_index", "profile_name", "map_type"]].to_records(
        index=False
    ).tolist() == [
        (2, "P3", "depth"),
        (2, "P3", "velocity"),
        (0, "P1", "depth"),
        (0, "P1", "velocity"),
        (0, "P1", "inundation_boundary"),
    ]
    assert frame["output_mode"].tolist() == [
        "raster",
        "raster",
        "raster",
        "raster",
        "polygon",
    ]
    assert all(Path(path).parent == destination for path in frame["primary_path"])
    assert frame.loc[frame["output_mode"] == "raster", "file_count"].eq(2).all()
    assert frame.loc[frame["output_mode"] == "polygon", "file_count"].eq(3).all()
    assert frame.attrs["schema"] == (
        "ras_commander.steady_profile_stored_maps.v1"
    )
    assert frame.attrs["helper_launch_count"] == 1
    assert frame.attrs["profile_count"] == 2
    assert frame.attrs["configured_map_count"] == 5
    assert frame.attrs["generated_file_count"] == 11
    assert frame.attrs["runtime_provenance"] == {"helper": "test-double"}
    schema_columns = [
        column["name"]
        for column in DATAFRAME_SCHEMAS["steady_profile_stored_maps"]["columns"]
    ]
    assert schema_columns == frame.columns.tolist()
    assert frame["result_hdf_path"].unique().tolist() == [str(hdf_path.resolve())]


@pytest.mark.parametrize("failure_mode", ["exit", "missing", "timeout"])
def test_steady_profile_engine_restores_rasmap_on_failure(
    monkeypatch,
    tmp_path,
    failure_mode,
):
    ras_obj, rasmap_path, _ = _configure_engine(monkeypatch, tmp_path)
    original_rasmap = rasmap_path.read_bytes()
    calls = []

    def fake_helper(**_kwargs):
        calls.append(failure_mode)
        if failure_mode == "timeout":
            raise subprocess.TimeoutExpired("RasStoreMapHelper.exe", 1)
        return subprocess.CompletedProcess(
            args=["RasStoreMapHelper.exe"],
            returncode=1 if failure_mode == "exit" else 0,
            stdout="",
            stderr="forced failure" if failure_mode == "exit" else "",
        )

    monkeypatch.setattr(
        ras_process_module,
        "run_store_all_maps_helper",
        fake_helper,
    )

    expected_exception = (
        subprocess.TimeoutExpired if failure_mode == "timeout" else RuntimeError
    )
    with pytest.raises(expected_exception):
        RasProcess.store_maps_at_steady_profiles(
            "01",
            fix_georef=False,
            ras_object=ras_obj,
        )

    assert calls == [failure_mode]
    assert rasmap_path.read_bytes() == original_rasmap


@pytest.mark.parametrize(
    "profiles",
    [True, -1, 99, "Missing", [0, "P1"]],
)
def test_steady_profile_engine_rejects_invalid_selectors_before_mutation(
    monkeypatch,
    tmp_path,
    profiles,
):
    ras_obj, rasmap_path, _ = _configure_engine(monkeypatch, tmp_path)
    original_rasmap = rasmap_path.read_bytes()
    helper_calls = []
    monkeypatch.setattr(
        ras_process_module,
        "run_store_all_maps_helper",
        lambda **kwargs: helper_calls.append(kwargs),
    )

    with pytest.raises((TypeError, ValueError)):
        RasProcess.store_maps_at_steady_profiles(
            "01",
            profiles=profiles,
            fix_georef=False,
            ras_object=ras_obj,
        )

    assert helper_calls == []
    assert rasmap_path.read_bytes() == original_rasmap


def test_steady_profile_engine_rejects_ambiguous_names_and_filename_collisions(
    monkeypatch,
    tmp_path,
):
    ambiguous_dir = tmp_path / "ambiguous"
    ambiguous_dir.mkdir()
    ras_obj, rasmap_path, _ = _configure_engine(
        monkeypatch,
        ambiguous_dir,
        profile_names=("Same", "Same"),
    )
    original = rasmap_path.read_bytes()
    with pytest.raises(ValueError, match="ambiguous"):
        RasProcess.store_maps_at_steady_profiles(
            "01",
            profiles="Same",
            fix_georef=False,
            ras_object=ras_obj,
        )
    assert rasmap_path.read_bytes() == original

    collision_dir = tmp_path / "collision"
    collision_dir.mkdir()
    ras_obj, rasmap_path, _ = _configure_engine(
        monkeypatch,
        collision_dir,
        profile_names=("A:B", "A/B"),
    )
    original = rasmap_path.read_bytes()
    with pytest.raises(ValueError, match="filename collision"):
        RasProcess.store_maps_at_steady_profiles(
            "01",
            fix_georef=False,
            ras_object=ras_obj,
        )
    assert rasmap_path.read_bytes() == original


def test_rasmap_steady_profiles_mode_serializes_dataframe(monkeypatch, tmp_path):
    ras_obj, _, hdf_path = _write_steady_project(tmp_path)
    calls = []
    frame = pd.DataFrame(
        [
            {
                "plan_number": "01",
                "result_hdf_path": str(hdf_path),
                "profile_index": 0,
                "profile_name": "P1",
                "map_type": "depth",
                "output_mode": "raster",
                "primary_path": str(tmp_path / "Depth (P1).vrt"),
                "files": [
                    str(tmp_path / "Depth (P1).vrt"),
                    str(tmp_path / "Depth (P1).Terrain.tif"),
                ],
                "file_count": 2,
            },
            {
                "plan_number": "01",
                "result_hdf_path": str(hdf_path),
                "profile_index": 0,
                "profile_name": "P1",
                "map_type": "inundation_boundary",
                "output_mode": "polygon",
                "primary_path": str(tmp_path / "Inundation Boundary (P1).shp"),
                "files": [str(tmp_path / "Inundation Boundary (P1).shp")],
                "file_count": 1,
            },
        ]
    )
    frame.attrs["schema"] = "ras_commander.steady_profile_stored_maps.v1"
    frame.attrs["helper_launch_count"] = 1

    def fake_engine(**kwargs):
        calls.append(kwargs)
        return frame

    monkeypatch.setattr(
        RasProcess,
        "store_maps_at_steady_profiles",
        staticmethod(fake_engine),
    )

    summary = RasMap.store_all_maps(
        "01",
        mode="steady_profiles",
        profiles=[0],
        map_types=("depth",),
        ras_object=ras_obj,
    )

    assert len(calls) == 1
    assert calls[0]["profiles"] == [0]
    assert calls[0]["map_types"] == ["depth"]
    assert calls[0]["inundation_boundary"] is True
    assert summary["success"] is True
    assert summary["mode"] == "steady_profiles"
    assert summary["plans"]["01"]["profiles"][0]["profile_name"] == "P1"
    assert len(summary["plans"]["01"]["stored_maps"]) == 2
    json.dumps(summary)


def test_rasmap_steady_profiles_mode_dispatches_flow_product(
    monkeypatch,
    tmp_path,
):
    ras_obj, _, _ = _write_steady_project(tmp_path)
    calls = []

    def fake_engine(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame(
            columns=[
                "plan_number",
                "result_hdf_path",
                "profile_index",
                "profile_name",
                "map_type",
                "output_mode",
                "primary_path",
                "files",
                "file_count",
            ]
        )

    monkeypatch.setattr(
        RasProcess,
        "store_maps_at_steady_profiles",
        staticmethod(fake_engine),
    )

    summary = RasMap.store_all_maps(
        "01",
        mode="steady_profiles",
        profiles=[0],
        map_types=("flow",),
        ras_object=ras_obj,
    )

    assert calls[0]["map_types"] == ["flow"]
    assert summary["success"] is True
