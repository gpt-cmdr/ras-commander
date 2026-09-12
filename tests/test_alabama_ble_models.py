"""Contract tests for the Alabama BLE watershed source adapter.

The fixtures deliberately model the public ArcGIS service rather than a local
copy of the Alabama corpus.  No live network requests or HEC-RAS processes are
used here.
"""

from __future__ import annotations

from collections import Counter
import io
import importlib
import json
from pathlib import Path
import stat
from typing import Any
from urllib.parse import quote
import zipfile

import pandas as pd
import pytest

from ras_commander.sources.base import ModelMetadata, ModelType, SourceStatus
import ras_commander.sources.state.alabama_ble as alabama_module
from ras_commander.sources.state.alabama_ble import AlabamaBleModels


HUC8 = "03130002"
STUDY_KEY = f"AL{HUC8}"
HUC8_NAME = "Middle Chattahoochee-Lake Harding"
BASIN_COUNTS = {
    "Halawakee Creek": 20,
    "Moores Creek": 13,
    "Osanippa Creek": 42,
    "Oseligee Creek": 46,
    "Stroud Creek": 21,
    "Town Creek": 5,
    "Wacoochee Creek": 15,
    "Wehadkee Creek": 35,
}


def _model_feature(
    ordinal: int,
    *,
    basin: str,
    model_id: str | None = None,
    name: str | None = None,
    huc8_name: str = HUC8_NAME,
) -> dict[str, Any]:
    model_id = model_id or f"model-{ordinal:03d}"
    name = name or f"MODEL {ordinal:03d} BLE"
    return {
        "attributes": {
            "OBJECTID": ordinal,
            "Type": "Base Level Engineering",
            "Zone": "Zone A",
            "Name": name,
            "HUC8_Name": huc8_name,
            "Basin": basin,
            "County": "Lee",
            "FIPS": "01081",
            # This is intentionally an unusable publisher-local staging path.
            "URL": rf"F:\\AL_Website\\PDS_Data\\Models\\{name}.zip",
            "ModelID": model_id,
            "GlobalID": f"{{00000000-0000-0000-0000-{ordinal:012d}}}",
        }
    }


def _model_link(
    ordinal: int,
    *,
    basin: str,
    model_id: str | None = None,
    name: str | None = None,
    web_path: str | None = None,
) -> dict[str, Any]:
    model_id = model_id or f"model-{ordinal:03d}"
    name = name or f"MODEL {ordinal:03d} BLE"
    file_name = f"{name}.zip"
    encoded_huc = quote(HUC8_NAME, safe="")
    encoded_basin = quote(basin, safe="")
    encoded_name = quote(name, safe="")
    web_path = web_path or (
        "https://files.alabamaflood.com/Models/BLE/"
        f"{encoded_huc}/{encoded_basin}/{encoded_name}/{encoded_name}.zip"
    )
    return {
        "attributes": {
            "OBJECTID": ordinal + 10_000,
            "ModelID": model_id,
            "FileName": file_name,
            "FileType": "zip",
            "RelativePath": rf"BLE\\{basin}\\{file_name}",
            "LocalPath": rf"F:\\AL_Website\\PDS_Data\\{file_name}",
            "WebPath": web_path,
        }
    }


def _full_watershed_service_rows() -> tuple[list[dict], list[dict]]:
    features: list[dict] = []
    links: list[dict] = []
    ordinal = 1
    # Reverse the service order to prove that the public manifest orders itself.
    for basin, count in reversed(tuple(BASIN_COUNTS.items())):
        for _ in range(count):
            features.append(_model_feature(ordinal, basin=basin))
            links.append(_model_link(ordinal, basin=basin))
            ordinal += 1
    features.reverse()
    links.reverse()
    return features, links


def _patch_service_rows(
    monkeypatch: pytest.MonkeyPatch,
    features: list[dict],
    links: list[dict],
) -> None:
    basin_counts = Counter(
        str(row["attributes"].get("Basin") or "") for row in features
    )
    monkeypatch.setitem(
        AlabamaBleModels._KNOWN_QUALIFICATIONS,
        HUC8,
        {
            "model_type": ModelType.STEADY_1D,
            "hecras_version": "6.20",
            "expected_model_count": len(features),
            "expected_basins": dict(basin_counts),
        },
    )

    def fake_query_layer(layer_id, *args, **kwargs):
        if layer_id == AlabamaBleModels._MODEL_LAYER_ID:
            return [item["attributes"] for item in features]
        if layer_id == AlabamaBleModels._LINK_LAYER_ID:
            return [item["attributes"] for item in links]
        raise AssertionError(f"unexpected layer {layer_id}")

    monkeypatch.setattr(
        AlabamaBleModels,
        "_query_layer",
        staticmethod(fake_query_layer),
    )


def _metadata(
    source_id: str,
    *,
    basin: str,
    name: str,
    url: str,
    file_name: str | None = None,
    size: int | None = None,
    etag: str | None = None,
) -> ModelMetadata:
    extra: dict[str, object] = {
        "huc8": HUC8,
        "study_key": STUDY_KEY,
        "huc8_name": HUC8_NAME,
        "basin": basin,
        "file_name": file_name or f"{name}.zip",
        "archive_name": file_name or f"{name}.zip",
        "source_prefix": url.rsplit("/", 2)[0] + "/",
    }
    if size is not None:
        extra["size_bytes"] = size
    if etag is not None:
        extra["etag"] = etag
    return ModelMetadata(
        source_name="Alabama BLE",
        source_id=source_id,
        name=name,
        location=f"{HUC8_NAME}, Alabama",
        model_type=ModelType.STEADY_1D,
        url=url,
        file_size_mb=None if size is None else size / (1024 * 1024),
        tags=["alabama", "ble", "steady", "1d", HUC8],
        extra=extra,
    )


def _patch_qualification(
    monkeypatch: pytest.MonkeyPatch,
    basin_counts: dict[str, int],
) -> None:
    monkeypatch.setattr(
        AlabamaBleModels,
        "_KNOWN_QUALIFICATIONS",
        {
            HUC8: {
                "model_type": ModelType.STEADY_1D,
                "expected_model_count": sum(basin_counts.values()),
                "expected_basins": dict(basin_counts),
            }
        },
    )


def _source_manifest_header(records: list[dict[str, object]]) -> dict[str, object]:
    basin_counts = dict(
        sorted(Counter(str(record.get("basin") or "") for record in records).items())
    )
    return {
        "schema_name": AlabamaBleModels._MANIFEST_SCHEMA_NAME,
        "contract_version": AlabamaBleModels._MANIFEST_CONTRACT_VERSION,
        "schema_version": 1,
        "source_name": AlabamaBleModels.SOURCE_NAME,
        "source_service": AlabamaBleModels._SERVICE_URL,
        "source_url": AlabamaBleModels._SERVICE_URL,
        "source_policy": AlabamaBleModels._SOURCE_POLICY,
        "status": "complete",
        "mode": "download",
        "study_key": STUDY_KEY,
        "huc8": HUC8,
        "expected_model_count": len(records),
        "model_count": len(records),
        "actual_record_count": len(records),
        "basin_count": len(basin_counts),
        "basin_counts": basin_counts,
        "records": records,
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (HUC8, HUC8),
        (STUDY_KEY, HUC8),
        (f"{STUDY_KEY}_AlabamaBLEMiddleChattahoocheeLakeHarding", HUC8),
        (f"  {STUDY_KEY.lower()}  ", HUC8),
    ],
)
def test_normalize_huc8_accepts_huc_and_alabama_study_keys(value, expected):
    assert AlabamaBleModels.normalize_huc8(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "AL", "3130002", "031300020", "TX03130002", "AL12X30002"],
)
def test_normalize_huc8_rejects_malformed_or_non_alabama_keys(value):
    with pytest.raises(ValueError, match="HUC8|Alabama|AL"):
        AlabamaBleModels.normalize_huc8(value)


def test_source_contract_is_available_state_source(monkeypatch):
    monkeypatch.setattr(
        AlabamaBleModels,
        "_request_json",
        staticmethod(
            lambda url, params: {
                "layers": [{"id": AlabamaBleModels._MODEL_LAYER_ID}],
                "tables": [{"id": AlabamaBleModels._LINK_LAYER_ID}],
            }
        ),
    )
    source = AlabamaBleModels()

    assert source.source_name == "Alabama BLE"
    assert source.source_type == "state"
    assert source.get_source_status() == SourceStatus.AVAILABLE


