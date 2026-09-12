import io
import json
import re
import sys
import types
import zipfile
from copy import deepcopy
from pathlib import Path

import h5py
import pytest


county_module = types.ModuleType("ras_commander.sources.county")
county_module.M3Model = object
sys.modules.setdefault("ras_commander.sources.county", county_module)

import ras_commander.sources.federal.ebfe_models as ebfe_module  # noqa: E402
from ras_commander.sources.federal.ebfe_models import RasEbfeModels  # noqa: E402


EXPECTED_ASSETS = {
    "12050004_Hydraulics_metadata.xml": (
        28_875,
        "a149836c1958feb0b3603d303af162d9",
        False,
    ),
    "2D_Model_Inventory_DMFB.xlsx": (
        75_079,
        "63e636e27ef24c0b8b9608ba7f7b1796",
        False,
    ),
    "DMF1.zip": (
        18_618_972_780,
        "b2525fb2acddab7bf6a08c9bb4b05e6d-2220",
        True,
    ),
    "DMF2.zip": (
        14_441_820_955,
        "5b45379aaf0e81094d895b52bc22ff40-1722",
        True,
    ),
    "DMF3.zip": (
        19_345_728_748,
        "07cc4953ed947f993f7a1d56a39171a9-2307",
        True,
    ),
    "DMF4.zip": (
        16_276_009_395,
        "5976fb982e816ad9ff018a4ecf36a277-1941",
        True,
    ),
    "Readme.txt": (
        366,
        "2edb770c1683ba7833d8122761f3a66b",
        False,
    ),
}


class _FakeDownloadResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status_code: int,
        headers: dict[str, str],
        url: str,
    ) -> None:
        self.body = body
        self.status_code = status_code
        self.headers = headers
        self.url = url
        self.closed = False

    def iter_content(self, chunk_size: int = 8192):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start:start + chunk_size]

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def close(self) -> None:
        self.closed = True


class _NoopProgress:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def update(self, amount: int) -> None:
        del amount


def _disable_download_progress(monkeypatch) -> None:
    monkeypatch.setattr(
        RasEbfeModels,
        "_progress",
        staticmethod(lambda **_kwargs: _NoopProgress()),
    )


