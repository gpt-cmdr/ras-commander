"""preprocess_plan() must not report success when referenced land-classification files are missing.

HEC-RAS 6.0-6.2 skip the geometry without an error when a land-cover,
infiltration, or sediment file the geometry references is missing, so the
plan HDF has no 2D mesh. 6.3 and later still preprocess the mesh.
"""

import importlib
from pathlib import Path

import h5py
import pandas as pd
import pytest

from ras_commander.RasPreprocess import RasPreprocess


raspreprocess_module = importlib.import_module("ras_commander.RasPreprocess")


class _FakeRas:
    def __init__(self, project_folder: Path, ras_exe_path: Path):
        self.project_folder = project_folder
        self.project_name = "fixture"
        self.ras_exe_path = ras_exe_path
        self.plan_df = pd.DataFrame([{"plan_number": "01", "Geom File": "g03"}])

    def check_initialized(self):
        return None


def _seed_project(tmp_path: Path, geometry_attrs=None, version="6.2") -> _FakeRas:
    project_folder = tmp_path / "project"
    project_folder.mkdir()
    exe = tmp_path / "HEC-RAS" / version / "Ras.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"fixture executable")
    project = _FakeRas(project_folder, exe)
    (project_folder / "fixture.prj").write_text("Proj Title=fixture\n", encoding="utf-8")
    (project_folder / "fixture.p01").write_text(
        "Plan Title=fixture\nGeom File=g03\n", encoding="utf-8"
    )
    if geometry_attrs is not None:
        with h5py.File(project_folder / "fixture.g03.hdf", "w") as hdf:
            group = hdf.create_group("Geometry")
            for name, value in geometry_attrs.items():
                group.attrs[name] = value.encode("utf-8")
    return project


def _forbid_launch(monkeypatch):
    def popen(*args, **kwargs):
        raise AssertionError("HEC-RAS must not be launched")

    monkeypatch.setattr(raspreprocess_module.subprocess, "Popen", popen)


_CHIPPEWA_ATTRS = {
    "Land Cover Filename": "..\\Chippewa\\Mannings_n.hdf",
    "Sediment Bed Material Filename": "..\\Chippewa\\Sediment Materials.hdf",
}


@pytest.mark.parametrize(
    ("version", "applies"),
    [("6.0", True), ("6.2", True), ("6.3", False), ("6.3.1", False),
     ("6.7 Beta 5", False), ("7.0.1", False), ("custom-build", True)],
)
def test_guard_applies_before_hec_ras_63(version, applies):
    exe = Path("C:/Program Files (x86)/HEC/HEC-RAS") / version / "Ras.exe"
    assert RasPreprocess._skips_geometry_without_land_classification(exe) is applies


def test_missing_files_do_not_block_hec_ras_63_and_later(tmp_path, monkeypatch):
    ras_obj = _seed_project(tmp_path, _CHIPPEWA_ATTRS, version="6.6")
    monkeypatch.setattr(
        RasPreprocess, "_tcu_supervision_availability_error", staticmethod(lambda: "stop-here")
    )

    result = RasPreprocess.preprocess_plan("01", ras_object=ras_obj)

    assert result.error == "stop-here"


def test_missing_referenced_files_fail_before_launch(tmp_path, monkeypatch):
    ras_obj = _seed_project(tmp_path, _CHIPPEWA_ATTRS)
    _forbid_launch(monkeypatch)

    result = RasPreprocess.preprocess_plan("01", ras_object=ras_obj)

    assert not result.success
    assert "land cover (Manning's n) '..\\Chippewa\\Mannings_n.hdf'" in result.error
    assert "sediment bed material '..\\Chippewa\\Sediment Materials.hdf'" in result.error
    assert "HEC-RAS 6.2 skips the geometry" in result.error
    assert result.geometry_number == "03"


def test_existing_referenced_files_are_not_reported(tmp_path):
    ras_obj = _seed_project(
        tmp_path,
        {
            "Land Cover Filename": ".\\Land\\Mannings_n.hdf",
            "Infiltration Filename": ".\\Land\\Infiltration.hdf",
        },
    )
    land = ras_obj.project_folder / "Land"
    land.mkdir()
    (land / "Mannings_n.hdf").write_bytes(b"")
    (land / "Infiltration.hdf").write_bytes(b"")

    assert RasPreprocess._missing_land_classification_files(
        ras_obj.project_folder / "fixture.g03.hdf"
    ) == []


def test_only_the_missing_file_is_reported(tmp_path):
    ras_obj = _seed_project(
        tmp_path,
        {
            "Land Cover Filename": ".\\Mannings_n.hdf",
            "Infiltration Filename": ".\\Infiltration.hdf",
        },
    )
    (ras_obj.project_folder / "Mannings_n.hdf").write_bytes(b"")

    missing = RasPreprocess._missing_land_classification_files(
        ras_obj.project_folder / "fixture.g03.hdf"
    )

    assert len(missing) == 1
    assert missing[0].startswith("infiltration '.\\Infiltration.hdf'")


def test_unset_associations_and_missing_or_unreadable_hdf_pass(tmp_path):
    ras_obj = _seed_project(tmp_path, {"Terrain Filename": ".\\Terrain\\missing.hdf"})
    geom_hdf = ras_obj.project_folder / "fixture.g03.hdf"

    # Terrain is not a land-classification association.
    assert RasPreprocess._missing_land_classification_files(geom_hdf) == []
    assert RasPreprocess._missing_land_classification_files(tmp_path / "absent.g01.hdf") == []

    unreadable = tmp_path / "broken.g01.hdf"
    unreadable.write_bytes(b"not an hdf file")
    assert RasPreprocess._missing_land_classification_files(unreadable) == []