def test_list_and_resolve_watershed_directory_use_joined_source_prefix(monkeypatch):
    features = [_model_feature(1, basin="Halawakee Creek")]
    links = [_model_link(1, basin="Halawakee Creek")]
    _patch_service_rows(monkeypatch, features, links)

    models = AlabamaBleModels.list_watershed_models(
        HUC8,
        basin="halawakee creek",
    )

    assert len(models) == 1
    assert (
        AlabamaBleModels.resolve_watershed_directory(
            models[0].source_id,
            huc8=HUC8,
        )
        == models[0].extra["source_prefix"]
    )


def test_alabama_ble_adapter_is_exported_from_state_sources():
    from ras_commander.sources.state import AlabamaBleModels as ExportedAlabamaBleModels

    assert ExportedAlabamaBleModels is AlabamaBleModels


def test_build_watershed_manifest_has_all_197_models_and_eight_basins(
    monkeypatch,
):
    features, links = _full_watershed_service_rows()
    _patch_service_rows(monkeypatch, features, links)

    assert AlabamaBleModels._KNOWN_QUALIFICATIONS[HUC8]["expected_model_count"] == 197
    assert AlabamaBleModels._KNOWN_QUALIFICATIONS[HUC8]["expected_basins"] == (
        BASIN_COUNTS
    )

    manifest = AlabamaBleModels.build_watershed_manifest(STUDY_KEY)

    assert len(manifest) == 197
    assert Counter(item.extra["basin"] for item in manifest) == BASIN_COUNTS
    assert all(item.extra["huc8"] == HUC8 for item in manifest)
    assert all(item.extra["study_key"] == STUDY_KEY for item in manifest)
    assert all(item.model_type == ModelType.STEADY_1D for item in manifest)


def test_manifest_is_deterministic_and_preserves_publisher_model_ids(
    monkeypatch,
):
    features, links = _full_watershed_service_rows()
    _patch_service_rows(monkeypatch, features, links)

    first = AlabamaBleModels.build_watershed_manifest(HUC8)
    features.reverse()
    links.reverse()
    second = AlabamaBleModels.build_watershed_manifest(HUC8)

    first_identity = [
        (item.extra["basin"], item.name.casefold(), item.source_id) for item in first
    ]
    second_identity = [
        (item.extra["basin"], item.name.casefold(), item.source_id) for item in second
    ]
    assert first_identity == sorted(first_identity)
    assert second_identity == first_identity
    assert {item.source_id for item in first} == {
        feature["attributes"]["ModelID"] for feature in features
    }
    assert all(not item.source_id.startswith("AL") for item in first)


def test_manifest_join_uses_only_public_webpath(monkeypatch):
    feature = _model_feature(
        1,
        basin="Halawakee Creek",
        model_id="publisher-model-id",
        name="HALAWAKEE CREEK BLE",
    )
    public_url = (
        "https://files.alabamaflood.com/Models/BLE/"
        "Middle%20Chattahoochee-Lake%20Harding/Halawakee%20Creek/"
        "HALAWAKEE%20CREEK/HALAWAKEE%20CREEK%20BLE.zip"
    )
    link = _model_link(
        1,
        basin="Halawakee Creek",
        model_id="publisher-model-id",
        name="HALAWAKEE CREEK BLE",
        web_path=public_url,
    )
    _patch_service_rows(monkeypatch, [feature], [link])

    metadata = AlabamaBleModels.build_watershed_manifest(HUC8)[0]

    assert metadata.url == public_url
    assert metadata.extra["source_prefix"] == public_url.rsplit("/", 2)[0] + "/"
    assert "directory_url" not in metadata.extra
    assert "F:" not in metadata.url
    assert "RelativePath" not in metadata.extra
    assert "LocalPath" not in metadata.extra


def test_query_layer_pages_with_stable_order(monkeypatch):
    calls: list[dict[str, Any]] = []

    def fake_request_json(url, params):
        calls.append({"url": url, "params": dict(params)})
        offset = params["resultOffset"]
        pages = {
            0: [
                _model_feature(1, basin="Town Creek"),
                _model_feature(2, basin="Town Creek"),
            ],
            2: [
                _model_feature(3, basin="Town Creek"),
                _model_feature(4, basin="Town Creek"),
            ],
            4: [_model_feature(5, basin="Town Creek")],
        }
        rows = pages[offset]
        return {
            "features": rows,
            "exceededTransferLimit": len(rows) == 2,
        }

    monkeypatch.setattr(AlabamaBleModels, "_PAGE_SIZE", 2)
    monkeypatch.setattr(
        AlabamaBleModels,
        "_request_json",
        staticmethod(fake_request_json),
    )

    rows = AlabamaBleModels._query_layer(
        AlabamaBleModels._MODEL_LAYER_ID,
        where="Type='Base Level Engineering'",
        out_fields="OBJECTID,ModelID",
        order_by="OBJECTID ASC",
    )

    assert [row["attributes"]["OBJECTID"] for row in rows] == [1, 2, 3, 4, 5]
    assert [call["params"]["resultOffset"] for call in calls] == [0, 2, 4]
    assert all(call["params"]["resultRecordCount"] == 2 for call in calls)
    assert all(call["params"]["returnGeometry"] == "false" for call in calls)
    assert all(call["params"]["orderByFields"] == "OBJECTID ASC" for call in calls)


def test_manifest_collapses_identical_duplicate_link_rows(monkeypatch):
    feature = _model_feature(1, basin="Town Creek", model_id="duplicate-link")
    link = _model_link(1, basin="Town Creek", model_id="duplicate-link")
    duplicate = json.loads(json.dumps(link))
    duplicate["attributes"]["OBJECTID"] += 1
    _patch_service_rows(monkeypatch, [feature], [link, duplicate])

    manifest = AlabamaBleModels.build_watershed_manifest(HUC8)

    assert len(manifest) == 1
    assert manifest[0].source_id == "duplicate-link"


def test_manifest_rejects_duplicate_model_records(monkeypatch):
    feature = _model_feature(1, basin="Town Creek", model_id="duplicate-model")
    duplicate = json.loads(json.dumps(feature))
    duplicate["attributes"]["OBJECTID"] = 2
    link = _model_link(1, basin="Town Creek", model_id="duplicate-model")
    _patch_service_rows(monkeypatch, [feature, duplicate], [link])

    with pytest.raises(RuntimeError, match="Duplicate.*ModelID"):
        AlabamaBleModels.build_watershed_manifest(HUC8)


def test_get_model_metadata_rejects_ambiguous_model_id(monkeypatch):
    feature = _model_feature(1, basin="Town Creek", model_id="ambiguous-model")
    duplicate = json.loads(json.dumps(feature))
    duplicate["attributes"]["OBJECTID"] = 2
    _patch_service_rows(monkeypatch, [feature, duplicate], [])

    with pytest.raises(KeyError, match="Expected one.*found 2"):
        AlabamaBleModels.get_model_metadata("ambiguous-model", huc8=HUC8)


def test_manifest_rejects_ambiguous_links_for_one_model_id(monkeypatch):
    feature = _model_feature(1, basin="Town Creek", model_id="ambiguous-link")
    first = _model_link(1, basin="Town Creek", model_id="ambiguous-link")
    second = _model_link(
        2,
        basin="Town Creek",
        model_id="ambiguous-link",
        web_path="https://files.alabamaflood.com/Models/BLE/conflicting.zip",
    )
    _patch_service_rows(monkeypatch, [feature], [first, second])

    with pytest.raises(ValueError, match="one public ZIP WebPath|multiple|WebPath"):
        AlabamaBleModels.build_watershed_manifest(HUC8)


def test_manifest_rejects_missing_and_non_public_webpaths(monkeypatch):
    feature = _model_feature(1, basin="Town Creek", model_id="bad-link")
    missing = _model_link(1, basin="Town Creek", model_id="other-model")
    _patch_service_rows(monkeypatch, [feature], [missing])
    with pytest.raises(ValueError, match="WebPath|link|orphan"):
        AlabamaBleModels.build_watershed_manifest(HUC8)

    local_link = _model_link(
        1,
        basin="Town Creek",
        model_id="bad-link",
        web_path=r"F:\AL_Website\PDS_Data\Models\bad.zip",
    )
    _patch_service_rows(monkeypatch, [feature], [local_link])
    with pytest.raises(ValueError, match="WebPath|http|public"):
        AlabamaBleModels.build_watershed_manifest(HUC8)


