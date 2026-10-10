"""Decimal compatibility with the original c731ef7 fixed-width formatters."""

from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, localcontext

import numpy as np
import pandas as pd
import pytest

from ras_commander import RasUnsteady
from ras_commander.fixit.obstructions import _format_value
from ras_commander.geom import GeomParser
from ras_commander.usgs.boundary_generation import BoundaryGenerator


# Formatting bodies copied from c731ef7fc98ce1015fde381822180239cb3e1b0f.
# Keep these independent of the shared helper so rounding regressions are visible.
def _original_geometry(values, column_width=8, values_per_line=10, precision=2):
    lines = []
    for i in range(0, len(values), values_per_line):
        row_values = values[i : i + values_per_line]
        formatted_row = "".join(
            f"{value:{column_width}.{precision}f}" for value in row_values
        )
        lines.append(formatted_row + "\n")
    return lines


def _original_usgs(values, width=8, decimals=2, values_per_line=10):
    if isinstance(values, pd.Series):
        values = values.values
    elif isinstance(values, list):
        values = np.array(values)
    lines = []
    for i in range(0, len(values), values_per_line):
        chunk = values[i : i + values_per_line]
        line = "".join(f"{v:>{width}.{decimals}f}" for v in chunk)
        lines.append(line)
    return "\n".join(lines)


def _original_fixit(value, width):
    s = f"{value:.2f}"
    if len(s) > width:
        return "*" * width
    return s.rjust(width)


def _geometry(value, width=8, precision=2):
    return GeomParser.format_fixed_width([value], width, 10, precision)[0][:-1]


def _usgs(value, width=8, precision=2):
    return BoundaryGenerator.format_fixed_width_values([value], width, precision)


WRITERS = [_geometry, _usgs, lambda value: _format_value(value, 8)]
ROUNDING_MODES = [ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_DOWN]


@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize(
    "value,expected",
    [
        ("1.015", "    1.02"),
        ("2.675", "    2.68"),
        ("-1.015", "   -1.02"),
        ("-2.675", "   -2.68"),
        ("1.005", "    1.00"),
        ("1.01", "    1.01"),
        ("-0", "   -0.00"),
        ("-0.004", "   -0.00"),
        ("1E-400", "    0.00"),
        ("99999.985", "99999.98"),
        ("-9999.985", "-9999.98"),
    ],
)
def test_decimal_gate_values_keep_original_field_bytes(writer, value, expected):
    with localcontext() as context:
        context.rounding = ROUND_HALF_EVEN
        number = Decimal(value)
        originals = [
            _original_geometry([number])[0][:-1],
            _original_usgs([number]),
            _original_fixit(number, 8),
        ]
        assert originals == [expected] * 3
        assert writer(number).encode("ascii") == expected.encode("ascii")


@pytest.mark.parametrize("rounding", ROUNDING_MODES)
@pytest.mark.parametrize("width,precision", [(5, 2), (8, 2), (8, 3), (16, 5)])
def test_decimal_tables_match_original_fitting_bytes(rounding, width, precision):
    # Exact decimal inputs include halfway cases, signed zero, both signs, and
    # a deterministic sample spanning the field's fitting range.
    values = [Decimal(v) for v in ["1.015", "2.675", "-1.015", "-0", "-0.004"]]
    values.extend(
        Decimal(int(v)) / Decimal(1000)
        for v in np.random.default_rng(497).integers(-9999000, 99999000, 1000)
    )
    with localcontext() as context:
        context.rounding = rounding
        fitting = [v for v in values if len(f"{v:{width}.{precision}f}") == width]
        assert fitting
        assert GeomParser.format_fixed_width(fitting, width, 10, precision) == (
            _original_geometry(fitting, width, 10, precision)
        )
        for container in [fitting, np.array(fitting), pd.Series(fitting)]:
            assert BoundaryGenerator.format_fixed_width_values(
                container, width, precision
            ).encode("ascii") == _original_usgs(container, width, precision).encode(
                "ascii"
            )
        if precision == 2:
            for value in fitting:
                assert _format_value(value, width).encode("ascii") == (
                    _original_fixit(value, width).encode("ascii")
                )


@pytest.mark.parametrize("rounding", ROUNDING_MODES)
@pytest.mark.parametrize(
    "generate,header",
    [
        (BoundaryGenerator.generate_flow_hydrograph_table, "Flow Hydrograph"),
        (BoundaryGenerator.generate_stage_hydrograph_table, "Stage Hydrograph"),
    ],
)
def test_decimal_public_hydrographs_keep_original_bytes(generate, header, rounding):
    values = [Decimal(v) for v in ["1.015", "2.675", "-1.015", "-2.675"]] * 3
    with localcontext() as context:
        context.rounding = rounding
        expected = f"Interval=1HOUR\n{header}= {len(values)}\n{_original_usgs(values)}"
        for container in [values, np.array(values), pd.Series(values)]:
            assert generate(container, interval="1HOUR").encode(
                "ascii"
            ) == expected.encode("ascii")


@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize(
    "value,expected",
    [
        ("99999.995", "100000.0"),
        ("-9999.995", "-10000.0"),
        ("999999.95", " 1000000"),
        ("-99999.95", " -100000"),
        ("108765.38", "108765.4"),
        ("163148.07725", "163148.1"),
        ("100000.05", "100000.0"),
        ("-10000.05", "-10000.0"),
        ("99999999.49", "99999999"),
        ("-9999999.49", "-9999999"),
    ],
)
def test_decimal_overflow_reduces_decimals_without_float_rounding(
    writer, value, expected
):
    with localcontext() as context:
        context.rounding = ROUND_HALF_EVEN
        result = writer(Decimal(value))
        assert result == expected
        assert len(result) == 8
        assert "e" not in result.lower() and "*" not in result


@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize(
    "value",
    ["1E8", "-1E7", "99999999.5", "-9999999.5", "1E400", "NaN", "sNaN", "Infinity"],
)
def test_decimal_unrepresentable_or_nonfinite_values_raise(writer, value):
    with localcontext() as context:
        context.rounding = ROUND_HALF_EVEN
        with pytest.raises(ValueError):
            writer(Decimal(value))


@pytest.mark.parametrize("rounding", ROUNDING_MODES)
def test_unsteady_retains_original_binary_float_conversion(rounding):
    with localcontext() as context:
        context.rounding = rounding
        for value in ["1.015", "2.675", "-1.015", "-2.675", "1.005"]:
            number = Decimal(value)
            assert (
                RasUnsteady._format_fixed_width_value(number) == f"{float(number):8.2f}"
            )
