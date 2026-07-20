"""Run fail-closed, exact-version HEC-RAS acceptance-state controls.

This private-runner harness launches HEC-RAS only through
``RasAcceptanceState``. It never derives an acceptance value, copies a value
between versions, or clicks a legal control. Positive cases use an opaque value
captured from the same exact executable only after a full no-modal source
probe. Missing and randomized invalid-state controls are restoring
transactions. Report JSON hashes opaque values rather than emitting them.

Wine first-start qualification uses ``run_user_acceptance_session.py`` instead
of accepting candidate values on a command line.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ras_commander import RasAcceptanceState


STABLE_INSTALLED_VERSIONS = (
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

BETA_INSTALLED_VERSIONS = (
    "6.7 Beta 4a",
    "6.7 Beta 5",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _opaque_hash(label: str, value: str) -> str:
    return hashlib.sha256(
        f"ras-commander:{label}:v1\0{value}".encode("utf-8")
    ).hexdigest()


def _safe_json(value: Any, *, field_name: str = "") -> Any:
    """Serialize evidence without exposing opaque acceptance-state values."""
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {
            str(key): _safe_json(item, field_name=str(key))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe_json(item, field_name=field_name) for item in value]
    if field_name in {"value", "candidate_value"} and value is not None:
        return {
            "opaque_sha256": _opaque_hash("acceptance-state", str(value)),
        }
    return value


def _executable(root: Path, version: str) -> Path:
    candidates = (root / version / "Ras.exe", root / version / "ras.exe")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"No Ras.exe for {version} below {root}")


def _probe_is_safe(probe) -> bool:
    return (
        probe.interactions == 0
        and probe.process_tree_terminated
        and not probe.survivors
    )


def _restored_state(executable: Path, version: str, before) -> dict[str, Any]:
    try:
        observed = RasAcceptanceState.capture(
            executable,
            expected_version=version,
        ).state
    except FileNotFoundError:
        observed = None
    restored_exactly = observed == before if before.exists else observed is None
    return {
        "observed": _safe_json(observed),
        "restored_exactly": restored_exactly,
    }


class MatrixRunner:
    def __init__(
        self,
        *,
        root: Path,
        output: Path,
        timeout_seconds: float,
        ready_seconds: float,
    ) -> None:
        self.root = root
        self.output = output
        self.timeout_seconds = timeout_seconds
        self.ready_seconds = ready_seconds
        self.cases: list[dict[str, Any]] = []
        self.bundles: dict[str, Any] = {}
        self.started_at = _utc_now()

    def _checkpoint(self) -> None:
        payload = self._report(include_hash=False)
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )

    def case(self, case_id: str, operation: Callable[[], dict[str, Any]]) -> None:
        print(f"START {case_id}", flush=True)
        record: dict[str, Any] = {
            "case_id": case_id,
            "started_at_utc": _utc_now(),
            "safe_completion": False,
            "passed": False,
        }
        try:
            record.update(operation())
        except BaseException as exc:
            record["exception"] = f"{type(exc).__name__}: {exc}"
        record["completed_at_utc"] = _utc_now()
        self.cases.append(_safe_json(record))
        self._checkpoint()
        print(
            f"END {case_id} passed={record.get('passed')} "
            f"safe={record.get('safe_completion')}",
            flush=True,
        )

    def _probe(self, executable: Path, version: str):
        return RasAcceptanceState.probe(
            executable,
            expected_version=version,
            timeout_seconds=self.timeout_seconds,
            ready_seconds=self.ready_seconds,
        )

    def exact_version(self, version: str) -> None:
        executable = _executable(self.root, version)

        def source_positive() -> dict[str, Any]:
            probe = self._probe(executable, version)
            safe = _probe_is_safe(probe)
            passed = (
                probe.no_modal_verified
                and probe.elapsed_seconds >= self.timeout_seconds
                and safe
            )
            bundle = None
            if passed:
                bundle = RasAcceptanceState.capture(
                    executable,
                    expected_version=version,
                    source_probe=probe,
                )
                self.bundles[version] = bundle
            return {
                "kind": "exact_version_source_capture",
                "candidate_origin": "captured_verified",
                "probe": probe,
                "source_bundle_fingerprint": (
                    bundle.fingerprint if bundle is not None else None
                ),
                "safe_completion": safe,
                "passed": passed,
            }

        self.case(f"{version}:source-capture", source_positive)

        def missing_negative() -> dict[str, Any]:
            with RasAcceptanceState.temporary_system_statistic(
                executable,
                None,
                expected_version=version,
                diagnostic_label=f"{version}-missing-negative",
            ) as (before, applied):
                probe = self._probe(executable, version)
            restoration = _restored_state(executable, version, before)
            safe = _probe_is_safe(probe) and restoration["restored_exactly"]
            return {
                "kind": "missing_state_negative",
                "before": before,
                "applied": applied,
                "probe": probe,
                "restoration": restoration,
                "safe_completion": safe,
                "passed": (
                    not applied.exists
                    and probe.status == "legal_modal"
                    and safe
                ),
            }

        self.case(f"{version}:missing-negative", missing_negative)

        def invalid_negative() -> dict[str, Any]:
            bundle = self.bundles[version]
            invalid_value = f"RAS_COMMANDER_INVALID_{secrets.token_hex(16)}"
            receipt = RasAcceptanceState.diagnose_candidate(
                executable,
                candidate_value=invalid_value,
                candidate_registry_type=bundle.state.registry_type,
                source_version=version,
                expected_version=version,
                permitted_transition=(version, version),
                diagnostic_label=f"{version}-invalid-negative",
                timeout_seconds=self.timeout_seconds,
                ready_seconds=self.ready_seconds,
                candidate_origin="synthetic_negative",
            )
            safe = _probe_is_safe(receipt.probe) and receipt.registry_restored
            return {
                "kind": "randomized_invalid_state_negative",
                "receipt": receipt,
                "safe_completion": safe,
                "passed": (
                    receipt.probe.status == "legal_modal"
                    and receipt.candidate_stayed_exact
                    and safe
                ),
            }

        self.case(f"{version}:invalid-negative", invalid_negative)

        def verified_positive() -> dict[str, Any]:
            bundle = self.bundles[version]
            receipt = RasAcceptanceState.diagnose_candidate(
                executable,
                candidate_value=bundle.state.value or "",
                candidate_registry_type=bundle.state.registry_type,
                source_version=version,
                expected_version=version,
                permitted_transition=(version, version),
                diagnostic_label=f"{version}-verified-positive",
                timeout_seconds=self.timeout_seconds,
                ready_seconds=self.ready_seconds,
                source_bundle=bundle,
            )
            safe = _probe_is_safe(receipt.probe) and receipt.registry_restored
            return {
                "kind": "exact_version_verified_captured_state_positive",
                "candidate_origin": "captured_verified",
                "source_bundle_fingerprint": bundle.fingerprint,
                "receipt": receipt,
                "safe_completion": safe,
                "passed": (
                    receipt.passed
                    and receipt.candidate_stayed_exact
                    and receipt.probe.elapsed_seconds >= self.timeout_seconds
                    and safe
                ),
            }

        self.case(f"{version}:verified-positive", verified_positive)

    def _report(self, *, include_hash: bool) -> dict[str, Any]:
        report: dict[str, Any] = {
            "schema_version": 2,
            "started_at_utc": self.started_at,
            "updated_at_utc": _utc_now(),
            "native_root": str(self.root),
            "timeout_seconds": self.timeout_seconds,
            "ready_seconds": self.ready_seconds,
            "qualification_mode": "exact_version_captured_state",
            "cases": self.cases,
            "summary": {
                "case_count": len(self.cases),
                "passed_count": sum(bool(case.get("passed")) for case in self.cases),
                "all_passed": bool(self.cases)
                and all(bool(case.get("passed")) for case in self.cases),
                "all_safe": bool(self.cases)
                and all(bool(case.get("safe_completion")) for case in self.cases),
                "critical_skips": [],
            },
        }
        if include_hash:
            canonical = json.dumps(
                report,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
            report["report_sha256"] = hashlib.sha256(canonical).hexdigest()
        return report

    def finish(self) -> dict[str, Any]:
        report = self._report(include_hash=True)
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(
            json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        return report


def _selected_versions(raw: str, include_betas: bool) -> Iterable[str]:
    if raw.strip():
        versions = tuple(item.strip() for item in raw.split(",") if item.strip())
    else:
        versions = STABLE_INSTALLED_VERSIONS + (
            BETA_INSTALLED_VERSIONS if include_betas else ()
        )
    if not include_betas and any("beta" in item.casefold() for item in versions):
        raise ValueError("Beta builds require --include-betas and separate authority")
    return versions


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(r"C:\Program Files (x86)\HEC\HEC-RAS"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--ready-seconds", type=float, default=5.0)
    parser.add_argument("--versions", default="")
    parser.add_argument("--include-betas", action="store_true")
    parser.add_argument("--beta-authorization-sha256", default="")
    args = parser.parse_args()

    beta_authority = args.beta_authorization_sha256.strip().lower()
    if args.include_betas and not _valid_sha256(beta_authority):
        parser.error(
            "--include-betas requires a separate --beta-authorization-sha256"
        )
    if not args.include_betas and beta_authority:
        parser.error("--beta-authorization-sha256 requires --include-betas")

    try:
        versions = tuple(_selected_versions(args.versions, args.include_betas))
    except ValueError as exc:
        parser.error(str(exc))

    runner = MatrixRunner(
        root=args.root,
        output=args.output,
        timeout_seconds=args.timeout_seconds,
        ready_seconds=args.ready_seconds,
    )
    for version in versions:
        runner.exact_version(version)
    report = runner.finish()
    print(json.dumps(report["summary"], indent=2, sort_keys=True), flush=True)
    print(f"REPORT {args.output}", flush=True)
    print(f"SHA256 {report['report_sha256']}", flush=True)
    return 0 if report["summary"]["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
