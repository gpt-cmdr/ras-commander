"""Tests for deprecated RasGeometry wrapper behavior."""

import warnings
from pathlib import Path

import pandas as pd

from ras_commander import RasGeometry
from ras_commander.geom import GeomCrossSection


def _call_deprecated_get_cross_sections():
    return RasGeometry.get_cross_sections("Project.g01")


def test_deprecation_warning_points_to_user_callsite(monkeypatch):
    monkeypatch.setattr(
        GeomCrossSection,
        "get_cross_sections",
        staticmethod(lambda geom_file, river=None, reach=None: pd.DataFrame()),
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        result = _call_deprecated_get_cross_sections()

    assert result.empty
    deprecation = next(
        warning
        for warning in caught
        if issubclass(warning.category, DeprecationWarning)
    )
    assert Path(deprecation.filename).name == Path(__file__).name
    assert Path(deprecation.filename).name != "Decorators.py"
    assert "RasGeometry.get_cross_sections() is deprecated" in str(deprecation.message)
