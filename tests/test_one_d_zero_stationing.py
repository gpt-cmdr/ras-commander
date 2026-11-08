"""Native modern-HDF Float32 zero-based station staging contracts."""
from copy import deepcopy

import numpy as np
import pytest

from ras_commander.fim._one_d import canonical_arrays, station_m
from test_fim_one_d import inputs


def shifted_inputs(first, block):
    data = inputs()
    data["Station Elevation Values"][:, 0] += first
    data["Attributes"]["Left Bank"] += first
    data["Attributes"]["Right Bank"] += first
    data["Obstruction Info"] = np.array([[0, 1], [1, 0]])
    data["Obstruction Blocks"] = np.array([block], dtype=[
        ("Left Sta", "f8"), ("Right Sta", "f8"), ("Elevation", "f8")])
    return data


@pytest.mark.parametrize("first", [125., -159.4, -1., 0.])
def test_native_translation_precedes_endpoint_selection_and_compute_m(first):
    data = shifted_inputs(first, (first, first + 50., 100.))
    data["Attributes"]["Left Levee Sta"] = first + 50.
    data["Attributes"]["Left Levee Elev"] = 100.
    before = deepcopy(data)
    arrays, receipts, _ = canonical_arrays(data)
    record = receipts[0]
    native = record["native_stationing"]
    f = np.float32
    offset = f(f(-1) * f(first))
    assert native["offset"] == float(offset)
    assert native["first_station"] == 0.
    assert record["first_station"] == first
    assert record["selected_left"] == 0
    right = f(f(first + 50.) + offset) if offset != 0 else f(first + 50.)
    expected_m = station_m(right, native["first_station"], native["last_station"], *native["banks"])
    assert arrays["xs_clip"][0, 4] == expected_m
    assert arrays["xs_clip"][0, 0] == expected_m
    assert record["levees"]["left"]["elevation"] == 100.
    assert record["ordered_blocks"][0]["native_elevation"] == 100.
    for key in before:
        assert data[key].dtype == before[key].dtype
        assert data[key].tobytes() == before[key].tobytes()


def test_native_float32_addition_is_not_float64_translation():
    data = shifted_inputs(.1, (.1, .3, 100.))
    _, records, _ = canonical_arrays(data)
    block = records[0]["ordered_blocks"][0]
    expected = np.float32(np.float32(.3) + np.float32(-np.float32(.1)))
    assert block["native_right"] == float(expected)
    assert expected.view("u4") != np.float32(.3 - .1).view("u4")
    assert block["right"] == .3
    assert records[0]["native_stationing"]["zero_based_f32_bits"][0] == 0


def test_translated_float32_station_is_used_for_strict_endpoint_tolerance():
    data = shifted_inputs(.01, (.0200000001, 5., 100.))
    _, records, _ = canonical_arrays(data)
    assert records[0]["ordered_blocks"][0]["left"] > .01
    assert records[0]["ordered_blocks"][0]["native_left"] < .01
    assert records[0]["selected_left"] == 0


@pytest.mark.parametrize(("block", "selection", "m_index", "m"), [
    ((70., 60., 100.), (None, None), None, None),
    ((0., -10., 100.), (0, None), 4, -2.),
    ((120., 100., 100.), (None, 0), 6, 2.),
])
def test_reversed_blocks_are_preserved_and_selected_only_by_native_endpoints(block, selection, m_index, m):
    data = shifted_inputs(0., block)
    arrays, records, _ = canonical_arrays(data)
    record = records[0]
    assert (record["selected_left"], record["selected_right"]) == selection
    assert record["ordered_blocks"][0]["reversed_interval"] is True
    assert [record["ordered_blocks"][0][key] for key in ("left", "right", "elevation")] == list(block)
    if m_index is not None:
        assert arrays["xs_clip"][0, m_index] == m
    else:
        assert np.isnan(arrays["xs_clip"][0, 4:]).all()
