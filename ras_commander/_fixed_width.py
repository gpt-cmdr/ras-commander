"""Shared fixed-decimal field formatter introduced by PR #488."""

import math


def _format_fixed_width_value(
    value: float,
    *,
    width: int = 8,
    max_decimals: int = 2,
    min_decimals: int = 0,
    trim_trailing_zeros: bool = False,
    zero_as_blank: bool = False,
    normalize_negative_zero: bool = True,
) -> str:
    """Retain decimals while they fit, reduce one at a time, or raise.

    Width and signed-zero handling let geometry writers retain their existing
    field layouts. The defaults preserve PR #488's unsteady-table behavior.
    Only finite numeric values are accepted; no exponent fallback is used.
    """
    if width < 1:
        raise ValueError("width must be positive")
    if isinstance(value, (str, bytes)):
        raise ValueError(f"HEC-RAS inline-table value must be numeric, got {value!r}")  # noqa: TRY004 - PR #488 contract
    try:
        numeric_value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"HEC-RAS inline-table value must be numeric, got {value!r}"
        ) from exc
    if not math.isfinite(numeric_value):
        raise ValueError(f"HEC-RAS inline-table value must be finite, got {value!r}")
    if min_decimals < 0 or max_decimals < min_decimals:
        raise ValueError(
            "max_decimals must be greater than or equal to non-negative min_decimals"
        )
    if zero_as_blank and numeric_value == 0:
        return " " * width

    for decimals in range(max_decimals, min_decimals - 1, -1):
        text = f"{numeric_value:.{decimals}f}"
        if normalize_negative_zero and float(text) == 0:
            # Never emit negative zero ("-0.00", "-0") for tiny negatives.
            text = f"{0.0:.{decimals}f}"
        if trim_trailing_zeros and "." in text:
            text = text.rstrip("0").rstrip(".")
        if len(text) <= width:
            return text.rjust(width)

    raise ValueError(
        "HEC-RAS inline-table value cannot be represented in an "
        f"{width}-character field without overflow: {numeric_value!r}"
    )
