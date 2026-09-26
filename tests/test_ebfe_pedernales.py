"""Pedernales eBFE source-organizer contract tests."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from ras_commander.sources.federal import ebfe_pedernales as pedernales

PROJECT_FOLDERS = (
    "Model/Headwaters- Pedernales River/MIDDLE CREEK",
    "Model/North Grape Creek - Pedernales River/MIDDLE CREEK",
    "Model/North Grape Creek - Pedernales River/EAST FORK ROCKY CREEK",
    (
        "Model/North Grape Creek - Pedernales River/MIDDLE FORK WILLIAMS CREEK/"
        "EAST FORK ROCKY CREEK"
    ),
    "Model/Headwaters- Pedernales River/WHITE OAK CREEK",
    "Model/North Grape Creek - Pedernales River/WHITE OAK CREEK",
)


def _project_name(folder: str) -> str:
    return folder.rsplit("/", 1)[-1]


def _build_source(
    root: Path,
    *,
    omit_repair_source: str | None = None,
    source_url: str = pedernales.SOURCE_URL,
    etag: str = pedernales.SOURCE_ETAG,
) -> Path:
    source = root / "source"
    source.mkdir(parents=True)
    archive_path = source / pedernales.SOURCE_ARCHIVE_NAME
    files: dict[str, bytes] = {"Pedernales_Index_Map.pdf": b"index"}
    for folder in PROJECT_FOLDERS:
        name = _project_name(folder)
        files[f"{folder}/{name}.prj"] = (
            f"Proj Title={name}\r\n"
            "Current Plan=p01\r\n"
            "Geom File=g01\r\n"
            "Flow File=f01\r\n"
            "Plan File=p01\r\n"
        ).encode("latin-1")
        files[f"{folder}/{name}.p01"] = (
            "Plan Title=Multiple Run\r\n"
            "Geom File=g01\r\n"
            "Flow File=f01\r\n"
            "Subcritical Flow\r\n"
        ).encode("latin-1")
        files[f"{folder}/{name}.g01"] = b"Geom Title=fixture\r\n"
        files[f"{folder}/{name}.f01"] = b"Flow Title=fixture\r\n"

    for index, (source_relative, _) in enumerate(pedernales.ASSET_COPY_REPAIRS):
        member = source_relative.removeprefix("RAS Model/")
        if member != omit_repair_source:
            files[member] = f"repair-{index}".encode()

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for member, payload in files.items():
            archive.writestr(member, payload)
    sidecar = pedernales._source_sidecar_path(archive_path)
    sidecar.write_text(
        json.dumps(
            {
                "partial": False,
                "source": source_url,
                "final_url": source_url,
                "size": archive_path.stat().st_size,
                "etag": etag,
            }
        ),
        encoding="utf-8",
    )
    return source


def _patch_fixture_contract(
    monkeypatch: pytest.MonkeyPatch,
    archive_path: Path,
) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
    monkeypatch.setattr(pedernales, "SOURCE_SIZE_BYTES", archive_path.stat().st_size)
    monkeypatch.setattr(
        pedernales,
        "ARCHIVE_FILE_COUNT",
        sum(not member.is_dir() for member in members),
    )
    monkeypatch.setattr(
        pedernales,
        "ARCHIVE_DIRECTORY_COUNT",
        sum(member.is_dir() for member in members),
    )
    monkeypatch.setattr(
        pedernales,
        "ARCHIVE_EXPANDED_BYTES",
        sum(member.file_size for member in members if not member.is_dir()),
    )
    monkeypatch.setattr(pedernales, "PROJECT_COUNT", len(PROJECT_FOLDERS))


def test_pedernales_authoritative_source_and_repair_contract() -> None:
    assert pedernales.HUC8 == "12090206"
    assert pedernales.SOURCE_SIZE_BYTES == 138_116_094
    assert pedernales.SOURCE_ETAG == "b73ad7fff398baa8132d40296a0e30ee-9"
    assert pedernales.SOURCE_URL == (
        "https://ebfedata.s3.amazonaws.com/12090206_Pedernales/12090206_Models.zip"
    )
    assert pedernales.ARCHIVE_FILE_COUNT == 5_109
    assert pedernales.ARCHIVE_DIRECTORY_COUNT == 1_066
    assert pedernales.ARCHIVE_EXPANDED_BYTES == 570_955_840
    assert pedernales.PROJECT_COUNT == 530
    assert len(pedernales.ASSET_COPY_REPAIRS) == 8
    assert all(
        source.startswith("RAS Model/Model/")
        and destination.startswith("RAS Model/Model/")
        for source, destination in pedernales.ASSET_COPY_REPAIRS
    )


def test_organizer_repairs_audits_and_reuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _build_source(tmp_path)
    archive = source / pedernales.SOURCE_ARCHIVE_NAME
    _patch_fixture_contract(monkeypatch, archive)
    source_state = (archive.stat().st_size, archive.stat().st_mtime_ns)
    target = tmp_path / "organized"

    result = pedernales.organize_pedernales(source, target)

    assert result == target.resolve()
    assert source_state == (archive.stat().st_size, archive.stat().st_mtime_ns)
    manifest = json.loads(
        (target / "agent" / pedernales.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert manifest["project_count"] == len(PROJECT_FOLDERS)
    assert manifest["asset_copy_repairs"]["expected"] == 8
    assert manifest["asset_copy_repairs"]["applied"] == 8
    assert manifest["reference_audit"]["active_hydraulic_reference_closure"]
    assert manifest["terrain_applicability"] == "not_applicable_1d_steady"
    assert manifest["terrain_required"] is False
    assert manifest["terrain_source_complete"] is None
    assert manifest["required_validation_level"] == "steady_plan_completion"
    assert manifest["validation_status"] == "pending"
    assert manifest["hec_ras_executed"] is False
    assert manifest["source_objects_immutable"] is True
    for source_relative, destination_relative in pedernales.ASSET_COPY_REPAIRS:
        source_copy = target / source_relative
        destination_copy = target / destination_relative
        assert source_copy.is_file()
        assert destination_copy.read_bytes() == source_copy.read_bytes()

    marker = target / "reuse-marker.txt"
    marker.write_text("must survive reuse", encoding="utf-8")
    assert pedernales.pedernales_is_reusable(target, source)
    assert pedernales.organize_pedernales(source, target) == target.resolve()
    assert marker.read_text(encoding="utf-8") == "must survive reuse"


def test_identity_is_bound_to_exact_url_size_and_etag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrong_url = _build_source(tmp_path / "wrong-url", source_url="https://example.test")
    archive = wrong_url / pedernales.SOURCE_ARCHIVE_NAME
    _patch_fixture_contract(monkeypatch, archive)
    with pytest.raises(RuntimeError, match="sidecar URL"):
        pedernales.organize_pedernales(wrong_url, tmp_path / "url-target")

    wrong_etag = _build_source(tmp_path / "wrong-etag", etag="different")
    archive = wrong_etag / pedernales.SOURCE_ARCHIVE_NAME
    _patch_fixture_contract(monkeypatch, archive)
    with pytest.raises(RuntimeError, match="ETag mismatch"):
        pedernales.organize_pedernales(wrong_etag, tmp_path / "etag-target")

    valid = _build_source(tmp_path / "wrong-size")
    archive = valid / pedernales.SOURCE_ARCHIVE_NAME
    _patch_fixture_contract(monkeypatch, archive)
    monkeypatch.setattr(pedernales, "SOURCE_SIZE_BYTES", archive.stat().st_size + 1)
    with pytest.raises(RuntimeError, match="source size mismatch"):
        pedernales.organize_pedernales(valid, tmp_path / "size-target")


def test_traversal_and_windows_case_collision_are_rejected(tmp_path: Path) -> None:
    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../escape.txt", b"bad")
    with (
        zipfile.ZipFile(traversal) as archive,
        pytest.raises(ValueError, match="Unsafe ZIP member"),
    ):
        pedernales._validated_members(archive)

    collision = tmp_path / "collision.zip"
    with zipfile.ZipFile(collision, "w") as archive:
        archive.writestr("Model/File.txt", b"one")
        archive.writestr("model/file.TXT", b"two")
    with (
        zipfile.ZipFile(collision) as archive,
        pytest.raises(ValueError, match="Duplicate ZIP extraction target"),
    ):
        pedernales._validated_members(archive)


def test_failed_repair_preserves_existing_target_and_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    omitted = pedernales.ASSET_COPY_REPAIRS[0][0].removeprefix("RAS Model/")
    source = _build_source(tmp_path, omit_repair_source=omitted)
    archive = source / pedernales.SOURCE_ARCHIVE_NAME
    _patch_fixture_contract(monkeypatch, archive)
    target = tmp_path / "organized"
    target.mkdir()
    marker = target / "preserve.txt"
    marker.write_text("original", encoding="utf-8")
    source_state = (archive.stat().st_size, archive.stat().st_mtime_ns)

    with pytest.raises(RuntimeError, match="repair source is missing"):
        pedernales.organize_pedernales(source, target)

    assert marker.read_text(encoding="utf-8") == "original"
    assert source_state == (archive.stat().st_size, archive.stat().st_mtime_ns)
    assert not list(tmp_path.glob(".organized.assembling-*"))


def test_reuse_fails_closed_after_repair_copy_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _build_source(tmp_path)
    archive = source / pedernales.SOURCE_ARCHIVE_NAME
    _patch_fixture_contract(monkeypatch, archive)
    target = pedernales.organize_pedernales(source, tmp_path / "organized")
    destination = target / pedernales.ASSET_COPY_REPAIRS[0][1]
    destination.write_bytes(b"tampered")

    assert not pedernales.pedernales_is_reusable(target, source)


def test_active_audit_ignores_registered_delete_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _build_source(tmp_path)
    archive = source / pedernales.SOURCE_ARCHIVE_NAME
    _patch_fixture_contract(monkeypatch, archive)
    target = pedernales.organize_pedernales(source, tmp_path / "organized")

    plan_project = target / "RAS Model" / PROJECT_FOLDERS[0]
    plan_name = _project_name(PROJECT_FOLDERS[0])
    with (plan_project / f"{plan_name}.prj").open("a", encoding="latin-1") as stream:
        stream.write("Plan File=p02\r\n")
    (plan_project / f"{plan_name}.p02").write_text(
        "Plan Title=Delete\r\nGeom File=g02\r\nFlow File=f01\r\n",
        encoding="latin-1",
    )

    geom_project = target / "RAS Model" / PROJECT_FOLDERS[1]
    geom_name = _project_name(PROJECT_FOLDERS[1])
    with (geom_project / f"{geom_name}.prj").open("a", encoding="latin-1") as stream:
        stream.write("Geom File=g02\r\n")
    (geom_project / f"{geom_name}.g02").write_text(
        "Geom Title=Delete\r\n", encoding="latin-1"
    )

    audit = pedernales._audit_workspace(target)
    assert audit["active_hydraulic_reference_closure"] is True
    assert audit["errors"] == []
