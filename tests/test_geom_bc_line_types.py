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
    # Python 3.10 does not provide hashlib.file_digest.
    monkeypatch.delattr("hashlib.file_digest", raising=False)
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

    monkeypatch.setattr("ras_commander._landcover_native._run_property_tables_worker", native)
    result = GeomBcLines.set_bc_line_types(path, {"Outlet": "External"}, hecras_dir=tmp_path)
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

    monkeypatch.setattr("ras_commander._landcover_native._run_property_tables_worker", truncated)
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


def test_matching_types_preserve_exact_hdf_without_native_writer(tmp_path, monkeypatch):
    path, hdf = geometry(tmp_path)
    original = hdf.read_bytes()
    monkeypatch.setattr(
        "ras_commander._landcover_native._run_property_tables_worker",
        lambda *args, **kwargs: pytest.fail("no-op must not rewrite native attributes"),
    )
    result = GeomBcLines.set_bc_line_types(path, {"Outlet": "Internal"}, hecras_dir=tmp_path)
    assert result["changed"] is False
    assert result["backup_path"] is None
    assert result["before_sha256"] == result["after_sha256"]
    assert hdf.read_bytes() == original


@pytest.mark.parametrize(
    "defect", [None, "name", "length", "unknown_field", "polyline", "worker_error", "receipt"]
)
def test_native_compact_export_preserves_original_input_schema_or_rolls_back(
    tmp_path, monkeypatch, defect
):
    path, hdf = geometry(tmp_path)
    with h5py.File(hdf, "r+") as handle:
        ds = handle["Geometry/Boundary Condition Lines/Attributes"]
        ds.attrs["units"] = "feet"
        before = ds[()]
        if defect == "unknown_field":
            group = handle["Geometry/Boundary Condition Lines"]
            del group["Attributes"]
            group.create_dataset(
                "Attributes",
                data=np.array(
                    [(b"Outlet", b"Synthetic", b"Internal", 1.0, 2.0)],
                    dtype=[
                        ("Name", "S32"),
                        ("SA-2D", "S16"),
                        ("Type", "S9"),
                        ("Length", "f4"),
                        ("Unknown Quantity", "f8"),
                    ],
                ),
            )
    original = hdf.read_bytes()

    def native(install, target, *, bc_types_receipt):
        with h5py.File(target, "r+") as handle:
            group = handle["Geometry/Boundary Condition Lines"]
            del group["Attributes"]
            fields = [("Name", "S6"), ("SA-2D", "S9"), ("Type", "S8")]
            values = [b"Altered" if defect == "name" else b"Outlet", b"Synthetic", b"External"]
            if defect == "length":
                fields.append(("Length", "f4"))
                values.append(2.0)
            group.create_dataset("Attributes", data=np.array([tuple(values)], dtype=fields))
            if defect == "polyline":
                group["Polyline Points"][1] = [2.0, 0.0]
        if defect == "worker_error":
            raise RuntimeError("native worker failed after writing")
        bc_types_receipt.write_text(
            json.dumps(
                {
                    "lines": [
                        {"index": 0, "name": "Outlet", "before": "Internal", "after": "External"}
                    ]
                }
            )
        )

    monkeypatch.setattr("ras_commander._landcover_native._run_property_tables_worker", native)
    if defect == "receipt":
        from pathlib import Path

        write_text = Path.write_text

        def fail_final_receipt(target, data, *args, **kwargs):
            if '"attribute_schema_preserved"' in data:
                raise RuntimeError("final receipt publication failed")
            return write_text(target, data, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", fail_final_receipt)
    if defect:
        with pytest.raises(RuntimeError):
            GeomBcLines.set_bc_line_types(path, {"Outlet": "External"}, hecras_dir=tmp_path)
        assert hdf.read_bytes() == original
    else:
        result = GeomBcLines.set_bc_line_types(path, {"Outlet": "External"}, hecras_dir=tmp_path)
        assert result["changed"] and result["attribute_schema_preserved"]
        assert result["native_attribute_fields"] == ["Name", "SA-2D", "Type"]
        with h5py.File(hdf, "r") as handle:
            ds = handle["Geometry/Boundary Condition Lines/Attributes"]
            after = ds[()]
            assert ds.dtype == before.dtype
            assert ds.attrs["units"] == "feet"
            for field in ("Name", "SA-2D", "Length"):
                assert after[field].tobytes() == before[field].tobytes()
            assert bytes(after["Type"][0]) == b"External"


def two_line_geometry(tmp_path):
    def block(name, y):
        return (
            f"BC Line Name={name}\nBC Line Storage Area=Synthetic\nBC Line Arc= 2\n"
            + f"{0.0:16.6f}{y:16.6f}{1.0:16.6f}{y:16.6f}\n"
        )

    path = tmp_path / "Synthetic.g01"
    path.write_text(block("Outlet", 0.0) + block("Inlet", 1.0))
    hdf = path.with_suffix(".g01.hdf")
    with h5py.File(hdf, "w") as handle:
        group = handle.create_group("Geometry/Boundary Condition Lines")
        ds = group.create_dataset(
            "Attributes",
            data=np.array(
                [
                    (b"Outlet", b"Synthetic", b"Internal", 1.0),
                    (b"Inlet", b"Synthetic", b"Internal", 1.0),
                ],
                dtype=[("Name", "S32"), ("SA-2D", "S16"), ("Type", "S9"), ("Length", "f4")],
            ),
        )
        ds.attrs["units"] = "feet"
        group.create_dataset("Polyline Info", data=[[0, 2, 0, 1], [2, 2, 1, 1]])
        group.create_dataset("Polyline Parts", data=[[0, 2], [2, 2]])
        group.create_dataset(
            "Polyline Points", data=[[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]
        )
    return path, hdf


def native_all_rows(defect=None):
    """Double of _property_tables_worker --bc-types: it visits every feature."""

    def native(install, target, *, bc_types_receipt):
        requested = json.loads(bc_types_receipt.read_text())["line_types"]
        if defect == "unrequested":
            requested = {**requested, "Inlet": "External"}
        lines = []
        with h5py.File(target, "r+") as handle:
            ds = handle["Geometry/Boundary Condition Lines/Attributes"]
            values = ds[()]
            for index, row in enumerate(values):
                name = row["Name"].decode()
                before = row["Type"].decode()
                after = requested.get(name, before)
                values["Type"][index] = after.encode()
                lines.append({"index": index, "name": name, "before": before, "after": after})
            if defect == "silent_unrequested":
                values["Type"][1] = b"External"
            ds[...] = values
        if defect == "omit_untouched":
            lines = [row for row in lines if row["name"] in requested]
        bc_types_receipt.write_text(json.dumps({"lines": lines}))

    return native


def test_subset_map_changes_requested_line_and_preserves_untouched(tmp_path, monkeypatch):
    path, hdf = two_line_geometry(tmp_path)
    original = hdf.read_bytes()
    monkeypatch.setattr(
        "ras_commander._landcover_native._run_property_tables_worker", native_all_rows()
    )
    result = GeomBcLines.set_bc_line_types(path, {"Outlet": "External"}, hecras_dir=tmp_path)
    assert result["changed"] and result["attribute_schema_preserved"]
    assert result["lines"] == [
        {"index": 0, "name": "Outlet", "before": "Internal", "after": "External"},
        {"index": 1, "name": "Inlet", "before": "Internal", "after": "Internal"},
    ]
    from pathlib import Path

    assert Path(result["backup_path"]).read_bytes() == original
    with h5py.File(hdf, "r") as handle:
        ds = handle["Geometry/Boundary Condition Lines/Attributes"]
        assert [bytes(v).rstrip(b"\x00") for v in ds["Type"]] == [b"External", b"Internal"]
        assert ds.attrs["units"] == "feet"
        assert ds["Length"].tolist() == [1.0, 1.0]


def test_subset_no_op_lists_every_line_without_native_writer(tmp_path, monkeypatch):
    path, hdf = two_line_geometry(tmp_path)
    original = hdf.read_bytes()
    monkeypatch.setattr(
        "ras_commander._landcover_native._run_property_tables_worker",
        lambda *args, **kwargs: pytest.fail("no-op must not rewrite native attributes"),
    )
    result = GeomBcLines.set_bc_line_types(path, {"Inlet": "Internal"}, hecras_dir=tmp_path)
    assert result["changed"] is False
    assert [row["name"] for row in result["lines"]] == ["Outlet", "Inlet"]
    assert all(row["before"] == row["after"] for row in result["lines"])
    assert hdf.read_bytes() == original


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("unrequested", "receipt differs"),
        ("silent_unrequested", "not persisted"),
        ("omit_untouched", "receipt differs"),
    ],
)
def test_native_change_to_unrequested_line_rolls_back(tmp_path, monkeypatch, defect, message):
    path, hdf = two_line_geometry(tmp_path)
    original = hdf.read_bytes()
    monkeypatch.setattr(
        "ras_commander._landcover_native._run_property_tables_worker", native_all_rows(defect)
    )
    with pytest.raises(RuntimeError, match=message):
        GeomBcLines.set_bc_line_types(path, {"Outlet": "External"}, hecras_dir=tmp_path)
    assert hdf.read_bytes() == original
