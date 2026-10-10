"""Clearing infiltration on clone geometries preserves unrelated associations."""

import hashlib
import shutil

import h5py
import pytest

from ras_commander import RasMap
from ras_commander import _geometry_association as association
from ras_commander._geometry_association import (
    clear_geometry_infiltration,
    read_geometry_association,
)

INFILTRATION_ATTRS = (
    "Infiltration Filename",
    "Infiltration Layername",
    "Infiltration File Date",
)


def _geometry_file(path):
    with h5py.File(path, "w") as handle:
        geometry = handle.create_group("Geometry")
        for name, value in zip(INFILTRATION_ATTRS, ("infiltration.hdf", "SCS", "old")):
            geometry.attrs[name] = value
        geometry.create_dataset("Preserved", data=[1, 2, 3], compression="gzip")
    return path


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_clear_geometry_infiltration_is_selective_and_idempotent(tmp_path):
    path = tmp_path / "child.g02.hdf"
    with h5py.File(path, "w") as h:
        g = h.create_group("Geometry")
        for k, v in {
            "Terrain Filename": "terrain.hdf",
            "Land Cover Filename": "cover.hdf",
            "Infiltration Filename": "infiltration.hdf",
            "Infiltration Layername": "SCS",
            "Infiltration File Date": "old",
            "Other": "untouched",
        }.items():
            g.attrs[k] = v
    assert clear_geometry_infiltration(path) == path.resolve()
    assert not read_geometry_association(path).get("infiltration_hdf_path")
    with h5py.File(path) as h:
        assert dict(h["Geometry"].attrs) == {
            "Terrain Filename": "terrain.hdf",
            "Land Cover Filename": "cover.hdf",
            "Other": "untouched",
        }
    before_noop = _sha256(path)
    assert RasMap.clear_geometry_infiltration(str(path)) == path.resolve()
    assert _sha256(path) == before_noop


@pytest.mark.parametrize(
    "name", ["parent.p01.hdf", "parent.u01.hdf", "terrain.hdf", "project.g01"]
)
def test_clear_geometry_infiltration_rejects_non_geometry_before_open(name, tmp_path):
    with pytest.raises(ValueError, match="gNN"):
        clear_geometry_infiltration(tmp_path / name)


@pytest.mark.parametrize("link_kind", ["external", "soft_external", "soft_internal"])
def test_clear_geometry_infiltration_rejects_indirect_geometry_without_writes(
    tmp_path, monkeypatch, link_kind
):
    parent = _geometry_file(tmp_path / "parent.g01.hdf")
    child = tmp_path / "child.g02.hdf"
    with h5py.File(child, "w") as handle:
        if link_kind == "external":
            handle["Geometry"] = h5py.ExternalLink(parent.name, "/Geometry")
        elif link_kind == "soft_external":
            handle["Alias"] = h5py.ExternalLink(parent.name, "/Geometry")
            handle["Geometry"] = h5py.SoftLink("/Alias")
        else:
            handle.create_group("Alias").attrs[INFILTRATION_ATTRS[0]] = (
                "infiltration.hdf"
            )
            handle["Geometry"] = h5py.SoftLink("/Alias")
    before = {path: _sha256(path) for path in (parent, child)}
    real_file = h5py.File
    modes = []

    def record_mode(path, mode="r", *args, **kwargs):
        modes.append(mode)
        return real_file(path, mode, *args, **kwargs)

    monkeypatch.setattr(h5py, "File", record_mode)
    with pytest.raises(ValueError, match="direct.*owned.*group"):
        RasMap.clear_geometry_infiltration(child)
    assert modes == ["r"]
    assert {path: _sha256(path) for path in before} == before
    assert set(tmp_path.iterdir()) == {parent, child}


@pytest.mark.parametrize("layout", ["dataset", "missing", "non_hdf"])
def test_clear_geometry_infiltration_rejects_malformed_geometry(tmp_path, layout):
    path = tmp_path / "child.g02.hdf"
    if layout == "non_hdf":
        path.write_bytes(b"not HDF data")
    else:
        with h5py.File(path, "w") as handle:
            if layout == "dataset":
                handle.create_dataset("Geometry", data=[1, 2, 3])
    before = _sha256(path)
    error = {"dataset": ValueError, "missing": KeyError, "non_hdf": OSError}[layout]
    with pytest.raises(error):
        RasMap.clear_geometry_infiltration(path)
    assert _sha256(path) == before
    assert list(tmp_path.iterdir()) == [path]


