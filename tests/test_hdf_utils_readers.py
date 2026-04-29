from datetime import datetime
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from ras_commander.hdf.HdfBenefitAreas import HdfBenefitAreas
from ras_commander.hdf.HdfChannelCapacity import HdfChannelCapacity
from ras_commander.hdf.HdfResultsPlan import HdfResultsPlan
from ras_commander.hdf.HdfUtils import (
    HdfAttributeSpec,
    HdfFieldSpec,
    HdfPathSpec,
    HdfUtils,
    HdfRaggedTableSpec,
    HdfTableSpec,
    HdfTimeAxisSpec,
)


class FakeHdfRasProject:
    def __init__(self, project_folder: Path, project_name: str = "TestProject"):
        self.folder = Path(project_folder)
        self.project_folder = Path(project_folder)
        self.project_name = project_name
        self.plan_df = pd.DataFrame(
            [
                {
                    "plan_number": "01",
                    "geometry_number": "01",
                    "Geom File": "g01",
                    "Geom Path": str(self.project_folder / f"{project_name}.g01"),
                    "full_path": str(self.project_folder / f"{project_name}.p01"),
                    "HDF_Results_Path": str(self.project_folder / f"{project_name}.p01.hdf"),
                }
            ]
        )
        self.geom_df = pd.DataFrame(
            [
                {
                    "geom_number": "01",
                    "full_path": str(self.project_folder / f"{project_name}.g01"),
                    "hdf_path": str(self.project_folder / f"{project_name}.g01.hdf"),
                }
            ]
        )

    def check_initialized(self):
        return None


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def test_read_attrs_decodes_bytes_and_maps_fields(tmp_path):
    hdf_path = tmp_path / "attrs.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        group = hdf.create_group("Plan Data/Plan Information")
        group.attrs["Plan Name"] = b"Base"
        group.attrs["Run Count"] = 3

    with h5py.File(hdf_path, "r") as hdf:
        attrs = HdfUtils.read_attrs(
            hdf,
            HdfAttributeSpec(
                HdfPathSpec("Plan Data/Plan Information"),
                fields=(
                    HdfFieldSpec("Plan Name", "plan_name"),
                    HdfFieldSpec("Run Count", "run_count"),
                    HdfFieldSpec("Missing", "missing", default="fallback"),
                ),
            ),
        )

    assert attrs == {
        "plan_name": "Base",
        "run_count": 3,
        "missing": "fallback",
    }


def test_read_compound_table_decodes_byte_columns(tmp_path):
    hdf_path = tmp_path / "table.hdf"
    dtype = np.dtype([("Name", "S10"), ("Value", "f8")])
    data = np.array([(b"Class A", 1.5), (b"Class B", 2.5)], dtype=dtype)
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_dataset("Raster Map", data=data)

    with h5py.File(hdf_path, "r") as hdf:
        table = HdfUtils.read_compound_table(
            hdf,
            HdfTableSpec(HdfPathSpec("//Raster Map", aliases=("Raster Map",))),
        )

    assert table["Name"].tolist() == ["Class A", "Class B"]
    assert table["Value"].tolist() == [1.5, 2.5]


def test_read_ragged_table_expands_info_values(tmp_path):
    hdf_path = tmp_path / "ragged.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_dataset("Info", data=np.array([[0, 2], [2, 1]], dtype="i4"))
        hdf.create_dataset(
            "Values",
            data=np.array([[0.0, 10.0], [1.0, 11.0], [2.0, 12.0]], dtype="f8"),
        )

    with h5py.File(hdf_path, "r") as hdf:
        table = HdfUtils.read_ragged_table(
            hdf,
            HdfRaggedTableSpec(
                HdfPathSpec("Info"),
                HdfPathSpec("Values"),
                id_column="feature_id",
                value_columns=("station", "elevation"),
            ),
        )

    assert table.to_dict("records") == [
        {"feature_id": 0, "station": 0.0, "elevation": 10.0},
        {"feature_id": 0, "station": 1.0, "elevation": 11.0},
        {"feature_id": 1, "station": 2.0, "elevation": 12.0},
    ]


