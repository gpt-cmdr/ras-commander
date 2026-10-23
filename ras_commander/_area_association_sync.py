"""Synchronize selected compiled area caches with current geometry associations."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

import h5py

from ._geometry_association import (
    GEOMETRY_ASSOCIATION_FIELDS,
    decode_hdf_attr,
    is_plan_or_result_hdf,
    resolve_association_attr_path,
)


def _sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plan(geometry_hdf, mesh_names):
    path = Path(geometry_hdf).resolve(strict=True)
    if is_plan_or_result_hdf(path):
        raise ValueError("Expected a compiled geometry-only HDF, not a plan/result HDF")
    before = _sha(path)
    if mesh_names is not None and (
        isinstance(mesh_names, str)
        or not mesh_names
        or len(set(mesh_names)) != len(mesh_names)
    ):
        raise ValueError("mesh_names must be a nonempty sequence of unique names")
    changes = []
    with h5py.File(path, "r") as hdf:
        if (
            "Results" in hdf
            or "Event Conditions" in hdf
            or "Geometry/2D Flow Areas" not in hdf
        ):
            raise ValueError("Expected a compiled geometry-only HDF with 2D areas")
        geometry = hdf["Geometry"]
        areas = geometry["2D Flow Areas"]
        available = sorted(
            name for name, obj in areas.items() if isinstance(obj, h5py.Group)
        )
        names = available if mesh_names is None else list(mesh_names)
        if not names or set(names) - set(available):
            raise ValueError(
                "Every requested mesh must be an existing compiled 2D area"
            )
        families = [
            (v["filename_attr"], v["layer_attr"])
            for v in GEOMETRY_ASSOCIATION_FIELDS.values()
        ]
        families.append(("Percent Impervious Filename", "Percent Impervious Layername"))
        for filename, layer in families:
            canonical = decode_hdf_attr(geometry.attrs.get(filename))
            if not canonical:
                # Preserve area-only associations when no geometry-wide slot exists.
                continue
            associated = resolve_association_attr_path(path, canonical)
            if not associated.is_file():
                raise FileNotFoundError(
                    f"Current geometry association is missing: {associated}"
                )
            for name in names:
                for key in (filename, layer):
                    old = decode_hdf_attr(areas[name].attrs.get(key))
                    new = decode_hdf_attr(geometry.attrs.get(key))
                    if old != new:
                        changes.append(
                            {
                                "mesh_name": name,
                                "attribute": key,
                                "before": old,
                                "after": new,
                            }
                        )
    if _sha(path) != before:
        raise RuntimeError("Geometry changed during area-association planning")
    return {
        "schema": "ras-area-association-sync/v1",
        "geometry_hdf": str(path),
        "geometry_sha256": before,
        "mesh_names": names,
        "changes": changes,
    }


def _apply(plan):
    from .geom.GeomParser import GeomParser

    if (
        not isinstance(plan, dict)
        or plan.get("schema") != "ras-area-association-sync/v1"
    ):
        raise ValueError("Expected an area-association synchronization plan")
    path = Path(plan["geometry_hdf"])
    if _plan(path, plan["mesh_names"]) != plan:
        raise RuntimeError("Geometry or area-association plan changed after planning")
    if not plan["changes"]:
        return {
            **plan,
            "status": "unchanged",
            "geometry_sha256_after": plan["geometry_sha256"],
        }
    with tempfile.TemporaryDirectory(
        prefix=".ras-area-associations-", dir=path.parent
    ) as scratch:
        staged = Path(scratch) / path.name
        shutil.copy2(path, staged)
        with h5py.File(staged, "r+") as hdf:
            geometry = hdf["Geometry"]
            for change in plan["changes"]:
                area = geometry["2D Flow Areas"][change["mesh_name"]]
                key = change["attribute"]
                if key in geometry.attrs:
                    area.attrs[key] = geometry.attrs[key]
                elif key in area.attrs:
                    del area.attrs[key]
            for change in plan["changes"]:
                actual = decode_hdf_attr(
                    geometry["2D Flow Areas"][change["mesh_name"]].attrs.get(
                        change["attribute"]
                    )
                )
                if actual != change["after"]:
                    raise RuntimeError(
                        "Staged area association readback differs from plan"
                    )
        if _sha(path) != plan["geometry_sha256"]:
            raise RuntimeError("Geometry changed before area-association application")
        backup = GeomParser.create_backup(path)
        staged.replace(path)
    return {
        **plan,
        "status": "applied",
        "backup": str(backup),
        "geometry_sha256_after": _sha(path),
    }
