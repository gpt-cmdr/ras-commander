"""Mesh-area-name reading on 1D-only HEC-RAS geometry.

Regression cover for eBFE study 12070203 (Lampasas). Every one of that
delivery's 825 ``.g01.hdf`` geometries logged

    ras_commander.hdf.HdfMesh - ERROR - Error reading mesh area names ...
    KeyError: "Unable to synchronously open object (object 'Attributes' doesn't exist)"

because HEC-RAS 5.0.5 writes ``Geometry/2D Flow Areas`` as an EMPTY PLACEHOLDER
group in a 1D-only geometry, exactly as it writes empty ``River Flow Paths`` and
``River Stationing`` groups beside it. The reader treated the group's presence as
a promise that an ``Attributes`` dataset existed, and reported "no mesh areas"
from an exception handler rather than from a determination.

The fixtures below transcribe the group skeleton and attribute values measured
from a real file in that delivery --
``Model/T101_Models/Gholson Creek/GholsonCreek.g01.hdf`` inside
``12070203_Models.zip`` -- rather than inventing a minimal 2D-flow-area layout.
"""

from pathlib import Path
import logging

import h5py
import numpy as np
import pytest

from ras_commander.hdf import HdfMesh


# Measured from GholsonCreek.g01.hdf: the root attributes HEC-RAS 5.0.5 writes.
REAL_FILE_VERSION = b"HEC-RAS 5.0.5 June 2018"
REAL_PROJECTION = (
    b'PROJCS["NAD_1983_StatePlane_Texas_Central_FIPS_4203_Feet",'
    b'GEOGCS["GCS_North_American_1983",DATUM["D_North_American_1983",'
    b'SPHEROID["GRS_1980",6378137.0,298.257222101]],PRIMEM["Greenwich",0.0],'
    b'UNIT["Degree",0.0174532925199433]],PROJECTION["Lambert_Conformal_Conic"],'
    b'PARAMETER["False_Easting",2296583.333333333],'
    b'PARAMETER["False_Northing",9842500.0],'
    b'PARAMETER["Central_Meridian",-100.3333333333333],'
    b'PARAMETER["Standard_Parallel_1",30.11666666666667],'
    b'PARAMETER["Standard_Parallel_2",31.88333333333333],'
    b'PARAMETER["Latitude_Of_Origin",29.66666666666667],'
    b'UNIT["Foot_US",0.3048006096012192]]'
)

# Measured dtype of Geometry/Cross Sections/Attributes, truncated to the fields
# that identify it as a real 1D cross-section table.
REAL_XS_DTYPE = np.dtype(
    [
        ("River", "S16"),
        ("Reach", "S16"),
        ("RS", "S8"),
        ("Name", "S16"),
        ("Len Channel", "<f4"),
        ("Left Bank", "<f4"),
        ("Right Bank", "<f4"),
    ]
)


def _write_1d_geometry(path: Path, *, include_flow_areas_group: bool) -> Path:
    """Write the measured HEC-RAS 5.0.5 1D-only geometry skeleton.

    ``include_flow_areas_group`` chooses between the two shapes the delivery
    actually contains: most of its geometries carry the empty placeholder group
    and the rest omit it entirely. Both are well-formed statements that the
    model has no 2D flow areas.
    """
    with h5py.File(path, "w") as hdf:
        hdf.attrs["File Type"] = np.bytes_(b"HEC-RAS Geometry")
        hdf.attrs["File Version"] = np.bytes_(REAL_FILE_VERSION)
        hdf.attrs["Projection"] = np.bytes_(REAL_PROJECTION)
        hdf.attrs["Units System"] = np.bytes_(b"US Customary")

        geometry = hdf.create_group("Geometry")
        geometry.attrs["Complete Geometry"] = np.int32(1)
        geometry.attrs["Title"] = np.bytes_(b"GholsonCreek")
        geometry.attrs["Version"] = np.bytes_(b"5.00")

        if include_flow_areas_group:
            # The defect: present, empty, and carrying no Attributes dataset.
            geometry.create_group("2D Flow Areas")

        cross_sections = geometry.create_group("Cross Sections")
        cross_sections.create_dataset(
            "Attributes",
            data=np.array(
                [
                    (b"Gholson Creek", b"Reach 1", b"4500", b"4500", 1200.0, 45.0, 310.0),
                    (b"Gholson Creek", b"Reach 1", b"3300", b"3300", 1100.0, 60.0, 295.0),
                ],
                dtype=REAL_XS_DTYPE,
            ),
        )
        geometry.create_group("River Centerlines")

        # 5.0.5 writes these two as empty placeholder groups in the same file.
        # They are why an empty group cannot be read as a malformed group.
        geometry.create_group("River Flow Paths")
        geometry.create_group("River Stationing")
    return path


