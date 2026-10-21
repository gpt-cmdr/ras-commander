"""Regression for native multipart refinement-region rings and point offsets."""

import h5py
import numpy as np
import pytest
from pyproj import CRS
from shapely.geometry import box

from ras_commander import HdfBndry


@pytest.mark.parametrize("global_offsets", [False, True])
@pytest.mark.parametrize("ordinate_count", [2, 4])
def test_refinement_holes_islands_and_disjoint_shells(
    tmp_path, global_offsets, ordinate_count
):
    path = tmp_path / "regions.g01.hdf"
    prefix = list(box(-10, -10, -9, -9).exterior.coords)
    rings = [
        list(box(0, 0, 10, 10).exterior.coords),
        list(box(2, 2, 8, 8).exterior.coords),
        list(box(3, 3, 4, 4).exterior.coords),
        list(box(20, 0, 21, 1).exterior.coords),
    ]
    with h5py.File(path, "w") as hdf:
        hdf.attrs["Projection"] = CRS.from_epsg(6588).to_wkt()
        group = hdf.create_group("Geometry/2D Flow Area Refinement Regions")
        group["Attributes"] = np.array(
            [(b"simple",), (b"multipart",)], dtype=[("Name", "S20")]
        )
        points = np.asarray(prefix + [p for ring in rings for p in ring])
        if ordinate_count == 4:
            points = np.column_stack((points, np.full((len(points), 2), np.nan)))
        group["Polygon Points"] = points
        group["Polygon Info"] = [[0, 5, 0, 1], [5, 20, 1, 4]]
        # Native collections use global offsets; historical readers also
        # support offsets relative to each feature's point slice.
        offset = 5 if global_offsets else 0
        group["Polygon Parts"] = [[0, 5]] + [[offset + i * 5, 5] for i in range(4)]
    result = HdfBndry.get_refinement_regions(path)
    assert result.Name.tolist() == ["simple", "multipart"]
    assert result.rr_id.tolist() == [0, 1]
    assert result.crs.to_epsg() == 6588
    assert result.is_valid.all()
    geometry = result.geometry.iloc[1]
    assert geometry.geom_type == "MultiPolygon"
    assert len(geometry.geoms) == 3
    assert sum(len(part.interiors) for part in geometry.geoms) == 1
    assert geometry.area == pytest.approx(66)


def _write_regions(path, points, info, parts):
    with h5py.File(path, "w") as hdf:
        group = hdf.create_group("Geometry/2D Flow Area Refinement Regions")
        group["Attributes"] = np.array(
            [(f"r{i}".encode(),) for i in range(len(info))], dtype=[("Name", "S20")]
        )
        group["Polygon Points"] = np.asarray(points, dtype=float)
        group["Polygon Info"] = np.asarray(info, dtype=np.int32)
        group["Polygon Parts"] = np.asarray(parts, dtype=np.int32)


SQUARES = [[0, 0], [2, 0], [2, 2], [0, 2], [5, 0], [7, 0], [7, 2], [5, 2]]


def test_local_parts_with_unused_leading_vertices(tmp_path):
    # Local Parts that also fit the global range must not be shifted.
    path = tmp_path / "local.g01.hdf"
    points = [[100, 100], [101, 100], [100, 101], [88, 88], [89, 88], [88, 89]] + SQUARES
    _write_regions(path, points, [[0, 3, 0, 1], [3, 11, 1, 2]], [[0, 3], [3, 4], [7, 4]])
    geometry = HdfBndry.get_refinement_regions(path).geometry.iloc[1]
    assert geometry.wkt == (
        "MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((5 0, 7 0, 7 2, 5 2, 5 0)))"
    )


def test_legacy_global_parts_covering_the_feature(tmp_path):
    path = tmp_path / "global.g01.hdf"
    points = [[100, 100], [101, 100], [100, 101]] + SQUARES
    _write_regions(path, points, [[0, 3, 0, 1], [3, 8, 1, 2]], [[0, 3], [3, 4], [7, 4]])
    geometry = HdfBndry.get_refinement_regions(path).geometry.iloc[1]
    assert geometry.wkt == (
        "MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((5 0, 7 0, 7 2, 5 2, 5 0)))"
    )


@pytest.mark.parametrize(
    "parts",
    [
        [[0, 3], [3, 4], [9, 4]],  # neither local nor a complete global cover
        [[0, 3], [0, 4], [7, 4]],  # mixed local and global offsets
        [[0, 3], [3, 4]],  # truncated Parts dataset
    ],
)
def test_unresolvable_parts_raise(tmp_path, parts):
    path = tmp_path / "bad.g01.hdf"
    points = [[100, 100], [101, 100], [100, 101]] + SQUARES
    _write_regions(path, points, [[0, 3, 0, 1], [3, 8, 1, 2]], parts)
    with pytest.raises(ValueError, match="polygon part"):
        HdfBndry.get_refinement_regions(path)
