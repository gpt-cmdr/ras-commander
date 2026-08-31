from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.qualification.execution_evidence.receipts import (
    EventJournal,
    ReceiptError,
    read_event_journal,
    read_json_with_digest,
    verify_attempt_receipt,
    write_json_with_digest,
)
from scripts.qualification.execution_evidence.schemas import table_from_rows
from scripts.qualification.execution_evidence.snapshots import SnapshotError
from ._helpers import make_attempt


pytestmark = pytest.mark.qualification_harness


def test_json_digest_round_trip_is_canonical_and_immutable(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    digest = write_json_with_digest(path, {"z": 1, "a": [True, None]})

    payload, observed = read_json_with_digest(path)
    assert payload == {"a": [True, None], "z": 1}
    assert observed == digest
    assert path.read_bytes() == b'{"a":[true,null],"z":1}\n'
    assert path.with_suffix(".sha256").read_text(encoding="ascii") == f"{digest}\n"
    with pytest.raises(FileExistsError):
        write_json_with_digest(path, payload)


def test_near_max_path_records_use_bounded_same_directory_atomic_temps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep request and longest live-record paths below legacy MAX_PATH."""
    receipts_module = __import__(
        "scripts.qualification.execution_evidence.receipts",
        fromlist=["os", "tempfile"],
    )
    absolute_root = Path(receipts_module.os.path.abspath(tmp_path))
    longest_record = Path("worker-authorization.json")
    longest_digest = longest_record.with_suffix(".sha256")
    attempt_length = 259 - 1 - len(longest_digest.name)
    padding_length = attempt_length - len(str(absolute_root)) - 1
    assert 0 < padding_length <= 255
    attempt = absolute_root / ("p" * padding_length)
    attempt.mkdir()
    assert len(str(attempt)) == attempt_length

    temporary_paths: list[Path] = []
    link_destinations: list[Path] = []
    replace_destinations: list[Path] = []
    original_mkstemp = receipts_module.tempfile.mkstemp
    original_link = receipts_module.os.link
    original_replace = receipts_module.os.replace

    def recording_mkstemp(*args, **kwargs):
        descriptor, name = original_mkstemp(*args, **kwargs)
        temporary_paths.append(Path(name))
        return descriptor, name

    def recording_link(source, destination):
        source_path = Path(source)
        destination_path = Path(destination)
        assert source_path.parent == destination_path.parent
        link_destinations.append(destination_path)
        return original_link(source, destination)

    def recording_replace(source, destination):
        source_path = Path(source)
        destination_path = Path(destination)
        assert source_path.parent == destination_path.parent
        replace_destinations.append(destination_path)
        return original_replace(source, destination)

    monkeypatch.setattr(receipts_module.tempfile, "mkstemp", recording_mkstemp)
    monkeypatch.setattr(receipts_module.os, "link", recording_link)
    monkeypatch.setattr(receipts_module.os, "replace", recording_replace)

    request_path = attempt / "request.json"
    request_digest = write_json_with_digest(request_path, {"value": "request"})
    longest_path = attempt / longest_record
    first_longest_digest = write_json_with_digest(longest_path, {"value": "first"})
    second_longest_digest = write_json_with_digest(
        longest_path,
        {"value": "replacement"},
        replace=True,
    )
    bounded_names = (
        "worker-launcher.json",
        "cancel-intent.json",
        "cancel-launcher.json",
        "cancel-hello.json",
        "cancel-auth.json",
    )
    for name in bounded_names:
        path = attempt / name
        assert len(str(path.with_suffix(".sha256"))) <= 259
        write_json_with_digest(path, {"value": name})

    assert len(str(request_path)) == 244
    assert len(str(request_path.with_suffix(".sha256"))) == 246
    assert len(str(longest_path)) == 257
    assert len(str(longest_path.with_suffix(".sha256"))) == 259
    assert {len(str(path)) for path in temporary_paths} == {247}
    assert all(path.parent == attempt for path in temporary_paths)
    assert all(path.name.startswith(".q-") for path in temporary_paths)
    assert all(path.name.endswith(".tmp") for path in temporary_paths)
    assert all(len(str(path)) < 260 for path in temporary_paths)

    assert set(link_destinations) == {
        request_path,
        request_path.with_suffix(".sha256"),
        longest_path,
        longest_path.with_suffix(".sha256"),
    } | {
        path
        for name in bounded_names
        for path in (attempt / name, (attempt / name).with_suffix(".sha256"))
    }
    assert set(replace_destinations) == {
        longest_path,
        longest_path.with_suffix(".sha256"),
    }
    assert read_json_with_digest(request_path) == (
        {"value": "request"},
        request_digest,
    )
    assert read_json_with_digest(longest_path) == (
        {"value": "replacement"},
        second_longest_digest,
    )
    assert second_longest_digest != first_longest_digest
    assert not any(path.exists() for path in temporary_paths)


def test_digest_tampering_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    write_json_with_digest(path, {"value": 1})
    path.write_bytes(b'{"value":2}\n')
    with pytest.raises(ReceiptError, match="digest mismatch"):
        read_json_with_digest(path)


def test_event_journal_is_fsynced_schema_compatible_jsonl(tmp_path: Path) -> None:
    journal = EventJournal(
        tmp_path / "events.jsonl",
        run_id="run-1",
        lane_id="lane-a",
        attempt_id="attempt-1",
    )
    first = journal.append(
        phase="request",
        event_name="request_verified",
        status="passed",
        payload={"source": "receipt"},
    )
    second = journal.append(
        phase="receipt",
        event_name="receipt_committed",
        status="passed",
    )
    rows = read_event_journal(journal.path)

    assert [row["sequence"] for row in rows] == [1, 2]
    assert json.loads(first["payload_json"]) == {"source": "receipt"}
    assert second["payload_json"] is None
    table = table_from_rows("events", rows)
    assert table.num_rows == 2


def test_event_payload_is_bounded(tmp_path: Path) -> None:
    journal = EventJournal(
        tmp_path / "events.jsonl",
        run_id="run-1",
        lane_id="lane-a",
        attempt_id="attempt-1",
    )
    with pytest.raises(ReceiptError, match="exceeds"):
        journal.append(
            phase="request",
            event_name="too_large",
            status="failed",
            payload={"detail": "x" * 17_000},
        )
    assert not journal.path.exists()


def test_receipt_verifies_request_binding_and_artifact_hash(tmp_path: Path) -> None:
    attempt = make_attempt(tmp_path)
    artifact = attempt / "messages.txt"
    artifact.write_bytes(b"controller message")
    request, request_sha = read_json_with_digest(attempt / "request.json")
    receipt, _ = read_json_with_digest(attempt / "receipt.json")
    receipt["request_sha256"] = request_sha
    receipt["referenced_artifacts"] = [
        {
            "relative_path": "messages.txt",
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        }
    ]
    write_json_with_digest(attempt / "receipt.json", receipt, replace=True)

    verified = verify_attempt_receipt(attempt)
    assert verified.request == request
    assert verified.receipt["terminal_category"] == "passed"

    artifact.write_bytes(b"tampered")
    with pytest.raises(ReceiptError, match="artifact digest mismatch"):
        verify_attempt_receipt(attempt)


def test_receipt_identity_and_exit_contract_fail_closed(tmp_path: Path) -> None:
    attempt = make_attempt(tmp_path)
    receipt, _ = read_json_with_digest(attempt / "receipt.json")
    receipt["lane_id"] = "different"
    write_json_with_digest(attempt / "receipt.json", receipt, replace=True)
    with pytest.raises(ReceiptError, match="identity mismatch"):
        verify_attempt_receipt(attempt)

    receipt["lane_id"] = "lane-a"
    receipt["worker_exit_code"] = 20
    write_json_with_digest(attempt / "receipt.json", receipt, replace=True)
    with pytest.raises(ReceiptError, match="exit code"):
        verify_attempt_receipt(attempt)


def test_receipt_requires_timezone_aware_commit_time(tmp_path: Path) -> None:
    attempt = make_attempt(tmp_path)
    receipt, _ = read_json_with_digest(attempt / "receipt.json")
    receipt["receipt_committed_at"] = "2026-08-28T12:00:00"
    write_json_with_digest(attempt / "receipt.json", receipt, replace=True)
    with pytest.raises(ReceiptError, match="timezone-aware"):
        verify_attempt_receipt(attempt)


def test_receipt_identity_must_match_its_directory(tmp_path: Path) -> None:
    attempt = make_attempt(tmp_path)
    request, _ = read_json_with_digest(attempt / "request.json")
    request["attempt_id"] = "another-attempt"
    request_sha = write_json_with_digest(attempt / "request.json", request, replace=True)
    receipt, _ = read_json_with_digest(attempt / "receipt.json")
    receipt["attempt_id"] = "another-attempt"
    receipt["request_sha256"] = request_sha
    write_json_with_digest(attempt / "receipt.json", receipt, replace=True)
    with pytest.raises(ReceiptError, match="attempt directory"):
        verify_attempt_receipt(attempt)


def test_immutable_publication_never_overwrites_concurrent_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipts_module = __import__(
        "scripts.qualification.execution_evidence.receipts",
        fromlist=["os"],
    )
    target = tmp_path / "record.json"
    original_link = receipts_module.os.link

    def concurrent_link(source, destination):
        destination = Path(destination)
        if destination == target:
            destination.write_bytes(b"concurrent winner")
        return original_link(source, destination)

    monkeypatch.setattr(receipts_module.os, "link", concurrent_link)
    with pytest.raises(FileExistsError, match="already exists"):
        write_json_with_digest(target, {"value": 1})
    assert target.read_bytes() == b"concurrent winner"


def test_immutable_publication_fails_closed_without_atomic_link_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipts_module = __import__(
        "scripts.qualification.execution_evidence.receipts",
        fromlist=["os"],
    )
    target = tmp_path / "record.json"
    monkeypatch.setattr(
        receipts_module.os,
        "link",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("hard links unavailable")
        ),
    )
    with pytest.raises(ReceiptError, match="no-overwrite publication is unavailable"):
        write_json_with_digest(target, {"value": 1})
    assert not target.exists()


def test_attempt_and_referenced_artifact_links_are_rejected(
    tmp_path: Path,
) -> None:
    attempt = make_attempt(tmp_path / "run")
    alias = tmp_path / "attempt-alias"
    try:
        alias.symlink_to(attempt, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink creation is unavailable")
    with pytest.raises(ReceiptError, match="plain directory"):
        verify_attempt_receipt(alias)

    target = attempt / "target.txt"
    target.write_bytes(b"target")
    linked = attempt / "linked.txt"
    linked.symlink_to(target)
    receipt, _ = read_json_with_digest(attempt / "receipt.json")
    receipt["referenced_artifacts"] = [
        {
            "relative_path": linked.name,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        }
    ]
    write_json_with_digest(attempt / "receipt.json", receipt, replace=True)
    with pytest.raises(ReceiptError, match="linked|not stable and plain"):
        verify_attempt_receipt(attempt)


def test_referenced_artifact_stability_uncertainty_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = make_attempt(tmp_path)
    artifact = attempt / "messages.txt"
    artifact.write_bytes(b"controller message")
    receipt, _ = read_json_with_digest(attempt / "receipt.json")
    receipt["referenced_artifacts"] = [
        {
            "relative_path": artifact.name,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        }
    ]
    write_json_with_digest(attempt / "receipt.json", receipt, replace=True)
    receipts_module = __import__(
        "scripts.qualification.execution_evidence.receipts",
        fromlist=["stable_sha256"],
    )
    monkeypatch.setattr(
        receipts_module,
        "stable_sha256",
        lambda _path: (_ for _ in ()).throw(SnapshotError("changed")),
    )
    with pytest.raises(ReceiptError, match="not stable and plain"):
        verify_attempt_receipt(attempt)


@pytest.mark.parametrize(
    "required",
    [None, [], ["R99"], ["R11", "R11"]],
)
def test_request_required_invariants_are_strict(
    tmp_path: Path,
    required,
) -> None:
    attempt = make_attempt(tmp_path)
    request, _ = read_json_with_digest(attempt / "request.json")
    if required is None:
        request.pop("required_invariants")
    else:
        request["required_invariants"] = required
    request_sha = write_json_with_digest(
        attempt / "request.json",
        request,
        replace=True,
    )
    receipt, _ = read_json_with_digest(attempt / "receipt.json")
    receipt["request_sha256"] = request_sha
    write_json_with_digest(attempt / "receipt.json", receipt, replace=True)
    with pytest.raises(ReceiptError, match="required_invariants"):
        verify_attempt_receipt(attempt)
