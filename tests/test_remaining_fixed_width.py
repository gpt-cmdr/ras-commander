"""Field-boundary and byte-compatibility regressions for remaining writers."""

import math

import numpy as np
import pandas as pd
import pytest

from ras_commander import RasBreach
from ras_commander.fixit.obstructions import (
    BlockedObstruction,
    _format_value,
    format_obstructions,
)
from ras_commander.geom import GeomCrossSection, GeomParser, GeomStorage
from ras_commander.usgs.boundary_generation import BoundaryGenerator


def _geometry(value, width=8, precision=2):
    return GeomParser.format_fixed_width([value], width, 10, precision)[0][:-1]


def _usgs(value, width=8, precision=2):
    return BoundaryGenerator.format_fixed_width_values([value], width, precision)


def _manning(value, column="Station", precision=2):
    row = {"Station": 1.0, "n_value": 0.035, "ChangeFlag": 0.0}
    row[column] = value
    line = GeomCrossSection._format_mannings_n_lines(pd.DataFrame([row]))[0]
    index = list(row).index(column) * 8
    return line[index : index + 8]


WRITERS = [
    _geometry,
    _usgs,
    _manning,
    GeomCrossSection._format_blocked_obstruction_value,
    lambda value: _format_value(value, 8),
]


@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize(
    "value,expected",
    [
        (99999.99, "99999.99"),
        (100000.0, "100000.0"),
        (1000000.0, " 1000000"),
        (99999999.0, "99999999"),
        (-9999.99, "-9999.99"),
        (-10000.0, "-10000.0"),
        (-100000.0, " -100000"),
        (-9999999.0, "-9999999"),
        (99999.999, "100000.0"),
        (999999.99, " 1000000"),
        (-9999.999, "-10000.0"),
        (-99999.99, " -100000"),
        (108765.38, "108765.4"),
        (163148.07725, "163148.1"),
        (-108765.38, " -108765"),
        (-163148.07725, " -163148"),
    ],
)
def test_eight_character_boundaries(writer, value, expected):
    assert writer(value) == expected


@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize(
    "value", [1e8, -1e7, 99999999.5, -9999999.5, math.inf, -math.inf, math.nan]
)
def test_writers_reject_unrepresentable_values(writer, value):
    with pytest.raises(ValueError):
        writer(value)


@pytest.mark.parametrize("writer", WRITERS)
def test_already_fitting_fields_are_byte_identical(writer):
    # Include signed zero and tiny negatives: these writers historically kept
    # the sign even though PR #488's unsteady formatter normalizes zero.
    values = [-0.0, -0.004, -1e-9, 0.0, 1e-9, 1.2345, 99999.99, -9999.99]
    values.extend(np.random.default_rng(488).uniform(-9999, 99999, 1000))
    for value in values:
        legacy = f"{value:8.2f}"
        assert len(legacy) == 8
        assert writer(value).encode("ascii") == legacy.encode("ascii")


@pytest.mark.parametrize("width,precision", [(5, 2), (8, 3), (16, 5)])
@pytest.mark.parametrize("writer", [_geometry, _usgs])
@pytest.mark.parametrize("negative", [False, True])
def test_configurable_width_and_precision_boundaries(
    writer, width, precision, negative
):
    sign = -1 if negative else 1
    digits = width - int(negative)
    largest_full = sign * (10 ** (digits - precision - 1) - 10**-precision)
    first_reduced = sign * 10 ** (digits - precision - 1)
    first_integer = sign * 10 ** (digits - 2)
    assert (
        writer(largest_full, width, precision) == f"{largest_full:{width}.{precision}f}"
    )
    assert (
        writer(first_reduced, width, precision)
        == f"{first_reduced:{width}.{precision - 1}f}"
    )
    assert writer(first_integer, width, precision) == f"{first_integer:{width}.0f}"
    with pytest.raises(ValueError):
        writer(sign * 10**digits, width, precision)


@pytest.mark.parametrize(
    "value,expected",
    [
        (9999.999, "9999.999"),
        (10000, "10000.00"),
        (1000000, " 1000000"),
        (-999.999, "-999.999"),
        (-1000, "-1000.00"),
        (-100000, " -100000"),
    ],
)
def test_manning_n_field_boundaries(value, expected):
    assert _manning(value, "n_value") == expected


