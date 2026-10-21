"""East Galveston Bay public eBFE registration and source-aware API tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import zipfile

import pytest

from ras_commander import RasExamples
from ras_commander.sources.base import ModelType
from ras_commander.sources.federal.ebfe_models import RasEbfeModels


def _component_zip(path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def _write_nested_ras_submission(path: Path) -> None:
    input_zip = path.parent / "Input.zip"
    terrain_zip = path.parent / "Terrain.zip"
    land_cover_zip = path.parent / "LandCover.zip"
    output_zip = path.parent / "Output.zip"
    _component_zip(input_zip, {
        "Input/EastGalvestonBay.prj": b"Proj Title=Fixture\n",
        "Input/EastGalvestonBay.p01": b"Geom File=g01\n",
        "Input/EastGalvestonBay.g01": b"Geom Title=Fixture\n",
        "Input/EastGalvestonBay.u01": b"Flow Title=Fixture\n",
        "Input/Features/archived.sr.lock": b"",
    })
    _component_zip(terrain_zip, {"Terrain/Terrain.hdf": b"terrain"})
    _component_zip(land_cover_zip, {"LandCover/LandCover.hdf": b"land"})
    _component_zip(output_zip, {"Output/EastGalvestonBay.p01.hdf": b"result"})
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(input_zip, "RAS_Submittal/Input.zip")
        archive.write(terrain_zip, "RAS_Submittal/Terrain.zip")
        archive.write(land_cover_zip, "RAS_Submittal/LandCover.zip")
        archive.write(output_zip, "RAS_Submittal/Output.zip")


def _delivery(root: Path) -> Path:
    source = root / "12040202_Models_extracted"
    hms = source / "Hydrology" / "HMS" / "EastGalvestonBay"
    hms.mkdir(parents=True)
    (hms / "EastGalvestonBay.hms").write_text("Project: Fixture\n", encoding="utf-8")
    (source / "480120_Hydraulics_metadata.xml").write_text("<metadata />\n", encoding="utf-8")
    hydraulic = source / "Hydraulic_Models"
    hydraulic.mkdir()
    (hydraulic / "2D_Model_Inventory.xlsx").write_bytes(b"fixture inventory")
    _write_nested_ras_submission(hydraulic / "RAS_Submittal.zip")
    return source


def test_east_galveston_registry_preserves_public_source_boundary():
    for alias in ("east-galveston-bay", "eastgalvestonbay", "12040202"):
        assert RasEbfeModels.normalize_model_key(alias) == "east-galveston-bay"

    metadata = RasEbfeModels.get_model_metadata("12040202")
    assert metadata.url == RasEbfeModels._EAST_GALVESTON_SOURCE_URL
    assert metadata.file_size_mb == RasEbfeModels._EAST_GALVESTON_SOURCE_SIZE / (1024 * 1024)
    assert metadata.model_type is ModelType.UNKNOWN
    assert metadata.hecras_version == "unverified"
    assert metadata.extra["source_program"] == "fema_ebfe"
    assert metadata.extra["public_delivery_model_type"] == "2D"
    assert metadata.extra["validation_status"] == "unverified"
    assert metadata.extra["hec_ras_executed"] is False
    assert "RBFS" not in metadata.description


def test_east_galveston_organizer_copies_confirmed_outer_members_only(tmp_path, monkeypatch):
    source = _delivery(tmp_path)
    submission = source / "Hydraulic_Models" / "RAS_Submittal.zip"
    source_snapshot = {path: path.read_bytes() for path in source.rglob("*") if path.is_file()}
    monkeypatch.setattr(
        RasEbfeModels,
        "_EAST_GALVESTON_RAS_SUBMITTAL_SIZE",
        submission.stat().st_size,
    )

    output = RasEbfeModels.organize_east_galveston_bay(
        source, tmp_path / "organized", extract_ras_nested=False
    )

    assert (output / "HMS Model" / "EastGalvestonBay" / "EastGalvestonBay.hms").is_file()
    assert (output / "Documentation" / "480120_Hydraulics_metadata.xml").is_file()
    assert (output / "Documentation" / "2D_Model_Inventory.xlsx").is_file()
    readme = (output / "RAS Model" / "README.md").read_text(encoding="utf-8")
    assert "does not establish the HEC-RAS version" in readme
    manifest = json.loads((output / "agent" / "east_galveston_manifest.json").read_text())
    assert manifest["ras_submission"]["extracted"] is False
    assert manifest["source_identity"]["archive_identity_verified"] is False
    assert source_snapshot == {path: path.read_bytes() for path in source.rglob("*") if path.is_file()}


def test_east_galveston_nested_extraction_is_generated_and_not_a_runtime_claim(tmp_path, monkeypatch):
    source = _delivery(tmp_path)
    submission = source / "Hydraulic_Models" / "RAS_Submittal.zip"
    monkeypatch.setattr(
        RasEbfeModels,
        "_EAST_GALVESTON_RAS_SUBMITTAL_SIZE",
        submission.stat().st_size,
    )
    monkeypatch.setattr(
        RasEbfeModels,
        "_standardize_ras_model_tree",
        staticmethod(lambda _folder: {"project_count": 1}),
    )
    output = RasEbfeModels.organize_east_galveston_bay(
        source, tmp_path / "organized", extract_ras_nested=True, validate_dss=False
    )

    assert list((output / "RAS Model").rglob("EastGalvestonBay.prj"))
    manifest = json.loads((output / "agent" / "east_galveston_manifest.json").read_text())
    assert manifest["ras_submission"]["extracted"] is True
    assert manifest["ras_submission"]["output_archive_included"] is False
    assert manifest["ras_projects"]
    assert not list((output / "RAS Model").rglob("*.p01.hdf"))
    assert not list((output / "RAS Model").rglob("*.sr.lock"))
    assert manifest["archived_gis_locks_removed"] == ["Features/archived.sr.lock"]
    assert manifest["hec_ras_executed"] is False
    assert manifest["validation_status"] == "unverified"


def test_east_galveston_rejects_partial_outer_extraction(tmp_path, monkeypatch):
    nested = tmp_path / "RAS_Submittal.zip"
    _write_nested_ras_submission(nested)
    archive = tmp_path / "12040202_Models.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as outer:
        outer.write(nested, "Hydraulic_Models/RAS_Submittal.zip")
        outer.writestr("Hydrology/HMS/EastGalvestonBay/EastGalvestonBay.hms", "fixture")
    sidecar = RasEbfeModels._source_sidecar_path(archive)
    sidecar.write_text(
        json.dumps({
            "partial": False,
            "source": RasEbfeModels._EAST_GALVESTON_SOURCE_URL,
            "final_url": RasEbfeModels._EAST_GALVESTON_SOURCE_URL,
            "size": archive.stat().st_size,
            "etag": "fixture-etag",
        }),
        encoding="utf-8",
    )
    asset = RasEbfeModels._MODEL_REGISTRY["east-galveston-bay"]["extra"]["source_assets"][0]
    original_asset = dict(asset)
    monkeypatch.setitem(asset, "size_bytes", archive.stat().st_size)
    monkeypatch.setitem(asset, "etag", "fixture-etag")
    monkeypatch.setattr(
        RasEbfeModels,
        "_EAST_GALVESTON_RAS_SUBMITTAL_SIZE",
        nested.stat().st_size,
    )
    partial = tmp_path / "12040202_Models_extracted" / "Hydraulic_Models"
    partial.mkdir(parents=True)
    (partial / "RAS_Submittal.zip").write_bytes(b"truncated")

    try:
        with pytest.raises(RuntimeError, match="Existing extraction is incomplete"):
            RasEbfeModels.organize_east_galveston_bay(
                archive, tmp_path / "organized", extract_ras_nested=False
            )
    finally:
        asset.clear()
        asset.update(original_asset)


def test_rasexamples_ebfe_facade_does_not_initialize_or_change_hec_examples(tmp_path, monkeypatch):
    calls = {}

    def fail_hec_archive(*_args, **_kwargs):
        raise AssertionError("HEC example archive must not be initialized")

    def organize(model_key, **kwargs):
        calls["model_key"] = model_key
        calls.update(kwargs)
        return tmp_path / "EastGalvestonBay_12040202"

    monkeypatch.setattr(RasExamples, "_find_zip_file", fail_hec_archive)
    monkeypatch.setattr(RasEbfeModels, "organize_model", staticmethod(organize))
    result = RasExamples.organize_ebfe_model(
        "east-galveston-bay",
        output_path=tmp_path,
        downloaded_folder=tmp_path / "raw",
        extract_ras_nested=False,
    )

    assert result == tmp_path / "EastGalvestonBay_12040202"
    assert calls == {
        "model_key": "east-galveston-bay",
        "output_root": tmp_path,
        "downloaded_folder": tmp_path / "raw",
        "extract_ras_nested": False,
    }



def _deflate64_fixture(tmp_path: Path) -> Path:
    executable = RasEbfeModels._find_7zip_executable()
    if executable is None:
        pytest.skip("7-Zip is unavailable")
    payload = tmp_path / "payload.txt"
    payload.write_bytes(b"Deflate64 regression fixture\n" * 10_000)
    archive = tmp_path / "deflate64.zip"
    subprocess.run(
        [str(executable), "a", "-tzip", "-mm=Deflate64", "-y", str(archive), str(payload)],
        check=True,
        capture_output=True,
        text=True,
    )
    with zipfile.ZipFile(archive) as stream:
        assert stream.getinfo("payload.txt").compress_type == 9
    return archive


def test_verified_extraction_uses_7zip_for_deflate64_and_preserves_receipt(tmp_path):
    archive = _deflate64_fixture(tmp_path)
    destination = tmp_path / "extracted"

    audit = RasEbfeModels._extract_zip_verified(archive, destination)

    assert audit["valid"] is True
    assert audit["backend"] == "7zip"
    assert (destination / "payload.txt").read_bytes() == b"Deflate64 regression fixture\n" * 10_000
    receipt = json.loads((destination / RasEbfeModels._EXTRACTION_RECEIPT_NAME).read_text())
    assert receipt["audit"]["crc32_verified"] is True
    assert receipt["audit"]["backend"] == "7zip"


def test_verified_deflate64_extraction_fails_closed_without_7zip(tmp_path, monkeypatch):
    archive = _deflate64_fixture(tmp_path)
    monkeypatch.setattr(RasEbfeModels, "_find_7zip_executable", staticmethod(lambda: None))

    with pytest.raises(RuntimeError, match="unsupported by Python's zipfile"):
        RasEbfeModels._extract_zip_verified(archive, tmp_path / "extracted")
    assert not (tmp_path / "extracted").exists()
