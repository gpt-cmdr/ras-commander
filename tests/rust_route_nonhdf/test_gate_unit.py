"""Fixture-free checks of the ROUTE-NONHDF gate wiring (always run)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rust_route_1 import _h5py_guard  # noqa: E402


def test_case_modules_are_harness():
    here = Path(__file__).parent
    assert _h5py_guard._is_harness(str(here / "_cases_check.py"))
    assert not _h5py_guard._is_harness(os.path.join("ras_commander", "check", "_utils.py"))
    assert not _h5py_guard._is_harness(str(here / "test_nonhdf_equivalence.py"))


def test_cases_declared():
    from ._case import KINDS, all_cases
    cases = all_cases()
    assert cases, "no ROUTE-NONHDF cases declared"
    for name, case in cases.items():
        assert callable(case.call), name
        assert case.kinds and case.kinds <= KINDS, name
