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


def test_global_lattice_arithmetic_cannot_hide_a_sampled_conflict():
    source = Affine(6.561666666666606, 0, 10_000_000.3, 0, -6.561666666666606, 10_000_012.3)
    window = SimpleNamespace(col_off=2341, row_off=1590)
    local = source * Affine.translation(window.col_off, window.row_off)
    grid = SimpleNamespace(transform=local, source_transform=source, window=window, shape=(3, 128))
    pairs = [(source.c + (col + window.col_off + .5) * source.a, local.c + (col + .5) * local.a) for col in range(128)]
    global_x, local_x = next(pair for pair in pairs if pair[0] != pair[1])
    global_y = source.f + (window.row_off + .5) * source.e
    sliver = shapely.box(np.nextafter(global_x, -np.inf), global_y - 1, np.nextafter(global_x, np.inf), global_y + 1)
    assert not sliver.contains(shapely.Point(local_x, global_y))
    assert sliver.contains(shapely.Point(global_x, global_y))
    assert not _numerical_overlap_without_sample(sliver, grid)
