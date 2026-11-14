"""Actual JSON delivery preserves transform bits and explicit missing values."""
import json
import struct

import numpy as np
import pandas as pd
import pytest

from ras_commander import RasFim
from ras_commander.fim._manifest_json import records


def bits(value):
    return struct.pack("<d", value)


@pytest.mark.parametrize("step", [13.123333333060145, np.nextafter(1., 2.), .13])
def test_manifest_transform_survives_binary64_json_round_trip(tmp_path, step):
    transform = (float(step), -0., 3189052.967507327, 0., -float(step), 14105913.686854402)
    frame = pd.DataFrame([{"profile": "max", "status": "complete", "transform": transform}])
    path = RasFim._write_manifest(tmp_path, frame, {"method": "synthetic precision control"})
    row = json.loads(path.read_text())["profiles"][0]
    assert [bits(v) for v in row["transform"]] == [bits(v) for v in transform]
    assert not path.with_suffix(".json.partial").exists()


def test_manifest_nullable_scalars_and_nested_metadata_are_valid_json(tmp_path):
    frame = pd.DataFrame({"profile": ["p", "q"], "count": pd.array([3, pd.NA], dtype="Int64"),
                          "error": [None, pd.NA], "finite": [1., float("inf")]})
    path = RasFim._write_manifest(tmp_path, frame, {
        "metadata": {"missing": pd.NaT, "values": np.array([np.nan, 2.]), "flag": np.bool_(True)},
    })
    data = json.loads(path.read_text(), parse_constant=lambda value: pytest.fail("non-JSON numeric token: "+value))
    assert data["profiles"][0]["count"] == 3
    assert isinstance(data["profiles"][0]["count"], int)
    assert data["profiles"][1]["count"] is None
    assert data["profiles"][1]["error"] is None
    assert data["profiles"][1]["finite"] is None
    assert data["metadata"] == {"missing": None, "values": [None, 2.], "flag": True}


def test_comparison_records_share_exact_float_serialization():
    value = np.nextafter(13.123333333060145, np.inf)
    frame = pd.DataFrame([{"transform": (value, -0.), "ratio": value}])
    actual = json.loads(json.dumps(records(frame), allow_nan=False))[0]
    assert bits(actual["transform"][0]) == bits(value)
    assert bits(actual["transform"][1]) == bits(-0.)
    assert bits(actual["ratio"]) == bits(value)
