"""Focused tests for the Medina (12100302) eBFE organizer."""

from __future__ import annotations

import json
import struct
import zipfile
from pathlib import Path

import h5py
import pytest

from ras_commander.sources.federal import ebfe_medina as medina
from ras_commander.sources.federal.ebfe_extract import StreamingZipReader


def _hdf_bytes(path: Path, *, terrain: bool = False) -> bytes:
    with h5py.File(path, "w") as hdf:
        if terrain:
            hdf.create_group("Modifications/Channels")
        else:
            hdf.create_group("Geometry")
            area = hdf.create_group("Geometry/2D Flow Areas/Test Area")
            area.create_group("Infiltration")
            parent = hdf["Geometry/2D Flow Areas"]
            for name in (
                "Attributes",
                "Cell Info",
                "Cell Points",
                "Face Info",
                "Face Points",
                "Perimeter",
            ):
                parent.create_dataset(name, data=[1])
    return path.read_bytes()


def _build_truncated_delivery(
    root: Path,
    *,
    truncated_member: str = medina.ALLOWED_UNRECOVERABLE_MEMBER,
) -> tuple[Path, int]:
    source = root / medina.SOURCE_NAME
    projection = b'PROJCS["NAD_1983_StatePlane_Texas_South_Central_FIPS_4204_Feet"]\n'
    hdf = _hdf_bytes(root / "geometry.hdf")
    terrain = _hdf_bytes(root / "terrain.hdf", terrain=True)

    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "Engineering Models/Hydraulic Models/2D_Model_Inventory_Medina.xlsx",
            b"inventory",
        )
        for project, spec in medina.PROJECTS.items():
            prefix = f"Engineering Models/Hydraulic Models/{project}"
            basename = str(spec["basename"])
            archive.writestr(f"{prefix}/Input/{basename}.prj", b"Proj Title=test\n")
            archive.writestr(
                f"{prefix}/Input/{basename}.p{spec['plan_number']}",
                (
                    f"Plan Title=test\nGeom File=g{spec['geometry_number']}\n"
                    f"Flow File=u{spec['unsteady_number']}\n"
                ).encode(),
            )
            archive.writestr(
                f"{prefix}/Input/{basename}.g{spec['geometry_number']}",
                b"Geom Title=test\n2D Flow Area=Test Area\n",
            )
            rasmap = "<RASMapper>fixture</RASMapper>\n"
            if project in medina._PROJECTION_REPAIRS:
                rasmap = rasmap.replace(
                    "fixture", medina._PROJECTION_REPAIRS[project][0]
                )
            archive.writestr(f"{prefix}/Input/{basename}.rasmap", rasmap)
            unsteady = "DSS File=.\\DSS\\100YR.dss\n"
            if project == "Leon1":
                unsteady += (
                    "DSS File=..\\..\\..\\_HMS_Models_v2\\_HMS_Models"
                    "\\Leon1\\500YR.dss\n"
                )
            archive.writestr(f"{prefix}/Input/{basename}.u02", unsteady)
            if spec["unsteady_number"] != "02":
                archive.writestr(
                    f"{prefix}/Input/{basename}.u{spec['unsteady_number']}",
                    "DSS File=.\\DSS\\100YR.dss\n",
                )
            archive.writestr(f"{prefix}/Output/{spec['geometry_hdf']}", hdf)
            if project != "UpperMedinaHeadwaters":
                archive.writestr(f"{prefix}/Output/{basename}.p01.hdf", hdf)
            for name in ("Infiltration.hdf", "Soils.hdf", "LandCover.hdf"):
                archive.writestr(f"{prefix}/Land Classification/{name}", b"delivered")
            if spec["terrain_hdf"] is not None:
                archive.writestr(f"{prefix}/Terrain/{spec['terrain_hdf']}", terrain)
            if project in {"Leon3", "MiddleLowerMedina"}:
                archive.writestr(
                    f"{prefix}/Terrain/Projection/Projection_File.prj",
                    projection,
                )
        archive.writestr(truncated_member, b"publisher tail" * 200)

    with zipfile.ZipFile(source) as archive:
        info = archive.getinfo(truncated_member)
        with source.open("rb") as handle:
            handle.seek(info.header_offset + 26)
            name_length, extra_length = struct.unpack("<HH", handle.read(4))
        data_offset = info.header_offset + 30 + name_length + extra_length
    source.write_bytes(source.read_bytes()[: data_offset + 100])

    survey = StreamingZipReader(source).probe()
    recoverable = len(
        [member for member in survey.complete_members if not member.is_dir]
    )
    sidecar = {
        "source": medina.SOURCE_URL,
        "final_url": medina.SOURCE_URL,
        "size": source.stat().st_size,
        "etag": medina.SOURCE_ETAG,
    }
    Path(f"{source}.ebfe-source.json").write_text(json.dumps(sidecar), encoding="utf-8")
    return source, recoverable