def test_clear_geometry_infiltration_missing_file(tmp_path):
    path = tmp_path / "child.g02.hdf"
    with pytest.raises(FileNotFoundError):
        RasMap.clear_geometry_infiltration(path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("mask", range(8))
def test_clear_geometry_infiltration_clears_partial_associations(tmp_path, mask):
    parent = _geometry_file(tmp_path / "parent.g01.hdf")
    path = tmp_path / "child.g02.hdf"
    shutil.copy2(parent, path)
    with h5py.File(path, "r+") as handle:
        geometry = handle["Geometry"]
        geometry.attrs["Other"] = "untouched"
        for index, name in enumerate(INFILTRATION_ATTRS):
            if not mask & (1 << index):
                del geometry.attrs[name]
    before = _sha256(path)
    parent_before = _sha256(parent)
    assert RasMap.clear_geometry_infiltration(path) == path.resolve()
    assert _sha256(parent) == parent_before
    with h5py.File(path, "r") as handle:
        geometry = handle["Geometry"]
        assert dict(geometry.attrs) == {"Other": "untouched"}
        assert geometry["Preserved"][:].tolist() == [1, 2, 3]
        assert geometry["Preserved"].compression == "gzip"
    if mask == 0:
        assert _sha256(path) == before
    assert set(tmp_path.iterdir()) == {parent, path}


def test_clear_geometry_infiltration_copy_failure_preserves_original(
    tmp_path, monkeypatch
):
    path = _geometry_file(tmp_path / "child.g02.hdf")
    before = _sha256(path)

    def fail_copy(original_path, staged_path):
        assert original_path == path
        staged_path.write_bytes(b"incomplete staged copy")
        raise OSError("injected copy I/O failure")

    monkeypatch.setattr(association.shutil, "copy2", fail_copy)
    with pytest.raises(OSError, match="injected copy"):
        RasMap.clear_geometry_infiltration(path)
    assert _sha256(path) == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("failed_attr", INFILTRATION_ATTRS)
def test_clear_geometry_infiltration_delete_failure_preserves_original(
    tmp_path, monkeypatch, failed_attr
):
    path = _geometry_file(tmp_path / "child.g02.hdf")
    before = _sha256(path)
    real_delete = h5py.AttributeManager.__delitem__

    def fail_delete(attrs, name):
        if name == failed_attr:
            raise OSError("injected attribute-delete I/O failure")
        real_delete(attrs, name)

    monkeypatch.setattr(h5py.AttributeManager, "__delitem__", fail_delete)
    with pytest.raises(OSError, match="injected attribute-delete"):
        RasMap.clear_geometry_infiltration(path)
    assert _sha256(path) == before
    assert list(tmp_path.iterdir()) == [path]


def test_clear_geometry_infiltration_validation_failure_preserves_original(
    tmp_path, monkeypatch
):
    path = _geometry_file(tmp_path / "child.g02.hdf")
    before = _sha256(path)

    def fail_validation(staged_path):
        assert staged_path != path
        assert staged_path.parent == path.parent
        with h5py.File(staged_path, "r") as handle:
            assert all(
                name not in handle["Geometry"].attrs for name in INFILTRATION_ATTRS
            )
        raise OSError("injected validation I/O failure")

    monkeypatch.setattr(association, "read_geometry_association", fail_validation)
    with pytest.raises(OSError, match="injected validation"):
        RasMap.clear_geometry_infiltration(path)
    assert _sha256(path) == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("retained_attr", INFILTRATION_ATTRS)
def test_clear_geometry_infiltration_validates_every_attribute_before_replacement(
    tmp_path, monkeypatch, retained_attr
):
    path = _geometry_file(tmp_path / "child.g02.hdf")
    before = _sha256(path)
    real_delete = h5py.AttributeManager.__delitem__

    def retain_attribute(attrs, name):
        if name != retained_attr:
            real_delete(attrs, name)

    monkeypatch.setattr(h5py.AttributeManager, "__delitem__", retain_attribute)
    with pytest.raises(RuntimeError, match="remained after clearing"):
        RasMap.clear_geometry_infiltration(path)
    assert _sha256(path) == before
    assert list(tmp_path.iterdir()) == [path]


def test_clear_geometry_infiltration_replace_failure_preserves_original(
    tmp_path, monkeypatch
):
    path = _geometry_file(tmp_path / "child.g02.hdf")
    before = _sha256(path)

    def fail_replace(staged_path, original_path):
        assert original_path == path
        assert staged_path.parent == path.parent
        assert not read_geometry_association(staged_path)["infiltration_hdf_path"]
        raise OSError("injected replace I/O failure")

    monkeypatch.setattr(association.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected replace"):
        RasMap.clear_geometry_infiltration(path)
    assert _sha256(path) == before
    assert list(tmp_path.iterdir()) == [path]