def _zip_bytes(files: dict[str, bytes | str]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return stream.getvalue()


def _write_inventory_fixture(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    root = tmp_path / STUDY_KEY
    documentation = root / "Documentation"
    model_root = root / "RAS Models" / "Halawakee_Creek" / "MODEL_BLE"
    archive = root / "Source Archives" / "Halawakee_Creek" / "MODEL_BLE.zip"
    documentation.mkdir(parents=True)
    archive.parent.mkdir(parents=True)
    paths = {
        "project": model_root / "MODEL.prj",
        "plan": model_root / "MODEL.p01",
        "geometry": model_root / "MODEL.g01",
        "geometry_hdf": model_root / "MODEL.g01.hdf",
        "flow": model_root / "MODEL.f01",
    }
    archive.write_bytes(
        _zip_bytes(
            {
                "MODEL.prj": "Proj Title=Model\nCurrent Plan=p01\n",
                "MODEL.p01": "Plan Title=Plan\n",
                "MODEL.g01": b"geometry",
                "MODEL.g01.hdf": b"geometry_hdf",
                "MODEL.f01": b"flow",
            }
        )
    )
    AlabamaBleModels._safe_extract_zip(archive, model_root)
    source_url = "https://files.alabamaflood.com/Models/BLE/MODEL_BLE.zip"
    source_identity = {
        "source_url": source_url,
        "final_url": source_url,
        "size_bytes": archive.stat().st_size,
        "etag": '"strong-etag"',
    }
    sidecar = archive.with_name(f"{archive.name}.ebfe-source.json")
    sidecar.write_text(json.dumps(source_identity), encoding="utf-8")
    receipt = AlabamaBleModels._read_extraction_receipt(model_root)
    record = {
        "study_id": STUDY_KEY,
        "source_id": "publisher-model-id",
        "model_id": "publisher-model-id",
        "model_key": f"{STUDY_KEY}:publisher-model-id",
        "display_id": "MODEL_BLE",
        "name": "MODEL",
        "basin": "Halawakee Creek",
        "archive_name": archive.name,
        "source_url": source_url,
        "source_identity": source_identity,
        "source_sidecar": sidecar.relative_to(root).as_posix(),
        "archive_path": archive.relative_to(root).as_posix(),
        "archive_sha256": AlabamaBleModels._sha256_file(archive),
        "extraction": {
            "path": model_root.relative_to(root).as_posix(),
            "member_count": receipt["member_count"],
            "file_count": receipt["file_count"],
            "project_files": ["MODEL.prj"],
        },
    }
    manifest = _source_manifest_header([record])
    (documentation / AlabamaBleModels._MANIFEST_NAME).write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return root, paths


def _patch_inventory_ras(
    monkeypatch: pytest.MonkeyPatch,
    paths: dict[str, Path],
    *,
    plan_type: str = "steady_1d",
    geometry_type: str = "1D",
    project_crs: str | None = "ESRI:102629",
    geometry_hdf: bool = True,
    flow_association: bool = True,
    units_system: str = "English",
) -> None:
    ras_prj_module = importlib.import_module("ras_commander.RasPrj")

    class FakeRasPrj:
        def __init__(self):
            self.plan_df = pd.DataFrame()
            self.geom_df = pd.DataFrame()
            self.project_crs = None

        @staticmethod
        def get_project_units(project_file):
            return units_system

    def fake_init(project_file, **kwargs):
        ras_object = kwargs["ras_object"]
        ras_object.project_crs = project_crs
        ras_object.plan_df = pd.DataFrame(
            [
                {
                    "plan_number": "01",
                    "geometry_number": "01",
                    "full_path": str(paths["plan"]),
                    "Flow Path": str(paths["flow"]) if flow_association else None,
                    "Flow File": "01" if flow_association else None,
                    "plan_type": plan_type,
                    "Program Version": "6.20",
                }
            ]
        )
        ras_object.geom_df = pd.DataFrame(
            [
                {
                    "geom_number": "01",
                    "full_path": str(paths["geometry"]),
                    "hdf_path": str(paths["geometry_hdf"]) if geometry_hdf else None,
                    "geometry_type": geometry_type,
                    "num_cross_sections": 10,
                }
            ]
        )
        return ras_object

    monkeypatch.setattr(ras_prj_module, "RasPrj", FakeRasPrj)
    monkeypatch.setattr(ras_prj_module, "init_ras_project", fake_init)


class _Response:
    def __init__(
        self,
        body: bytes = b"",
        *,
        url: str,
        headers: dict[str, str],
        status_code: int = 200,
    ) -> None:
        self.body = body
        self.url = url
        self.headers = headers
        self.status_code = status_code
        self.closed = False

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start : start + chunk_size]

    def close(self) -> None:
        self.closed = True


def test_download_file_pins_exact_size_etag_and_final_url(monkeypatch, tmp_path):
    body = _zip_bytes({"model/model.prj": "Proj Title=Model\n"})
    source_url = "https://files.alabamaflood.com/model.zip"
    final_url = "https://files.alabamaflood.com/Models/BLE/model.zip"
    etag = "strong-etag-123"
    head = _Response(
        url=final_url,
        headers={"Content-Length": str(len(body)), "ETag": f'"{etag}"'},
    )
    get = _Response(
        body,
        url=final_url,
        headers={"Content-Length": str(len(body)), "ETag": f'"{etag}"'},
    )
    monkeypatch.setattr(alabama_module.requests, "head", lambda *args, **kwargs: head)
    monkeypatch.setattr(alabama_module.requests, "get", lambda *args, **kwargs: get)
    destination = tmp_path / "model.zip"

    record = AlabamaBleModels._download_file(source_url, destination)

    assert destination.read_bytes() == body
    assert record["source_url"] == source_url
    assert record["final_url"] == final_url
    assert record["size_bytes"] == len(body)
    assert record["etag"] == etag
    sidecar = AlabamaBleModels._source_sidecar(destination)
    persisted = json.loads(sidecar.read_text(encoding="utf-8"))
    assert persisted["size_bytes"] == len(body)
    assert persisted["etag"] == etag
    assert persisted["final_url"] == final_url
    assert get.closed is True


@pytest.mark.parametrize(
    ("header", "observed"),
    [("Content-Length", "999999"), ("ETag", "different-etag")],
)
def test_download_file_fails_closed_when_get_identity_differs_from_preflight(
    monkeypatch,
    tmp_path,
    header,
    observed,
):
    body = _zip_bytes({"model/model.prj": "Proj Title=Model\n"})
    url = "https://files.alabamaflood.com/model.zip"
    expected_headers = {
        "Content-Length": str(len(body)),
        "ETag": "strong-etag-123",
    }
    get_headers = dict(expected_headers)
    get_headers[header] = observed
    monkeypatch.setattr(
        alabama_module.requests,
        "head",
        lambda *args, **kwargs: _Response(
            url=url,
            headers=expected_headers,
        ),
    )
    monkeypatch.setattr(
        alabama_module.requests,
        "get",
        lambda *args, **kwargs: _Response(
            body,
            url=url,
            headers=get_headers,
        ),
    )
    destination = tmp_path / "model.zip"

    with pytest.raises(RuntimeError, match="identity differs|Content-Length|ETag"):
        AlabamaBleModels._download_file(url, destination)

    assert not destination.exists()
    assert not AlabamaBleModels._source_sidecar(destination).exists()
    assert not list(tmp_path.glob("*.part-*"))


def test_download_file_reuses_cache_only_with_exact_identity_sidecar(
    monkeypatch,
    tmp_path,
):
    body = _zip_bytes({"model/model.prj": "Proj Title=Model\n"})
    url = "https://files.alabamaflood.com/model.zip"
    identity = {
        "source_url": url,
        "final_url": url,
        "size_bytes": len(body),
        "etag": "strong-etag-123",
    }
    destination = tmp_path / "model.zip"
    destination.write_bytes(body)
    AlabamaBleModels._source_sidecar(destination).write_text(
        json.dumps(identity),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        alabama_module.requests,
        "get",
        lambda *args, **kwargs: pytest.fail("verified cache must not GET again"),
    )

    record = AlabamaBleModels._download_file(
        url,
        destination,
        expected_identity=identity,
    )

    assert record["size_bytes"] == len(body)
    assert record["etag"] == identity["etag"]

    wrong = {**identity, "etag": "replacement-object"}
    with pytest.raises(RuntimeError, match="identity mismatch.*etag"):
        AlabamaBleModels._download_file(
            url,
            destination,
            expected_identity=wrong,
        )


def test_archive_redirect_is_validated_before_next_request(monkeypatch):
    source_url = "https://files.alabamaflood.com/model.zip"
    requested: list[str] = []

    def fake_get(url, **kwargs):
        requested.append(url)
        return _Response(
            url=url,
            headers={"Location": "http://127.0.0.1/private.zip"},
            status_code=302,
        )

    monkeypatch.setattr(alabama_module.requests, "get", fake_get)

    with pytest.raises(ValueError, match="HTTPS archive URL"):
        AlabamaBleModels._request_archive("GET", source_url, stream=True)

    assert requested == [source_url]


@pytest.mark.parametrize(
    "member_name",
    [
        "../escape.txt",
        "/absolute.txt",
        r"C:\\absolute.txt",
        "nested/../../escape.txt",
        "model/file.txt:payload",
        "model/CON",
        "model/NUL.txt",
        "model/trailing.",
        "model/trailing ",
    ],
)
def test_safe_extract_rejects_zip_slip_without_touching_destination(
    tmp_path,
    member_name,
):
    archive_path = tmp_path / "unsafe.zip"
    archive_path.write_bytes(_zip_bytes({member_name: b"bad"}))
    source_before = archive_path.read_bytes()
    destination = tmp_path / "delivery"
    destination.mkdir()
    sentinel = destination / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsafe|unsafe|ZIP|path"):
        AlabamaBleModels._safe_extract_zip(
            archive_path,
            destination,
            overwrite=True,
        )

    assert archive_path.read_bytes() == source_before
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "escape.txt").exists()


