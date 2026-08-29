from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pyarrow.parquet as pq
import pytest

from scripts.qualification.execution_evidence.schemas import (
    SCHEMAS,
    SchemaValidationError,
    schema_metadata,
    table_from_rows,
    validate_table,
)
from ._helpers import GIT_HEAD, HASH_A, valid_table_rows


pytestmark = pytest.mark.qualification_harness


@pytest.mark.parametrize("table_name", sorted(SCHEMAS))
def test_exact_arrow_schemas_round_trip_parquet(tmp_path, table_name: str) -> None:
    rows = valid_table_rows()[table_name]
    metadata = schema_metadata(
        table_name,
        manifest_sha256=HASH_A,
        git_head=GIT_HEAD,
        created_at=datetime.now(timezone.utc),
    )
    table = table_from_rows(table_name, rows, metadata=metadata)
    output = tmp_path / f"{table_name}.parquet"
    pq.write_table(table, output, compression="zstd")
    restored = pq.read_table(output)

    validate_table(table_name, restored)
    assert restored.schema.remove_metadata() == SCHEMAS[table_name]
    assert restored.schema.metadata[b"manifest_sha256"] == HASH_A.encode()


def test_extra_or_missing_columns_are_rejected() -> None:
    row = valid_table_rows()["lanes"][0]
    with_extra = {**row, "surprise": True}
    with pytest.raises(SchemaValidationError, match="extra"):
        table_from_rows("lanes", [with_extra])

    missing = dict(row)
    missing.pop("detail")
    with pytest.raises(SchemaValidationError, match="missing"):
        table_from_rows("lanes", [missing])


@pytest.mark.parametrize("wall_seconds", [float("nan"), float("inf"), -1.0])
def test_nonfinite_or_negative_duration_is_rejected(wall_seconds: float) -> None:
    row = dict(valid_table_rows()["lanes"][0])
    row["wall_seconds"] = wall_seconds
    with pytest.raises(SchemaValidationError, match="wall_seconds"):
        table_from_rows("lanes", [row])


def test_available_observation_requires_exactly_one_typed_value() -> None:
    row = dict(valid_table_rows()["observations"][0])
    row["value_string"] = "also populated"
    with pytest.raises(SchemaValidationError, match="exactly one value"):
        table_from_rows("observations", [row])


def test_modeled_local_datetime_round_trips_without_invented_timezone() -> None:
    row = dict(valid_table_rows()["observations"][0])
    row.update(
        observation_name="simulation_start",
        channel="filesystem",
        value_type="local_datetime",
        value_bool=None,
        value_string="1999-01-01T12:00:00.123456",
    )

    restored = table_from_rows("observations", [row]).to_pylist()[0]

    assert restored["value_type"] == "local_datetime"
    assert restored["value_string"] == "1999-01-01T12:00:00.123456"
    assert restored["value_timestamp"] is None


def test_local_datetime_rejects_an_attached_timezone() -> None:
    row = dict(valid_table_rows()["observations"][0])
    row.update(
        observation_name="simulation_start",
        channel="filesystem",
        value_type="local_datetime",
        value_bool=None,
        value_string="1999-01-01T12:00:00+00:00",
    )
    with pytest.raises(SchemaValidationError, match="timezone-naive"):
        table_from_rows("observations", [row])


def test_aware_evidence_datetime_remains_a_deterministic_utc_timestamp() -> None:
    row = dict(valid_table_rows()["observations"][0])
    row.update(
        observation_name="result_artifact_modified_at",
        channel="filesystem",
        value_type="timestamp",
        value_bool=None,
        value_timestamp=datetime(
            2026,
            8,
            28,
            12,
            0,
            tzinfo=timezone(timedelta(hours=-5)),
        ),
    )

    restored = table_from_rows("observations", [row]).to_pylist()[0]

    assert restored["value_timestamp"] == datetime(
        2026, 8, 28, 17, 0, tzinfo=timezone.utc
    )


def test_unavailable_observation_cannot_retain_a_value() -> None:
    row = dict(valid_table_rows()["observations"][0])
    row["state"] = "not_inspected"
    with pytest.raises(SchemaValidationError, match="value_type='null'"):
        table_from_rows("observations", [row])


def test_naive_timestamps_are_rejected() -> None:
    row = dict(valid_table_rows()["lanes"][0])
    row["started_at"] = datetime(2026, 8, 28, 12, 0, 0)
    with pytest.raises(SchemaValidationError, match="timezone-aware"):
        table_from_rows("lanes", [row])


def test_invariant_status_is_closed_enum() -> None:
    row = dict(valid_table_rows()["invariants"][0])
    row["status"] = "maybe"
    with pytest.raises(SchemaValidationError, match="status is invalid"):
        table_from_rows("invariants", [row])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observation_name", "invented_observation"),
        ("state", "unknown"),
        ("channel", "mixed_hdf_and_legacy"),
    ],
)
def test_observation_registry_fields_are_closed(field: str, value: str) -> None:
    row = dict(valid_table_rows()["observations"][0])
    row[field] = value
    with pytest.raises(SchemaValidationError, match=f"{field} is"):
        table_from_rows("observations", [row])


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("error_count", -1, "nonnegative"),
        ("warning_count", -1, "nonnegative"),
        ("selected_result_format", "mixed", "selected_result_format"),
        ("terminal_category", "maybe", "terminal_category"),
        ("plan_number", "0١", "two digits"),
    ],
)
def test_lane_claim_enums_and_counts_are_closed(
    field: str,
    value,
    match: str,
) -> None:
    row = dict(valid_table_rows()["lanes"][0])
    row[field] = value
    with pytest.raises(SchemaValidationError, match=match):
        table_from_rows("lanes", [row])


def test_lane_engine_identity_contract_is_coherent() -> None:
    row = dict(valid_table_rows()["lanes"][0])
    row["controller_version"] = "6.6"
    row["controller_progid"] = "RAS66.HECRASController"
    with pytest.raises(SchemaValidationError, match="cannot claim Controller"):
        table_from_rows("lanes", [row])


def test_artifact_existence_and_relative_path_claims_are_coherent() -> None:
    row = dict(valid_table_rows()["artifacts"][0])
    row["relative_path"] = "../escape"
    with pytest.raises(SchemaValidationError, match="POSIX-relative"):
        table_from_rows("artifacts", [row])

    row = dict(valid_table_rows()["artifacts"][0])
    row.update(exists=False, is_file=False, size_bytes=10)
    with pytest.raises(SchemaValidationError, match="retains existence metadata"):
        table_from_rows("artifacts", [row])


def test_invariant_name_must_match_registered_id() -> None:
    row = dict(valid_table_rows()["invariants"][0])
    row["name"] = "Invented meaning"
    with pytest.raises(SchemaValidationError, match="disagrees"):
        table_from_rows("invariants", [row])
