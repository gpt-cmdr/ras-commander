"""Contract tests for the compliant exact-version acceptance matrix."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from ras_commander import RasAcceptanceState
from tests.qualification import test_hybrid_wine_tcu_receipts as hybrid_gate
from tests.qualification import test_portable_captured_transfer_receipts as portable_gate
from tests.qualification import test_user_driven_wine_tcu_receipts as user_gate


SCRIPT = Path(__file__).with_name("run_acceptance_state_matrix.py")
SPEC = importlib.util.spec_from_file_location("acceptance_matrix", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
matrix = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(matrix)


def test_default_matrix_covers_all_installed_stable_exact_builds():
    versions = tuple(matrix._selected_versions("", include_betas=False))

    assert versions == matrix.STABLE_INSTALLED_VERSIONS
    assert len(versions) == 15
    assert all("beta" not in version.casefold() for version in versions)


def test_beta_builds_require_explicit_opt_in():
    with pytest.raises(ValueError, match="separate authority"):
        tuple(matrix._selected_versions(matrix.BETA_INSTALLED_VERSIONS[0], False))

    versions = tuple(matrix._selected_versions("", include_betas=True))
    assert versions[-2:] == matrix.BETA_INSTALLED_VERSIONS


def test_matrix_json_hashes_opaque_state_fields():
    raw = {
        "candidate_value": "opaque-private-state",
        "snapshot": {"value": "opaque-private-state"},
        "ordinary": "visible",
    }

    safe = matrix._safe_json(raw)

    assert safe["ordinary"] == "visible"
    assert safe["candidate_value"]["opaque_sha256"]
    assert safe["snapshot"]["value"]["opaque_sha256"]
    assert "opaque-private-state" not in str(safe)


def test_public_namespace_exposes_only_opaque_acceptance_workflows():
    assert callable(RasAcceptanceState.capture)
    assert callable(RasAcceptanceState.diagnose_candidate)
    assert callable(RasAcceptanceState.provision)
    assert callable(RasAcceptanceState.run_user_driven_acceptance)


@pytest.mark.parametrize(
    "gate",
    [user_gate._assert_main_signature, portable_gate._assert_main_signature],
)
def test_wine_receipt_gates_require_exact_unowned_enabled_main_window(gate):
    gate(["ThunderRT6Main", "RAS", "0", "1"])

    for invalid in (
        ["OtherClass", "HEC-RAS 7.0", "0", "1"],
        ["ThunderRT6Main", "RAS", "123", "1"],
        ["ThunderRT6Main", "RAS", "0", "0"],
        ["ThunderRT6Main", "Unrelated", "0", "1"],
    ):
        with pytest.raises(AssertionError):
            gate(invalid)


def test_hybrid_gate_limits_captured_transfer_to_seven_stable_builds():
    for version in hybrid_gate.CAPTURED_TRANSFER_EXACT_BUILDS:
        hybrid_gate._assert_method_version_allowed(
            {"method": "captured_verified_transfer", "version": version},
            beta=False,
        )

    with pytest.raises(AssertionError):
        hybrid_gate._assert_method_version_allowed(
            {"method": "captured_verified_transfer", "version": "7.0.1"},
            beta=False,
        )
    with pytest.raises(AssertionError):
        hybrid_gate._assert_method_version_allowed(
            {"method": "captured_verified_transfer", "version": "6.7 Beta 5"},
            beta=True,
        )

    hybrid_gate._assert_method_version_allowed(
        {"method": "user_driven", "version": "7.0.1"},
        beta=False,
    )