def test_safe_extract_rejects_symlink_members(tmp_path):
    archive_path = tmp_path / "symlink.zip"
    member = zipfile.ZipInfo("link-to-elsewhere")
    member.create_system = 3
    member.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(member, "../../elsewhere")

    with pytest.raises(ValueError, match="symbolic link|Unsafe|unsafe"):
        AlabamaBleModels._safe_extract_zip(archive_path, tmp_path / "delivery")


def test_safe_extract_rejects_case_only_windows_target_collision(tmp_path):
    archive_path = tmp_path / "collision.zip"
    archive_path.write_bytes(
        _zip_bytes(
            {
                "Model/Model.prj": "Proj Title=First\n",
                "model/model.prj": "Proj Title=Second\n",
            }
        )
    )

    with pytest.raises(ValueError, match="Duplicate ZIP target"):
        AlabamaBleModels._safe_extract_zip(archive_path, tmp_path / "delivery")


def test_safe_extract_is_atomic_and_preserves_source_archive(tmp_path):
    archive_path = tmp_path / "model.zip"
    archive_path.write_bytes(
        _zip_bytes(
            {
                "HALAWAKEE CREEK BLE/HALAWAKEE CREEK.prj": "Proj Title=Halawakee\n",
                "HALAWAKEE CREEK BLE/HALAWAKEE CREEK.p01": "Plan Title=Plan\n",
                "HALAWAKEE CREEK BLE/HALAWAKEE CREEK.g01": "Geom Title=Halawakee\n",
            }
        )
    )
    source_before = archive_path.read_bytes()
    destination = tmp_path / "delivery"

    extracted = AlabamaBleModels._safe_extract_zip(archive_path, destination)

    assert extracted == destination
    receipt = json.loads(
        (destination / AlabamaBleModels._EXTRACTION_RECEIPT).read_text(encoding="utf-8")
    )
    assert receipt["member_count"] == 3
    assert receipt["file_count"] == 3
    assert archive_path.read_bytes() == source_before
    assert (destination / "HALAWAKEE CREEK BLE" / "HALAWAKEE CREEK.prj").is_file()


def test_safe_extract_rejects_same_size_tamper_against_receipt(tmp_path):
    archive_path = tmp_path / "model.zip"
    archive_path.write_bytes(
        _zip_bytes(
            {
                "model/model.prj": b"Proj Title=Model\n",
                "model/model.p01": b"Plan Title=Plan\n",
                "model/model.g01": b"ORIGINAL",
            }
        )
    )
    destination = tmp_path / "delivery"
    AlabamaBleModels._safe_extract_zip(archive_path, destination)
    geometry = destination / "model" / "model.g01"
    geometry.write_bytes(b"TAMPERED")

    with pytest.raises(RuntimeError, match="CRC32 audit"):
        AlabamaBleModels._safe_extract_zip(archive_path, destination)


@pytest.mark.parametrize(("target_length", "succeeds"), [(240, True), (241, False)])
def test_safe_extract_enforces_hecras_active_path_boundary(
    tmp_path,
    target_length,
    succeeds,
):
    destination = tmp_path / f"delivery-{target_length}"
    file_name = "model.prj"
    folder_length = (
        target_length - len(str(destination.absolute())) - len(file_name) - 2
    )
    assert folder_length > 0
    folder = "a" * folder_length
    archive_path = tmp_path / f"boundary-{target_length}.zip"
    archive_path.write_bytes(
        _zip_bytes(
            {
                f"{folder}/{file_name}": "Proj Title=Model\n",
                f"{folder}/model.p01": "Plan Title=Plan\n",
            }
        )
    )
    assert len(str(destination.absolute() / folder / file_name)) == target_length

    if succeeds:
        AlabamaBleModels._safe_extract_zip(archive_path, destination)
        assert (destination / folder / file_name).is_file()
    else:
        with pytest.raises(ValueError, match="241-character|shorter workspace"):
            AlabamaBleModels._safe_extract_zip(archive_path, destination)
        assert not destination.exists()


def test_organize_watershed_copies_flat_staged_corpus_into_one_delivery(
    monkeypatch,
    tmp_path,
):
    _patch_qualification(
        monkeypatch,
        {"Halawakee Creek": 1, "Town Creek": 1},
    )
    source_root = tmp_path / "staged-source"
    source_root.mkdir()
    metadata_rows: list[ModelMetadata] = []
    source_snapshots: dict[Path, bytes] = {}
    for ordinal, basin in enumerate(("Halawakee Creek", "Town Creek"), start=1):
        name = f"MODEL {ordinal} BLE"
        archive_name = f"MODEL_{ordinal}_BLE.zip"
        archive = source_root / archive_name
        archive.write_bytes(
            _zip_bytes(
                {
                    f"{name}/{name}.prj": f"Proj Title={name}\n",
                    f"{name}/{name}.p01": "Plan Title=Plan\n",
                }
            )
        )
        identity = {
            "source": f"https://files.alabamaflood.com/{archive_name}",
            "final_url": f"https://files.alabamaflood.com/{archive_name}",
            "size": archive.stat().st_size,
            "etag": f"etag-{ordinal}",
        }
        sidecar = source_root / f"{archive_name}.ebfe-source.json"
        sidecar.write_text(json.dumps(identity), encoding="utf-8")
        source_snapshots[archive] = archive.read_bytes()
        source_snapshots[sidecar] = sidecar.read_bytes()
        metadata_rows.append(
            _metadata(
                f"model-{ordinal}",
                basin=basin,
                name=name,
                file_name=archive_name,
                url=identity["source"],
                size=identity["size"],
                etag=identity["etag"],
            )
        )

    monkeypatch.setattr(
        AlabamaBleModels,
        "build_watershed_manifest",
        staticmethod(lambda huc8: metadata_rows),
    )
    output_root = tmp_path / "output"

    result = AlabamaBleModels.organize_watershed(
        STUDY_KEY,
        source_root,
        output_root,
    )

    delivery = output_root / STUDY_KEY
    assert result.success is True
    assert Path(result.model_path) == delivery
    assert delivery.is_dir()
    assert (delivery / "Source Archives").is_dir()
    assert (delivery / "RAS Models" / "Halawakee_Creek").is_dir()
    assert (delivery / "RAS Models" / "Town_Creek").is_dir()
    manifest_path = delivery / "Documentation" / "alabama_ble_source_manifest.json"
    assert manifest_path.is_file()
    written = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert written["study_key"] == STUDY_KEY
    assert written["huc8"] == HUC8
    assert written["expected_model_count"] == 2
    assert written["actual_record_count"] == 2
    assert written["basin_counts"] == {
        "Halawakee Creek": 1,
        "Town Creek": 1,
    }
    for record in written["records"]:
        assert record["study_id"] == STUDY_KEY
        assert record["model_id"] == record["source_id"]
        assert record["model_key"].startswith(f"{STUDY_KEY}:")
        assert len(record["archive_sha256"]) == 64
        assert "archive" not in record["staged_source"]
        assert "extraction" not in record["staged_source"]
        assert set(record["extraction"]) >= {
            "path",
            "member_count",
            "file_count",
            "project_files",
        }
    for source_path, expected in source_snapshots.items():
        assert source_path.read_bytes() == expected