def test_read_time_axis_from_timestamp_path(tmp_path):
    hdf_path = tmp_path / "time.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_dataset(
            "Time Date Stamp (ms)",
            data=np.array([b"2026-01-01 00:00:00", b"2026-01-01 01:00:00"]),
        )

    with h5py.File(hdf_path, "r") as hdf:
        index = HdfUtils.read_time_axis(
            hdf,
            HdfTimeAxisSpec(timestamp_path=HdfPathSpec("Time Date Stamp (ms)")),
        )

    assert isinstance(index, pd.DatetimeIndex)
    assert list(index.hour) == [0, 1]


def test_hdf_results_plan_attribute_readers_use_decoded_attrs(tmp_path):
    hdf_path = tmp_path / "plan.p01.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        unsteady = hdf.create_group("Results/Unsteady")
        unsteady.attrs["Program Name"] = b"RAS"
        summary = hdf.create_group("Results/Unsteady/Summary")
        summary.attrs["Solution"] = b"Complete"
        volume = hdf.create_group("Results/Unsteady/Summary/Volume Accounting")
        volume.attrs["Error"] = b"0.0"

        steady = hdf.create_group("Results/Steady")
        output = hdf.create_group("Results/Steady/Output")
        output.attrs["Solution"] = b"Steady Finished Successfully"
        hdf.create_group("Results/Steady/Summary").attrs["Profiles"] = 1
        plan_info = hdf.create_group("Plan Data/Plan Information")
        plan_info.attrs["Flow Filename"] = b"test.f01"
        plan_info.attrs["Flow Title"] = b"Base Flow"

    assert HdfResultsPlan.get_unsteady_info(hdf_path)["Program Name"].iloc[0] == "RAS"
    assert HdfResultsPlan.get_unsteady_summary(hdf_path)["Solution"].iloc[0] == "Complete"
    assert HdfResultsPlan.get_volume_accounting(hdf_path)["Error"].iloc[0] == "0.0"

    steady_info = HdfResultsPlan.get_steady_info(hdf_path)
    assert steady_info["Solution"].iloc[0] == "Steady Finished Successfully"
    assert steady_info["Flow Filename"].iloc[0] == "test.f01"


def test_hdf_plan_formats_timestamps_for_rasmapper(monkeypatch, tmp_path):
    from ras_commander.hdf.HdfPlan import HdfPlan

    hdf_path = tmp_path / "plan.p01.hdf"
    hdf_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        HdfPlan,
        "get_plan_timestamps_list",
        staticmethod(
            lambda path: [
                datetime(2026, 1, 2, 3, 4, 5),
                datetime(2026, 9, 10, 12, 30, 0),
            ]
        ),
    )

    assert HdfPlan.get_plan_timestamps_rasmapper(hdf_path) == [
        "02JAN2026 03:04:05",
        "10SEP2026 12:30:00",
    ]


def test_resolve_hdf_input_uses_plan_assets_for_plan_selectors(tmp_path):
    ras = FakeHdfRasProject(tmp_path)
    expected = _touch(tmp_path / "TestProject.p01.hdf")

    assert HdfUtils.resolve_hdf_input("01", ras_object=ras, hdf_kind="plan") == expected
    assert HdfUtils.resolve_hdf_input("p01", ras_object=ras, hdf_kind="plan") == expected
    assert HdfBenefitAreas._standardize_hdf_input("01", "existing", ras) == expected


def test_resolve_hdf_input_uses_geometry_assets_for_geometry_selectors(tmp_path):
    ras = FakeHdfRasProject(tmp_path)
    expected = _touch(tmp_path / "TestProject.g01.hdf")

    assert HdfUtils.resolve_hdf_input("01", ras_object=ras, hdf_kind="geometry") == expected
    assert HdfUtils.resolve_hdf_input("g01", ras_object=ras, hdf_kind="geometry") == expected
    assert HdfChannelCapacity._standardize_hdf_input("01", "geometry", ras) == expected


def test_resolve_hdf_input_resolves_project_local_filenames(tmp_path):
    ras = FakeHdfRasProject(tmp_path)

    assert (
        HdfUtils.resolve_hdf_input("NamedPlan.p02.hdf", ras_object=ras)
        == tmp_path / "NamedPlan.p02.hdf"
    )


def test_resolve_hdf_input_preserves_direct_paths_without_project(tmp_path):
    hdf_path = _touch(tmp_path / "direct.p01.hdf")

    assert HdfUtils.resolve_hdf_input(hdf_path) == hdf_path
