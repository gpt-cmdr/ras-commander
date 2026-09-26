"""Regression for native multipart refinement-region rings and point offsets."""

import h5py
import numpy as np
import pytest
from pyproj import CRS
from shapely.geometry import box

from ras_commander import HdfBndry


@pytest.mark.parametrize("global_offsets", [False, True])
def test_refinement_holes_islands_and_disjoint_shells(tmp_path, global_offsets):
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
        group["Polygon Points"] = prefix + [p for ring in rings for p in ring]
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