def test_organize_requires_archive_and_never_trusts_extracted_folder(
    monkeypatch,
    tmp_path,
):
    _patch_qualification(monkeypatch, {"Halawakee Creek": 1})
    source_root = tmp_path / "staged-source"
    extracted = source_root / "MODEL_BLE"
    extracted.mkdir(parents=True)
    (extracted / "MODEL.prj").write_text("Proj Title=Unverified\n", encoding="utf-8")
    (extracted / "MODEL.p01").write_text("Plan Title=Unverified\n", encoding="utf-8")
    metadata = _metadata(
        "model-1",
        basin="Halawakee Creek",
        name="MODEL BLE",
        file_name="MODEL_BLE.zip",
        url="https://files.alabamaflood.com/MODEL_BLE.zip",
    )
    monkeypatch.setattr(
        AlabamaBleModels,
        "build_watershed_manifest",
        staticmethod(lambda huc8: [metadata]),
    )

    result = AlabamaBleModels.organize_watershed(
        HUC8,
        source_root,
        tmp_path / "output",
    )

    assert result.success is False
    assert "extracted folders alone" in result.message
    assert not (tmp_path / "output" / STUDY_KEY).exists()


def test_staged_archive_symlink_cannot_escape_source_root(tmp_path):
    source_root = tmp_path / "staged-source"
    source_root.mkdir()
    outside_archive = tmp_path / "outside.zip"
    outside_archive.write_bytes(
        _zip_bytes(
            {
                "MODEL.prj": "Proj Title=Model\n",
                "MODEL.p01": "Plan Title=Plan\n",
            }
        )
    )
    linked_archive = source_root / "MODEL_BLE.zip"
    try:
        linked_archive.symlink_to(outside_archive)
    except OSError as exc:
        pytest.skip(f"File symlinks are unavailable: {exc}")

    with pytest.raises(RuntimeError, match="outside staged source root"):
        AlabamaBleModels._index_staged_source(source_root)


def test_staged_sidecar_symlink_cannot_escape_source_root(tmp_path):
    source_root = tmp_path / "staged-source"
    source_root.mkdir()
    archive = source_root / "MODEL_BLE.zip"
    archive.write_bytes(
        _zip_bytes(
            {
                "MODEL.prj": "Proj Title=Model\n",
                "MODEL.p01": "Plan Title=Plan\n",
            }
        )
    )
    source_url = "https://files.alabamaflood.com/MODEL_BLE.zip"
    outside_sidecar = tmp_path / "outside-source.json"
    outside_sidecar.write_text(
        json.dumps(
            {
                "source": source_url,
                "final_url": source_url,
                "size": archive.stat().st_size,
                "etag": "strong-etag",
            }
        ),
        encoding="utf-8",
    )
    linked_sidecar = archive.with_name(f"{archive.name}.ebfe-source.json")
    try:
        linked_sidecar.symlink_to(outside_sidecar)
    except OSError as exc:
        pytest.skip(f"File symlinks are unavailable: {exc}")
    metadata = _metadata(
        "model-1",
        basin="Halawakee Creek",
        name="MODEL BLE",
        file_name=archive.name,
        url=source_url,
        size=archive.stat().st_size,
        etag="strong-etag",
    )

    with pytest.raises(RuntimeError, match="outside staged source root"):
        AlabamaBleModels._validate_staged_archive(
            archive,
            metadata,
            source_root=source_root,
        )


def test_organize_derives_delivery_from_archive_not_staged_extraction(
    monkeypatch,
    tmp_path,
):
    _patch_qualification(monkeypatch, {"Halawakee Creek": 1})
    source_root = tmp_path / "staged-source"
    source_root.mkdir()
    archive = source_root / "MODEL_BLE.zip"
    archive.write_bytes(
        _zip_bytes(
            {
                "MODEL/MODEL.prj": "Proj Title=From verified archive\n",
                "MODEL/MODEL.p01": "Plan Title=Plan\n",
            }
        )
    )
    source_url = "https://files.alabamaflood.com/MODEL_BLE.zip"
    identity = {
        "source": source_url,
        "final_url": source_url,
        "size": archive.stat().st_size,
        "etag": "strong-etag",
    }
    archive.with_name(f"{archive.name}.ebfe-source.json").write_text(
        json.dumps(identity),
        encoding="utf-8",
    )
    staged_extraction = source_root / "MODEL_BLE" / "MODEL"
    staged_extraction.mkdir(parents=True)
    (staged_extraction / "MODEL.prj").write_text(
        "Proj Title=Tampered staged folder\n",
        encoding="utf-8",
    )
    (staged_extraction / "MODEL.p01").write_text(
        "Plan Title=Tampered\n",
        encoding="utf-8",
    )
    metadata = _metadata(
        "model-1",
        basin="Halawakee Creek",
        name="MODEL BLE",
        file_name=archive.name,
        url=source_url,
        size=archive.stat().st_size,
        etag="strong-etag",
    )
    monkeypatch.setattr(
        AlabamaBleModels,
        "build_watershed_manifest",
        staticmethod(lambda huc8: [metadata]),
    )

    result = AlabamaBleModels.organize_watershed(
        HUC8,
        source_root,
        tmp_path / "output",
    )

    assert result.success is True
    delivered_project = (
        Path(result.model_path)
        / "RAS Models"
        / "Halawakee_Creek"
        / "MODEL_BLE"
        / "MODEL"
        / "MODEL.prj"
    )
    assert delivered_project.read_text(encoding="utf-8") == (
        "Proj Title=From verified archive\n"
    )


def test_organize_rejects_source_inside_final_delivery_root(tmp_path):
    output_root = tmp_path / "output"
    source_root = output_root / STUDY_KEY / "raw"
    source_root.mkdir(parents=True)
    sentinel = source_root / "retain.txt"
    sentinel.write_text("immutable", encoding="utf-8")

    result = AlabamaBleModels.organize_watershed(
        HUC8,
        source_root,
        output_root,
        overwrite=True,
    )

    assert result.success is False
    assert "must not be equal or contain" in result.message
    assert sentinel.read_text(encoding="utf-8") == "immutable"


def test_organize_restores_prior_delivery_when_promotion_fails(
    monkeypatch,
    tmp_path,
):
    _patch_qualification(monkeypatch, {"Halawakee Creek": 1})
    source_root = tmp_path / "staged-source"
    source_root.mkdir()
    archive = source_root / "MODEL_BLE.zip"
    archive.write_bytes(
        _zip_bytes(
            {
                "MODEL.prj": "Proj Title=Model\n",
                "MODEL.p01": "Plan Title=Plan\n",
            }
        )
    )
    source_url = "https://files.alabamaflood.com/MODEL_BLE.zip"
    identity = {
        "source": source_url,
        "final_url": source_url,
        "size": archive.stat().st_size,
        "etag": "strong-etag",
    }
    archive.with_name(f"{archive.name}.ebfe-source.json").write_text(
        json.dumps(identity), encoding="utf-8"
    )
    metadata = _metadata(
        "model-1",
        basin="Halawakee Creek",
        name="MODEL BLE",
        file_name=archive.name,
        url=source_url,
        size=archive.stat().st_size,
        etag="strong-etag",
    )
    monkeypatch.setattr(
        AlabamaBleModels,
        "build_watershed_manifest",
        staticmethod(lambda huc8: [metadata]),
    )
    output_root = tmp_path / "output"
    existing = output_root / STUDY_KEY
    existing.mkdir(parents=True)
    sentinel = existing / "prior.txt"
    sentinel.write_text("prior delivery", encoding="utf-8")
    original_replace = alabama_module.os.replace

    def fail_delivery_promotion(source, destination):
        source_path = Path(str(source))
        destination_path = Path(str(destination))
        if (
            source_path.name.startswith(f".{STUDY_KEY}.organizing-")
            and destination_path == existing
        ):
            raise OSError("simulated promotion failure")
        return original_replace(source, destination)

    monkeypatch.setattr(alabama_module.os, "replace", fail_delivery_promotion)

    result = AlabamaBleModels.organize_watershed(
        HUC8,
        source_root,
        output_root,
        overwrite=True,
    )

    assert result.success is False
    assert "simulated promotion failure" in result.message
    assert sentinel.read_text(encoding="utf-8") == "prior delivery"


