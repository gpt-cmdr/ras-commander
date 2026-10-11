"""Guarded native recovery of unchanged regional roughness input mappings."""

import hashlib
import shutil
from pathlib import Path
from uuid import uuid4

import h5py
import numpy as np

from ..RasUtils import RasUtils

GROUP = "Geometry/Land Cover (Manning's n)"
TABLE = GROUP + "/Calibration Table"
REGIONS = ("Attributes", "Polygon Info", "Polygon Parts", "Polygon Points")


def _mapping_signature(hdf):
    data = hdf[TABLE][:]
    if not data.dtype.names or any(
        data.dtype.fields[name][0].kind != "f"
        or data.dtype.fields[name][0].itemsize != 4
        for name in data.dtype.names[1:]
    ):
        raise ValueError("Calibration numeric columns must be native float32 values.")
    signature = {
        bytes(row[data.dtype.names[0]]).rstrip(b"\0"): tuple(
            np.float32(row[name]).tobytes() for name in data.dtype.names[1:]
        )
        for row in data
    }
    if len(signature) != len(data):
        raise ValueError("Calibration class names must be unique.")
    return signature


def _verify_region_write(before, child):
    """Permit native string widths and an empty area-name column only."""
    for name, expected in before.items():
        actual = child[GROUP + "/" + name][:]
        if name != "Attributes":
            if (
                actual.dtype != expected.dtype
                or actual.shape != expected.shape
                or actual.tobytes() != expected.tobytes()
            ):
                raise RuntimeError(f"Native recovery changed region geometry: {name}")
            continue
        if (
            actual.shape != expected.shape
            or not actual.dtype.names
            or not expected.dtype.names
        ):
            raise RuntimeError("Native recovery changed region attributes.")
        for field in expected.dtype.names:
            if field not in actual.dtype.names:
                raise RuntimeError("Native recovery removed a region attribute.")
            old, new = expected[field], actual[field]
            if old.dtype.kind == new.dtype.kind == "S":
                equal = old.tolist() == new.tolist()
            else:
                equal = old.dtype == new.dtype and old.tobytes() == new.tobytes()
            if not equal:
                raise RuntimeError("Native recovery changed a region attribute value.")
        added = set(actual.dtype.names) - set(expected.dtype.names)
        if added and (
            added != {"2D Area Name"}
            or actual["2D Area Name"].dtype.kind != "S"
            or any(actual["2D Area Name"].tolist())
        ):
            raise RuntimeError("Native recovery added unsupported region attributes.")


def restore_region_mappings(source: Path, target: Path, version: str) -> dict:
    """Restore only a missing table, rejecting any changed region or base override."""
    source, target = RasUtils.safe_resolve(source), RasUtils.safe_resolve(target)
    if source == target:
        raise ValueError("Source and target geometry HDFs must differ.")
    with h5py.File(source, "r") as original, h5py.File(target, "r") as child:
        if TABLE not in original or TABLE in child:
            raise ValueError(
                "Recovery requires a source calibration table and a missing target table."
            )
        data = original[TABLE][:]
        if len(data.dtype.names or ()) < 3 or not len(data):
            raise ValueError("Source must contain regional Manning mappings.")
        if not np.isnan(data[data.dtype.names[1]]).all():
            raise ValueError(
                "Recovery of finite base-table overrides is not supported."
            )
        for name in REGIONS:
            path = GROUP + "/" + name
            if path not in original or path not in child:
                raise ValueError(f"Missing native Manning region identity: {name}")
            before, after = original[path], child[path]
            if (
                before.shape != after.shape
                or before.dtype != after.dtype
                or before[:].tobytes() != after[:].tobytes()
            ):
                raise ValueError(f"Native Manning region identity differs: {name}")
        regions_before = {name: child[GROUP + "/" + name][:] for name in REGIONS}
        expected = _mapping_signature(original)
        if len(expected) != len(data):
            raise ValueError("Source calibration class names must be unique.")
        fields = data.dtype.names
        original_hash = hashlib.sha256(data.tobytes()).hexdigest()
    backup = target.with_name(target.name + f".mannings-recovery-{uuid4().hex[:8]}.bak")
    shutil.copy2(target, backup)
    from .._landcover_native import _run_property_tables_worker
    from ..dotnet.clr_bootstrap import find_hecras_install

    try:
        _run_property_tables_worker(
            find_hecras_install(version), target, calibration_source=source
        )
        with h5py.File(target, "r") as child:
            _verify_region_write(regions_before, child)
            if (
                TABLE not in child
                or child[TABLE].dtype.names != fields
                or _mapping_signature(child) != expected
            ):
                raise RuntimeError(
                    "Native regional Manning mappings do not match the source."
                )
            target_hash = hashlib.sha256(child[TABLE][:].tobytes()).hexdigest()
    except BaseException:
        shutil.copy2(backup, target)
        raise
    return {
        "source_geometry_hdf": str(source),
        "target_geometry_hdf": str(target),
        "backup_path": str(backup),
        "class_count": len(expected),
        "source_table_sha256": original_hash,
        "target_table_sha256": target_hash,
        "region_identity": "input polygon/attribute bytes exact; output polygons exact and attribute values preserved",
        "mapping_identity": "class names and float32 value bytes",
        "recompute_required": True,
    }
