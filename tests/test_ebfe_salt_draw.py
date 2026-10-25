"""Focused tests for the Salt Draw 13070004 eBFE organizer (no network)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from ras_commander.sources import RasEbfeModels
from ras_commander.sources.base import ModelType
from ras_commander.sources.federal import ebfe_salt_draw

ROOT = ebfe_salt_draw.DELIVERY_ROOT
INPUT = f"{ROOT}/Hydraulic Models/RAS_Submittal/Input"
SUBMITTAL = f"{ROOT}/Hydraulic Models/RAS_Submittal"


def _delivery_files(*, broken_dss: bool = False) -> dict[str, bytes]:
    rasmap_refs = [
        r".\Projection.prj",
        r".\SLDR_004.g02.hdf",
        r"..\Terrain\Terrain.hdf",
        r"..\Terrain\Terrain.Hydroenforced.hdf",
        r"..\Landcover\LandCover.hdf",
        r"..\Landcover\Mannings.hdf",
        r"..\Landcover\Infiltration.hdf",
        r"..\Landcover\Soils.hdf",
        *ebfe_salt_draw.NONBLOCKING_RASMAP_REFERENCES,
    ]
    for plan, spec in ebfe_salt_draw.PLAN_EVENTS.items():
        rasmap_refs += [
            f".\\SLDR_004.{plan}",
            f".\\SLDR_004.{plan}.hdf",
            f".\\SLDR_004.{spec['flow']}.hdf",
        ]
    rasmap = "<RASMapper>\n" + "".join(
        f'  <Layer Filename="{ref}" />\n' for ref in rasmap_refs
    ) + "</RASMapper>\n"
    files: dict[str, bytes] = {
        f"{ROOT}/ReadMe.txt": b"Salt Draw domain readme",
        f"{ROOT}/Hydraulic Models/ReadMe.txt": b"hydraulic readme",
        f"{ROOT}/Hydrologic Models/ReadMe.txt": b"hydrologic readme",
        f"{ROOT}/Hydrologic Models/HMS Models/SLDR_03070004_HMS/SLDR.hms": b"hms",
        f"{SUBMITTAL}/Output/_ReadMe.txt": b"Model inputs and outputs are under Input.",
        f"{INPUT}/SLDR_004.prj": (
            b"Proj Title=SLDR_004\r\nCurrent Plan=p07\r\nGeom File=g02\r\n"
            + b"".join(f"Unsteady File=u0{n}\r\n".encode() for n in range(1, 8))
            + b"".join(f"Plan File=p0{n}\r\n".encode() for n in range(1, 8))
            + b"DSS File=.\\Hydrology\\LPLWR_001.dss\r\nDSS File=dss\r\n"
        ),
        f"{INPUT}/SLDR_004.rasmap": rasmap.encode(),
        f"{INPUT}/SLDR_004.g02": b"Geom Title=SLDR_004\r\n",
        f"{INPUT}/SLDR_004.g02.hdf": b"geometry-hdf",
        f"{INPUT}/Projection.prj": b"PROJCS[...]",
        f"{INPUT}/Hydrology/LPLWR_001.dss": b"dss",
        f"{INPUT}/Hydrology/SLDR_03070004.dss": b"dss",
        f"{INPUT}/Features/SDraw_Perimeter.shp": b"shape",
    }
    for plan, spec in ebfe_salt_draw.PLAN_EVENTS.items():
        flow = spec["flow"]
        files[f"{INPUT}/SLDR_004.{plan}"] = (
            f"Plan Title={spec['title']}\r\nProgram Version=6.41\r\n"
            f"Geom File=g02\r\nFlow File={flow}\r\n"
        ).encode()
        files[f"{INPUT}/SLDR_004.{plan}.hdf"] = f"results-{plan}".encode()
        dss = r".\Hydrology\MISSING.dss" if broken_dss else r".\Hydrology\LPLWR_001.dss"
        files[f"{INPUT}/SLDR_004.{flow}"] = (
            f"Flow Title={plan}\r\nDSS File={dss}\r\n"
            "Met BC=Precipitation|TS DSS Filename=.\\Hydrology\\SLDR_03070004.dss\r\n"
        ).encode()
        files[f"{INPUT}/SLDR_004.{flow}.hdf"] = b"unsteady-hdf"
    for name in (
        "Terrain.hdf",
        "Terrain.vrt",
        "Terrain.Hydroenforced.hdf",
        "Terrain.Hydroenforced.vrt",
        "Terrain.salt_draw_mosaic_max.tif",
    ):
        files[f"{SUBMITTAL}/Terrain/{name}"] = name.encode()
    for name in ("LandCover.hdf", "Mannings.hdf", "Infiltration.hdf", "Soils.hdf"):
        files[f"{SUBMITTAL}/Landcover/{name}"] = name.encode()
    return files


def _write_archive(
    folder: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    files: dict[str, bytes] | None = None,
    etag: str | None = None,
    sidecar: bool = True,
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / ebfe_salt_draw.SOURCE_NAME
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as stream:
        stream.writestr(f"{ROOT}/", b"")
        stream.writestr(
            f"{ROOT}/Hydrologic Models/HMS Models/SLDR_03070004_HMS/results/", b""
        )
        for name, payload in (files or _delivery_files()).items():
            stream.writestr(name, payload)
    monkeypatch.setattr(ebfe_salt_draw, "SOURCE_SIZE_BYTES", archive.stat().st_size)
    if sidecar:
        archive.with_name(archive.name + ".ebfe-source.json").write_text(
            json.dumps(
                {
                    "source": ebfe_salt_draw.SOURCE_URL,
                    "final_url": ebfe_salt_draw.SOURCE_URL,
                    "size": archive.stat().st_size,
                    "etag": etag or ebfe_salt_draw.SOURCE_ETAG,
                }
            ),
            encoding="utf-8",
        )
    return archive


def _write_tree(folder: Path, files: dict[str, bytes]) -> Path:
    for name, payload in files.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return folder / ROOT


def _input(output: Path) -> Path:
    return output / "RAS Model" / "RAS_Submittal" / "Input"


def test_pinned_public_contract_and_registry() -> None:
    assert ebfe_salt_draw.SOURCE_SIZE_BYTES == 66_982_389_960
    assert ebfe_salt_draw.SOURCE_ETAG == "4a242424595c638af489fd1b41c94b0d-7985"
    assert ebfe_salt_draw.SOURCE_URL.endswith("/13070004_SaltDraw/13070004_Models.zip")
    assert ebfe_salt_draw.DEFAULT_OUTPUT_PLANS == ("p01", "p02")
    assert ebfe_salt_draw.PLAN_EVENTS["p01"]["event"] == "1% AEP"
    assert ebfe_salt_draw.PLAN_EVENTS["p02"]["event"] == "0.2% AEP"

    for alias in ("Salt Draw", "saltdraw", "SLDR", "13070004"):
        assert RasEbfeModels.normalize_model_key(alias) == "salt-draw"
    metadata = RasEbfeModels.get_model_metadata("13070004")
    assert metadata.source_id == "salt-draw"
    assert metadata.location == "13070004"
    assert metadata.model_type == ModelType.UNSTEADY_2D
    assert metadata.hecras_version == "6.4.1"
    assert metadata.url == ebfe_salt_draw.SOURCE_URL
    assert metadata.extra["qualified_ras_version"] == "6.6"
    assert metadata.extra["hec_ras_executed"] is False
    asset = metadata.extra["source_assets"][0]
    assert asset == {
        "role": "models",
        "name": ebfe_salt_draw.SOURCE_NAME,
        "url": ebfe_salt_draw.SOURCE_URL,
        "size_bytes": 66_982_389_960,
        "etag": ebfe_salt_draw.SOURCE_ETAG,
        "extract": False,
    }
    registry = RasEbfeModels._MODEL_REGISTRY["salt-draw"]
    assert registry["default_kwargs"] == {"output_plans": ["p01", "p02"]}
    assert registry["file_size_bytes"] == ebfe_salt_draw.SOURCE_SIZE_BYTES
    for plan, spec in ebfe_salt_draw.PLAN_EVENTS.items():
        recorded = metadata.extra["plan_events"][plan]
        assert recorded["title"] == spec["title"]
        assert f"u{recorded['unsteady']}" == spec["flow"]
    assert "salt-draw" in RasEbfeModels.available_models()


def test_member_selection_keeps_only_requested_result_hdfs() -> None:
    names = list(_delivery_files())
    selected = ebfe_salt_draw.select_salt_draw_members(names)
    hdfs = sorted(
        dest.name for dest in selected.values() if dest.name.endswith(tuple(
            f".{plan}.hdf" for plan in ebfe_salt_draw.PLAN_EVENTS
        ))
    )
    assert hdfs == ["SLDR_004.p01.hdf", "SLDR_004.p02.hdf"]
    assert sum(1 for d in selected.values() if d.suffix.startswith(".p0")) == 7
    assert Path("Documentation/Hydraulic_Models_ReadMe.txt") in selected.values()
    assert any(d.parts[0] == "HMS Model" for d in selected.values())

    only_p03 = ebfe_salt_draw.select_salt_draw_members(names, ["3"], include_hms=False)
    assert {d.name for d in only_p03.values() if d.name.endswith(".hdf") and ".p0" in d.name} == {
        "SLDR_004.p03.hdf"
    }
    assert not any(d.parts[0] == "HMS Model" for d in only_p03.values())
    with pytest.raises(ValueError, match="Unknown Salt Draw plan"):
        ebfe_salt_draw.select_salt_draw_members(names, ["p08"])


def test_organize_from_archive_extracts_selected_plans_and_reuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _write_archive(tmp_path / "raw", monkeypatch)
    before = (archive.stat().st_size, archive.stat().st_mtime_ns)
    output = tmp_path / "organized" / "SaltDraw_13070004"

    result = ebfe_salt_draw.organize_salt_draw(archive, output)

    assert result == output.resolve()
    project = _input(output)
    assert (project / "SLDR_004.prj").is_file()
    assert sorted(p.name for p in project.glob("SLDR_004.p0?.hdf")) == [
        "SLDR_004.p01.hdf",
        "SLDR_004.p02.hdf",
    ]
    assert len(list(project.glob("SLDR_004.p0?"))) == 7
    assert (output / "RAS Model/RAS_Submittal/Terrain/Terrain.Hydroenforced.hdf").is_file()
    assert (output / "RAS Model/RAS_Submittal/Landcover/Mannings.hdf").is_file()
    assert (output / "HMS Model/SLDR_03070004_HMS/SLDR.hms").is_file()
    assert (output / "HMS Model/SLDR_03070004_HMS/results").is_dir()
    assert (output / "Documentation/ReadMe.txt").is_file()
    assert not list(output.parent.glob(".*assembling-*"))
    assert (archive.stat().st_size, archive.stat().st_mtime_ns) == before

    manifest = json.loads((output / "agent/salt_draw_manifest.json").read_text())
    assert manifest["output_plans"] == ["p01", "p02"]
    assert manifest["staging"]["mode"] == "archive"
    assert manifest["staging"]["crc32_verified"] is True
    assert manifest["source_identity"]["etag_verified"] is True
    assert manifest["repair_summary"]["text_updates"] == 0
    assert manifest["hec_ras_executed"] is False
    audit = manifest["reference_audit"]
    assert audit["active_hydraulic_reference_closure"] is True
    assert len(audit["nonblocking_unresolved_references"]) == 4
    assert audit["result_layers_not_extracted"] == [
        f".\\SLDR_004.p0{n}.hdf" for n in range(3, 8)
    ]
    assert (output / "agent/model_log.md").is_file()

    assert ebfe_salt_draw.organize_salt_draw(archive, output) == output.resolve()
    assert RasEbfeModels._organized_model_is_reusable(
        output, RasEbfeModels._MODEL_REGISTRY["salt-draw"]
    )
    with pytest.raises(FileExistsError, match="not reusable"):
        ebfe_salt_draw.organize_salt_draw(archive, output, output_plans=["p01"])

    (project / "SLDR_004.p02.hdf").unlink()
    assert not ebfe_salt_draw.salt_draw_is_reusable(output)


def test_organize_model_dispatches_with_default_plans_without_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "raw" / "13070004_SaltDraw"
    _write_archive(raw, monkeypatch)

    def _no_download(*args, **kwargs):  # pragma: no cover - failure path
        raise AssertionError("download must not run when the archive exists")

    monkeypatch.setattr(RasEbfeModels, "download_source_asset", _no_download)
    organized = RasEbfeModels.organize_model(
        "salt-draw",
        download_root=tmp_path / "raw",
        output_root=tmp_path / "organized",
        output_plans=["p01"],
        include_hms=False,
    )
    assert organized == (tmp_path / "organized" / "SaltDraw_13070004").resolve()
    assert [p.name for p in _input(organized).glob("*.p0?.hdf")] == ["SLDR_004.p01.hdf"]
    assert not (organized / "HMS Model").exists()

    result = RasEbfeModels.download_model("salt-draw", tmp_path / "organized")
    assert result.success, result.message
    assert "existing organized model" in result.message


def test_missing_archive_downloads_catalogued_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def _fake_download(model_key, role, output_folder):
        calls.append((model_key, role, Path(output_folder)))
        return _write_archive(Path(output_folder), monkeypatch)

    monkeypatch.setattr(RasEbfeModels, "download_source_asset", _fake_download)
    organized = RasEbfeModels.organize_salt_draw(
        tmp_path / "raw", tmp_path / "out", output_plans=["p02"]
    )
    assert calls == [("salt-draw", "models", (tmp_path / "raw").resolve())]
    assert [p.name for p in _input(organized).glob("*.p0?.hdf")] == ["SLDR_004.p02.hdf"]


def test_organize_from_extracted_tree_requires_requested_hdfs(
    tmp_path: Path,
) -> None:
    files = _delivery_files()
    del files[f"{INPUT}/SLDR_004.p02.hdf"]
    tree = _write_tree(tmp_path / "extracted", files)

    with pytest.raises(FileNotFoundError, match="p02"):
        RasEbfeModels.organize_salt_draw(tmp_path / "extracted", tmp_path / "out")
    assert not (tmp_path / "out").exists()

    organized = RasEbfeModels.organize_salt_draw(
        tree, tmp_path / "out", output_plans=["p01", "p07"]
    )
    assert sorted(p.name for p in _input(organized).glob("*.p0?.hdf")) == [
        "SLDR_004.p01.hdf",
        "SLDR_004.p07.hdf",
    ]
    manifest = json.loads((organized / "agent/salt_draw_manifest.json").read_text())
    assert manifest["staging"]["mode"] == "pre_extracted_tree"
    assert manifest["source_identity"]["archive_identity_verified"] is False


@pytest.mark.parametrize("variant", ["wrong_etag", "no_sidecar"])
def test_archive_identity_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    archive = _write_archive(
        tmp_path / "raw",
        monkeypatch,
        etag="0" * 32 + "-1" if variant == "wrong_etag" else None,
        sidecar=variant != "no_sidecar",
    )
    with pytest.raises(RuntimeError, match="ETag"):
        ebfe_salt_draw.organize_salt_draw(archive, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_unresolved_hydraulic_reference_aborts_without_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _write_archive(
        tmp_path / "raw", monkeypatch, files=_delivery_files(broken_dss=True)
    )
    with pytest.raises(RuntimeError, match="DSS reference unresolved"):
        ebfe_salt_draw.organize_salt_draw(archive, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert not list(tmp_path.glob(".*assembling-*"))