def test_organize_watershed_rejects_size_or_etag_identity_mismatch(
    monkeypatch,
    tmp_path,
):
    _patch_qualification(monkeypatch, {"Halawakee Creek": 1})
    source_root = tmp_path / "staged-source"
    source_root.mkdir()
    archive = source_root / "HALAWAKEE_CREEK_BLE.zip"
    archive.write_bytes(_zip_bytes({"model/model.prj": "Proj Title=Model\n"}))
    sidecar = source_root / "HALAWAKEE_CREEK_BLE.zip.ebfe-source.json"
    sidecar.write_text(
        json.dumps(
            {
                "source": "https://files.alabamaflood.com/model.zip",
                "final_url": "https://files.alabamaflood.com/model.zip",
                "size": archive.stat().st_size + 1,
                "etag": "wrong-etag",
            }
        ),
        encoding="utf-8",
    )
    metadata = _metadata(
        "model-1",
        basin="Halawakee Creek",
        name="HALAWAKEE CREEK BLE",
        file_name=archive.name,
        url="https://files.alabamaflood.com/model.zip",
        size=archive.stat().st_size,
        etag="expected-etag",
    )
    monkeypatch.setattr(
        AlabamaBleModels,
        "build_watershed_manifest",
        staticmethod(lambda huc8: [metadata]),
    )

    result = AlabamaBleModels.organize_watershed(
        HUC8,
        source_root,
        tmp_path / "output",
    )

    assert result.success is False
    assert "size" in result.message.lower() or "etag" in result.message.lower()
    assert not (tmp_path / "output" / STUDY_KEY).exists()
    assert archive.is_file()
    assert sidecar.is_file()


def test_organize_full_197_model_corpus_as_one_watershed_delivery(
    monkeypatch,
    tmp_path,
):
    source_root = tmp_path / "staged"
    source_root.mkdir()
    models: list[ModelMetadata] = []
    ordinal = 1
    for basin, count in BASIN_COUNTS.items():
        for _ in range(count):
            archive_name = f"M{ordinal:03d}.zip"
            archive = source_root / archive_name
            archive.write_bytes(
                _zip_bytes(
                    {
                        "model.prj": "Proj Title=Model\n",
                        "model.p01": "Plan Title=Plan\n",
                    }
                )
            )
            url = f"https://files.alabamaflood.com/Models/BLE/{archive_name}"
            etag = f"etag-{ordinal:03d}"
            archive.with_name(f"{archive.name}.ebfe-source.json").write_text(
                json.dumps(
                    {
                        "source": url,
                        "final_url": url,
                        "size": archive.stat().st_size,
                        "etag": etag,
                    }
                ),
                encoding="utf-8",
            )
            models.append(
                _metadata(
                    f"model-{ordinal:03d}",
                    basin=basin,
                    name=f"Model {ordinal:03d}",
                    file_name=archive_name,
                    url=url,
                    size=archive.stat().st_size,
                    etag=etag,
                )
            )
            ordinal += 1

    monkeypatch.setattr(
        AlabamaBleModels,
        "build_watershed_manifest",
        staticmethod(lambda huc8: models),
    )

    def fake_extract(zip_path, destination, overwrite=False, **kwargs):
        destination = Path(destination)
        destination.mkdir(parents=True)
        (destination / "model.prj").write_text(
            "Proj Title=Model\n",
            encoding="utf-8",
        )
        (destination / "model.p01").write_text(
            "Plan Title=Plan\n",
            encoding="utf-8",
        )
        (destination / AlabamaBleModels._EXTRACTION_RECEIPT).write_text(
            json.dumps(
                {
                    "member_count": 1,
                    "file_count": 1,
                    "project_files": ["model.prj"],
                }
            ),
            encoding="utf-8",
        )
        return destination

    monkeypatch.setattr(
        AlabamaBleModels,
        "_safe_extract_zip",
        staticmethod(fake_extract),
    )
    output_root = tmp_path / "output"

    result = AlabamaBleModels.organize_watershed(
        HUC8,
        source_root,
        output_root,
    )

    assert result.success is True
    delivery = output_root / STUDY_KEY
    assert Path(result.model_path) == delivery
    assert [path.name for path in output_root.iterdir()] == [STUDY_KEY]
    assert len(list((delivery / "Source Archives").rglob("*.zip"))) == 197
    assert len(list((delivery / "RAS Models").rglob("*.prj"))) == 197
    assert {folder.name for folder in (delivery / "RAS Models").iterdir()} == {
        name.replace(" ", "_") for name in BASIN_COUNTS
    }
    payload = json.loads(
        (delivery / "Documentation" / "alabama_ble_source_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["status"] == "complete"
    assert payload["actual_record_count"] == 197
    assert payload["basin_counts"] == BASIN_COUNTS


def test_inventory_reapplies_known_huc_model_count(tmp_path):
    root = tmp_path / STUDY_KEY
    documentation = root / "Documentation"
    documentation.mkdir(parents=True)
    manifest = _source_manifest_header([{"basin": "Halawakee Creek"}])
    (documentation / AlabamaBleModels._MANIFEST_NAME).write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="expected 197"):
        AlabamaBleModels.build_watershed_delivery_inventory(root)


def test_inventory_reapplies_known_huc_exact_basin_counter(tmp_path):
    root = tmp_path / STUDY_KEY
    documentation = root / "Documentation"
    documentation.mkdir(parents=True)
    records = [
        {"basin": "Incorrect Basin", "model_id": f"model-{index:03d}"}
        for index in range(197)
    ]
    manifest = _source_manifest_header(records)
    (documentation / AlabamaBleModels._MANIFEST_NAME).write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="basin inventory differs"):
        AlabamaBleModels.build_watershed_delivery_inventory(root)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_name", "wrong.schema"),
        ("contract_version", "9.9.9"),
        ("schema_version", True),
        ("source_name", "Other source"),
        ("source_service", "https://example.com/service"),
        ("source_url", "https://example.com/source"),
        ("source_policy", ""),
        ("study_key", "AL99999999"),
    ],
)
def test_inventory_rejects_invalid_offline_source_manifest_identity(
    monkeypatch,
    tmp_path,
    field,
    value,
):
    _patch_qualification(monkeypatch, {"Halawakee Creek": 1})
    root = tmp_path / STUDY_KEY
    documentation = root / "Documentation"
    documentation.mkdir(parents=True)
    manifest = _source_manifest_header([{"basin": "Halawakee Creek"}])
    manifest[field] = value
    (documentation / AlabamaBleModels._MANIFEST_NAME).write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    with pytest.raises((RuntimeError, ValueError), match="identity|HUC8"):
        AlabamaBleModels.build_watershed_delivery_inventory(root)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("mode", "copied", "mode"),
        ("expected_model_count", 2, "record count"),
        ("model_count", True, "record count"),
        ("actual_record_count", 2, "record count"),
        ("basin_count", 2, "basin declaration"),
        ("basin_counts", {"Town Creek": 1}, "basin declaration"),
    ],
)
def test_inventory_rejects_tampered_manifest_declarations(
    monkeypatch,
    tmp_path,
    field,
    value,
    message,
):
    _patch_qualification(monkeypatch, {"Halawakee Creek": 1})
    root = tmp_path / STUDY_KEY
    documentation = root / "Documentation"
    documentation.mkdir(parents=True)
    manifest = _source_manifest_header([{"basin": "Halawakee Creek"}])
    manifest[field] = value
    (documentation / AlabamaBleModels._MANIFEST_NAME).write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match=message):
        AlabamaBleModels.build_watershed_delivery_inventory(root)


