"""A four-ordinate vertex array must not cost the caller the whole layer.

HEC-RAS writes some geometry point tables with four ordinates per vertex. Every
Shapely constructor raises ``ValueError: The ordinate (last) dimension should be
2 or 3, got 4`` on one, and the HDF readers here catch that at the top of the
function and return an empty GeoDataFrame -- so a layer that could not be read
is indistinguishable from a model that never had one.

Measured on the FEMA eBFE submittal for HUC8 12090106, model ``MidCo_0601_A1``:
41 refinement regions, ``Polygon Points`` of ``(21592, 4)``, third and fourth
columns entirely NaN. The fixture and its provenance are in
``tests/fixtures/refinement_regions_xyzm/``.
"""

from pathlib import Path

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")
pytest.importorskip("geopandas")

from shapely.geometry import Polygon

from ras_commander.hdf.HdfBase import HdfBase
from ras_commander.hdf.HdfBndry import HdfBndry

GROUP = "/Geometry/2D Flow Area Refinement Regions"
FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "refinement_regions_xyzm"
    / "12090106_MidCo_0601_A1.refinement_regions.hdf"
)


def _datasets(path):
    with h5py.File(path, "r") as source:
        group = source[GROUP]
        return {name: group[name][()] for name in
                ("Attributes", "Polygon Info", "Polygon Parts", "Polygon Points")}


def _write(path, datasets):
    with h5py.File(path, "w") as destination:
        group = destination.create_group(GROUP)
        for name, value in datasets.items():
            group.create_dataset(name, data=value)
    return path


def test_the_fixture_still_carries_the_shape_that_causes_the_failure():
    """Guard the fixture itself.

    A fixture quietly normalised to two ordinates would let every assertion
    below pass while testing nothing, so the shape and the NaN padding are
    asserted before they are relied on.
    """
    points = _datasets(FIXTURE)["Polygon Points"]
    assert points.ndim == 2 and points.shape[1] == 4
    assert np.isnan(points[:, 2]).all(), "the third ordinate is padding in this model"
    assert np.isnan(points[:, 3]).all(), "the fourth ordinate is padding in this model"
    with pytest.raises(ValueError, match="should be 2 or 3, got 4"):
        Polygon(points)


def test_four_ordinate_refinement_regions_are_read_rather_than_lost():
    """The defect this file exists for.

    Before the fix this returns an EMPTY GeoDataFrame: the ``ValueError`` is
    swallowed by the reader's blanket ``except Exception`` and 41 real regions
    are reported as none at all.
    """
    regions = HdfBndry.get_refinement_regions(FIXTURE)

    assert len(regions) == 2, "the regions must survive a four-ordinate source"
    assert sorted(regions["Name"]) == ["Region 41", "Region 58"]
    assert sorted(set(regions.geom_type)) == ["Polygon"]
    assert not regions.geometry.isna().any()
    assert not regions.geometry.is_empty.any()
    assert regions.geometry.is_valid.all()
    # NaN padding must not be promoted to a Z ordinate: that would construct
    # NaN-Z geometry out of nothing and move the failure downstream.
    assert not regions.geometry.has_z.any()


def test_a_real_z_ordinate_is_kept_and_only_the_measure_is_dropped(tmp_path):
    """M is a measure, Z is a spatial dimension. Only one of them may be dropped.

    The vertices are the fixture's real coordinates; the third column is
    replaced with finite elevations so that this asks about a genuine XYZM
    source rather than about padding.
    """
    datasets = _datasets(FIXTURE)
    points = datasets["Polygon Points"].copy()
    points[:, 2] = np.linspace(100.0, 140.0, points.shape[0])  # a real Z
    points[:, 3] = np.arange(points.shape[0], dtype=float)  # a station measure
    datasets["Polygon Points"] = points

    regions = HdfBndry.get_refinement_regions(_write(tmp_path / "xyzm.hdf", datasets))

    assert len(regions) == 2
    assert regions.geometry.has_z.all(), "a real Z must survive"
    kept = np.asarray(regions.geometry.iloc[0].exterior.coords)
    assert kept.shape[1] == 3, "the measure must be dropped, not carried"
    # The ring closes, so it repeats its first vertex; the first five are the
    # five the source supplied for this region.
    np.testing.assert_allclose(kept[:5, 2], points[:5, 2])
    np.testing.assert_allclose(kept[:5, :2], points[:5, :2])


def test_a_source_that_already_fits_is_returned_untouched(tmp_path):
    """The reduction is conditional, so nothing that reads today changes."""
    datasets = _datasets(FIXTURE)
    xy = np.ascontiguousarray(datasets["Polygon Points"][:, :2])
    datasets["Polygon Points"] = xy

    regions = HdfBndry.get_refinement_regions(_write(tmp_path / "xy.hdf", datasets))

    assert len(regions) == 2
    assert not regions.geometry.has_z.any()
    # And identical to what the four-ordinate source recovers, which is the
    # point of dropping padding rather than keeping it as Z.
    recovered = HdfBndry.get_refinement_regions(FIXTURE)
    assert list(regions.geometry.to_wkt()) == list(recovered.geometry.to_wkt())


@pytest.mark.parametrize("width", [2, 3])
def test_plan_vertex_ordinates_passes_narrow_arrays_through(width):
    array = np.arange(12, dtype=float).reshape(-1, width)
    assert HdfBase.plan_vertex_ordinates(array) is array


def test_plan_vertex_ordinates_drops_padding_but_keeps_elevation():
    padded = np.array([[1.0, 2.0, np.nan, np.nan], [3.0, 4.0, np.nan, np.nan]])
    assert HdfBase.plan_vertex_ordinates(padded).shape == (2, 2)

    elevated = np.array([[1.0, 2.0, 10.0, 0.0], [3.0, 4.0, 11.0, 1.0]])
    assert HdfBase.plan_vertex_ordinates(elevated).shape == (2, 3)

    # A partly populated Z is still a Z: one finite value is enough to keep it,
    # because dropping it would silently flatten real elevations.
    partial = np.array([[1.0, 2.0, np.nan, 0.0], [3.0, 4.0, 11.0, 1.0]])
    assert HdfBase.plan_vertex_ordinates(partial).shape == (2, 3)


def test_plan_vertex_ordinates_leaves_a_non_vertex_array_alone():
    flat = np.arange(6, dtype=float)
    assert HdfBase.plan_vertex_ordinates(flat) is flat
