"""Exercise XYZM decoding and fail-closed reads across affected HDF layers.

The retained FEMA refinement fixture supplies the domain regression. Minimal
native-format tables here isolate otherwise unavailable XYZM and corruption
combinations across each public reader without invoking HEC-RAS.
"""

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")
pytest.importorskip("geopandas")

from ras_commander.hdf.HdfBase import HdfBase
from ras_commander.hdf.HdfBndry import HdfBndry
from ras_commander.hdf.HdfInfiltration import HdfInfiltration
from ras_commander.hdf.HdfLandCover import HdfLandCover
from ras_commander.hdf.HdfStruc import HdfStruc

READERS = [
    pytest.param("base", "Geometry/Test Lines", "Polyline", id="base-polylines"),
    pytest.param(
        "breaklines", "Geometry/2D Flow Area Break Lines", "Polyline", id="breaklines"
    ),
    pytest.param(
        "refinement",
        "Geometry/2D Flow Area Refinement Regions",
        "Polygon",
        id="refinement",
    ),
    pytest.param(
        "structures", "Geometry/Structures", "Centerline", id="structure-centerlines"
    ),
    pytest.param(
        "landcover",
        "Geometry/Land Cover (Manning's n)",
        "Polygon",
        id="mannings-regions",
    ),
    pytest.param(
        "infiltration", "Geometry/Infiltration", "Polygon", id="infiltration-regions"
    ),
]


def _read(kind, path, group):
    if kind == "base":
        return HdfBase.get_polylines_from_parts(path, group)
    return {
        "breaklines": HdfBndry.get_breaklines,
        "refinement": HdfBndry.get_refinement_regions,
        "structures": HdfStruc.get_structures,
        "landcover": HdfLandCover.get_mannings_region_polygons,
        "infiltration": HdfInfiltration.get_infiltration_region_polygons,
    }[kind](path)


def _write(path, group, prefix, *, z=False, records=1, malformed=None):
    xy = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]])
    points = np.column_stack(
        (xy, np.arange(5.0) + 100 if z else np.full(5, np.nan), np.arange(5.0))
    )
    if z and prefix == "Polygon":
        points[-1, 2] = points[0, 2]  # Close the ring in XYZ as well as XY.
    points = np.tile(points, (records, 1))
    info = np.array([[i * 5, 5, i, 1] for i in range(records)], dtype=np.int32).reshape(
        -1, 4
    )
    parts = np.array([[0, 5] for _ in range(records)], dtype=np.int32).reshape(-1, 2)
    if malformed == "point_count":
        info[-1, 1] = 1
    elif malformed == "point_width":
        points = points[:, :1]
    attrs = np.array(
        [(f"Feature {i}".encode(),) for i in range(records)], dtype=[("Name", "S32")]
    )
    with h5py.File(path, "w") as destination:
        layer = destination.create_group(group)
        layer.create_dataset("Attributes", data=attrs)
        layer.create_dataset(
            f"{prefix} Info", data=info[:, :2] if prefix == "Centerline" else info
        )
        if prefix != "Centerline":
            layer.create_dataset(f"{prefix} Parts", data=parts)
        if malformed != "missing_points":
            layer.create_dataset(f"{prefix} Points", data=points)
    return path


@pytest.mark.parametrize("kind,group,prefix", READERS)
@pytest.mark.parametrize("z", [False, True], ids=["nan-padding", "finite-z"])
def test_readers_reduce_xyzm_without_losing_layer(tmp_path, kind, group, prefix, z):
    path = _write(tmp_path / "vertices.hdf", group, prefix, z=z)
    result = _read(kind, path, group)
    geometries = result if kind == "base" else list(result.geometry)
    assert len(geometries) == 1
    geometry = geometries[0]
    assert not geometry.is_empty
    assert geometry.has_z == z
    coords = np.asarray(
        geometry.exterior.coords if prefix == "Polygon" else geometry.coords
    )
    assert coords.shape == (5, 3 if z else 2)
    np.testing.assert_allclose(
        coords[:, :2], [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    )
    if z:
        expected_z = np.arange(5.0) + 100
        if prefix == "Polygon":
            expected_z[-1] = expected_z[0]
        np.testing.assert_allclose(coords[:, 2], expected_z)


@pytest.mark.parametrize("kind,group,prefix", READERS)
def test_truly_absent_layers_are_empty(tmp_path, kind, group, prefix):
    path = tmp_path / "absent.hdf"
    with h5py.File(path, "w"):
        pass
    assert len(_read(kind, path, group)) == 0


@pytest.mark.parametrize("kind,group,prefix", READERS)
@pytest.mark.parametrize("malformed", ["missing_points", "point_width", "point_count"])
def test_present_corrupt_layers_raise(tmp_path, kind, group, prefix, malformed):
    # Two records ensure a broken second record cannot return a partial layer.
    path = _write(
        tmp_path / "corrupt.hdf", group, prefix, records=2, malformed=malformed
    )
    with pytest.raises((ValueError, KeyError)):
        _read(kind, path, group)


@pytest.mark.parametrize("kind,group,prefix", READERS)
def test_well_formed_zero_record_layers_are_empty(tmp_path, kind, group, prefix):
    path = _write(tmp_path / "empty.hdf", group, prefix, records=0)
    assert len(_read(kind, path, group)) == 0
