"""Opt-in real native compile and complete ownership acceptance."""

import importlib.util
import os
from pathlib import Path

import pytest


@pytest.mark.real_ras
@pytest.mark.destructive_copy
def test_native_perimeter_bc_replacement(tmp_path):
    executable = os.environ.get("RAS_BC_NATIVE_EXE")
    if not executable:
        pytest.skip(
            "Set RAS_BC_NATIVE_EXE to opt in to native preprocessing on a disposable example clone"
        )
    script = Path(__file__).parents[1] / "scripts" / "validate_perimeter_bc.py"
    spec = importlib.util.spec_from_file_location("perimeter_bc_acceptance", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evidence = module._validate(tmp_path / "acceptance", True, executable)
    assert evidence["source_unchanged"]
    assert evidence["after_assigned_faces"] > 0
    assert evidence["after_unassigned_faces"] > 0