def _patch_fixture_identity(
    monkeypatch: pytest.MonkeyPatch, source: Path, recoverable: int
) -> None:
    monkeypatch.setattr(medina, "SOURCE_SIZE_BYTES", source.stat().st_size)
    monkeypatch.setattr(medina, "EXPECTED_RECOVERABLE_FILES", recoverable)


def test_pinned_source_and_project_terrain_truth_table() -> None:
    assert medina.SOURCE_SIZE_BYTES == 52_085_665_792
    assert medina.SOURCE_ETAG == "5474dc597ff3a2fb4418a59807a439ff-6210"
    assert medina.SOURCE_URL.endswith("/12100302_Medina/12100302_Models.zip")
    assert len(medina.PROJECTS) == 5
    assert {name: spec["terrain_hdf"] for name, spec in medina.PROJECTS.items()} == {
        "Leon1": "Terrain (1).hdf",
        "Leon2": "Terrain (1).hdf",
        "Leon3": "Terrain (1).hdf",
        "MiddleLowerMedina": "Terrain_Clipped.hdf",
        "UpperMedinaHeadwaters": None,
    }
    assert medina.PROJECTS["UpperMedinaHeadwaters"]["terrain_modification"] == (
        "UpperMedinaHW_TerrainModifications"
    )
    assert {
        project: (
            spec["plan_number"],
            spec["geometry_number"],
            spec["unsteady_number"],
        )
        for project, spec in medina.PROJECTS.items()
    } == {
        "Leon1": ("01", "01", "01"),
        "Leon2": ("03", "01", "01"),
        "Leon3": ("02", "01", "01"),
        "MiddleLowerMedina": ("03", "01", "01"),
        "UpperMedinaHeadwaters": ("04", "02", "04"),
    }


