"""Compatibility-break tests for the corrected delete_boundary API."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from ras_commander.RasUnsteady import RasUnsteady


def test_delete_boundary_signature_requires_stage_and_exact_evidence() -> None:
    signature = inspect.signature(RasUnsteady.delete_boundary)

    assert list(signature.parameters) == [
        "staged_project",
        "unsteady_number",
        "boundary_id",
        "expected_source_sha256",
        "expected_block_sha256",
        "expected_bc_type",
        "expected_location_raw",
        "dry_run",
    ]
    assert signature.parameters["unsteady_number"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["dry_run"].default is True


@pytest.mark.parametrize(
    "legacy_arguments",
    [
        {"boundary_index": 0},
        {"river": "River", "reach": "Reach", "river_station": "1000"},
        {"sa_2d_name": "Area", "bc_line": "Line"},
        {"boundary_index": 0, "force": True},
        {"boundary_index": 0, "ras_object": object()},
    ],
)
def test_legacy_direct_path_selectors_are_rejected_before_io(
    tmp_path: Path,
    legacy_arguments: dict[str, object],
) -> None:
    nonexistent = tmp_path / "source-library.u01"

    with pytest.raises(TypeError):
        RasUnsteady.delete_boundary(nonexistent, **legacy_arguments)

    assert not nonexistent.exists()


def test_inspection_signature_is_stage_bound_and_keyword_scoped() -> None:
    signature = inspect.signature(RasUnsteady.inspect_boundary_blocks)

    assert list(signature.parameters) == ["staged_project", "unsteady_number"]
    assert signature.parameters["unsteady_number"].kind is inspect.Parameter.KEYWORD_ONLY


def test_boundary_evidence_and_error_types_are_exported() -> None:
    import ras_commander
    from ras_commander import RasBoundary

    names = (
        "BoundaryMutationResult",
        "BoundaryMutationError",
        "BoundaryStageOwnershipError",
        "BoundarySelectorError",
        "BoundaryStaleEvidenceError",
        "BoundaryFormatError",
        "BoundaryPublicationError",
        "BoundaryPostPublicationError",
    )
    for name in names:
        assert getattr(ras_commander, name) is getattr(RasBoundary, name)
        assert name in ras_commander.__all__