@pytest.mark.parametrize(
    "column,precision", [("Station", 2), ("n_value", 3), ("ChangeFlag", 0)]
)
def test_manning_fields_keep_legacy_bytes_and_raise(column, precision):
    for value in [-0.0, -0.00001, 0.035, 1.0, 123.45, -999.999]:
        assert _manning(value, column) == f"{value:8.{precision}f}"
    for value in [1e8, -1e7]:
        with pytest.raises(ValueError):
            _manning(value, column)


def test_manning_and_obstruction_row_wrapping():
    row = {"Station": 108765.38, "n_value": 0.035, "ChangeFlag": 0}
    lines = GeomCrossSection._format_mannings_n_lines(pd.DataFrame([row] * 4))
    assert [len(line.rstrip("\n")) for line in lines] == [72, 24]
    obstructions = [BlockedObstruction(108765.38, 163148.07725, 123.45)] * 4
    direct = GeomCrossSection.format_blocked_obstructions(obstructions)
    assert format_obstructions(obstructions) == [line.rstrip("\n") for line in direct]
    assert all("*" not in line and "e" not in line.lower() for line in direct)


def _legacy_breach(value):
    if value == 0:
        return "0"
    if abs(value) >= 10000 or 0 < abs(value) < 1e-4:
        return f"{value:.3e}"
    return f"{value:.6g}"


@pytest.mark.parametrize("width", [8, 10, 16])
def test_breach_preserves_every_already_fitting_legacy_form(width):
    values = [
        -0.0,
        0,
        1e-5,
        -1e-5,
        1e-20,
        123.456,
        9999.99,
        10000,
        108765.38,
        163148.07725,
        -10000,
    ]
    values.extend(np.random.default_rng(488).uniform(-100000, 100000, 1000))
    for value in values:
        text = _legacy_breach(value)
        if len(text) <= width:
            assert RasBreach._format_numeric_value(value, width) == text.rjust(width)


@pytest.mark.parametrize(
    "value,expected",
    [
        (9999.99, " 9999.99"),
        (10000, "   10000"),
        (99999.99, "99999.99"),
        (100000.01, "  100000"),
        (108765.38, "108765.4"),
        (163148.07725, "163148.1"),
        (1000000.01, " 1000000"),
        (99999999, "99999999"),
        (-9999.99, "-9999.99"),
        (-10000.01, "  -10000"),
        (-100000.01, " -100000"),
        (-9999999, "-9999999"),
    ],
)
def test_breach_overflow_uses_shared_fixed_decimal_rule(value, expected):
    result = RasBreach._format_numeric_value(value, 8)
    assert result == expected
    assert "e" not in result.lower()


@pytest.mark.parametrize(
    "value", [1e8, -1e7, 99999999.5, -9999999.5, math.inf, -math.inf, math.nan]
)
def test_breach_rejects_instead_of_truncating(value):
    with pytest.raises(ValueError):
        RasBreach._format_numeric_value(value, 8)


def test_geometry_storage_table_round_trip_and_rejected_write(tmp_path):
    geom = tmp_path / "table.g01"
    geom.write_text(
        "Storage Area=Pool,0,0\nStorage Area Elev Volume= 2\n    0.00    0.00   10.00   10.00\nStorage Area Is2D=0\n"
    )
    elevations = [0, 10, 20]
    volumes = [0, 108765.38, 163148.07725]
    GeomStorage.set_elevation_volume(geom, "Pool", elevations, volumes)
    curve = GeomStorage.get_elevation_volume(geom, "Pool")
    assert curve["Volume"].tolist() == [0, 108765.4, 163148.1]
    before = geom.read_bytes()
    with pytest.raises(ValueError):
        GeomStorage.set_elevation_volume(geom, "Pool", elevations, [0, 1e8, 2e8])
    assert geom.read_bytes() == before


def test_table_chunking_keeps_fitting_bytes():
    values = [0, 1234.56, -1234.56] * 4
    expected = [
        "".join(f"{v:8.2f}" for v in values[i : i + 10])
        for i in range(0, len(values), 10)
    ]
    assert GeomParser.format_fixed_width(values) == [line + "\n" for line in expected]
    assert BoundaryGenerator.format_fixed_width_values(pd.Series(values)) == "\n".join(
        expected
    )
    for generate, header in [
        (BoundaryGenerator.generate_flow_hydrograph_table, "Flow Hydrograph="),
        (BoundaryGenerator.generate_stage_hydrograph_table, "Stage Hydrograph="),
    ]:
        table = generate([108765.38, 163148.07725])
        assert header in table
        assert "108765.4163148.1" in table
