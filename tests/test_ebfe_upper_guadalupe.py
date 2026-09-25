"""Focused tests for the Upper Guadalupe eBFE source adapter."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import h5py
import pytest

from ras_commander.sources.federal.ebfe_models import RasEbfeModels


def _plan_hdf(path: Path, project: str) -> None:
    with h5py.File(path, "w") as hdf:
        hdf.create_group("Geometry")
        area = hdf.create_group(f"Geometry/2D Flow Areas/{project}_2DArea")
        area.create_group("Infiltration")


def _terrain_hdf(path: Path, modifications: list[str]) -> None:
    with h5py.File(path, "w") as hdf:
        root = hdf.create_group("Modifications")
        for modification in modifications:
            root.create_group(modification)


def _build_extracted_delivery(root: Path) -> Path:
    models = root / "Engineering Models" / "HEC-RAS Models"
    models.mkdir(parents=True)
    hydrologic = root / "Engineering Models" / "Hydrologic Models"
    hydrologic.mkdir(parents=True)
    (hydrologic / "Readme.txt").write_text("no HMS model\n")
    (models / "2D_Model_Inventory_UpperGuadalupe.xlsx").write_bytes(b"inventory")
    for number in range(1, 5):
        project = f"UPGU{number}"
        delivered = models / project
        input_root = delivered / "Input"
        output_root = delivered / "Output"
        terrain_root = delivered / "Terrain"
        land_root = delivered / "Land Cover"
        for folder in (input_root, output_root, terrain_root, land_root):
            folder.mkdir(parents=True)
        if project == "UPGU1":
            (input_root / "Projection_File.prj").write_text("projection")
        for suffix in ("prj", "g01", "dss"):
            (input_root / f"{project}.{suffix}").write_text("fixture\n")
        _plan_hdf(input_root / f"{project}.g01.hdf", project)
        projection_reference = (
            r"..\..\_Workspace\KC\SHP\UPGU1\UPGU_WA1.prj"
            if project == "UPGU1"
            else r".\Projection\Projection_File.prj"
        )
        (input_root / f"{project}.rasmap").write_text(
            f'<RASProjectionFilename Filename="{projection_reference}" />\n'
            f'<Layer Type="TerrainLayer" Filename=".\\Terrain\\RAS_Terrain\\'
            f'{"Terrain (1).hdf" if number == 4 else "Terrain.hdf"}" />\n'
        )
        (input_root / "UPGU_precip.dss").write_bytes(b"precip")
        (input_root / "UPGU_precip.dsc.h5").write_bytes(b"catalog")
        predecessor = None if number == 1 else f"UPGU{number - 1}"
        for plan in range(1, 8):
            (input_root / f"{project}.p{plan:02d}").write_text(
                f"Geom File=g01\nFlow File=u{plan:02d}\n"
            )
            upstream = (
                "" if predecessor is None
                else f"DSS File=..\\UPGU_{number - 1}\\{predecessor}.dss\n"
            )
            (input_root / f"{project}.u{plan:02d}").write_text(
                upstream
                + "Met BC=Precipitation|Gridded DSS Filename="
                ".\\DSS_Input\\UPGU_precip.dss\n"
            )
            (input_root / f"{project}.u{plan:02d}.hdf").write_bytes(b"event")
            (input_root / f"{project}.b{plan:02d}").write_text("boundary")
            (output_root / f"{project}.IC.O{plan:02d}").write_bytes(b"ic")
            _plan_hdf(output_root / f"{project}.p{plan:02d}.hdf", project)
        terrain_payloads = RasEbfeModels._UPPER_GUADALUPE_TERRAIN_PAYLOADS[project]
        _terrain_hdf(
            terrain_root / terrain_payloads[0],
            RasEbfeModels._UPPER_GUADALUPE_TERRAIN_MODIFICATIONS[project],
        )
        (terrain_root / terrain_payloads[1]).write_text("vrt")
        (terrain_root / terrain_payloads[2]).write_bytes(b"raster")
        for name in ("Infiltration.hdf", "LandCover.hdf", "Soils.hdf"):
            (land_root / name).write_bytes(b"land")
    return root


def test_registry_exposes_exact_source_and_pending_contract() -> None:
    metadata = RasEbfeModels.get_model_metadata("12100201")
    assert metadata.url == RasEbfeModels._UPPER_GUADALUPE_SOURCE_URL
    assert metadata.file_size_mb == pytest.approx(58_575_220_457 / 1024**2)
    assert metadata.hecras_version == "6.3.1"
    assert metadata.extra["project_count"] == 4
    assert metadata.extra["canonical_plan"] == "01"
    assert metadata.extra["required_validation_level"] == "unsteady_start"
    assert metadata.extra["validation_status"] == "partial"
    assert metadata.extra["validation_level"] == "unsteady_start"
    assert metadata.extra["validation_scope"] == "isolated_copy"
    assert metadata.extra["hec_ras_executed"] is True
    assert metadata.extra["qualified_plans"] == [{
        "project": "UPGU1",
        "plan": "01",
        "title": "UPGU1_1pct",
        "num_cores": 2,
        "signal_source": "owned_process_artifacts",
    }]
    assert metadata.extra["unqualified_projects"] == ["UPGU2", "UPGU3", "UPGU4"]
    assert metadata.extra["terrain_modification_layers"] == {
        "UPGU1": ["Channels"],
        "UPGU2": ["Channels"],
        "UPGU3": ["Channels"],
        "UPGU4": ["Polygons", "Channels"],
    }
    asset = metadata.extra["source_assets"][0]
    assert asset == {
        "role": "models",
        "name": "12100201_Models.zip",
        "url": RasEbfeModels._UPPER_GUADALUPE_SOURCE_URL,
        "size_bytes": 58_575_220_457,
        "etag": "67e7b10db40c2659eee9a5f1e6032b47-6983",
        "extract": False,
    }


def test_legacy_extracted_organizer_builds_four_projects_and_224_attributes(
    tmp_path: Path,
) -> None:
    source = _build_extracted_delivery(tmp_path / "source")
    target = tmp_path / "organized"

    assert RasEbfeModels.organize_upper_guadalupe(source, target) == target
    manifest = json.loads(
        (target / "agent" / "upper_guadalupe_manifest.json").read_text()
    )
    assert set(manifest["projects"]) == {"UPGU1", "UPGU2", "UPGU3", "UPGU4"}
    assert manifest["association_attributes"] == {
        "expected": 224,
        "plan_hdf_expected": 196,
        "geometry_hdf_expected": 28,
        "checked": 224,
        "updated": 224,
        "already_correct": 0,
    }
    assert manifest["required_validation_level"] == "unsteady_start"
    assert manifest["validation_status"] == "pending"
    assert manifest["fresh_output_status"] == "pending"
    assert manifest["hec_ras_executed"] is False
    assert manifest["archive_member_counts"] is None
    assert manifest["source_inventory"]["file_count"] > 0
    assert manifest["source_inventory"]["total_bytes"] > 0
    assert manifest["reference_audit"] == {
        "active_hydraulic_reference_closure": True,
        "project_count": 4,
        "terrain_payload_files_checked": 12,
        "terrain_modification_groups_checked": 5,
        "hdf_association_attributes_checked": 224,
        "plan_bindings_checked": 28,
        "local_precipitation_references_checked": 28,
        "upstream_dss_references_checked": 21,
        "rasmap_hydraulic_references_checked": 8,
        "errors": [],
    }

    for number in range(1, 5):
        project = f"UPGU{number}"
        root = target / "RAS Model" / project
        assert (root / f"{project}.prj").is_file()
        assert len(list(root.glob(f"{project}.p??.hdf"))) == 7
        assert len(list(root.glob(f"{project}.IC.O??"))) == 7
        assert (root / "DSS Inputs" / "UPGU_precip.dss").is_file()
        assert (
            root / "Projection" / f"{project}_Projection.prj"
        ).read_text() == "projection"
        assert not (root / "Projection_File.prj").exists()
        with h5py.File(root / f"{project}.p01.hdf") as hdf:
            assert hdf["Geometry"].attrs["Infiltration Filename"] == (
                rb".\Land Cover\Infiltration.hdf"
            )
            assert hdf[
                f"Geometry/2D Flow Areas/{project}_2DArea"
            ].attrs["Land Cover Filename"] == rb".\Land Cover\LandCover.hdf"
            terrain = "Terrain (1).hdf" if number == 4 else "Terrain.hdf"
            assert hdf["Geometry"].attrs["Terrain Filename"] == (
                f".\\Terrain\\{terrain}".encode()
            )
            assert hdf["Geometry"].attrs.get_id(
                "Terrain Filename"
            ).dtype.kind == "S"
        for plan in range(1, 8):
            text = (root / f"{project}.u{plan:02d}").read_text()
            assert "./DSS Inputs/UPGU_precip.dss" in text
            if number > 1:
                upstream = f"UPGU{number - 1}"
                assert f"../{upstream}/{upstream}.dss" in text

    assert RasEbfeModels.organize_upper_guadalupe(source, target) == target


def test_hdf_repair_rejects_conflicting_nonempty_prestate(tmp_path: Path) -> None:
    _plan_hdf(tmp_path / "UPGU1.g01.hdf", "UPGU1")
    for number in range(1, 8):
        _plan_hdf(tmp_path / f"UPGU1.p{number:02d}.hdf", "UPGU1")
    with h5py.File(tmp_path / "UPGU1.p01.hdf", "r+") as hdf:
        hdf["Geometry"].attrs["Terrain Filename"] = r"C:\other\Terrain.hdf"

    with pytest.raises(RuntimeError, match="pre-state conflict"):
        RasEbfeModels._repair_upper_guadalupe_hdf_associations(
            tmp_path, "UPGU1", "Terrain.hdf"
        )


def test_hdf_repair_accepts_only_exact_audited_stale_prestate(
    tmp_path: Path,
) -> None:
    groups = (
        "Geometry",
        "Geometry/2D Flow Areas/UPGU1_2DArea",
    )
    paths = [tmp_path / "UPGU1.g01.hdf"]
    paths.extend(tmp_path / f"UPGU1.p{number:02d}.hdf" for number in range(1, 8))
    for path in paths:
        _plan_hdf(path, "UPGU1")
        with h5py.File(path, "r+") as hdf:
            for group_name in groups:
                hdf[group_name].attrs["Infiltration Filename"] = (
                    r".\Land Classification\Infiltration.hdf"
                )
                hdf[group_name].attrs["Land Cover Filename"] = (
                    r".\Land Classification\LandCover.hdf"
                )
                hdf[group_name].attrs["Terrain Filename"] = (
                    r".\Terrain\RAS_Terrain\Terrain.hdf"
                )
            hdf[
                "Geometry/2D Flow Areas/UPGU1_2DArea/Infiltration"
            ].attrs["Infiltration Filename"] = (
                r".\Land Classification\Infiltration.hdf"
            )

    result = RasEbfeModels._repair_upper_guadalupe_hdf_associations(
        tmp_path, "UPGU1", "Terrain.hdf"
    )
    assert result == {
        "hdf_attributes_checked": 56,
        "hdf_attribute_updates": 56,
        "hdf_attributes_already_correct": 0,
    }
    with h5py.File(tmp_path / "UPGU1.p01.hdf") as hdf:
        assert hdf["Geometry"].attrs["Terrain Filename"] == (
            rb".\Terrain\Terrain.hdf"
        )
        assert hdf["Geometry"].attrs["Land Cover Filename"] == (
            rb".\Land Cover\LandCover.hdf"
        )


def test_terrain_triplet_and_modifications_are_fail_closed(tmp_path: Path) -> None:
    missing_raster_source = _build_extracted_delivery(tmp_path / "missing-raster")
    missing_raster = (
        missing_raster_source
        / "Engineering Models"
        / "HEC-RAS Models"
        / "UPGU4"
        / "Terrain"
        / "Terrain (1).upgu34.tif"
    )
    missing_raster.unlink()
    with pytest.raises(RuntimeError, match="active hydraulic reference closure"):
        RasEbfeModels.organize_upper_guadalupe(
            missing_raster_source, tmp_path / "missing-raster-output"
        )

    missing_group_source = _build_extracted_delivery(tmp_path / "missing-group")
    terrain_hdf = (
        missing_group_source
        / "Engineering Models"
        / "HEC-RAS Models"
        / "UPGU4"
        / "Terrain"
        / "Terrain (1).hdf"
    )
    with h5py.File(terrain_hdf, "r+") as hdf:
        del hdf["Modifications/Polygons"]
    with pytest.raises(RuntimeError, match="active hydraulic reference closure"):
        RasEbfeModels.organize_upper_guadalupe(
            missing_group_source, tmp_path / "missing-group-output"
        )


def test_partial_reuse_is_rejected(tmp_path: Path) -> None:
    source = _build_extracted_delivery(tmp_path / "source")
    target = tmp_path / "organized"
    RasEbfeModels.organize_upper_guadalupe(source, target)
    missing = target / "RAS Model" / "UPGU4" / "UPGU4.p07.hdf"
    quarantine = tmp_path / missing.name
    shutil.move(missing, quarantine)

    assert RasEbfeModels._upper_guadalupe_is_reusable(
        target, source_root=source
    ) is False

    shutil.move(quarantine, missing)
    assert RasEbfeModels._upper_guadalupe_is_reusable(
        target, source_root=source
    ) is False

    # Legacy extracted trees are intentionally never reusable: equal aggregate
    # counts and sizes cannot prove content identity without the pinned ZIP.
    source_file = (
        source
        / "Engineering Models"
        / "HEC-RAS Models"
        / "UPGU1"
        / "Input"
        / "UPGU1.prj"
    )
    original = source_file.read_bytes()
    source_file.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    assert RasEbfeModels._upper_guadalupe_is_reusable(
        target, source_root=source
    ) is False
    source_file.write_bytes(original)

    (source / "unexpected-source-object.txt").write_text("tamper")
    assert RasEbfeModels._upper_guadalupe_is_reusable(
        target, source_root=source
    ) is False
    (source / "unexpected-source-object.txt").unlink()

    with h5py.File(
        target / "RAS Model" / "UPGU4" / "UPGU4.p01.hdf", "r+"
    ) as hdf:
        hdf["Geometry"].attrs["Terrain Filename"] = r"C:\tampered\Terrain.hdf"
    assert RasEbfeModels._upper_guadalupe_is_reusable(
        target, source_root=source
    ) is False
