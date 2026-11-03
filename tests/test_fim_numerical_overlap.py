"""Roundoff residue may not bypass a sampled ownership conflict."""
from types import SimpleNamespace

import numpy as np
import pytest
import shapely
from affine import Affine

from ras_commander.fim._horizontal import _numerical_overlap_without_sample


def plan():
    return SimpleNamespace(transform=Affine(6, 0, 10_000_000, 0, -6, 10_000_012), shape=(2, 3))


def test_unsampled_roundoff_sliver_is_accepted_without_geometry_change():
    eps = np.spacing(10_000_000.)
    sliver = shapely.box(10_000_007 - eps, 10_000_000, 10_000_007, 10_000_012)
    before = sliver.wkb
    assert _numerical_overlap_without_sample(sliver, plan())
    assert sliver.wkb == before


def test_roundoff_containing_pixel_centre_still_rejects():
    eps = np.spacing(10_000_000.)
    sliver = shapely.box(10_000_003 - eps, 10_000_000, 10_000_003 + eps, 10_000_012)
    assert not _numerical_overlap_without_sample(sliver, plan())


def test_substantial_unsampled_overlap_still_rejects():
    overlap = shapely.box(10_000_007, 10_000_000, 10_000_007.1, 10_000_012)
    assert not _numerical_overlap_without_sample(overlap, plan())


def test_grid_preflight_accepts_only_unsampled_numerical_residue():
    import geopandas as gpd
    from ras_commander.fim._horizontal import prepare_grid
    from ras_commander.fim.errors import FimUnsupportedError

    eps = np.spacing(10_000_000.)
    left = shapely.box(10_000_000, 10_000_000, 10_000_007, 10_000_012)
    right = shapely.box(10_000_007-eps, 10_000_000, 10_000_014, 10_000_012)
    cells = gpd.GeoDataFrame(geometry=[left, right])
    grid = plan()
    grid.cell_positions = np.array([0, 1])
    before = cells.geometry.to_wkb().tolist()
    with pytest.warns(RuntimeWarning, match="Numerical cell-overlap residue"):
        prepare_grid(cells, None, grid, False)
    assert cells.geometry.to_wkb().tolist() == before
    cells.loc[1, "geometry"] = shapely.box(10_000_006.9, 10_000_000, 10_000_014, 10_000_012)
    with pytest.raises(FimUnsupportedError, match="overlapping interiors"):
        prepare_grid(cells, None, grid, False)
