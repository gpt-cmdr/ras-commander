"""Static safety contract for the Wine TCU shell entry points."""

from __future__ import annotations

from pathlib import Path


QUALIFICATION_DIR = Path(__file__).resolve().parent


def _script(name: str) -> str:
    return (QUALIFICATION_DIR / name).read_text(encoding="utf-8")


def test_stable_wrapper_uses_only_user_driven_acceptance_harness() -> None:
    script = _script("run_wine_acceptance_version.sh")

    assert "run_user_acceptance_session.py" in script
    assert "--destination-is-disposable" in script
    assert "RAS_COMMANDER_TCU_SOURCE_EVIDENCE_SHA256" in script
    assert "RAS_COMMANDER_TCU_USER_VISIBLE" in script
    assert "RAS_COMMANDER_TCU_CONTROLLED_ROOT" in script
    assert "RAS_COMMANDER_TCU_SOURCE_ROOT" in script
    assert "RAS_COMMANDER_TCU_WINDOWS_SOURCE_ROOT" in script

    for forbidden in (
        "--wine-version-case",
        "--wine-701-case",
        "--candidate-value",
        "--candidate-source",
        "--candidate-provenance-sha256",
        "/opt/rasq/diagnostics/",
        "Z:\\opt\\rasq\\diagnostics\\",
    ):
        assert forbidden not in script


def test_stable_wrapper_allowlist_is_the_15_installed_stable_builds() -> None:
    script = _script("run_wine_acceptance_version.sh")
    stable_versions = (
        "4.0",
        "4.1.0",
        "5.0.3",
        "5.0.6",
        "5.0.7",
        "6.0",
        "6.1",
        "6.2",
        "6.3",
        "6.3.1",
        "6.4.1",
        "6.5",
        "6.6",
        "7.0",
        "7.0.1",
    )

    allowlist = next(
        line.strip()
        for line in script.splitlines()
        if line.strip().startswith("4.0|")
    )
    assert allowlist.removesuffix(") ;;").split("|") == list(stable_versions)
    assert "beta builds require a separate beta-authorized workflow" in script


def test_legacy_candidate_wrapper_is_a_fail_closed_tombstone() -> None:
    script = _script("run_wine_acceptance_case.sh")

    assert "is retired" in script
    assert "run_wine_acceptance_version.sh" in script
    assert "run_acceptance_state_matrix.py" not in script
    assert "--wine-701-case" not in script
    assert "wine 'C:" not in script