def test_inventory_rejects_manifest_symlink_outside_delivery(tmp_path):
    root = tmp_path / STUDY_KEY
    root.mkdir()
    outside = tmp_path / "outside-documentation"
    outside.mkdir()
    (outside / AlabamaBleModels._MANIFEST_NAME).write_text("{}", encoding="utf-8")
    documentation = root / "Documentation"
    try:
        documentation.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlinks are unavailable: {exc}")

    with pytest.raises(RuntimeError, match="manifest escapes"):
        AlabamaBleModels.build_watershed_delivery_inventory(root)


@pytest.mark.parametrize(
    ("ras_overrides", "message"),
    [
        ({"plan_type": "unsteady_1d"}, "not steady_1d"),
        ({"geometry_type": "2D"}, "not 1D geometry"),
        ({"project_crs": None}, "no project CRS"),
        ({"geometry_hdf": False}, "no registered geometry HDF"),
        ({"flow_association": False}, "registered geometry or steady-flow"),
        ({"units_system": ""}, "no project units system"),
    ],
)
def test_inventory_rejects_unqualified_project_classification(
    monkeypatch,
    tmp_path,
    ras_overrides,
    message,
):
    _patch_qualification(monkeypatch, {"Halawakee Creek": 1})
    root, paths = _write_inventory_fixture(tmp_path)
    _patch_inventory_ras(monkeypatch, paths, **ras_overrides)

    with pytest.raises(RuntimeError, match=message):
        AlabamaBleModels.build_watershed_delivery_inventory(root)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("display_id", "_MODEL", "display ID"),
        ("name", "", "name and source basin"),
    ],
)
def test_inventory_rejects_nonportable_required_model_strings(
    monkeypatch,
    tmp_path,
    field,
    value,
    message,
):
    _patch_qualification(monkeypatch, {"Halawakee Creek": 1})
    root, paths = _write_inventory_fixture(tmp_path)
    manifest_path = root / "Documentation" / AlabamaBleModels._MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["records"][0][field] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _patch_inventory_ras(monkeypatch, paths)

    with pytest.raises(RuntimeError, match=message):
        AlabamaBleModels.build_watershed_delivery_inventory(root)