def test_organizer_recovers_five_projects_and_records_only_real_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, recoverable = _build_truncated_delivery(tmp_path)
    _patch_fixture_identity(monkeypatch, source, recoverable)
    target = tmp_path / "organized"

    assert medina.organize_medina(source, target) == target.resolve()
    manifest = json.loads(
        (target / "agent" / "medina_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["project_count"] == 5
    assert manifest["hec_ras_executed"] is False
    assert manifest["fresh_output_status"] == "pending"
    assert manifest["delivery_readiness"] == "critical_source_gap"
    assert manifest["archive"]["allowed_unrecoverable_members"] == [
        medina.ALLOWED_UNRECOVERABLE_MEMBER
    ]
    assert manifest["repair_summary"] == {
        "output_assets_relocated_by_projection": 68,
        "projection_paths": 4,
        "dss_paths": 1,
        "active_geometry_hdf_associations": 33,
        "delivered_result_hdfs_modified": 0,
    }
    assert manifest["critical_deficiencies"] == [
        {
            "project": "UpperMedinaHeadwaters",
            "asset": r".\Terrain\Terrain.hdf",
            "reason": (
                "The RASMapper geometry references the load-bearing "
                "UpperMedinaHW_TerrainModifications group, but the compiled "
                "modified Terrain.hdf is not in the public delivery."
            ),
        }
    ]

    for project, spec in medina.PROJECTS.items():
        project_manifest = manifest["projects"][project]
        assert project_manifest["land_cover_delivered"] is True
        assert project_manifest["infiltration_delivered"] is True
        assert project_manifest["soils_delivered"] is True
        expected_complete = project != "UpperMedinaHeadwaters"
        assert project_manifest["terrain_source_complete"] is expected_complete
        assert project_manifest["validation_status"] == (
            "pending" if expected_complete else "blocked_source_gap"
        )
        assert project_manifest["hec_ras_executed"] is False
        assert project_manifest["canonical_plan_contract"] == {
            "plan": spec["plan_number"],
            "geometry": spec["geometry_number"],
            "unsteady": spec["unsteady_number"],
        }
        root = target / "RAS Model" / project
        for name in ("Infiltration.hdf", "Soils.hdf", "LandCover.hdf"):
            assert (root / "Land Classification" / name).is_file()

        geometry = root / str(spec["geometry_hdf"])
        with h5py.File(geometry) as hdf:
            assert hdf["Geometry"].attrs["Land Cover Filename"] == (
                rb".\Land Classification\LandCover.hdf"
            )
            assert hdf["Geometry"].attrs.get_id("Land Cover Filename").dtype.kind == "S"
            if expected_complete:
                expected = f".\\Terrain\\{spec['terrain_hdf']}".encode()
                assert hdf["Geometry"].attrs["Terrain Filename"] == expected
            else:
                assert "Terrain Filename" not in hdf["Geometry"].attrs

        if project != "UpperMedinaHeadwaters":
            # Result HDFs are evidence, not a repair surface.
            with h5py.File(root / f"{spec['basename']}.p01.hdf") as hdf:
                assert "Terrain Filename" not in hdf["Geometry"].attrs

    leon_u02 = (target / "RAS Model" / "Leon1" / "Leon1.u02").read_text()
    assert r".\DSS\500YR.dss" in leon_u02
    assert "_HMS_Models_v2" not in leon_u02
    assert medina.medina_is_reusable(target, source_archive=source) is True
    # Runtime qualification metadata is a separate lifecycle surface. It must
    # not make an otherwise byte-identical organized source tree non-reusable.
    manifest["hec_ras_executed"] = True
    (target / "agent" / "medina_manifest.json").write_text(json.dumps(manifest))
    assert medina.medina_is_reusable(target, source_archive=source) is True
    assert medina.organize_medina(source, target) == target.resolve()


def test_only_exact_publisher_truncation_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrong = (
        "Engineering Models/Hydraulic Models/UpperMedinaHeadwaters/Output/"
        "UpperMedinaHW.p02.hdf"
    )
    source, recoverable = _build_truncated_delivery(tmp_path, truncated_member=wrong)
    _patch_fixture_identity(monkeypatch, source, recoverable)
    target = tmp_path / "organized"

    with pytest.raises(RuntimeError, match="truncation contract changed"):
        medina.organize_medina(source, target)
    assert not target.exists()
    assert not list(tmp_path.glob(".organized.medina-*.tmp"))


def test_identity_and_existing_output_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, recoverable = _build_truncated_delivery(tmp_path)
    _patch_fixture_identity(monkeypatch, source, recoverable)
    sidecar = Path(f"{source}.ebfe-source.json")
    payload = json.loads(sidecar.read_text())
    payload["etag"] = "wrong"
    sidecar.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="sidecar ETag"):
        medina.organize_medina(source, tmp_path / "bad-identity")

    payload["etag"] = medina.SOURCE_ETAG
    sidecar.write_text(json.dumps(payload))
    target = tmp_path / "existing"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("preserve")
    with pytest.raises(FileExistsError, match="not safely reusable"):
        medina.organize_medina(source, target)
    assert marker.read_text() == "preserve"


def test_reuse_rejects_geometry_association_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, recoverable = _build_truncated_delivery(tmp_path)
    _patch_fixture_identity(monkeypatch, source, recoverable)
    target = medina.organize_medina(source, tmp_path / "organized")
    geometry = target / "RAS Model" / "Leon1" / "Leon1.g01.hdf"
    with h5py.File(geometry, "r+") as hdf:
        del hdf["Geometry"].attrs["Terrain Filename"]
        hdf["Geometry"].attrs["Terrain Filename"] = r"C:\wrong\Terrain.hdf"
    assert medina.medina_is_reusable(target, source_archive=source) is False
