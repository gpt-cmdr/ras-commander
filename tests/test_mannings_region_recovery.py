"""HDF identity guards and rollback for source regional mapping recovery."""

import h5py
import numpy as np
import pytest

import ras_commander._landcover_native as native
import ras_commander.dotnet.clr_bootstrap as bootstrap
from ras_commander import GeomLandCover
from ras_commander.geom._mannings_region_recovery import GROUP, TABLE


def fixture(tmp_path):
    source, target = [tmp_path / name for name in ("source.g01.hdf", "target.g02.hdf")]
    for path in (source, target):
        with h5py.File(path, "w") as h:
            h.attrs["Complete Geometry"] = False
            h.create_dataset(
                "Geometry/2D Flow Areas/Test/Cells Minimum Elevation",
                data=np.array([1.0, np.nan], dtype="f4"),
            )
            h.create_dataset(
                "Unrelated Text", data=["preserved"], dtype=h5py.string_dtype()
            )
            group = h.create_group(GROUP)
            group.create_dataset(
                "Attributes", data=np.array([(b"Region",)], dtype=[("Name", "S32")])
            )
            for name in (
                "Polygon Info",
                "Polygon Parts",
                "Polygon Points",
            ):
                group.create_dataset(name, data=np.array([[1, 2]], dtype="f8"))
    dtype = [
        ("Land Cover Name", "S32"),
        ("Base Manning's n Value", "f4"),
        ("Region", "f4"),
    ]
    with h5py.File(source, "r+") as h:
        h.create_dataset(TABLE, data=np.array([(b"Forest", np.nan, 0.06)], dtype=dtype))
    return source, target


def test_changed_regions_refuse_without_mutation(tmp_path):
    source, target = fixture(tmp_path)
    with h5py.File(target, "r+") as h:
        h[GROUP + "/Polygon Points"][0, 0] = 5
    before = target.read_bytes()
    with pytest.raises(ValueError, match="region identity differs"):
        GeomLandCover.restore_mannings_region_mappings(source, target)
    assert target.read_bytes() == before
    assert not list(tmp_path.glob("*.bak"))


def test_finite_base_override_refuses_without_mutation(tmp_path):
    source, target = fixture(tmp_path)
    with h5py.File(source, "r+") as h:
        data = h[TABLE][:]
        data["Base Manning's n Value"] = 0.04
        h[TABLE][:] = data
    before = target.read_bytes()
    with pytest.raises(ValueError, match="finite base-table overrides"):
        GeomLandCover.restore_mannings_region_mappings(source, target)
    assert target.read_bytes() == before


@pytest.mark.parametrize(
    "failure",
    [
        "exception",
        "wrong_value",
        "duplicate",
        "float64",
        "polygon",
        "attribute",
        "completion",
        "hydraulics",
        "inventory",
        "text",
    ],
)
def test_native_failure_rolls_back_exact_target_bytes(tmp_path, monkeypatch, failure):
    source, target = fixture(tmp_path)
    before = target.read_bytes()
    monkeypatch.setattr(bootstrap, "find_hecras_install", lambda _: tmp_path)

    def run(install, geometry, **kwargs):
        with h5py.File(geometry, "r+") as child, h5py.File(source, "r") as original:
            data = original[TABLE][:]
            if failure == "duplicate":
                data = np.concatenate([data, data])
            elif failure == "float64":
                data = data.astype(
                    [
                        (name, "S32" if index == 0 else "f8")
                        for index, name in enumerate(data.dtype.names)
                    ]
                )
            elif failure not in (
                "polygon",
                "attribute",
                "completion",
                "hydraulics",
                "inventory",
                "text",
            ):
                data["Region"] = 0.9
            child.create_dataset(TABLE, data=data)
            if failure == "polygon":
                child[GROUP + "/Polygon Points"][0, 0] = 3
            if failure == "attribute":
                child[GROUP + "/Attributes"][0] = (b"Changed",)
            if failure == "completion":
                child.attrs["Complete Geometry"] = True
            if failure == "hydraulics":
                child["Geometry/2D Flow Areas/Test/Cells Minimum Elevation"][0] = 99
            if failure == "inventory":
                child.create_dataset("Unexpected", data=[1])
            if failure == "text":
                child["Unrelated Text"][0] = "changed"
        if failure == "exception":
            raise RuntimeError("native failure")

    monkeypatch.setattr(native, "_run_property_tables_worker", run)
    with pytest.raises((RuntimeError, ValueError)):
        GeomLandCover.restore_mannings_region_mappings(source, target)
    assert target.read_bytes() == before
    assert len(list(tmp_path.glob("*.bak"))) == 1


def test_float64_source_refuses_without_mutation(tmp_path):
    source, target = fixture(tmp_path)
    with h5py.File(source, "r+") as h:
        data = h[TABLE][:].astype(
            [
                ("Land Cover Name", "S32"),
                ("Base Manning's n Value", "f8"),
                ("Region", "f8"),
            ]
        )
        del h[TABLE]
        h.create_dataset(TABLE, data=data)
    before = target.read_bytes()
    with pytest.raises(ValueError, match="float32"):
        GeomLandCover.restore_mannings_region_mappings(source, target)
    assert target.read_bytes() == before
    assert not list(tmp_path.glob("*.bak"))


def test_native_narrower_name_storage_preserves_source_value_bits(
    tmp_path, monkeypatch
):
    source, target = fixture(tmp_path)
    source_before = source.read_bytes()
    monkeypatch.setattr(bootstrap, "find_hecras_install", lambda _: tmp_path)

    def run(install, geometry, **kwargs):
        dtype = [
            ("Land Cover Name", "S28"),
            ("Base Manning's n Value", "f4"),
            ("Region", "f4"),
        ]
        with h5py.File(geometry, "r+") as h:
            del h[GROUP + "/Attributes"]
            h.create_dataset(
                GROUP + "/Attributes",
                data=np.array(
                    [(b"Region", b"")], dtype=[("Name", "S6"), ("2D Area Name", "S1")]
                ),
            )
            h.create_dataset(
                TABLE, data=np.array([(b"Forest", np.nan, 0.06)], dtype=dtype)
            )

    monkeypatch.setattr(native, "_run_property_tables_worker", run)
    report = GeomLandCover.restore_mannings_region_mappings(str(source), str(target))
    assert report["class_count"] == 1
    assert report["recompute_required"]
    assert report["source_table_sha256"] != report["target_table_sha256"]
    assert source.read_bytes() == source_before
    with pytest.raises(ValueError, match="missing target table"):
        GeomLandCover.restore_mannings_region_mappings(source, target)
