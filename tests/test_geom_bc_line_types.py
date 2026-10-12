"""Native BC classification authoring verifies current geometry and saves evidence."""

import json

import h5py
import numpy as np
import pytest

from ras_commander import GeomBcLines


def geometry(tmp_path):
    path = tmp_path / "Synthetic.g01"
    path.write_text(
        "BC Line Name=Outlet\nBC Line Storage Area=Synthetic\nBC Line Arc= 2\n"
        + f"{0.0:16.6f}{0.0:16.6f}{1.0:16.6f}{0.0:16.6f}\n"
    )
    hdf = path.with_suffix(".g01.hdf")
    with h5py.File(hdf, "w") as handle:
        group = handle.create_group("Geometry/Boundary Condition Lines")
        group.create_dataset(
            "Attributes",
            data=np.array(
                [(b"Outlet", b"Synthetic", b"Internal", 1.0)],
                dtype=[
                    ("Name", "S32"),
                    ("SA-2D", "S16"),
                    ("Type", "S9"),
                    ("Length", "f4"),
                ],
            ),
        )
        group.create_dataset("Polyline Info", data=[[0, 2, 0, 1]])
        group.create_dataset("Polyline Points", data=[[0.0, 0.0], [1.0, 0.0]])
        group.create_dataset("Polyline Parts", data=[[0, 2]])
    return path, hdf


def test_native_classification_changes_only_type_with_backup(tmp_path, monkeypatch):
    path, hdf = geometry(tmp_path)
    original = hdf.read_bytes()

    def native(install, target, *, bc_types_receipt):
        assert h5py.h5f.get_obj_count(types=h5py.h5f.OBJ_FILE) == 0
        with h5py.File(target, "r+") as handle:
            ds = handle["Geometry/Boundary Condition Lines/Attributes"]
            values = ds[()]
            values["Type"] = b"External"
            ds[...] = values
        bc_types_receipt.write_text(
            json.dumps(
                {
                    "lines": [
                        {
                            "index": 0,
                            "name": "Outlet",
                            "before": "Internal",
                            "after": "External",
                        }
                    ]
                }
            )
        )

    monkeypatch.setattr(
        "ras_commander._landcover_native._run_property_tables_worker", native
    )
    result = GeomBcLines.set_bc_line_types(
        path, {"Outlet": "External"}, hecras_dir=tmp_path
    )
    assert result["changed"] and result["bc_geometry_unchanged"]
    from pathlib import Path

    assert Path(result["backup_path"]).read_bytes() == original
    assert result["before_sha256"] != result["after_sha256"]


def test_stale_compiled_bc_coordinates_fail_before_native_work(tmp_path, monkeypatch):
    path, hdf = geometry(tmp_path)
    with h5py.File(hdf, "r+") as handle:
        handle["Geometry/Boundary Condition Lines/Polyline Points"][1] = [2.0, 0.0]
    monkeypatch.setattr(
        "ras_commander._landcover_native._run_property_tables_worker",
        lambda *a, **k: pytest.fail("native called on stale geometry"),
    )
    with pytest.raises(ValueError, match="not current"):
        GeomBcLines.set_bc_line_types(path, {"Outlet": "External"}, hecras_dir=tmp_path)


def test_native_bc_type_truncation_is_rejected(tmp_path, monkeypatch):
    path, _ = geometry(tmp_path)

    def truncated(install, target, *, bc_types_receipt):
        bc_types_receipt.write_text(
            json.dumps(
                {
                    "lines": [
                        {
                            "index": 0,
                            "name": "Outlet",
                            "before": "Internal",
                            "after": "External",
                        }
                    ]
                }
            )
        )

    monkeypatch.setattr(
        "ras_commander._landcover_native._run_property_tables_worker", truncated
    )
    with pytest.raises(RuntimeError, match="not persisted"):
        GeomBcLines.set_bc_line_types(path, {"Outlet": "External"}, hecras_dir=tmp_path)


def test_wrong_geometry_digest_fails_before_native_work(tmp_path):
    path, _ = geometry(tmp_path)
    with pytest.raises(ValueError, match="changed before"):
        GeomBcLines.set_bc_line_types(
            path,
            {"Outlet": "External"},
            hecras_dir=tmp_path,
            expected_geometry_sha256="0" * 64,
        )
