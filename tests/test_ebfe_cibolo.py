"""Focused tests for the Cibolo 12100304 eBFE organizer."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from ras_commander.sources.federal import ebfe_cibolo


def _project_files(*, projection_conflict: bool = False) -> dict[str, bytes]:
    files: dict[str, bytes] = {
        "_Final/HECRAS_507/Cibolo.prj": b"Proj Title=Cibolo\nCurrent Plan=p14\n",
        "_Final/HECRAS_507/Cibolo.g05": b"Geom Title=Cibolo_Geometry\n",
        "_Final/HECRAS_507/Cibolo.g05.hdf": b"geometry-hdf",
        "_Final/HECRAS_507/Cibolo.rasmap": (
            b'Projection Filename="..\\Projections\\Cibolo_Projection.prj"\n'
            b'Layer Filename="..\\Terrain_LandUse\\Terrain\\Cibolo_Terrain_Burn.hdf"\n'
            b'Layer Filename="..\\Terrain_LandUse\\ManningsN\\ManningsN_Widened2D.tif"\n'
            b'Layer Filename=".\\Features\\Profile Lines(2).shp"\n'
            + (
                b'Projection Filename=".\\Projection\\Cibolo_Projection.prj"\n'
                if projection_conflict
                else b""
            )
        ),
        "_Final/Projections/Cibolo_Projection.prj": b"projection",
        "_Final/HECRAS_507/Backup.p01": b"Geom File=g01\nFlow File=u01\n",
        "_Final/HECRAS_507/Backup.u01": (
            b"DSS File=..\\..\\..\\..\\HEC-HMS_v43\\Cibolo\\Upper_Cibolo\\100YR.dss\n"
        ),
        "_Final/Terrain_LandUse/Terrain/Cibolo_Terrain_Burn.hdf": b"terrain-hdf",
        "_Final/Terrain_LandUse/Terrain/Cibolo_Terrain_Burn.vrt": b"vrt",
        "_Final/Terrain_LandUse/Terrain/Cibolo_Terrain_Burn.cib10_terrain.tif": b"terrain",
        "_Final/Terrain_LandUse/Terrain/Cibolo_Terrain_Burn.cibolo_burn10.tif": b"burn",
        "_Final/Terrain_LandUse/ManningsN/ManningsN_Widened2D.hdf": b"land-hdf",
        "_Final/Terrain_LandUse/ManningsN/ManningsN_Widened2D.tif": b"land",
    }
    for number in ebfe_cibolo.PLAN_NUMBERS:
        geom = "g05"
        flow = "u02" if number == "14" else "u01"
        files[f"_Final/HECRAS_507/Cibolo.p{number}"] = (
            f"Plan Title=Cibolo{number}\nGeom File={geom}\nFlow File={flow}\n"
        ).encode()
    for number, (old, new) in ebfe_cibolo._DSS_REPAIRS.items():
        del new
        files[f"_Final/HECRAS_507/Cibolo.u{number}"] = (
            f"Flow Title=Cibolo_{number}\nDSS File={old}\n"
        ).encode()
    for _old, new in ebfe_cibolo._DSS_REPAIRS.values():
        name = new.rsplit("\\", 1)[-1]
        files[f"_Final/HECRAS_507/Hydrology/{name}"] = name.encode()
    return files


def _write_zip(path: Path, files: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as stream:
        for name, payload in files.items():
            stream.writestr(name, payload)


def _build_delivery(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    nested_files: dict[str, bytes] | None = None,
) -> Path:
    source = root / "source"
    nested = root / "fixture-final.zip"
    files = nested_files or _project_files()
    _write_zip(nested, files)
    archive = source / ebfe_cibolo.SOURCE_NAME
    _write_zip(
        archive,
        {
            ebfe_cibolo.NESTED_ARCHIVE_MEMBER: nested.read_bytes(),
            ebfe_cibolo.INVENTORY_MEMBER: b"inventory",
        },
    )
    monkeypatch.setattr(ebfe_cibolo, "SOURCE_SIZE_BYTES", archive.stat().st_size)
    with zipfile.ZipFile(archive) as stream:
        monkeypatch.setattr(
            ebfe_cibolo, "OUTER_MEMBER_COUNT", len(stream.infolist())
        )
    monkeypatch.setattr(ebfe_cibolo, "NESTED_MEMBER_COUNT", len(files))
    sidecar = archive.with_name(archive.name + ebfe_cibolo.SOURCE_SIDECAR_SUFFIX)
    sidecar.write_text(
        json.dumps(
            {
                "source": ebfe_cibolo.SOURCE_URL,
                "final_url": ebfe_cibolo.SOURCE_URL,
                "size": archive.stat().st_size,
                "etag": ebfe_cibolo.SOURCE_ETAG,
            }
        ),
        encoding="utf-8",
    )
    return source


def test_pinned_public_contract() -> None:
    assert ebfe_cibolo.SOURCE_SIZE_BYTES == 38_827_758_483
    assert ebfe_cibolo.SOURCE_ETAG == "7d88e8a2b047780c8df9fd486c7bb34d-4629"
    assert ebfe_cibolo.SOURCE_URL.endswith(
        "/12100304_Cibolo/12100304_Models.zip"
    )
    assert ebfe_cibolo.CANONICAL_PLAN == "14"
    assert ebfe_cibolo.CANONICAL_GEOMETRY == "05"
    assert ebfe_cibolo.CANONICAL_UNSTEADY == "02"
    assert ebfe_cibolo.OUTER_MEMBER_COUNT == 3
    assert ebfe_cibolo.NESTED_MEMBER_COUNT == 274
    assert len(ebfe_cibolo._DSS_REPAIRS) == 7


def test_organizer_replays_exact_repairs_and_is_reusable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _build_delivery(tmp_path, monkeypatch)
    archive = source / ebfe_cibolo.SOURCE_NAME
    source_state = (archive.stat().st_size, archive.stat().st_mtime_ns)
    output = tmp_path / "organized"

    assert ebfe_cibolo.organize_cibolo_delivery(source, output) == output
    manifest = json.loads((output / ebfe_cibolo.MANIFEST_RELATIVE).read_text())
    assert manifest["source_program"] == "fema_ebfe"
    assert manifest["lane_kind"] == "integrated_2d"
    assert manifest["project_count"] == 1
    assert manifest["canonical_plan"] == "14"
    assert manifest["canonical_geometry"] == "05"
    assert manifest["canonical_unsteady"] == "02"
    assert manifest["repair_summary"] == {
        "recipe_rows": 16,
        "recursive_extraction_rows": 1,
        "asset_relocation_rows": 8,
        "dss_path_updates": 7,
        "rasmap_projection_updates": 1,
        "content_updates": 8,
    }
    assert manifest["terrain_source_complete"] is True
    assert manifest["terrain_modification_layers"] == []
    assert manifest["validation_status"] == "pending"
    assert manifest["hec_ras_executed"] is False
    assert manifest["downstream_usable"] is False
    assert manifest["reproducible"] is False
    assert len(manifest["nonblocking_unresolved_references"]) == 5

    project = output / ebfe_cibolo.PROJECT_RELATIVE
    for number, (old, new) in ebfe_cibolo._DSS_REPAIRS.items():
        text = (project / f"Cibolo.u{number}").read_text()
        assert old not in text
        assert text.count(new) == 1
    rasmap = (project / "Cibolo.rasmap").read_text()
    assert ebfe_cibolo._PROJECTION_FROM not in rasmap
    assert rasmap.count(ebfe_cibolo._PROJECTION_TO) == 1
    assert "Upper_Cibolo\\100YR.dss" in (project / "Backup.u01").read_text()
    assert source_state == (archive.stat().st_size, archive.stat().st_mtime_ns)
    assert ebfe_cibolo.cibolo_output_is_reusable(output, source)
    assert ebfe_cibolo.organize_cibolo_delivery(source, output) == output


def test_reuse_rejects_tampered_active_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _build_delivery(tmp_path, monkeypatch)
    output = tmp_path / "organized"
    ebfe_cibolo.organize_cibolo_delivery(source, output)
    active = output / ebfe_cibolo.PROJECT_RELATIVE / "Cibolo.u02"
    text = active.read_text()
    active.write_text(text.replace(r".\Hydrology\01__ACE.dss", "X" * 30))

    assert not ebfe_cibolo.cibolo_output_is_reusable(output, source)


def test_conflicting_repair_prestate_is_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _build_delivery(
        tmp_path, monkeypatch, nested_files=_project_files(projection_conflict=True)
    )
    output = tmp_path / "organized"
    output.mkdir()
    marker = output / "preserve.txt"
    marker.write_text("original")

    with pytest.raises(RuntimeError, match="projection pre-state conflict"):
        ebfe_cibolo.organize_cibolo_delivery(source, output)
    assert marker.read_text() == "original"
    assert not list(tmp_path.glob(".organized.assembling-*"))


def test_nested_traversal_is_rejected_without_source_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = _project_files()
    files["../escape.txt"] = b"bad"
    source = _build_delivery(tmp_path, monkeypatch, nested_files=files)
    archive = source / ebfe_cibolo.SOURCE_NAME
    source_state = (archive.stat().st_size, archive.stat().st_mtime_ns)

    with pytest.raises(ValueError, match="Unsafe ZIP member"):
        ebfe_cibolo.organize_cibolo_delivery(source, tmp_path / "organized")
    assert source_state == (archive.stat().st_size, archive.stat().st_mtime_ns)
    assert not (tmp_path / "escape.txt").exists()


def test_source_identity_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _build_delivery(tmp_path, monkeypatch)
    archive = source / ebfe_cibolo.SOURCE_NAME
    sidecar = archive.with_name(archive.name + ebfe_cibolo.SOURCE_SIDECAR_SUFFIX)
    payload = json.loads(sidecar.read_text())
    payload["etag"] = "wrong"
    sidecar.write_text(json.dumps(payload))

    with pytest.raises(RuntimeError, match="ETag mismatch"):
        ebfe_cibolo.organize_cibolo_delivery(source, tmp_path / "organized")
