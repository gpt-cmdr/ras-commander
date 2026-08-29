from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from scripts.qualification.execution_evidence.aggregate import (
    AggregateError,
    aggregate_run,
    verify_run,
)
from scripts.qualification.execution_evidence.cli import main
from scripts.qualification.execution_evidence.report import render_summary
from ._helpers import make_attempt, valid_table_rows


pytestmark = pytest.mark.qualification_harness


def _two_attempt_run(tmp_path: Path) -> Path:
    second_rows = valid_table_rows(lane_id="lane-z", attempt_id="attempt-2")
    make_attempt(
        tmp_path,
        lane_id="lane-z",
        attempt_id="attempt-2",
        tables=second_rows,
    )
    first_rows = valid_table_rows(lane_id="lane-a", attempt_id="attempt-1")
    make_attempt(
        tmp_path,
        lane_id="lane-a",
        attempt_id="attempt-1",
        tables=first_rows,
    )
    return tmp_path


def test_aggregate_rebuilds_exact_sorted_parquet_and_verifies(tmp_path: Path) -> None:
    run_root = _two_attempt_run(tmp_path)
    tables = aggregate_run(run_root)

    assert {name: table.num_rows for name, table in tables.items()} == {
        "artifacts": 2,
        "events": 2,
        "invariants": 2,
        "lanes": 2,
        "observations": 2,
    }
    assert tables["lanes"].column("lane_id").to_pylist() == ["lane-a", "lane-z"]
    assert verify_run(run_root) == {
        "lanes": 2,
        "artifacts": 2,
        "observations": 2,
        "events": 2,
        "invariants": 2,
    }


def test_repeated_aggregation_is_byte_deterministic(tmp_path: Path) -> None:
    run_root = _two_attempt_run(tmp_path)
    aggregate_run(run_root)
    before = {
        path.name: path.read_bytes() for path in sorted((run_root / "tables").glob("*.parquet"))
    }
    aggregate_run(run_root)
    after = {
        path.name: path.read_bytes() for path in sorted((run_root / "tables").glob("*.parquet"))
    }
    assert after == before


def test_verify_detects_aggregate_data_tampering(tmp_path: Path) -> None:
    run_root = _two_attempt_run(tmp_path)
    aggregate_run(run_root)
    lane_path = run_root / "tables" / "lanes.parquet"
    table = pq.read_table(lane_path).slice(0, 1)
    pq.write_table(table, lane_path, compression="zstd")
    with pytest.raises(AggregateError, match="differs"):
        verify_run(run_root)


def test_report_is_deterministic_and_contains_audit_counts(tmp_path: Path) -> None:
    run_root = _two_attempt_run(tmp_path)
    aggregate_run(run_root)
    first = render_summary(run_root)
    second = render_summary(run_root)
    assert first == second
    assert "Attempts: **2**" in first
    assert "| `passed` | 2 |" in first
    assert "| `pass` | 2 |" in first


def test_cli_aggregate_and_verify_emit_machine_readable_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_root = _two_attempt_run(tmp_path)
    assert main(["aggregate", "--run-root", str(run_root)]) == 0
    aggregated = json.loads(capsys.readouterr().out)
    assert aggregated["lanes"] == 2

    assert main(["verify", "--run-root", str(run_root)]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified == aggregated


def test_aggregate_rejects_incomplete_attempt_instead_of_silently_skipping(
    tmp_path: Path,
) -> None:
    incomplete = tmp_path / "attempts" / "lane-a" / "attempt-1"
    incomplete.mkdir(parents=True)
    (incomplete / "request.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(AggregateError, match="no terminal receipt"):
        aggregate_run(tmp_path)


def test_aggregate_rejects_lane_claim_that_disagrees_with_receipt(tmp_path: Path) -> None:
    rows = valid_table_rows()
    rows["lanes"][0]["terminal_category"] = "failed_invariant"
    make_attempt(tmp_path, tables=rows)
    with pytest.raises(AggregateError, match="terminal_category disagrees"):
        aggregate_run(tmp_path)


@pytest.mark.parametrize("invariant_rows", [[], "failed", "not_applicable"])
def test_passed_lane_requires_every_request_required_invariant_to_pass(
    tmp_path: Path,
    invariant_rows,
) -> None:
    rows = valid_table_rows()
    if invariant_rows == []:
        rows["invariants"] = []
    else:
        rows["invariants"][0]["status"] = invariant_rows
    make_attempt(tmp_path, tables=rows)
    with pytest.raises(
        AggregateError,
        match="all_invariants_passed disagrees|lacks complete passing",
    ):
        aggregate_run(tmp_path)


def test_all_invariants_claim_cannot_hide_nonrequired_failure(tmp_path: Path) -> None:
    rows = valid_table_rows()
    failed_extra = dict(rows["invariants"][0])
    failed_extra.update(
        invariant_id="R12",
        name="Owned-process hygiene",
        status="fail",
    )
    rows["invariants"].append(failed_extra)
    make_attempt(tmp_path, tables=rows)
    with pytest.raises(AggregateError, match="all_invariants_passed disagrees"):
        aggregate_run(tmp_path)


def test_verify_rejects_any_deterministic_metadata_substitution(tmp_path: Path) -> None:
    run_root = _two_attempt_run(tmp_path)
    aggregate_run(run_root)
    lane_path = run_root / "tables" / "lanes.parquet"
    table = pq.read_table(lane_path)
    metadata = dict(table.schema.metadata or {})
    metadata[b"created_at"] = b"1900-01-01T00:00:00+00:00"
    metadata[b"pyarrow_version"] = b"substituted"
    pq.write_table(
        table.replace_schema_metadata(metadata),
        lane_path,
        compression="zstd",
        version="2.6",
        use_dictionary=True,
    )
    with pytest.raises(AggregateError, match="metadata map differs"):
        verify_run(run_root)


def test_aggregate_rejects_symlink_run_and_attempt_roots(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    make_attempt(run_root)
    alias = tmp_path / "run-alias"
    try:
        alias.symlink_to(run_root, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink creation is unavailable")
    with pytest.raises(AggregateError, match="plain directory"):
        aggregate_run(alias)

    real_attempt = run_root / "attempts" / "lane-a" / "attempt-1"
    moved_attempt = tmp_path / "outside-attempt"
    real_attempt.rename(moved_attempt)
    real_attempt.symlink_to(moved_attempt, target_is_directory=True)
    with pytest.raises(AggregateError, match="attempt directory is linked"):
        aggregate_run(run_root)