def _write_2d_geometry(path: Path, names: list) -> Path:
    """Write a geometry whose 2D Flow Areas carry a real Attributes table."""
    attrs_dtype = np.dtype([("Name", "S32"), ("Cell Count", "<i4")])
    rows = np.array(
        [(name.encode("utf-8"), 100 + index) for index, name in enumerate(names)],
        dtype=attrs_dtype,
    )
    with h5py.File(path, "w") as hdf:
        hdf.attrs["File Type"] = np.bytes_(b"HEC-RAS Geometry")
        hdf.create_dataset("Geometry/2D Flow Areas/Attributes", data=rows)
        for name in names:
            hdf.create_group(f"Geometry/2D Flow Areas/{name}")
    return path


def _errors(caplog) -> list:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.ERROR
    ]


def test_empty_placeholder_group_is_not_an_error(tmp_path, caplog):
    """The 12070203 shape: empty group, zero areas, and no error logged.

    Before the fix this returned the same empty list, but from an exception
    handler, and logged an ERROR for every model in the study.
    """
    path = _write_1d_geometry(
        tmp_path / "GholsonCreek.g01.hdf", include_flow_areas_group=True
    )

    with caplog.at_level(logging.ERROR, logger="ras_commander"):
        assert HdfMesh.get_mesh_area_names(path) == []

    assert _errors(caplog) == []


def test_absent_group_reads_as_no_mesh_areas(tmp_path, caplog):
    """The other 1D shape in the same delivery: no 2D Flow Areas group at all."""
    path = _write_1d_geometry(
        tmp_path / "LampasasRiver.g01.hdf", include_flow_areas_group=False
    )

    with caplog.at_level(logging.ERROR, logger="ras_commander"):
        assert HdfMesh.get_mesh_area_names(path) == []

    assert _errors(caplog) == []


def test_area_groups_answer_when_attributes_is_absent(tmp_path):
    """Named area groups carry the same names, so they settle the question.

    This is the one case where the group is non-empty but has no Attributes
    table. Returning the group names reads a second authoritative location that
    every other mesh reader in the module already addresses by name; it does not
    invent a name.
    """
    path = tmp_path / "areas_without_attributes.g01.hdf"
    with h5py.File(path, "w") as hdf:
        hdf.create_group("Geometry/2D Flow Areas/BaldEagleCr")
        hdf.create_group("Geometry/2D Flow Areas/LockHaven")

    assert sorted(HdfMesh.get_mesh_area_names(path)) == ["BaldEagleCr", "LockHaven"]


def test_real_attributes_table_still_reads(tmp_path):
    """Regression guard: a genuine 2D declaration is unchanged."""
    path = _write_2d_geometry(
        tmp_path / "BaldEagleDamBrk.g06.hdf", ["193", "194", "LockHaven"]
    )

    assert HdfMesh.get_mesh_area_names(path) == ["193", "194", "LockHaven"]


def test_attributes_without_a_name_field_refuses(tmp_path):
    """A mesh declaration that cannot be read is never reported as no meshes.

    Before the fix this returned [], which every caller in the library reads as
    "this model has no 2D flow areas" -- a silent wrong answer.
    """
    path = tmp_path / "attributes_without_name.g01.hdf"
    with h5py.File(path, "w") as hdf:
        hdf.create_dataset(
            "Geometry/2D Flow Areas/Attributes",
            data=np.array([(100,)], dtype=np.dtype([("Cell Count", "<i4")])),
        )

    with pytest.raises(ValueError, match="no Name field"):
        HdfMesh.get_mesh_area_names(path)


def test_attributes_that_is_a_group_refuses(tmp_path):
    """An Attributes node of the wrong kind is malformation, not absence."""
    path = tmp_path / "attributes_is_a_group.g01.hdf"
    with h5py.File(path, "w") as hdf:
        hdf.create_group("Geometry/2D Flow Areas/Attributes")

    with pytest.raises(ValueError, match="is not a dataset"):
        HdfMesh.get_mesh_area_names(path)
