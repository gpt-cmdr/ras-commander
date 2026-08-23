"""Synthetic proof tests for exact, stage-bound boundary deletion."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pandas as pd
import pytest

import ras_commander.RasBoundary as boundary_module
from ras_commander.RasBoundary import (
    BOUNDARY_BLOCK_COLUMNS,
    BoundaryFormatError,
    BoundaryPostPublicationError,
    BoundaryPublicationError,
    BoundarySelectorError,
    BoundaryStaleEvidenceError,
)
from ras_commander.RasProject import StageProjectResult, _tree_snapshot
from ras_commander.RasUnsteady import RasUnsteady
from ras_commander.schemas import DATAFRAME_SCHEMAS


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class _SyntheticRasPrj:
    def __init__(self, project_file: Path, unsteady_file: Path) -> None:
        self.prj_file = project_file
        self.unsteady_df = pd.DataFrame(
            [{"unsteady_number": "01", "full_path": unsteady_file}]
        )
        self.boundaries_df = pd.DataFrame()
        self.fail_refresh = False

    def get_boundary_conditions(self) -> pd.DataFrame:
        if self.fail_refresh:
            raise RuntimeError("injected refresh failure")
        raw = Path(self.unsteady_df.iloc[0]["full_path"]).read_bytes()
        count = sum(
            line.startswith(b"Boundary Location=") for line in raw.splitlines()
        )
        return pd.DataFrame(
            [{"unsteady_number": "01"} for _ in range(count)]
        )


def _make_stage(tmp_path: Path, raw: bytes) -> StageProjectResult:
    source_root = tmp_path / "synthetic-source"
    source_root.mkdir()
    source_project = source_root / "Model.prj"
    source_project.write_bytes(b"Proj Title=Synthetic\n")

    stage_root = tmp_path / "synthetic-stage"
    stage_root.mkdir()
    project_file = stage_root / "Model.prj"
    project_file.write_bytes(source_project.read_bytes())
    unsteady_file = stage_root / "Model.u01"
    unsteady_file.write_bytes(raw)
    metadata = stage_root / ".ras-commander"
    metadata.mkdir()
    manifest = {
        "schema_version": 1,
        "operation_id": "synthetic-boundary-test",
        "source_project_file": str(source_project),
        "destination_project_file": str(project_file),
        "source_fingerprint_before": _sha256(source_project.read_bytes()),
        "source_fingerprint_after": _sha256(source_project.read_bytes()),
        "copied_fingerprint": "0" * 64,
        "copied_file_count": 2,
        "copied_bytes": project_file.stat().st_size + unsteady_file.stat().st_size,
        "execution_readiness": "ready",
        "artifacts": [
            {
                "relative_path": "Model.prj",
                "provenance": "copied_source",
                "size_bytes": project_file.stat().st_size,
                "sha256": _sha256(project_file.read_bytes()),
            },
            {
                "relative_path": "Model.u01",
                "provenance": "copied_source",
                "size_bytes": len(raw),
                "sha256": _sha256(raw),
            },
            {
                "relative_path": ".ras-commander/stage.json",
                "provenance": "generated_stage_metadata",
            },
        ],
    }
    (metadata / "stage.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _, published_fingerprint, _ = _tree_snapshot(stage_root)
    ras_object = _SyntheticRasPrj(project_file, unsteady_file)
    return StageProjectResult(
        source_project_file=source_project,
        destination_project_file=project_file,
        destination_root=stage_root,
        source_fingerprint_before=manifest["source_fingerprint_before"],
        source_fingerprint_after=manifest["source_fingerprint_after"],
        copied_fingerprint=manifest["copied_fingerprint"],
        published_fingerprint=published_fingerprint,
        copied_file_count=2,
        copied_bytes=manifest["copied_bytes"],
        publication_state="published",
        execution_readiness="ready",
        assets=pd.DataFrame(),
        ras_object=ras_object,
    )


def _default_raw(newline: bytes = b"\r\n") -> bytes:
    lines = (
        b"Flow Title=Synthetic",
        b"Program Version=6.60",
        b"Boundary Location=River,Reach,1000,,,,,",
        b"Interval=1HOUR",
        b"Lateral Inflow Hydrograph= 2",
        b"       1       2",
        b"Use DSS=False",
        b"Boundary Location=,,,,,Area 2D,,Downstream,",
        b"Friction Slope=0.001,0",
        b"Met Point Raster Parameters=,,,,",
        b"Precipitation Mode=Disable",
    )
    return newline.join(lines) + newline


def _selector(row: pd.Series) -> dict[str, object]:
    return {
        "unsteady_number": str(row["unsteady_number"]),
        "boundary_id": str(row["boundary_id"]),
        "expected_source_sha256": str(row["owner_sha256"]),
        "expected_block_sha256": str(row["block_sha256"]),
        "expected_bc_type": str(row["bc_type"]),
        "expected_location_raw": str(row["boundary_location_raw"]),
    }


def test_inspect_returns_exact_arrow_snapshot_for_1d_and_2d(tmp_path: Path) -> None:
    stage = _make_stage(tmp_path, _default_raw())

    inventory = RasUnsteady.inspect_boundary_blocks(stage, unsteady_number="01")

    schema_columns = DATAFRAME_SCHEMAS["boundary_block_inventory"]["columns"]
    assert tuple(inventory.columns) == BOUNDARY_BLOCK_COLUMNS == tuple(
        column["name"] for column in schema_columns
    )
    assert {
        column: str(inventory[column].dtype) for column in inventory.columns
    } == {
        column["name"]: column["dtype"] for column in schema_columns
    }
    assert len(inventory) == 2
    assert inventory["boundary_id"].is_unique
    assert inventory["location_kind"].tolist() == ["1d", "2d"]
    assert inventory["bc_type"].tolist() == [
        "Lateral Inflow Hydrograph",
        "Normal Depth",
    ]
    assert inventory["newline"].tolist() == ["CRLF", "CRLF"]
    assert inventory["encoding"].tolist() == ["ascii", "ascii"]


def test_preview_is_no_write_and_apply_is_exact_byte_splice(tmp_path: Path) -> None:
    raw = _default_raw()
    stage = _make_stage(tmp_path, raw)
    target = stage.destination_root / "Model.u01"
    inventory = RasUnsteady.inspect_boundary_blocks(stage, unsteady_number="01")
    row = inventory.iloc[0]
    expected = raw[: int(row["start_byte"])] + raw[int(row["end_byte_exclusive"]) :]

    preview = RasUnsteady.delete_boundary(stage, **_selector(row))

    assert preview.state == "previewed"
    assert preview.result_sha256 == _sha256(expected)
    assert target.read_bytes() == raw
    with pytest.raises(TypeError, match="no truth value"):
        bool(preview)
    assert not list(target.parent.glob(".*.ras-boundary-*.tmp"))
    assert not list(target.parent.parent.glob(".*.boundary-mutation.lock"))

    applied = RasUnsteady.delete_boundary(stage, **_selector(row), dry_run=False)

    assert applied.state == "applied"
    assert applied.boundaries_df_refreshed is True
    assert target.read_bytes() == expected
    assert not Path(str(target) + ".bak").exists()
    assert not list(target.parent.glob(".*.ras-boundary-*.tmp"))
    assert not list(target.parent.parent.glob(".*.boundary-mutation.lock"))


@pytest.mark.parametrize(
    ("field", "replacement", "error_type", "reason_code"),
    [
        (
            "expected_source_sha256",
            "0" * 64,
            BoundaryStaleEvidenceError,
            "source_digest_mismatch",
        ),
        (
            "expected_block_sha256",
            "0" * 64,
            BoundaryStaleEvidenceError,
            "block_digest_mismatch",
        ),
        (
            "expected_bc_type",
            "Stage Hydrograph",
            BoundarySelectorError,
            "boundary_type_mismatch",
        ),
        (
            "expected_location_raw",
            "River,Reach,9999,,,,,",
            BoundarySelectorError,
            "boundary_location_mismatch",
        ),
    ],
)
def test_redundant_confirmation_mismatch_never_writes(
    tmp_path: Path,
    field: str,
    replacement: str,
    error_type: type[Exception],
    reason_code: str,
) -> None:
    raw = _default_raw()
    stage = _make_stage(tmp_path, raw)
    row = RasUnsteady.inspect_boundary_blocks(stage, unsteady_number="01").iloc[0]
    arguments = _selector(row)
    arguments[field] = replacement

    with pytest.raises(error_type, match=reason_code):
        RasUnsteady.delete_boundary(stage, **arguments, dry_run=False)

    assert (stage.destination_root / "Model.u01").read_bytes() == raw


def test_stale_inventory_after_content_or_identity_change_never_writes(
    tmp_path: Path,
) -> None:
    raw = _default_raw()
    stage = _make_stage(tmp_path, raw)
    target = stage.destination_root / "Model.u01"
    row = RasUnsteady.inspect_boundary_blocks(stage, unsteady_number="01").iloc[0]

    replacement = target.with_name("replacement.u01")
    replacement.write_bytes(raw)
    os.replace(replacement, target)

    with pytest.raises(BoundaryStaleEvidenceError, match="boundary_id_not_current"):
        RasUnsteady.delete_boundary(stage, **_selector(row), dry_run=False)

    assert target.read_bytes() == raw


def test_unrelated_stage_drift_invalidates_inventory(tmp_path: Path) -> None:
    stage = _make_stage(tmp_path, _default_raw())
    (stage.destination_root / "Model.prj").write_bytes(b"changed")

    with pytest.raises(BoundaryStaleEvidenceError, match="stage_population_changed"):
        RasUnsteady.inspect_boundary_blocks(stage, unsteady_number="01")


def test_duplicate_blocks_have_distinct_ids_and_exact_occurrence_is_removed(
    tmp_path: Path,
) -> None:
    newline = b"\n"
    block = newline.join(
        (
            b"Boundary Location=River,Reach,1000,,,,,",
            b"Interval=1HOUR",
            b"Lateral Inflow Hydrograph=0",
            b"Use DSS=False",
        )
    ) + newline
    raw = b"Flow Title=Synthetic\n" + block + block + b"Precipitation Mode=Disable\n"
    stage = _make_stage(tmp_path, raw)
    inventory = RasUnsteady.inspect_boundary_blocks(stage, unsteady_number="01")

    assert inventory["block_sha256"].nunique() == 1
    assert inventory["boundary_id"].nunique() == 2
    assert inventory["occurrence_ordinal"].tolist() == [0, 1]
    selected = inventory.iloc[1]

    result = RasUnsteady.delete_boundary(
        stage,
        **_selector(selected),
        dry_run=False,
    )

    assert result.boundary_index == 1
    assert (stage.destination_root / "Model.u01").read_bytes() == (
        b"Flow Title=Synthetic\n" + block + b"Precipitation Mode=Disable\n"
    )


@pytest.mark.parametrize(
    ("raw", "reason_code"),
    [
        (
            b"Flow Title=Synthetic\r\n"
            b"Boundary Location=River,Reach,1000,,,,,\n"
            b"Flow Hydrograph=0\n",
            "mixed_newlines",
        ),
        (
            b"Flow Title=Synthetic\n"
            b"Boundary Location=River,Reach,1000,,,,,\n"
            b"Unknown Future Boundary=1\n",
            "ambiguous_boundary_type",
        ),
        (
            b"Flow Title=Synthetic\n"
            b"Boundary Location=River,Reach,1000,,,,,\n"
            b"Flow Hydrograph=0\n"
            b"Future Global Setting=1\n",
            "unsupported_final_block_extent",
        ),
        (
            b"\xff\xfeF\x00l\x00o\x00w\x00\n\x00",
            "unsupported_encoding",
        ),
    ],
)
def test_ambiguous_formats_fail_closed(
    tmp_path: Path,
    raw: bytes,
    reason_code: str,
) -> None:
    stage = _make_stage(tmp_path, raw)

    with pytest.raises(BoundaryFormatError, match=reason_code):
        RasUnsteady.inspect_boundary_blocks(stage, unsteady_number="01")


def test_gate_block_accepts_multiple_markers_for_same_canonical_type(
    tmp_path: Path,
) -> None:
    raw = (
        b"Flow Title=Synthetic\r"
        b"Boundary Location=River,Reach,1000,,,,,\r"
        b"Gate Name=Gate A\r"
        b"Gate Openings=0\r"
        b"Precipitation Mode=Disable\r"
    )
    stage = _make_stage(tmp_path, raw)

    inventory = RasUnsteady.inspect_boundary_blocks(stage, unsteady_number="01")

    assert len(inventory) == 1
    assert inventory.iloc[0]["bc_type"] == "Gate Opening"
    assert inventory.iloc[0]["newline"] == "CR"


@pytest.mark.parametrize(
    ("encoding", "bom", "location", "expected_encoding"),
    [
        ("utf-8", b"\xef\xbb\xbf", "Rivière,Reach,1000,,,,,", "utf-8-sig"),
        ("cp1252", b"", "Café,Reach,1000,,,,,", "cp1252"),
    ],
)
def test_encoding_and_bom_are_preserved_on_exact_apply(
    tmp_path: Path,
    encoding: str,
    bom: bytes,
    location: str,
    expected_encoding: str,
) -> None:
    text = (
        "Flow Title=Synthetic\n"
        f"Boundary Location={location}\n"
        "Lateral Inflow Hydrograph=0\n"
        "Boundary Location=,,,,,Area,,Line,\n"
        "Friction Slope=0.001\n"
        "Precipitation Mode=Disable\n"
    )
    raw = bom + text.encode(encoding)
    stage = _make_stage(tmp_path, raw)
    inventory = RasUnsteady.inspect_boundary_blocks(stage, unsteady_number="01")
    selected = inventory.iloc[1]
    expected = raw[: int(selected["start_byte"])] + raw[
        int(selected["end_byte_exclusive"]) :
    ]

    result = RasUnsteady.delete_boundary(
        stage,
        **_selector(selected),
        dry_run=False,
    )

    assert result.encoding == expected_encoding
    assert (stage.destination_root / "Model.u01").read_bytes() == expected
    assert expected.startswith(bom)


def test_replace_failure_leaves_original_and_cleans_owned_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _default_raw()
    stage = _make_stage(tmp_path, raw)
    row = RasUnsteady.inspect_boundary_blocks(stage, unsteady_number="01").iloc[0]

    def fail_replace(source: Path, target: Path) -> None:
        raise PermissionError(source, target)

    monkeypatch.setattr(boundary_module.os, "replace", fail_replace)
    with pytest.raises(BoundaryPublicationError, match="atomic_replace_failed") as exc:
        RasUnsteady.delete_boundary(stage, **_selector(row), dry_run=False)

    assert exc.value.mutation_applied is False
    assert (stage.destination_root / "Model.u01").read_bytes() == raw
    assert not list(stage.destination_root.glob(".*.ras-boundary-*.tmp"))
    assert not list(stage.destination_root.parent.glob(".*.boundary-mutation.lock"))


def test_refresh_failure_reports_that_atomic_mutation_was_committed(
    tmp_path: Path,
) -> None:
    raw = _default_raw()
    stage = _make_stage(tmp_path, raw)
    target = stage.destination_root / "Model.u01"
    row = RasUnsteady.inspect_boundary_blocks(stage, unsteady_number="01").iloc[0]
    expected = raw[: int(row["start_byte"])] + raw[int(row["end_byte_exclusive"]) :]
    stage.ras_object.fail_refresh = True

    with pytest.raises(
        BoundaryPostPublicationError,
        match="boundaries_df_refresh_failed",
    ) as exc:
        RasUnsteady.delete_boundary(stage, **_selector(row), dry_run=False)

    assert exc.value.mutation_applied is True
    assert target.read_bytes() == expected
