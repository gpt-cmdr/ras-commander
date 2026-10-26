"""Opt-in precision on a retained HEC-authored inline hydrograph fixture."""

import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ras_commander import RasUnsteady

FIXTURE = Path(__file__).parent / "fixtures/rasunsteady_fixed_width/BaldEagleDamBrk.u02"
VALUES = [
    9.452924361595741,
    43.18325776320238,
    20.95723504286546,
    209.7442145714393,
    166.24587073692908,
    0.000123456789,
]


def write_hydrograph(path, values=VALUES, **kwargs):
    return RasUnsteady.set_boundary_inline_hydrograph(
        path,
        pd.DataFrame({"hour": list(range(len(values))), "value": values}),
        area_2d="BaldEagleCr",
        bc_line="Upstream Inflow",
        **kwargs,
    )


def ordinates(path):
    lines = path.read_text().splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.startswith("Flow Hydrograph=")
    )
    count = int(lines[start].split("=")[1])
    text = "".join(lines[start + 1 : start + 1 + (count + 9) // 10])
    assert len(text) == count * 8
    fields = [text[i : i + 8] for i in range(0, len(text), 8)]
    return fields, np.asarray([float(field) for field in fields])


def test_opt_in_precision_preserves_fractional_flows_and_other_real_boundaries(
    tmp_path,
):
    path = tmp_path / FIXTURE.name
    shutil.copyfile(FIXTURE, path)
    before = path.read_bytes()
    first = before.index(b"Boundary Location=")
    target = before.index(b"Boundary Location=", before.index(b"DS2NormalD"))
    after_target = before.index(b"Boundary Location=", target + 1)
    assert write_hydrograph(path, max_decimals=6)
    fields, values = ordinates(path)
    assert fields == [
        "9.452924",
        "43.18326",
        "20.95724",
        "209.7442",
        "166.2459",
        "0.000123",
    ]
    assert np.allclose(values, VALUES, rtol=1e-5, atol=1e-4)
    changed = path.read_bytes()
    assert changed[first:target] == before[first:target]
    assert (
        changed[changed.index(b"Boundary Location=", target + 1) :]
        == before[after_target:]
    )
    assert FIXTURE.read_bytes() == before


def test_default_precision_keeps_existing_serialization(tmp_path):
    default = tmp_path / "default.u01"
    explicit = tmp_path / "explicit.u01"
    for path in (default, explicit):
        shutil.copyfile(FIXTURE, path)
    assert write_hydrograph(default)
    assert write_hydrograph(explicit, max_decimals=2)
    assert default.read_bytes() == explicit.read_bytes()
    assert ordinates(default)[0][:2] == ["    9.45", "   43.18"]


def test_precision_keeps_ten_eight_character_fields_per_row(tmp_path):
    path = tmp_path / FIXTURE.name
    shutil.copyfile(FIXTURE, path)
    values = VALUES * 2
    assert write_hydrograph(path, values, max_decimals=6)
    fields, actual = ordinates(path)
    assert len(fields) == 12 and all(len(field) == 8 for field in fields)
    assert np.allclose(actual, values, rtol=1e-5, atol=1e-4)


@pytest.mark.parametrize("precision", [-1, 7, 1.5, True, "6", None])
def test_invalid_precision_does_not_mutate_file(tmp_path, precision):
    path = tmp_path / FIXTURE.name
    shutil.copyfile(FIXTURE, path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="max_decimals"):
        write_hydrograph(path, max_decimals=precision)
    assert path.read_bytes() == before