def _iter_manifest_strings(value, trail=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _iter_manifest_strings(item, (*trail, str(key)))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _iter_manifest_strings(item, (*trail, str(index)))
    elif isinstance(value, str):
        yield trail, value


def _write_zip(path: Path, members: dict[str, str | bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return path


def _geometry_hdf_bytes(
    area_name: str,
    top_level_associations: dict[str, str],
    area_associations: dict[str, str] | None = None,
) -> bytes:
    stream = io.BytesIO()
    with h5py.File(stream, "w") as hdf_file:
        geometry = hdf_file.create_group("Geometry")
        geometry.attrs["Extents"] = [0.0, 100.0, 0.0, 100.0]
        for attr_name, attr_value in top_level_associations.items():
            geometry.attrs[attr_name] = attr_value.encode("utf-8")
        area = geometry.create_group("2D Flow Areas").create_group(area_name)
        area.attrs["Extents"] = [0.0, 100.0, 0.0, 100.0]
        for attr_name, attr_value in (area_associations or {}).items():
            area.attrs[attr_name] = attr_value.encode("utf-8")
    return stream.getvalue()


def _asset_hdf_bytes(vrt_name: str) -> bytes:
    stream = io.BytesIO()
    with h5py.File(stream, "w") as hdf_file:
        raster = hdf_file.create_group("Raster")
        raster.attrs["Raster Filename"] = vrt_name.encode("utf-8")
    return stream.getvalue()


def _vrt(raster_name: str) -> str:
    return (
        "<VRTDataset rasterXSize=\"1\" rasterYSize=\"1\">"
        "<VRTRasterBand dataType=\"Byte\" band=\"1\"><SimpleSource>"
        f"<SourceFilename relativeToVRT=\"1\">{raster_name}</SourceFilename>"
        "</SimpleSource></VRTRasterBand></VRTDataset>"
    )


def _project_members(name: str) -> dict[str, str | bytes]:
    settings = RasEbfeModels._DOUBLE_MOUNTAIN_FORK_BRAZOS_PROJECTS[name]
    stem = settings["project"]
    plan = settings["plan"]
    geometry = settings["geometry"]
    unsteady = settings["unsteady"]
    root = f"{name}/"

    if name == "DMF1":
        projection_source = "Projection/Projection.prj"
        projection_reference = ".\\Projection\\Projection.prj"
        terrain_name = "Terrain.hdf"
        land_name = "LandCover.hdf"
        dss_folder = "InputDSS"
        unsteady_dss = "..\\InputDSS\\TO1_Precipitation.dss"
        dependency_files = {}
        area_name = "DMF_1"
        land_folder = "Landcover"
    elif name == "DMF2":
        projection_source = (
            "NAD 1983 State Plane Texas North Central FIPS 4202.prj"
        )
        projection_reference = (
            ".\\NAD 1983 State Plane Texas North Central FIPS 4202.prj"
        )
        terrain_name = "Terrain.Clone (1).hdf"
        land_name = "Landcover2.hdf"
        dss_folder = "Input_DSS"
        unsteady_dss = "..\\Input_DSS\\TO1_Precipitation.dss"
        dependency_files = {"DMF_1.dss": "upstream DMF1"}
        area_name = "Upper Double Mountain Fork"
        land_folder = "LandCover"
    elif name == "DMF3":
        projection_source = (
            "Projection/NAD 1983 State Plane Texas North Central FIPS 4202.prj"
        )
        projection_reference = (
            ".\\Projection\\NAD 1983 State Plane Texas North Central "
            "FIPS 4202.prj"
        )
        terrain_name = "Terrain.hdf"
        land_name = "LandCover.hdf"
        dss_folder = "Input_DSS"
        unsteady_dss = ".\\Input_DSS\\TO1_Precipitation.dss"
        dependency_files = {
            "DMF2.dss": "upstream DMF2",
            "NFDMFB_3.dss": "local tributary",
        }
        area_name = "DMF_3"
        land_folder = "LandCover"
    else:
        projection_source = (
            "NAD 1983 State Plane Texas North Central FIPS 4202.prj"
        )
        projection_reference = (
            ".\\NAD 1983 State Plane Texas North Central FIPS 4202.prj"
        )
        terrain_name = "Terrain.hdf"
        land_name = "LandCover_v2.hdf"
        dss_folder = "Precipitation_DSS"
        unsteady_dss = ".\\Precipitation_DSS\\TO1_Precipitation.dss"
        dependency_files = {"DMF_3.dss": "upstream DMF3"}
        area_name = "DMF_BrazosRiver4"
        land_folder = "LandCover"

    delivered_area_associations = {}
    infiltration_name = (
        "InfiltrationSCS (1).hdf"
        if name == "DMF2"
        else "InfiltrationSCS.hdf"
    )
    delivered_top_level_associations = {
        "Terrain Filename": f"..\\Terrain\\{terrain_name}",
        "Land Cover Filename": f"..\\{land_folder}\\{land_name}",
        "Infiltration Filename": (
            f"..\\{land_folder}\\{infiltration_name}"
        ),
    }
    if name in {"DMF3", "DMF4"}:
        delivered_area_associations = {
            "Terrain Filename": f".\\Terrain\\{terrain_name}",
            "Land Cover Filename": (
                f".\\Land Classification\\{land_name}"
            ),
            "Infiltration Filename": (
                f".\\Land Classification\\{infiltration_name}"
            ),
        }

    terrain_members = {
        f"{root}Terrain/{terrain_name}": _asset_hdf_bytes("terrain.vrt"),
        f"{root}Terrain/terrain.vrt": _vrt("terrain_part.tif"),
        f"{root}Terrain/terrain_part.tif": f"terrain-raster-{name}",
    }
    if name == "DMF2":
        terrain_members[f"{root}Terrain/Terrain.hdf"] = _asset_hdf_bytes(
            "terrain.vrt"
        )

    members = {
        f"{root}Input/{stem}.prj": (
            f"Proj Title={name}\n"
            f"Current Plan=p{plan}\n"
            f"Plan File=p{plan}\n"
        ),
        f"{root}Input/{stem}.p{plan}": (
            f"Geom File=g{geometry}\nUnsteady File=u{unsteady}\n"
        ),
        f"{root}Input/{stem}.g{geometry}": "geometry",
        f"{root}Input/{stem}.g{geometry}.hdf": _geometry_hdf_bytes(
            area_name,
            delivered_top_level_associations,
            delivered_area_associations,
        ),
        f"{root}Input/{stem}.u{unsteady}": (
            "Precipitation|Gridded DSS Filename=" + unsteady_dss + "\n"
        ),
        f"{root}Input/{stem}.p{plan}.hdf": "delivered-result",
        f"{root}Input/{stem}.IC.O{plan}": "initial-condition",
        f"{root}Input/{dss_folder}/TO1_Precipitation.dss": "precipitation",
        f"{root}Input/{projection_source}": "PROJCS[\"Texas North Central\"]",
        f"{root}Input/{stem}.rasmap": (
            "<RASMapper>\n"
            f"<RASProjectionFilename Filename=\"{projection_reference}\" />\n"
            "<Terrains>"
            f"<Layer Name=\"Terrain\" Type=\"TerrainLayer\" "
            f"Filename=\"..\\Terrain\\{terrain_name}\" />"
            "</Terrains>\n"
            "<LandCoverLayers>\n"
            f"<Layer Name=\"Land Cover\" Type=\"LandCoverLayer\" "
            f"Filename=\"..\\{land_folder}\\{land_name}\">\n"
            f"<Layer Name=\"Infiltration\" Type=\"LandCoverLayer\" "
            f"Filename=\"..\\{land_folder}\\{infiltration_name}\" />\n"
            "</Layer>\n"
            "</LandCoverLayers>\n"
            + (
                "<Layer Type=\"Precipitation\" "
                "Filename=\"..\\Input_DSS\\TO1_Precipitation.dss\" />\n"
                if name == "DMF2"
                else ""
            )
            + "</RASMapper>\n"
        ),
        f"{root}{land_folder}/{land_name}": _asset_hdf_bytes("landcover.vrt"),
        f"{root}{land_folder}/landcover.vrt": _vrt("landcover.tif"),
        f"{root}{land_folder}/landcover.tif": f"land-cover-raster-{name}",
        f"{root}{land_folder}/InfiltrationSCS.hdf": _asset_hdf_bytes(
            "infiltration.vrt"
        ),
        f"{root}{land_folder}/infiltration.vrt": _vrt("infiltration.tif"),
        f"{root}{land_folder}/infiltration.tif": f"infiltration-raster-{name}",
        **terrain_members,
    }
    if name == "DMF2":
        members.pop(f"{root}{land_folder}/InfiltrationSCS.hdf")
        members[f"{root}{land_folder}/InfiltrationSCS (1).hdf"] = (
            _asset_hdf_bytes("infiltration.vrt")
        )
    for filename, content in dependency_files.items():
        members[f"{root}Input/{dss_folder}/{filename}"] = content
    return members


def _build_synthetic_delivery(tmp_path: Path, monkeypatch) -> Path:
    source_root = tmp_path / "raw" / "12050004_DoubleMountainForkBrazos"
    source_root.mkdir(parents=True)
    for name in RasEbfeModels._DOUBLE_MOUNTAIN_FORK_BRAZOS_PROJECTS:
        _write_zip(source_root / f"{name}.zip", _project_members(name))

    (source_root / "12050004_Hydraulics_metadata.xml").write_text(
        "<metadata />", encoding="utf-8"
    )
    (source_root / "2D_Model_Inventory_DMFB.xlsx").write_text(
        "inventory", encoding="utf-8"
    )
    (source_root / "Readme.txt").write_text("readme", encoding="utf-8")

    assets = deepcopy(
        RasEbfeModels._DOUBLE_MOUNTAIN_FORK_BRAZOS_SOURCE_ASSETS
    )
    for asset in assets:
        source_file = source_root / asset["name"]
        asset["size_bytes"] = source_file.stat().st_size
        RasEbfeModels._source_sidecar_path(source_file).write_text(
            json.dumps({
                "source": asset["url"],
                "final_url": asset["url"],
                "size": source_file.stat().st_size,
                "etag": asset["etag"],
            }),
            encoding="utf-8",
        )
    monkeypatch.setitem(
        RasEbfeModels._MODEL_REGISTRY[
            "double-mountain-fork-brazos"
        ]["extra"],
        "source_assets",
        assets,
    )
    return source_root


def test_registry_aliases_exact_sources_and_chain_contract() -> None:
    assert (
        RasEbfeModels.normalize_model_key("Double Mountain Fork Brazos")
        == "double-mountain-fork-brazos"
    )
    assert RasEbfeModels.normalize_model_key("dmfb") == (
        "double-mountain-fork-brazos"
    )
    assert RasEbfeModels.normalize_model_key("12050004") == (
        "double-mountain-fork-brazos"
    )

    metadata = RasEbfeModels.get_model_metadata("12050004")
    assert metadata.hecras_version == "6.10"
    assert metadata.model_type.name == "UNSTEADY_2D"
    assert metadata.url.endswith("/Models/DMF1.zip")
    assert metadata.file_size_mb == 18_618_972_780 / (1024 * 1024)
    assert metadata.extra["qualified_ras_version"] == "6.1"
    assert metadata.extra["source_program"] == "fema_ebfe"
    assert metadata.extra["campaign_lane_classification"] == "pending"
    assert "lane_kind" not in metadata.extra
    assert metadata.extra["total_size_bytes"] == 68_682_636_198
    assert metadata.extra["required_validation_level"] == "unsteady_start"
    assert metadata.extra["validation_status"] == "pending"
    assert metadata.extra["hec_ras_executed"] is False
    assert metadata.extra["native_hydraulic_readiness"] is False
    assert metadata.extra["native_qualification_required"] is True
    assert "preprocessed geometry" not in metadata.description
    assert metadata.extra["dependency_order"] == ["DMF1", "DMF2", "DMF3", "DMF4"]
    assert metadata.extra["canonical_plan_contract"] == {
        "DMF1": {"project": "DMF_1", "plan": "04", "geometry": "01", "unsteady": "03"},
        "DMF2": {"project": "DMF2", "plan": "01", "geometry": "01", "unsteady": "01"},
        "DMF3": {"project": "DMF_3", "plan": "01", "geometry": "01", "unsteady": "02"},
        "DMF4": {"project": "DMF_BrazosRiver4", "plan": "01", "geometry": "01", "unsteady": "01"},
    }

    assets = {item["name"]: item for item in metadata.extra["source_assets"]}
    assert set(assets) == set(EXPECTED_ASSETS)
    assert sum(item["size_bytes"] for item in assets.values()) == 68_682_636_198
    for name, (size, etag, extract) in EXPECTED_ASSETS.items():
        assert assets[name]["size_bytes"] == size
        assert assets[name]["etag"] == etag
        assert assets[name]["extract"] is extract
        assert assets[name]["url"].endswith(f"/Models/{name}")


def test_download_source_asset_retains_loose_files_and_defaults_to_archives(
    tmp_path,
    monkeypatch,
) -> None:
    loose_calls = {}
    archive_calls = {}

    def fake_download_file(url, dest, description="", **kwargs):
        loose_calls.update(url=url, dest=dest, description=description, **kwargs)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("metadata", encoding="utf-8")
        return dest

    def fake_download_and_extract(url, output_folder, description, **kwargs):
        archive_calls.update(
            url=url,
            output_folder=output_folder,
            description=description,
            **kwargs,
        )
        return output_folder / "DMF1_extracted"

    monkeypatch.setattr(
        RasEbfeModels, "_download_file", staticmethod(fake_download_file)
    )
    monkeypatch.setattr(
        RasEbfeModels,
        "_download_and_extract",
        staticmethod(fake_download_and_extract),
    )

    loose = RasEbfeModels.download_source_asset(
        "12050004", "hydraulics_metadata", tmp_path
    )
    assert loose == tmp_path / "12050004_Hydraulics_metadata.xml"
    assert loose_calls["expected_size_bytes"] == 28_875
    assert loose_calls["expected_etag"] == EXPECTED_ASSETS[
        "12050004_Hydraulics_metadata.xml"
    ][1]

    extracted = RasEbfeModels.download_source_asset(
        "dmfb", "dmf1_models", tmp_path
    )
    assert extracted == tmp_path / "DMF1_extracted"
    assert archive_calls["expected_size_bytes"] == 18_618_972_780
    assert archive_calls["expected_etag"].endswith("-2220")


def test_loose_file_resume_requires_recorded_etag_and_exact_range(
    tmp_path,
    monkeypatch,
) -> None:
    url = "https://example.com/metadata.xml"
    current = b"current-loose-file"
    dest = tmp_path / "metadata.xml"
    part = RasEbfeModels._get_partial_download_path(dest)
    resume_from = 7
    part.write_bytes(current[:resume_from])
    RasEbfeModels._write_partial_download_identity(
        part,
        source_url=url,
        final_url=url,
        etag="current-etag",
    )
    calls = []

    def fake_get(request_url, **kwargs):
        calls.append((request_url, kwargs))
        return _FakeDownloadResponse(
            current[resume_from:],
            status_code=206,
            headers={
                "etag": '"current-etag"',
                "content-length": str(len(current) - resume_from),
                "content-range": (
                    f"bytes {resume_from}-{len(current) - 1}/{len(current)}"
                ),
            },
            url=url,
        )

    monkeypatch.setattr(ebfe_module.requests, "get", fake_get)
    _disable_download_progress(monkeypatch)

    result = RasEbfeModels._download_file(
        url,
        dest,
        expected_size_bytes=len(current),
        expected_etag="current-etag",
    )

    assert result.read_bytes() == current
    assert calls[0][1]["headers"] == {
        "Range": f"bytes={resume_from}-",
        "If-Range": '"current-etag"',
    }
    assert not RasEbfeModels._source_sidecar_path(part).exists()
    final_identity = json.loads(
        RasEbfeModels._source_sidecar_path(dest).read_text(encoding="utf-8")
    )
    assert final_identity["partial"] is False
    assert final_identity["etag"] == "current-etag"


def test_unverified_stale_loose_file_prefix_restarts_without_range(
    tmp_path,
    monkeypatch,
) -> None:
    url = "https://example.com/metadata.xml"
    current = b"current-loose-file"
    dest = tmp_path / "metadata.xml"
    part = RasEbfeModels._get_partial_download_path(dest)
    part.write_bytes(b"stale-prefix")
    calls = []

    def fake_get(request_url, **kwargs):
        calls.append((request_url, kwargs))
        return _FakeDownloadResponse(
            current,
            status_code=200,
            headers={
                "etag": '"current-etag"',
                "content-length": str(len(current)),
            },
            url=url,
        )

    monkeypatch.setattr(ebfe_module.requests, "get", fake_get)
    _disable_download_progress(monkeypatch)

    RasEbfeModels._download_file(
        url,
        dest,
        expected_size_bytes=len(current),
        expected_etag="current-etag",
    )

    assert dest.read_bytes() == current
    assert len(calls) == 1
    assert calls[0][1]["headers"] is None
    final_identity = json.loads(
        RasEbfeModels._source_sidecar_path(dest).read_text(encoding="utf-8")
    )
    assert final_identity["etag"] == "current-etag"
    assert final_identity["size"] == len(current)


def test_unverified_stale_prefix_cannot_gain_sidecar_from_unrequested_tail(
    tmp_path,
    monkeypatch,
) -> None:
    url = "https://example.com/metadata.xml"
    current = b"current-loose-file"
    dest = tmp_path / "metadata.xml"
    part = RasEbfeModels._get_partial_download_path(dest)
    part.write_bytes(b"stale-prefix")

    def fake_get(request_url, **kwargs):
        assert request_url == url
        assert kwargs["headers"] is None
        return _FakeDownloadResponse(
            current[7:],
            status_code=206,
            headers={
                "etag": '"current-etag"',
                "content-range": (
                    f"bytes 7-{len(current) - 1}/{len(current)}"
                ),
            },
            url=url,
        )

    monkeypatch.setattr(ebfe_module.requests, "get", fake_get)
    _disable_download_progress(monkeypatch)

    with pytest.raises(RuntimeError, match="Unexpected partial HTTP response"):
        RasEbfeModels._download_file(
            url,
            dest,
            expected_size_bytes=len(current),
            expected_etag="current-etag",
        )

    assert not dest.exists()
    assert not part.exists()
    assert not RasEbfeModels._source_sidecar_path(dest).exists()


def test_wrong_resume_content_range_discards_prefix_before_full_download(
    tmp_path,
    monkeypatch,
) -> None:
    url = "https://example.com/metadata.xml"
    current = b"current-loose-file"
    dest = tmp_path / "metadata.xml"
    part = RasEbfeModels._get_partial_download_path(dest)
    resume_from = 7
    part.write_bytes(current[:resume_from])
    RasEbfeModels._write_partial_download_identity(
        part,
        source_url=url,
        final_url=url,
        etag="current-etag",
    )
    calls = []

    def fake_get(request_url, **kwargs):
        calls.append((request_url, kwargs))
        if len(calls) == 1:
            return _FakeDownloadResponse(
                current[resume_from:],
                status_code=206,
                headers={
                    "etag": '"current-etag"',
                    "content-range": (
                        f"bytes {resume_from + 1}-{len(current) - 1}/"
                        f"{len(current)}"
                    ),
                },
                url=url,
            )
        return _FakeDownloadResponse(
            current,
            status_code=200,
            headers={
                "etag": '"current-etag"',
                "content-length": str(len(current)),
            },
            url=url,
        )

    monkeypatch.setattr(ebfe_module.requests, "get", fake_get)
    _disable_download_progress(monkeypatch)

    RasEbfeModels._download_file(
        url,
        dest,
        expected_size_bytes=len(current),
        expected_etag="current-etag",
    )

    assert dest.read_bytes() == current
    assert len(calls) == 2
    assert calls[0][1]["headers"]["If-Range"] == '"current-etag"'
    assert "headers" not in calls[1][1]


def test_existing_asset_identity_rejects_wrong_size_and_etag(tmp_path) -> None:
    source = tmp_path / "source.zip"
    source.write_bytes(b"1234")

    try:
        RasEbfeModels._validate_source_asset_identity(
            source, expected_size_bytes=4, expected_etag="right"
        )
    except RuntimeError as exc:
        assert "ETag cannot be verified" in str(exc)
    else:
        raise AssertionError("same-size source without an ETag sidecar was accepted")

    sidecar = RasEbfeModels._source_sidecar_path(source)
    sidecar.write_text(
        json.dumps({"size": 4, "etag": "wrong"}),
        encoding="utf-8",
    )

    try:
        RasEbfeModels._validate_source_asset_identity(
            source, expected_size_bytes=5
        )
    except RuntimeError as exc:
        assert "size mismatch" in str(exc)
    else:
        raise AssertionError("wrong source size was accepted")

    try:
        RasEbfeModels._validate_source_asset_identity(
            source, expected_size_bytes=4, expected_etag="right"
        )
    except RuntimeError as exc:
        assert "ETag mismatch" in str(exc)
    else:
        raise AssertionError("wrong source ETag was accepted")


def test_serialized_path_relocation_handles_mapped_and_unc_staging_aliases(
    monkeypatch,
) -> None:
    lexical_staging = Path(
        r"H:\Testing\eBFE\12050004\.organized-final-v2.assembling-token"
    )
    resolved_staging = Path(
        r"\\192.168.3.20\CLB-Engineering\Testing\eBFE\12050004"
        r"\.organized-final-v2.assembling-token"
    )
    final_root = Path(
        r"\\192.168.3.20\CLB-Engineering\Testing\eBFE\12050004"
        r"\organized-final-v2"
    )
    original_resolve = Path.resolve

    def _resolve_alias(path, *args, **kwargs):
        normalized = str(path).replace("/", "\\").casefold().rstrip("\\")
        if normalized == str(lexical_staging).casefold().rstrip("\\"):
            return resolved_staging
        if normalized == str(final_root).casefold().rstrip("\\"):
            return final_root
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", _resolve_alias)
    payload = {
        "lexical": str(lexical_staging / "RAS Model" / "DMF1"),
        "resolved": str(resolved_staging / "RAS Model" / "DMF2"),
        "forward_slashes": str(
            lexical_staging / "agent" / "model_log.md"
        ).replace("\\", "/"),
        "embedded": (
            f"Unreadable HDF {resolved_staging / 'RAS Model' / 'DMF3'}: "
            "synthetic reason"
        ),
    }

    relocated = (
        RasEbfeModels
        ._relocate_double_mountain_fork_brazos_serialized_paths(
            payload,
            staging_root=lexical_staging,
            final_root=final_root,
        )
    )
    serialized = json.dumps(relocated)

    assert relocated["lexical"] == str(final_root / "RAS Model" / "DMF1")
    assert relocated["resolved"] == str(final_root / "RAS Model" / "DMF2")
    assert relocated["forward_slashes"].startswith(str(final_root))
    assert str(final_root / "RAS Model" / "DMF3") in relocated["embedded"]
    assert ".assembling-" not in serialized.casefold()
    assert str(lexical_staging).casefold() not in serialized.casefold()
    assert str(resolved_staging).casefold() not in serialized.casefold()


def test_organizer_assembles_four_projects_and_preserves_source(
    tmp_path,
    monkeypatch,
) -> None:
    source_root = _build_synthetic_delivery(tmp_path, monkeypatch)
    output = tmp_path / "organized"
    source_state = {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in source_root.iterdir()
        if path.is_file()
    }
    delivered_geometry_hdfs = {}
    for name, settings in (
        RasEbfeModels._DOUBLE_MOUNTAIN_FORK_BRAZOS_PROJECTS.items()
    ):
        member = (
            f"{name}/Input/{settings['project']}."
            f"g{settings['geometry']}.hdf"
        )
        with zipfile.ZipFile(source_root / f"{name}.zip") as archive:
            delivered_geometry_hdfs[name] = archive.read(member)

    organized = RasEbfeModels.organize_double_mountain_fork_brazos(
        downloaded_folder=source_root,
        output_folder=output,
        validate_dss=False,
    )
    assert organized == output
    assert source_state == {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in source_root.iterdir()
        if path.is_file()
    }

    for name, settings in (
        RasEbfeModels._DOUBLE_MOUNTAIN_FORK_BRAZOS_PROJECTS.items()
    ):
        project = output / "RAS Model" / name / name / "Input"
        stem = settings["project"]
        assert (project / f"{stem}.prj").is_file()
        assert (project / f"{stem}.p{settings['plan']}").is_file()
        assert (project / f"{stem}.g{settings['geometry']}").is_file()
        assert (project / f"{stem}.u{settings['unsteady']}").is_file()
        assert (project / "DSS Inputs" / "TO1_Precipitation.dss").is_file()
        unsteady_text = (project / f"{stem}.u{settings['unsteady']}").read_text(
            encoding="utf-8"
        )
        assert "DSS Inputs\\TO1_Precipitation.dss" in unsteady_text
        assert not (project / "Terrain").exists()
        assert not (project / "Land Cover").exists()
        assert (
            project / f"{stem}.g{settings['geometry']}.hdf"
        ).read_bytes() == delivered_geometry_hdfs[name]

    from ras_commander._geometry_association import read_geometry_association

    dmf2 = output / "RAS Model" / "DMF2" / "DMF2" / "Input"
    outer_dmf2_terrain = (
        dmf2.parent / "Terrain" / "Terrain.Clone (1).hdf"
    )
    assert outer_dmf2_terrain.is_file()
    assert "..\\Terrain\\Terrain.Clone (1).hdf" in (
        dmf2 / "DMF2.rasmap"
    ).read_text(encoding="utf-8")
    dmf1 = output / "RAS Model" / "DMF1" / "DMF1" / "Input"
    assert "..\\Landcover\\LandCover.hdf" in (
        dmf1 / "DMF_1.rasmap"
    ).read_text(encoding="utf-8")
    for name, settings in (
        RasEbfeModels._DOUBLE_MOUNTAIN_FORK_BRAZOS_PROJECTS.items()
    ):
        project = output / "RAS Model" / name / name / "Input"
        rasmap_text = (
            project / f"{settings['project']}.rasmap"
        ).read_text(encoding="utf-8")
        land_folder = "Landcover" if name == "DMF1" else "LandCover"
        asset_contract = (
            RasEbfeModels._DOUBLE_MOUNTAIN_FORK_BRAZOS_ASSOCIATION_ASSETS[
                name
            ]
        )
        assert (
            f"..\\Terrain\\{asset_contract['terrain']}" in rasmap_text
        )
        assert (
            f"..\\{land_folder}\\{asset_contract['landcover']}"
            in rasmap_text
        )
        assert (
            f"..\\{land_folder}\\{asset_contract['infiltration']}"
            in rasmap_text
        )
        infiltration_tag = next(
            match.group(0)
            for match in re.finditer(
                r"<Layer\b[^>]*>",
                rasmap_text,
                flags=re.IGNORECASE,
            )
            if 'Name="Infiltration"' in match.group(0)
        )
        assert (
            RasEbfeModels
            ._classify_double_mountain_fork_brazos_rasmap_layer(
                infiltration_tag,
                asset_contract,
            )
            == "infiltration"
        )
    dmf2_association = read_geometry_association(
        dmf2 / "DMF2.g01.hdf",
        resolve_paths=True,
        include_2d_area_attrs=True,
    )
    assert Path(dmf2_association["terrain_hdf_path"]) == outer_dmf2_terrain
    assert Path(dmf2_association["landcover_hdf_path"]) == (
        dmf2.parent / "LandCover" / "Landcover2.hdf"
    )
    assert Path(dmf2_association["infiltration_hdf_path"]) == (
        dmf2.parent / "LandCover" / "InfiltrationSCS (1).hdf"
    )
    dmf2_area_association = (
        dmf2_association["two_d_area_terrain_associations"][0]
    )
    assert dmf2_area_association["flow_area"] == (
        "Upper Double Mountain Fork"
    )
    assert dmf2_area_association["terrain_raw_filename"] is None
    assert dmf2_area_association["terrain_hdf_path"] is None

    expected_projections = {
        "DMF1": "DMF_1_Projection.prj",
        "DMF2": "NAD 1983 State Plane Texas North Central FIPS 4202.prj",
        "DMF3": "DMF_3_Projection.prj",
        "DMF4": "NAD 1983 State Plane Texas North Central FIPS 4202.prj",
    }
    for name, projection_name in expected_projections.items():
        project = output / "RAS Model" / name / name / "Input"
        assert (project / "Projection" / projection_name).is_file()
        rasmap = next(project.glob("*.rasmap")).read_text(encoding="utf-8")
        assert f".\\Projection\\{projection_name}" in rasmap

    for name in (
        "12050004_Hydraulics_metadata.xml",
        "2D_Model_Inventory_DMFB.xlsx",
        "Readme.txt",
    ):
        assert (output / "Documentation" / name).is_file()

    manifest_path = (
        output / "agent" / "double_mountain_fork_brazos_manifest.json"
    )
    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert ".assembling-" not in manifest_text
    manifest = json.loads(manifest_text)
    assert Path(manifest["output_root"]) == output.resolve()
    for trail, value in _iter_manifest_strings(manifest):
        candidate = Path(value)
        if not candidate.is_absolute():
            continue
        if (
            trail[-1] == "resolved_path"
            and any(
                section in trail
                for section in (
                    "named_area_association_gaps",
                    "native_blocking_gaps",
                    "blocking_gaps",
                    "qualification_required_gaps",
                )
            )
        ):
            continue
        assert candidate.exists(), (
            f"Serialized local path does not survive promotion at "
            f"{'.'.join(trail)}: {candidate}"
        )
    assert manifest["dependency_order"] == ["DMF1", "DMF2", "DMF3", "DMF4"]
    assert manifest["source_objects_immutable"] is True
    assert manifest["terrain_source_complete"] is True
    assert manifest["modified_terrain"]["preserved"] is True
    assert manifest["supplied_audit_repair_recipe_rows"] == 47
    assert manifest["actual_explicit_corrections"] == len(
        manifest["explicit_repairs"]
    )
    assert manifest["required_validation_level"] == "unsteady_start"
    assert manifest["validation_status"] == "pending"
    assert manifest["hec_ras_executed"] is False
    assert manifest["campaign_lane_classification"] == "pending"
    assert manifest["standardization"]["surface_asset_policy"] == (
        "preserve_delivered_outer_siblings"
    )
    assert all(
        item["geometry_hdf_modified"] is False
        for item in manifest["sibling_asset_associations"]
    )
    assert manifest["reference_audit"]["static_path_closure"] is True
    assert manifest["reference_audit"]["hydraulic_reference_closure"] is None
    assert manifest["reference_audit"]["association_mismatches"] == []
    assert (
        manifest["reference_audit"]["native_geometry_association_ready"]
        is False
    )
    assert manifest["reference_audit"]["native_qualification_required"] is True
    assert len(
        manifest["reference_audit"]["named_area_association_gaps"]
    ) == 12
    assert {
        item["project"]
        for item in manifest["reference_audit"][
            "named_area_association_gaps"
        ]
    } == {"DMF1", "DMF2", "DMF3", "DMF4"}
    assert len(manifest["reference_audit"]["companion_references"]) == 24
    native_blocking_gaps = manifest["reference_audit"][
        "native_blocking_gaps"
    ]
    assert len(native_blocking_gaps) == 17
    assert {
        item["gap_type"] for item in native_blocking_gaps
    } == {
        "named_area_surface_association",
        "native_property_tables_pending",
        "unsteady_start_validation_pending",
    }
    assert manifest["reference_audit"]["native_hydraulic_readiness"] is False
    assert manifest["blocking_gaps"] == native_blocking_gaps
    assert manifest["native_blocking_gaps"] == native_blocking_gaps
    assert manifest["qualification_required_gaps"] == native_blocking_gaps
    assert len(manifest["nonblocking_unresolved_references"]) == 3
    assert len(manifest["explicit_repairs"]) >= 6
    assert (output / "agent" / "model_log.md").is_file()
    rod = (
        output / "agent" / "record_of_deficiencies.md"
    ).read_text(encoding="utf-8")
    model_log = (
        output / "agent" / "model_log.md"
    ).read_text(encoding="utf-8")
    assert ".assembling-" not in rod
    assert ".assembling-" not in model_log
    assert "static delivery-path closure" in rod
    assert "hydraulic path closure" not in rod
    assert "**DMF1, DMF2, DMF3, DMF4**" in rod

    before = manifest_path.read_bytes()
    assert RasEbfeModels.organize_double_mountain_fork_brazos(
        downloaded_folder=source_root,
        output_folder=output,
    ) == output
    assert manifest_path.read_bytes() == before
    assert ".assembling-" not in manifest_path.read_text(encoding="utf-8")

    missing_companion = (
        output
        / "RAS Model"
        / "DMF3"
        / "DMF3"
        / "Terrain"
        / "terrain_part.tif"
    )
    missing_companion.unlink()
    project_folders = (
        RasEbfeModels._double_mountain_fork_brazos_project_folders(
            output / "RAS Model",
            require_contract=True,
        )
    )
    failed_audit = RasEbfeModels._audit_double_mountain_fork_brazos_references(
        project_folders
    )
    assert failed_audit["static_path_closure"] is False
    assert failed_audit["hydraulic_reference_closure"] is None
    assert str(missing_companion) in failed_audit["missing_hydraulic_references"]
    assert RasEbfeModels._double_mountain_fork_brazos_is_reusable(
        output,
        source_root=source_root,
        assets=RasEbfeModels._MODEL_REGISTRY[
            "double-mountain-fork-brazos"
        ]["extra"]["source_assets"],
    ) is False


def test_reference_audit_classifies_stale_named_area_path_as_qualification_gap(
    tmp_path,
    monkeypatch,
) -> None:
    source_root = _build_synthetic_delivery(tmp_path, monkeypatch)
    output = tmp_path / "organized"
    RasEbfeModels.organize_double_mountain_fork_brazos(
        downloaded_folder=source_root,
        output_folder=output,
    )

    project = output / "RAS Model" / "DMF3" / "DMF3" / "Input"
    with h5py.File(project / "DMF_3.g01.hdf", "r+") as hdf_file:
        area = hdf_file["Geometry/2D Flow Areas/DMF_3"]
        area.attrs["Terrain Filename"] = b".\\Terrain\\Terrain.hdf"

    project_folders = (
        RasEbfeModels._double_mountain_fork_brazos_project_folders(
            output / "RAS Model",
            require_contract=True,
        )
    )
    audit = RasEbfeModels._audit_double_mountain_fork_brazos_references(
        project_folders
    )
    assert audit["static_path_closure"] is True
    assert audit["hydraulic_reference_closure"] is None
    assert audit["missing_hydraulic_references"] == []
    assert audit["association_mismatches"] == []
    stale_gap = next(
        item
        for item in audit["named_area_association_gaps"]
        if item["surface"] == "named_2d_area:DMF_3"
        and item["asset_kind"] == "terrain"
    )
    assert stale_gap["observed"] == ".\\Terrain\\Terrain.hdf"
    assert stale_gap["resolved_path"] == str(
        project / "Terrain" / "Terrain.hdf"
    )
    assert stale_gap["expected"] == str(
        project.parent / "Terrain" / "Terrain.hdf"
    )


def test_pending_unsteady_start_remains_blocking_with_complete_associations(
    tmp_path,
    monkeypatch,
) -> None:
    source_root = _build_synthetic_delivery(tmp_path, monkeypatch)
    output = tmp_path / "organized"
    RasEbfeModels.organize_double_mountain_fork_brazos(
        downloaded_folder=source_root,
        output_folder=output,
    )
    project_folders = (
        RasEbfeModels._double_mountain_fork_brazos_project_folders(
            output / "RAS Model",
            require_contract=True,
        )
    )
    for name, project in project_folders.items():
        settings = (
            RasEbfeModels._DOUBLE_MOUNTAIN_FORK_BRAZOS_PROJECTS[name]
        )
        geometry_hdf = (
            project
            / f"{settings['project']}.g{settings['geometry']}.hdf"
        )
        with h5py.File(geometry_hdf, "r+") as hdf_file:
            geometry = hdf_file["Geometry"]
            flow_areas = geometry["2D Flow Areas"]
            area = next(
                item
                for item in flow_areas.values()
                if isinstance(item, h5py.Group)
            )
            for attr_name in (
                "Terrain Filename",
                "Land Cover Filename",
                "Infiltration Filename",
            ):
                area.attrs[attr_name] = geometry.attrs[attr_name]

    audit = RasEbfeModels._audit_double_mountain_fork_brazos_references(
        project_folders
    )
    assert audit["static_path_closure"] is True
    assert audit["named_area_association_gaps"] == []
    assert audit["native_geometry_association_ready"] is True
    assert audit["native_hydraulic_readiness"] is False
    assert len(audit["native_blocking_gaps"]) == 1
    pending_gap = audit["native_blocking_gaps"][0]
    assert pending_gap["gap_type"] == "unsteady_start_validation_pending"
    assert pending_gap["validation_status"] == "pending"
    assert pending_gap["hec_ras_executed"] is False
    assert pending_gap["projects"] == ["DMF1", "DMF2", "DMF3", "DMF4"]


def test_corrupt_manifest_forces_staged_rebuild_and_preserves_old_output(
    tmp_path,
    monkeypatch,
) -> None:
    source_root = _build_synthetic_delivery(tmp_path, monkeypatch)
    output = tmp_path / "organized"
    RasEbfeModels.organize_double_mountain_fork_brazos(
        downloaded_folder=source_root,
        output_folder=output,
    )
    manifest_path = (
        output / "agent" / "double_mountain_fork_brazos_manifest.json"
    )
    manifest_path.write_text("{not-json", encoding="utf-8")

    RasEbfeModels.organize_double_mountain_fork_brazos(
        downloaded_folder=source_root,
        output_folder=output,
    )

    rebuilt = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert rebuilt["huc8"] == "12050004"
    backups = list(tmp_path.glob("organized.interrupted-*"))
    assert len(backups) == 1
    assert (
        backups[0]
        / "agent"
        / "double_mountain_fork_brazos_manifest.json"
    ).read_text(encoding="utf-8") == "{not-json"


def test_interrupted_no_manifest_retry_uses_clean_sibling_staging(
    tmp_path,
    monkeypatch,
) -> None:
    source_root = _build_synthetic_delivery(tmp_path, monkeypatch)
    output = tmp_path / "organized"
    interrupted_file = (
        output / "RAS Model" / "DMF1" / "DMF1" / "Input" / "DMF_1.rasmap"
    )
    interrupted_file.parent.mkdir(parents=True)
    interrupted_file.write_text("repaired partial output", encoding="utf-8")

    RasEbfeModels.organize_double_mountain_fork_brazos(
        downloaded_folder=source_root,
        output_folder=output,
    )

    assert "<RASMapper>" in (
        output / "RAS Model" / "DMF1" / "DMF1" / "Input" / "DMF_1.rasmap"
    ).read_text(encoding="utf-8")
    backups = list(tmp_path.glob("organized.interrupted-*"))
    assert len(backups) == 1
    assert (
        backups[0]
        / "RAS Model"
        / "DMF1"
        / "DMF1"
        / "Input"
        / "DMF_1.rasmap"
    ).read_text(encoding="utf-8") == "repaired partial output"


def test_organize_model_dispatches_double_mountain_fork_brazos(
    tmp_path,
    monkeypatch,
) -> None:
    expected = tmp_path / "organized"
    observed = {}

    def fake_organizer(**kwargs):
        observed.update(kwargs)
        return expected

    monkeypatch.setattr(
        RasEbfeModels,
        "organize_double_mountain_fork_brazos",
        staticmethod(fake_organizer),
    )
    result = RasEbfeModels.organize_model(
        "12050004",
        downloaded_folder=tmp_path / "raw",
        output_folder=expected,
    )
    assert result == expected
    assert observed["downloaded_folder"] == tmp_path / "raw"
    assert observed["output_folder"] == expected
