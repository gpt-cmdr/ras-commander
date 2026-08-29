"""Strict JSON contracts for structured compute-result metadata."""

from __future__ import annotations

import json
from typing import Any, Callable

import pytest

from ras_commander.ComputeResults import ComputeResult, RasControlResult


ResultFactory = Callable[[dict[str, Any]], Any]


@pytest.fixture(params=["compute", "control"])
def result_factory(request: pytest.FixtureRequest) -> ResultFactory:
    if request.param == "compute":
        return lambda details: ComputeResult(
            success=True,
            execution_details=details,
        )
    return lambda details: RasControlResult(
        success=True,
        execution_details=details,
    )


def test_execution_details_are_detached_strict_json(
    result_factory: ResultFactory,
) -> None:
    nested = {"engine": {"gates": [True, None]}, "tokens": ("a", "b")}

    result = result_factory(nested)
    nested["engine"]["gates"].append(False)

    assert result.execution_details == {
        "engine": {"gates": [True, None]},
        "tokens": ["a", "b"],
    }
    assert (
        json.loads(
            json.dumps(result.execution_details, allow_nan=False)
        )
        == result.execution_details
    )


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_execution_details_reject_nonfinite_values(
    result_factory: ResultFactory,
    invalid: float,
) -> None:
    with pytest.raises(ValueError, match="finite JSON-safe"):
        result_factory({"nested": {"value": invalid}})


def test_execution_details_reject_unsupported_nested_values(
    result_factory: ResultFactory,
) -> None:
    with pytest.raises(ValueError, match="finite JSON-safe"):
        result_factory({"nested": {"unsupported": object()}})
