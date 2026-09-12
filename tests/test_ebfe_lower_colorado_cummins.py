from pathlib import Path

import pytest

from ras_commander import RasUtils
from ras_commander.sources.base import ModelType
from ras_commander.sources.federal.ebfe_models import RasEbfeModels


def _write_project(folder: Path, name: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.prj").write_text(
        "Proj Title=Test\nCurrent Plan=p01\nPlan File=p01\nGeom File=g01\nFlow File=f01\n",
        encoding="utf-8",
    )
    (folder / f"{name}.p01").write_text(
        "Plan Title=Multiple Run\n"
        "Program Version=4.10\n"
        "Geom File=g01\n"
        "Flow File=f01\n",
        encoding="utf-8",
    )
    (folder / f"{name}.g01").write_text("Geom Title=Test\n", encoding="utf-8")
    (folder / f"{name}.f01").write_text("Flow Title=Test\n", encoding="utf-8")


def test_lower_colorado_metadata_is_steady_and_preserves_provenance():
    metadata = RasEbfeModels.get_model_metadata("12090301")

    assert metadata.source_id == "lower-colorado-cummins"
    assert metadata.model_type == ModelType.STEADY_1D
    assert metadata.hecras_version == "4.1.0"
    assert metadata.file_size_mb == 290_650_116 / (1024 * 1024)
    assert metadata.url.endswith("/12090301_Models.zip")
    assert metadata.extra["qualified_ras_version"] == "6.6"
    assert metadata.extra["project_count"] == 2_378
    assert metadata.extra["nested_project_count"] == 46
    assert metadata.extra["plan_timeout_seconds"] == 600
    assert metadata.extra["profiles_per_plan_exceptions"] == {
        "Walnut Creek-Colorado River/WALNUT 0329": 6,
    }
    assert metadata.extra["plan_flow_corrections"] == {
        "Piney Creek-Colorado River/PINEY 062": {"01": "01"},
        "Piney Creek-Colorado River/PINEY 089": {"01": "01"},
    }
    assert metadata.extra["terrain_required"] is False
    assert {asset["role"] for asset in metadata.extra["source_assets"]} == {
        "models",
        "spatial_data",
        "documents",
    }


def test_ebfe_list_models_honors_model_type_version_and_tags():
    steady = RasEbfeModels.list_models(
        model_type=ModelType.STEADY_1D,
        tags=["steady"],
    )
    source_ids = {metadata.source_id for metadata in steady}

    assert "lower-colorado-cummins" in source_ids
    assert "rio-hondo" in source_ids
    assert all(metadata.model_type == ModelType.STEADY_1D for metadata in steady)
    assert [
        metadata.source_id
        for metadata in RasEbfeModels.list_models(hecras_version="4.1.0")
    ] == ["lower-colorado-cummins"]
    compact = RasEbfeModels.available_models()["lower-colorado-cummins"]
    assert compact["ras_version"] == "6.6"
    assert compact["delivered_ras_version"] == "4.1.0"
    assert compact["qualified_ras_version"] == "6.6"


def test_lower_colorado_organizer_preserves_nested_project_folders(tmp_path):
    source = tmp_path / "raw"
    index_map = source / "Model" / "IndexMap_LCC.pdf"
    index_map.parent.mkdir(parents=True)
    index_map.write_bytes(b"index map")
    _write_project(source / "Model" / "River A" / "DIRECT 001", "DIRECT 001")
    _write_project(
        source / "Model" / "River A" / "GROUP 001" / "NESTED 002",
        "NESTED 002",
    )
    piney_source = (
        source
        / "Model"
        / "Piney Creek-Colorado River"
        / "PINEY 062"
    )
    _write_project(piney_source, "PINEY 062")
    piney_plan = piney_source / "PINEY 062.p01"
    piney_plan.write_text(
        "Plan Title=Multiple Run\n"
        "Program Version=4.10\n"
        "Geom File=g01\n",
        encoding="utf-8",
    )
    piney_plan_before = piney_plan.read_bytes()
    similar_source = (
        source
        / "Model"
        / "Piney Creek-Colorado River"
        / "PINEY 062 COPY"
    )
    _write_project(similar_source, "PINEY 062 COPY")
    similar_plan = similar_source / "PINEY 062 COPY.p01"
    similar_plan.write_text(
        "Plan Title=Multiple Run\n"
        "Program Version=4.10\n"
        "Geom File=g01\n",
        encoding="utf-8",
    )
    projection = source / "Model" / "River A" / "Projection"
    projection.mkdir()
    (projection / "model.prj").write_text(
        'PROJCS["NAD83 / test"]',
        encoding="utf-8",
    )
    (projection / "model.p01").write_text(
        "not a HEC-RAS plan",
        encoding="utf-8",
    )
    output = tmp_path / "organized"

    result = RasEbfeModels.organize_model(
        "12090301",
        downloaded_folder=source,
        output_folder=output,
    )

    assert result == output
    assert (output / "RAS Model" / "River A" / "DIRECT 001" / "DIRECT 001.prj").is_file()
    assert (
        output
        / "RAS Model"
        / "River A"
        / "GROUP 001"
        / "NESTED 002"
        / "NESTED 002.prj"
    ).is_file()
    assert (output / "Documentation" / "IndexMap_LCC.pdf").read_bytes() == b"index map"
    model_log = (output / "agent" / "model_log.md").read_text(encoding="utf-8")
    assert "Total Reaches Available**: 4" in model_log
    assert "Reaches Organized**: 4" in model_log
    assert "Missing Plan-Flow References Corrected**: 1" in model_log
    repaired_plan = (
        output
        / "RAS Model"
        / "Piney Creek-Colorado River"
        / "PINEY 062"
        / "PINEY 062.p01"
    ).read_text(encoding="utf-8")
    assert repaired_plan.splitlines()[:4] == [
        "Plan Title=Multiple Run",
        "Program Version=4.10",
        "Geom File=g01",
        "Flow File=f01",
    ]
    assert piney_plan.read_bytes() == piney_plan_before
    untouched_similar = (
        output
        / "RAS Model"
        / "Piney Creek-Colorado River"
        / "PINEY 062 COPY"
        / "PINEY 062 COPY.p01"
    ).read_text(encoding="utf-8")
    assert "Flow File=" not in untouched_similar


