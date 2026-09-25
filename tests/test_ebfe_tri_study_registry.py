from __future__ import annotations

from pathlib import Path

import pytest

from ras_commander.sources import RasEbfeModels
from ras_commander.sources.base import ModelType


@pytest.mark.parametrize(
    ("alias", "slug", "huc8", "model_type", "version"),
    [
        ("Pedernales", "pedernales", "12090206", ModelType.STEADY_1D, "4.1.0"),
        ("12100304", "cibolo", "12100304", ModelType.UNSTEADY_2D, "5.0.7"),
        ("Medina", "medina", "12100302", ModelType.UNSTEADY_2D, "6.4.1"),
    ],
)
def test_tri_study_aliases_and_public_metadata(
    alias: str,
    slug: str,
    huc8: str,
    model_type: ModelType,
    version: str,
) -> None:
    assert RasEbfeModels.normalize_model_key(alias) == slug
    metadata = RasEbfeModels.get_model_metadata(alias)
    assert metadata.source_id == slug
    assert metadata.location == huc8
    assert metadata.model_type == model_type
    assert metadata.hecras_version == version
    assert metadata.extra["source_program"] == "fema_ebfe"
    assert len(metadata.extra["source_assets"]) == 1
    assert metadata.extra["source_assets"][0]["extract"] is False


def test_pedernales_registry_records_full_corpus_runtime_qualification() -> None:
    metadata = RasEbfeModels.get_model_metadata("12090206")

    assert metadata.extra["validation_status"] == "qualified"
    assert metadata.extra["validation_level"] == "steady_plan_completion"
    assert metadata.extra["hec_ras_executed"] is True
    assert metadata.extra["validation_scope"] == "isolated_copy"
    assert metadata.extra["qualified_plan"] == {
        "plan": "01",
        "project_count": 530,
        "passed_project_count": 530,
        "execution_version": "6.6",
        "num_cores": 2,
    }
    assert metadata.extra["downstream_usable"] is True
    assert metadata.extra["reproducible"] is True


def test_cibolo_registry_records_unsteady_start_qualification() -> None:
    metadata = RasEbfeModels.get_model_metadata("12100304")

    assert metadata.extra["validation_status"] == "qualified"
    assert metadata.extra["validation_level"] == "unsteady_start"
    assert metadata.extra["validation_scope"] == "isolated_copy"
    assert metadata.extra["hec_ras_executed"] is True
    assert metadata.extra["qualified_plan"] == {
        "project": "Cibolo",
        "plan": "14",
        "geometry": "05",
        "unsteady": "02",
        "title": "Cibolo100YR",
        "execution_version": "5.0.7",
        "num_cores": 2,
    }
    assert metadata.extra["downstream_usable"] is True
    assert metadata.extra["reproducible"] is True


def test_medina_registry_preserves_partial_qualification_and_critical_block() -> None:
    metadata = RasEbfeModels.get_model_metadata("12100302")

    assert metadata.extra["validation_status"] == "blocked_source_gap"
    assert metadata.extra["validation_level"] == "partial_unsteady_start"
    assert metadata.extra["hec_ras_executed"] is True
    assert metadata.extra["qualified_project_count"] == 4
    assert metadata.extra["blocked_project_count"] == 1
    projects = metadata.extra["projects"]
    assert all(
        projects[name]["validation_status"] == "qualified"
        and projects[name]["validation_level"] == "unsteady_start"
        and projects[name]["hec_ras_executed"] is True
        for name in ("Leon1", "Leon2", "Leon3", "MiddleLowerMedina")
    )
    upper = projects["UpperMedinaHeadwaters"]
    assert upper["validation_status"] == "blocked_source_gap"
    assert upper["terrain_source_complete"] is False
    assert upper["hec_ras_executed"] is False
    assert metadata.extra["downstream_usable"] is False
    assert metadata.extra["reproducible"] is False


@pytest.mark.parametrize("alias", ["12090206", "12100304", "12100302"])
def test_invalid_existing_specialized_target_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alias: str,
) -> None:
    metadata = RasEbfeModels.get_model_metadata(alias)
    target = tmp_path / metadata.name
    target.mkdir()
    (target / "do-not-replace.txt").write_text("preserve", encoding="utf-8")
    monkeypatch.setattr(
        RasEbfeModels,
        "_organized_model_is_reusable",
        staticmethod(lambda *_args, **_kwargs: False),
    )
    called = False

    def forbidden_organize(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("organizer must not run over an invalid existing target")

    monkeypatch.setattr(RasEbfeModels, "organize_model", staticmethod(forbidden_organize))

    result = RasEbfeModels.download_model(alias, tmp_path)

    assert result.success is False
    assert "Preserve it for audit" in result.message
    assert called is False
    assert (target / "do-not-replace.txt").read_text(encoding="utf-8") == "preserve"
