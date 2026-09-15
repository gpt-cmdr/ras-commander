"""Contract tests for Alabama Effective and Preliminary model discovery."""

from __future__ import annotations

from typing import Any

import pytest

from ras_commander.sources.base import ModelType
from ras_commander.sources.state import (
    AlabamaFloodModels,
    AlabamaModelClassification,
)


def _model(model_id: str, classification: str, county: str) -> dict[str, Any]:
    return {
        "attributes": {
            "OBJECTID": len(model_id),
            "Type": classification,
            "Zone": "Zone A",
            "Name": f"{county} Creek",
            "HUC8_Name": "Upper Coosa",
            "Basin": "Coosa",
            "County": county,
            "FIPS": "01001",
            "ModelID": model_id,
            "GlobalID": f"global-{model_id}",
        }
    }


def _link(model_id: str, classification: str, county: str) -> dict[str, Any]:
    return {
        "attributes": {
            "OBJECTID": 100 + len(model_id),
            "ModelID": model_id,
            "FileName": f"{county} Creek.zip",
            "FileType": "zip",
            "WebPath": (
                "https://files.alabamaflood.com/Models/"
                f"{classification}/{county}%20Creek.zip"
            ),
        }
    }


@pytest.fixture
def catalog_rows(monkeypatch):
    models = [
        _model("effective-1", "Effective", "Autauga"),
        _model("preliminary-1", "Preliminary", "Cleburne"),
        _model("ble-1", "Base Level Engineering", "Lee"),
    ]
    links = [
        _link("effective-1", "Effective", "Autauga"),
        _link("preliminary-1", "Preliminary", "Cleburne"),
        _link("ble-1", "BLE", "Lee"),
    ]

    def fake_query(layer_id, where, *args, **kwargs):
        del args, kwargs
        if layer_id == AlabamaFloodModels._LINK_LAYER_ID:
            requested = {
                row["attributes"]["ModelID"]
                for row in models
                if row["attributes"]["ModelID"] in where
            }
            return [
                row for row in links if row["attributes"]["ModelID"] in requested
            ]
        if "ModelID =" in where:
            return [
                row
                for row in models
                if row["attributes"]["ModelID"] in where
                and row["attributes"]["Type"] in where
            ]
        return [row for row in models if row["attributes"]["Type"] in where]

    monkeypatch.setattr(
        AlabamaFloodModels,
        "_query_layer",
        staticmethod(fake_query),
    )
    return models, links


def test_default_scope_lists_effective_and_preliminary_without_ble(catalog_rows):
    models = AlabamaFloodModels.list_models()

    assert {item.source_id for item in models} == {
        "effective-1",
        "preliminary-1",
    }
    assert {item.extra["classification"] for item in models} == {
        "Effective",
        "Preliminary",
    }
    preliminary = next(item for item in models if item.source_id == "preliminary-1")
    assert "non-regulatory" in preliminary.tags
    assert preliminary.model_type == ModelType.UNKNOWN


def test_direct_provider_can_query_each_classification_or_all(catalog_rows):
    effective = AlabamaFloodModels.list_models(
        classification=AlabamaModelClassification.EFFECTIVE,
        county="Autauga",
    )
    all_models = AlabamaFloodModels.list_models(classification="all")

    assert [item.source_id for item in effective] == ["effective-1"]
    assert {item.source_id for item in all_models} == {
        "effective-1",
        "preliminary-1",
        "ble-1",
    }


def test_model_lookup_and_filters_preserve_public_identity(catalog_rows):
    model = AlabamaFloodModels.get_model_metadata(
        "preliminary-1", classification="prelim"
    )

    assert model.source_name == "Alabama Flood Models"
    assert model.url.startswith("https://files.alabamaflood.com/Models/Preliminary/")
    assert AlabamaFloodModels.list_models(location="cleburne", tags=["PRELIMINARY"])
    assert AlabamaFloodModels.list_models(model_type=ModelType.STEADY_1D) == []
    assert AlabamaFloodModels.list_models(hecras_version="6.6") == []
    assert AlabamaFloodModels.list_models(limit=0) == []


def test_invalid_classification_is_rejected(catalog_rows):
    with pytest.raises(ValueError, match="Unknown Alabama model classification"):
        AlabamaFloodModels.list_models(classification="draft")


def test_public_exports_are_available():
    from ras_commander.sources import AlabamaFloodModels as Exported

    assert Exported is AlabamaFloodModels


def test_download_namespaces_same_filename_from_distinct_urls(
    monkeypatch, tmp_path, catalog_rows
):
    second = _model("effective-2", "Effective", "Baldwin")
    second["attributes"]["Name"] = "Autauga Creek"
    models, links = catalog_rows
    models.append(second)
    links.append(
        {
            "attributes": {
                "OBJECTID": 999,
                "ModelID": "effective-2",
                "FileName": "Autauga Creek.zip",
                "FileType": "zip",
                "WebPath": (
                    "https://files.alabamaflood.com/Models/Effective/"
                    "Baldwin/Autauga%20Creek.zip"
                ),
            }
        }
    )
    destinations = []

    def fake_download(cls, source_url, destination, overwrite=False):
        del cls, source_url, overwrite
        destinations.append(destination)
        return {"source_url": "test", "size_bytes": 1, "etag": "etag"}

    monkeypatch.setattr(AlabamaFloodModels, "_download_file", classmethod(fake_download))

    first = AlabamaFloodModels.download_model(
        "effective-1", tmp_path, extract=False
    )
    second_result = AlabamaFloodModels.download_model(
        "effective-2", tmp_path, extract=False
    )

    assert first.success and second_result.success
    assert destinations[0].name == destinations[1].name == "Autauga_Creek.zip"
    assert destinations[0].parent != destinations[1].parent


@pytest.mark.parametrize(
    "method",
    [
        "build_watershed_manifest",
        "list_watershed_models",
        "resolve_watershed_directory",
        "download_watershed",
        "organize_watershed",
        "build_watershed_delivery_inventory",
    ],
)
def test_ble_only_watershed_methods_are_explicitly_blocked(method):
    with pytest.raises(NotImplementedError, match="AlabamaBleModels"):
        getattr(AlabamaFloodModels, method)("03130002")
