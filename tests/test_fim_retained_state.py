"""Retained-state admission and geometry validation regressions."""

from collections import OrderedDict
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.mark.parametrize(
    "control", ["window_cache_mib", "hydraulic_cache_mib", "validation_cache_mib"]
)
@pytest.mark.parametrize("value", [True, -1, 4097, 1.5])
def test_invalid_cache_controls_fail_before_inputs(control, value, tmp_path):
    from ras_commander import RasFim

    with pytest.raises(ValueError, match=control):
        RasFim.prepare_sloping_model(
            tmp_path / "missing.hdf", tmp_path / "missing.tif", **{control: value}
        )


def context(cells, budget=4096):
    from ras_commander.fim._sloping_context import FimPreparedSlopingModel

    model = object.__new__(FimPreparedSlopingModel)
    model._cells, model._terrain = cells, None
    model._validated_positions, model._validation_bytes = OrderedDict(), 0
    model._validation_limit = budget
    return model


def plan(indices):
    return SimpleNamespace(
        cell_positions=np.array(indices, dtype=np.int64), shape=(1, 1)
    )


def test_validation_cache_reuses_only_passed_identical_subsets():
    import geopandas as gpd
    from shapely.geometry import box
    from ras_commander import FimUnsupportedError

    # Cells 0 and 1 share an edge; cell 2 overlaps 1. A cached subset must
    # never certify a different candidate set, including a strict superset.
    cells = gpd.GeoDataFrame(
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(1.5, 0, 2.5, 1)]
    )
    model = context(cells)
    assert model._validate_grid(plan([0, 1])) is False
    assert model._validate_grid(plan([0, 1])) is True
    with pytest.raises(FimUnsupportedError, match="overlapping"):
        model._validate_grid(plan([0, 1, 2]))
    with pytest.raises(FimUnsupportedError, match="overlapping"):
        model._validate_grid(plan([0, 1, 2]))
    assert len(model._validated_positions) == 1


def test_validation_cache_eviction_and_disabled_cache():
    import geopandas as gpd
    from shapely.geometry import box

    cells = gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)])
    model = context(cells, 136)
    assert not model._validate_grid(plan([0]))
    assert not model._validate_grid(plan([1]))
    assert not model._validate_grid(plan([0]))
    assert model._validation_bytes == 136
    model._validation_limit = 0
    model._validated_positions.clear()
    model._validation_bytes = 0
    assert not model._validate_grid(plan([0]))
    assert not model._validate_grid(plan([0]))


def test_one_shot_forwards_native_writer(monkeypatch):
    from ras_commander import RasFim
    from ras_commander.fim import _sloping

    seen = {}

    def capture(*args, **kwargs):
        seen.update(kwargs)
        return "mapped"

    monkeypatch.setattr(_sloping, "map_profiles", capture)
    assert (
        RasFim.map_sloping_profiles(
            "model.hdf", "terrain.tif", "new-output", product_writer="native"
        )
        == "mapped"
    )
    assert seen["product_writer"] == "native"