def test_build_delivery_inventory_uses_ras_dataframes_and_relative_paths(
    monkeypatch,
    tmp_path,
):
    _patch_qualification(monkeypatch, {"Halawakee Creek": 1})
    ras_prj_module = importlib.import_module("ras_commander.RasPrj")

    root = tmp_path / STUDY_KEY
    documentation = root / "Documentation"
    model_root = root / "RAS Models" / "Halawakee_Creek" / "MODEL_BLE"
    archive = root / "Source Archives" / "Halawakee_Creek" / "MODEL_BLE.zip"
    documentation.mkdir(parents=True)
    archive.parent.mkdir(parents=True)
    paths = {
        "project": model_root / "MODEL.prj",
        "plan": model_root / "MODEL.p01",
        "geometry": model_root / "MODEL.g01",
        "geometry_hdf": model_root / "MODEL.g01.hdf",
        "flow": model_root / "MODEL.f01",
    }
    archive.write_bytes(
        _zip_bytes(
            {
                "MODEL.prj": b"Proj Title=Model\nCurrent Plan=p01\n",
                "MODEL.p01": b"Plan Title=Plan\n",
                "MODEL.g01": b"geometry",
                "MODEL.g01.hdf": b"geometry_hdf",
                "MODEL.f01": b"flow",
            }
        )
    )
    source_url = "https://files.alabamaflood.com/Models/BLE/MODEL_BLE.zip"
    source_identity = {
        "source_url": source_url,
        "final_url": source_url,
        "size_bytes": archive.stat().st_size,
        "etag": '"strong-etag"',
    }
    sidecar = archive.with_name(f"{archive.name}.ebfe-source.json")
    sidecar.write_text(json.dumps(source_identity), encoding="utf-8")
    AlabamaBleModels._safe_extract_zip(archive, model_root)
    source_manifest = {
        "schema_name": AlabamaBleModels._MANIFEST_SCHEMA_NAME,
        "contract_version": AlabamaBleModels._MANIFEST_CONTRACT_VERSION,
        "schema_version": 1,
        "source_name": AlabamaBleModels.SOURCE_NAME,
        "source_service": AlabamaBleModels._SERVICE_URL,
        "source_url": AlabamaBleModels._SERVICE_URL,
        "source_policy": AlabamaBleModels._SOURCE_POLICY,
        "status": "complete",
        "mode": "download",
        "study_key": STUDY_KEY,
        "huc8": HUC8,
        "expected_model_count": 1,
        "model_count": 1,
        "actual_record_count": 1,
        "basin_count": 1,
        "basin_counts": {"Halawakee Creek": 1},
        "records": [
            {
                "study_id": STUDY_KEY,
                "source_id": "publisher-model-id",
                "model_id": "publisher-model-id",
                "model_key": f"{STUDY_KEY}:publisher-model-id",
                "display_id": "MODEL_BLE",
                "name": "MODEL",
                "basin": "Halawakee Creek",
                "archive_name": archive.name,
                "source_url": source_url,
                "source_identity": source_identity,
                "source_sidecar": sidecar.relative_to(root).as_posix(),
                "archive_path": archive.relative_to(root).as_posix(),
                "archive_sha256": AlabamaBleModels._sha256_file(archive),
                "extraction": {
                    "path": model_root.relative_to(root).as_posix(),
                    "project_files": ["MODEL.prj"],
                },
            }
        ],
    }
    (documentation / AlabamaBleModels._MANIFEST_NAME).write_text(
        json.dumps(source_manifest),
        encoding="utf-8",
    )

    class FakeRasPrj:
        def __init__(self):
            self.plan_df = pd.DataFrame()
            self.geom_df = pd.DataFrame()
            self.project_crs = None

        @staticmethod
        def get_project_units(project_file):
            return "English"

    def fake_init(project_file, **kwargs):
        ras_object = kwargs["ras_object"]
        ras_object.project_crs = "ESRI:102629"
        ras_object.plan_df = pd.DataFrame(
            [
                {
                    "plan_number": "01",
                    "geometry_number": "01",
                    "full_path": str(paths["plan"]),
                    "Flow Path": str(paths["flow"]),
                    "Flow File": "01",
                    "plan_type": "steady_1d",
                    "Program Version": "6.20",
                }
            ]
        )
        ras_object.geom_df = pd.DataFrame(
            [
                {
                    "geom_number": "01",
                    "full_path": str(paths["geometry"]),
                    "hdf_path": str(paths["geometry_hdf"]),
                    "geometry_type": "1D",
                    "num_cross_sections": 10,
                }
            ]
        )
        return ras_object

    monkeypatch.setattr(ras_prj_module, "RasPrj", FakeRasPrj)
    monkeypatch.setattr(ras_prj_module, "init_ras_project", fake_init)

    payload = AlabamaBleModels.build_watershed_delivery_inventory(root)

    assert payload["model_count"] == 1
    assert payload["schema_name"] == "ras_commander.watershed_delivery_inventory"
    assert payload["contract_version"] == "1.0.0"
    assert payload["schema_version"] == 1
    assert payload["path_policy"] == "relative_to_delivery_root"
    record = payload["records"][0]
    assert record["model_id"] == "publisher-model-id"
    assert record["project_crs"] == "ESRI:102629"
    assert record["files"]["project"]["path"].startswith("RAS Models/")
    assert str(tmp_path) not in json.dumps(payload)
    assert (documentation / "watershed_delivery_inventory.json").is_file()

    custom_relative = Path("Documentation") / "custom_inventory.json"
    AlabamaBleModels.build_watershed_delivery_inventory(
        root,
        output_path=custom_relative,
    )
    assert (root / custom_relative).is_file()

    paths["geometry"].write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="CRC32 audit"):
        AlabamaBleModels.build_watershed_delivery_inventory(root)
    paths["geometry"].write_bytes(b"geometry")

    sidecar.write_text(
        json.dumps({**source_identity, "etag": '"different-etag"'}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="sidecar identity differs"):
        AlabamaBleModels.build_watershed_delivery_inventory(root)
    sidecar.write_text(json.dumps(source_identity), encoding="utf-8")

    source_manifest["records"][0]["extraction"]["path"] = "../outside"
    (documentation / AlabamaBleModels._MANIFEST_NAME).write_text(
        json.dumps(source_manifest),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="escapes its delivery container"):
        AlabamaBleModels.build_watershed_delivery_inventory(root)


def test_downloaded_watershed_feeds_portable_delivery_inventory(
    monkeypatch,
    tmp_path,
):
    _patch_qualification(monkeypatch, {"Halawakee Creek": 1})
    url = "https://files.alabamaflood.com/Models/BLE/MODEL_BLE.zip"
    metadata = _metadata(
        "publisher-model-id",
        basin="Halawakee Creek",
        name="MODEL BLE",
        file_name="MODEL_BLE.zip",
        url=url,
    )
    monkeypatch.setattr(
        AlabamaBleModels,
        "build_watershed_manifest",
        staticmethod(lambda huc8: [metadata]),
    )

    def fake_download(source_url, destination, **kwargs):
        assert source_url == url
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(
            _zip_bytes(
                {
                    "MODEL/MODEL.prj": "Proj Title=Model\n",
                    "MODEL/MODEL.p01": "Plan Title=Plan\n",
                    "MODEL/MODEL.g01": "Geom Title=Geometry\n",
                    "MODEL/MODEL.g01.hdf": b"geometry-hdf",
                    "MODEL/MODEL.f01": "Flow Title=Flow\n",
                }
            )
        )
        identity = {
            "source_url": source_url,
            "final_url": source_url,
            "size_bytes": destination.stat().st_size,
            "etag": '"strong-etag"',
        }
        sidecar = AlabamaBleModels._source_sidecar(destination)
        sidecar.write_text(json.dumps(identity), encoding="utf-8")
        return {**identity, "path": str(destination), "sidecar": str(sidecar)}

    monkeypatch.setattr(
        AlabamaBleModels,
        "_download_file",
        staticmethod(fake_download),
    )

    result = AlabamaBleModels.download_watershed(HUC8, tmp_path)

    assert result.success is True
    delivery = Path(result.model_path)
    source_manifest = json.loads(
        (delivery / "Documentation" / AlabamaBleModels._MANIFEST_NAME).read_text(
            encoding="utf-8"
        )
    )
    record = source_manifest["records"][0]
    assert record["study_id"] == STUDY_KEY
    assert record["model_id"] == "publisher-model-id"
    assert record["model_key"] == f"{STUDY_KEY}:publisher-model-id"
    assert record["display_id"] == "MODEL_BLE"
    assert len(record["archive_sha256"]) == 64
    assert record["archive_path"].startswith("Source Archives/")
    assert record["extraction"]["project_files"] == ["MODEL/MODEL.prj"]
    assert set(record["extraction"]) >= {
        "path",
        "member_count",
        "file_count",
        "project_files",
    }

    ras_prj_module = importlib.import_module("ras_commander.RasPrj")

    class FakeRasPrj:
        def __init__(self):
            self.plan_df = pd.DataFrame()
            self.geom_df = pd.DataFrame()
            self.project_crs = None

        @staticmethod
        def get_project_units(project_file):
            return "English"

    def fake_init(project_file, **kwargs):
        ras_object = kwargs["ras_object"]
        model_root = Path(project_file).parent
        ras_object.project_crs = "ESRI:102629"
        ras_object.plan_df = pd.DataFrame(
            [
                {
                    "plan_number": "01",
                    "geometry_number": "01",
                    "full_path": str(model_root / "MODEL.p01"),
                    "Flow Path": str(model_root / "MODEL.f01"),
                    "Flow File": "01",
                    "plan_type": "steady_1d",
                    "Program Version": "6.20",
                }
            ]
        )
        ras_object.geom_df = pd.DataFrame(
            [
                {
                    "geom_number": "01",
                    "full_path": str(model_root / "MODEL.g01"),
                    "hdf_path": str(model_root / "MODEL.g01.hdf"),
                    "geometry_type": "1D",
                    "num_cross_sections": 10,
                }
            ]
        )
        return ras_object

    monkeypatch.setattr(ras_prj_module, "RasPrj", FakeRasPrj)
    monkeypatch.setattr(ras_prj_module, "init_ras_project", fake_init)

    inventory = AlabamaBleModels.build_watershed_delivery_inventory(delivery)

    assert inventory["model_count"] == 1
    assert inventory["records"][0]["model_key"] == record["model_key"]
    assert (
        inventory["records"][0]["files"]["source_archive"]["sha256"]
        == record["archive_sha256"]
    )


def test_download_watershed_rejects_incorrect_qualified_count_before_writes(
    monkeypatch,
    tmp_path,
):
    metadata = _metadata(
        "only-one",
        basin="Halawakee Creek",
        name="ONLY ONE",
        url="https://files.alabamaflood.com/only-one.zip",
    )
    monkeypatch.setattr(
        AlabamaBleModels,
        "build_watershed_manifest",
        staticmethod(lambda huc8: [metadata]),
    )
    monkeypatch.setattr(
        AlabamaBleModels,
        "_download_file",
        staticmethod(lambda *args, **kwargs: pytest.fail("must fail before download")),
    )

    result = AlabamaBleModels.download_watershed(HUC8, tmp_path)

    assert result.success is False
    assert "expected 197" in result.message
    assert not (tmp_path / STUDY_KEY).exists()


def test_organize_watershed_rejects_incorrect_qualified_basins_before_writes(
    monkeypatch,
    tmp_path,
):
    source_root = tmp_path / "staged"
    source_root.mkdir()
    models = [
        _metadata(
            f"model-{ordinal:03d}",
            basin="Incorrect Basin",
            name=f"MODEL {ordinal:03d}",
            url=f"https://files.alabamaflood.com/M{ordinal:03d}.zip",
        )
        for ordinal in range(197)
    ]
    monkeypatch.setattr(
        AlabamaBleModels,
        "build_watershed_manifest",
        staticmethod(lambda huc8: models),
    )

    result = AlabamaBleModels.organize_watershed(
        HUC8,
        source_root,
        tmp_path / "output",
    )

    assert result.success is False
    assert "basin inventory differs" in result.message
    assert not (tmp_path / "output" / STUDY_KEY).exists()


def test_download_watershed_deduplicates_shared_webpaths_and_uses_one_folder(
    monkeypatch,
    tmp_path,
):
    _patch_qualification(monkeypatch, {"Town Creek": 2})
    shared_url = "https://files.alabamaflood.com/Models/BLE/shared.zip"
    manifest = [
        _metadata(
            "alias-a",
            basin="Town Creek",
            name="Alias A",
            url=shared_url,
            file_name="shared.zip",
        ),
        _metadata(
            "alias-b",
            basin="Town Creek",
            name="Alias B",
            url=shared_url,
            file_name="shared.zip",
        ),
    ]
    monkeypatch.setattr(
        AlabamaBleModels,
        "build_watershed_manifest",
        staticmethod(lambda huc8: manifest),
    )
    downloads: list[tuple[str, Path]] = []

    def fake_download(url, destination, overwrite=False, **kwargs):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(
            _zip_bytes(
                {
                    "model/model.prj": "Proj Title=Model\n",
                    "model/model.p01": "Plan Title=Plan\n",
                }
            )
        )
        identity = {
            "source_url": url,
            "final_url": url,
            "size_bytes": destination.stat().st_size,
            "etag": '"strong-etag"',
        }
        sidecar = AlabamaBleModels._source_sidecar(destination)
        sidecar.write_text(json.dumps(identity), encoding="utf-8")
        downloads.append((url, destination))
        return {**identity, "path": str(destination), "sidecar": str(sidecar)}

    monkeypatch.setattr(
        AlabamaBleModels,
        "_download_file",
        staticmethod(fake_download),
    )

    result = AlabamaBleModels.download_watershed(HUC8, tmp_path)

    assert result.success is True
    assert Path(result.model_path) == tmp_path / STUDY_KEY
    assert [url for url, _ in downloads] == [shared_url]
    assert (tmp_path / STUDY_KEY / "RAS Models" / "Town_Creek").is_dir()