def test_missing_flow_repair_is_idempotent_and_preserves_plan_structure(
    tmp_path,
):
    folder = tmp_path / "PINEY 062"
    _write_project(folder, "PINEY 062")
    plan = folder / "PINEY 062.p01"
    plan.write_bytes(
        b"Plan Title=Multiple Run\r\n"
        b"Geom File=g01\r\n"
        b"BEGIN DESCRIPTION:\r\n"
        b"Flow File=q99\r\n"
        b"END DESCRIPTION\r\n"
    )

    assert RasEbfeModels._insert_missing_steady_flow_reference(
        folder,
        project_name="PINEY 062",
        plan_number="01",
        flow_number="01",
    ) is True
    expected = (
        b"Plan Title=Multiple Run\r\n"
        b"Geom File=g01\r\n"
        b"Flow File=f01\r\n"
        b"BEGIN DESCRIPTION:\r\n"
        b"Flow File=q99\r\n"
        b"END DESCRIPTION\r\n"
    )
    assert plan.read_bytes() == expected
    assert RasEbfeModels._insert_missing_steady_flow_reference(
        folder,
        project_name="PINEY 062",
        plan_number="01",
        flow_number="01",
    ) is False
    assert plan.read_bytes() == expected

    (folder / "PINEY 062.f02").write_text(
        "Flow Title=Unexpected\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="exactly one physical flow file"):
        RasEbfeModels._insert_missing_steady_flow_reference(
            folder,
            project_name="PINEY 062",
            plan_number="01",
            flow_number="01",
        )
    assert plan.read_bytes() == expected


def test_project_discovery_can_include_nested_projects(tmp_path):
    parent = tmp_path / "River A" / "PARENT 001"
    child = parent / "CHILD 002"
    _write_project(parent, "PARENT 001")
    _write_project(child, "CHILD 002")

    default_projects = RasUtils.find_valid_ras_folders(tmp_path)
    nested_projects = RasUtils.find_valid_ras_folders(
        tmp_path,
        include_nested_projects=True,
    )

    assert default_projects == [parent]
    assert set(nested_projects) == {parent, child}


def test_download_model_normalizes_alias_and_respects_existing_output(
    tmp_path,
    monkeypatch,
):
    organized = tmp_path / "LowerColoradoCummins_12090301"
    _write_project(organized / "RAS Model" / "River A" / "MODEL 001", "MODEL 001")
    (organized / "agent").mkdir()
    (organized / "agent" / "model_log.md").write_text(
        "complete",
        encoding="utf-8",
    )

    monkeypatch.setitem(
        RasEbfeModels._MODEL_REGISTRY["lower-colorado-cummins"]["extra"],
        "project_count",
        1,
    )
    result = RasEbfeModels.download_model("12090301", tmp_path)

    assert result.success is True
    assert result.model_path == organized
    assert result.metadata is not None
    assert result.metadata.source_id == "lower-colorado-cummins"


def test_download_model_rejects_incomplete_existing_output(tmp_path):
    organized = tmp_path / "LowerColoradoCummins_12090301"
    organized.mkdir()

    result = RasEbfeModels.download_model("12090301", tmp_path)

    assert result.success is False
    assert "incomplete or invalid" in result.message


def test_download_model_rejects_unimplemented_no_extract_mode(tmp_path):
    result = RasEbfeModels.download_model("12090301", tmp_path, extract=False)

    assert result.success is False
    assert "extract=False is not supported" in result.message


def test_download_source_asset_uses_catalogued_role(tmp_path, monkeypatch):
    calls = {}

    def fake_download_and_extract(url, output_folder, description):
        calls.update(
            url=url,
            output_folder=output_folder,
            description=description,
        )
        return output_folder / "12090301_Documents_extracted"

    monkeypatch.setattr(
        RasEbfeModels,
        "_download_and_extract",
        staticmethod(fake_download_and_extract),
    )

    result = RasEbfeModels.download_source_asset(
        "12090301",
        "documents",
        tmp_path,
    )

    assert result == tmp_path / "12090301_Documents_extracted"
    assert calls["url"].endswith("/12090301_Documents.zip")
    assert calls["output_folder"] == tmp_path
    assert "documents" in calls["description"]
