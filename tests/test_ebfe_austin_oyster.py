"""Austin--Oyster source contract and hardened organizer tests."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import zipfile

import h5py
import pytest

from ras_commander.sources.federal.ebfe_models import RasEbfeModels


def _zip_tree(path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def _plan_hdf(path: Path) -> None:
    with h5py.File(path, "w") as hdf:
        hdf.create_group("Geometry")
        hdf.create_group("Geometry/2D Flow Areas/Perimeter 1")


def _build_delivery(root: Path, *, omit_output: str | None = None) -> Path:
    source = root / "source"
    source.mkdir(parents=True)
    input_dir = root / "input"
    output_dir = root / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    for suffix in ("prj", "g02"):
        (input_dir / f"AustinOyster.{suffix}").write_text("test\n")
    for number in range(3, 10):
        (input_dir / f"AustinOyster.p{number:02d}").write_text(
            "Geom File=g02\nFlow File=u01\n"
        )
    for number in range(1, 8):
        (input_dir / f"AustinOyster.u{number:02d}").write_text("test\n")
    (input_dir / "AustinOyster.rasmap").write_text(
        'Projection Filename="./NAD_1983_2011_StatePlane_Texas_South_Central_'
        'FIPS_4204_FtUS.prj"\n'
        r"%LocalAppData%\HEC\Mapping\506\XML\Google Map.xml"
        "\n"
        r"%LocalAppData%\HEC\Mapping\506\XML\Google Hybrid.xml"
        "\n"
    )
    (
        input_dir / "NAD_1983_2011_StatePlane_Texas_South_Central_FIPS_4204_FtUS.prj"
    ).write_text("prj")
    for number in range(68):
        (input_dir / f"support-{number:02d}.dat").write_text("support")
    for number in range(3, 10):
        ic_name = f"AustinOyster.IC.O{number:02d}"
        hdf_name = f"AustinOyster.p{number:02d}.hdf"
        if omit_output != ic_name:
            (output_dir / ic_name).write_text("ic")
        if omit_output != hdf_name:
            _plan_hdf(output_dir / hdf_name)

    input_zip = root / "Input.zip"
    with zipfile.ZipFile(input_zip, "w") as archive:
        archive.writestr("Input/", b"")
        for path in input_dir.rglob("*"):
            if path.is_file():
                archive.write(path, f"Input/{path.relative_to(input_dir).as_posix()}")
    output_zip = root / "Output.zip"
    with zipfile.ZipFile(output_zip, "w") as archive:
        archive.writestr("Output/", b"")
        for path in output_dir.iterdir():
            archive.write(path, f"Output/{path.name}")
    land_zip = root / "LandCover.zip"
    _zip_tree(
        land_zip,
        {"LandCover/": b"", "LandCover/Landcover.tif": b"land"},
    )
    terrain_zip = root / "Terrain.zip"
    _zip_tree(
        terrain_zip,
        {"Terrain/": b"", "Terrain/Terrain.hdf": b"terrain"},
    )
    submittal = root / "RAS_Submittal.zip"
    with zipfile.ZipFile(submittal, "w") as archive:
        archive.writestr("Components/", b"")
        archive.writestr("Evidence/", b"")
        for path in (input_zip, land_zip, output_zip, terrain_zip):
            archive.write(path, path.name)

    outer = source / "12040205_Models.zip"
    with zipfile.ZipFile(outer, "w") as archive:
        for number in range(15):
            archive.writestr(f"Directory-{number:02d}/", b"")
        archive.write(submittal, "Models/RAS_Submittal.zip")
        for number in range(47):
            archive.writestr(f"Documents/evidence-{number:03d}.txt", b"evidence")
    sidecar = RasEbfeModels._source_sidecar_path(outer)
    sidecar.write_text(
        json.dumps(
            {
                "partial": False,
                "source": RasEbfeModels._AUSTIN_OYSTER_SOURCE_URL,
                "final_url": RasEbfeModels._AUSTIN_OYSTER_SOURCE_URL,
                "size": outer.stat().st_size,
                "etag": "fixture-etag",
            }
        )
    )
    return source


@pytest.fixture
def fixture_identity(monkeypatch: pytest.MonkeyPatch):
    asset = RasEbfeModels._MODEL_REGISTRY["austin-oyster"]["extra"]["source_assets"][0]
    original = dict(asset)
    monkeypatch.setitem(asset, "etag", "fixture-etag")
    yield asset
    asset.clear()
    asset.update(original)


def test_aliases_and_exact_registry_metadata():
    for alias in ("austin-oyster", "austinoyster", "12040205"):
        assert RasEbfeModels.normalize_model_key(alias) == "austin-oyster"
    metadata = RasEbfeModels.get_model_metadata("12040205")
    assert metadata.url == RasEbfeModels._AUSTIN_OYSTER_SOURCE_URL
    assert metadata.hecras_version == "5.0.7"
    assert metadata.extra["plans"] == ["03", "04", "05", "06", "07", "08", "09"]
    assert metadata.extra["geometry"] == "02"
    assert metadata.extra["unsteady_files"] == [
        "01",
        "02",
        "03",
        "04",
        "05",
        "06",
        "07",
    ]
    assert metadata.extra["terrain_source_complete"] is True
    assert metadata.extra["terrain_modification_layers"] == []
    assert metadata.extra["required_validation_level"] == "unsteady_start"
    assert metadata.extra["validation_status"] == "qualified"
    assert metadata.extra["validation_level"] == "unsteady_start"
    assert metadata.extra["hec_ras_executed"] is True
    assert metadata.extra["validation_scope"] == "isolated_copy"
    assert metadata.extra["qualified_plan"] == {
        "project": "AustinOyster",
        "plan": "08",
        "title": "1PAC",
    }
    assert metadata.extra["qualification_record"] == (
        "agent_tasks/2026-09-23_austin_oyster_record_of_deficiencies.md"
    )
    assert "full-plan completion was not claimed" in metadata.description
    refs = metadata.extra["nonblocking_unresolved_references"]
    assert sum(item["count"] for item in refs) == 2
    assert {item["classification"] for item in refs} == {"display_only"}
    asset = metadata.extra["source_assets"][0]
    assert asset["size_bytes"] == 24_083_078_085
    assert asset["etag"] == "cacc1f6de4d01d273f319dcf6514c9a2-2871"
    assert asset["extract"] is False


def test_organizer_exact_contract_repairs_and_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixture_identity
):
    source = _build_delivery(tmp_path)
    archive = source / "12040205_Models.zip"
    monkeypatch.setitem(fixture_identity, "size_bytes", archive.stat().st_size)
    target = tmp_path / "organized"
    source_state = (archive.stat().st_size, archive.stat().st_mtime_ns)

    result = RasEbfeModels.organize_austin_oyster(source, target)
    assert result == target
    assert source_state == (archive.stat().st_size, archive.stat().st_mtime_ns)
    manifest = json.loads(
        (target / "agent" / "austin_oyster_manifest.json").read_text()
    )
    assert manifest["outer_member_count"] == 48
    assert manifest["outer_directory_count"] == 15
    assert manifest["submittal_member_count"] == 4
    assert manifest["submittal_directory_count"] == 2
    assert manifest["component_member_count"] == 102
    assert sum(manifest["component_directory_counts"].values()) == 4
    assert manifest["actual_explicit_corrections"] == 29
    assert manifest["path_repairs"]["hdf_attributes_checked"] == 28
    assert manifest["path_repairs"]["hdf_attribute_updates"] == 28
    assert manifest["path_repairs"]["hdf_attributes_already_correct"] == 0
    assert manifest["path_repairs"]["projection_asset_relocations"] == 1
    assert len(manifest["output_assets_relocated"]) == 14
    assert manifest["reference_audit"]["static_path_closure"] is True
    assert manifest["required_validation_level"] == "unsteady_start"
    assert manifest["validation_status"] == "pending"
    assert manifest["hec_ras_executed"] is False

    active = target / "RAS Model" / "AustinOyster" / "Input"
    projection_name = "NAD_1983_2011_StatePlane_Texas_South_Central_FIPS_4204_FtUS.prj"
    assert not (active / projection_name).exists()
    assert (active / "Projection" / projection_name).is_file()
    with h5py.File(active / "AustinOyster.p03.hdf") as hdf:
        assert hdf["Geometry"].attrs["Terrain Filename"] == r"..\Terrain\Terrain.hdf"
        assert (
            hdf["Geometry/2D Flow Areas/Perimeter 1"].attrs["Land Cover Filename"]
            == r"..\LandCover\Landcover.tif"
        )
    assert "./Projection/NAD_" in (active / "AustinOyster.rasmap").read_text()
    assert RasEbfeModels.organize_austin_oyster(source, target) == target


def test_zip_traversal_case_collision_and_crc_integrity_rejected(tmp_path: Path):
    traversal = tmp_path / "traversal.zip"
    _zip_tree(traversal, {"../escape.txt": b"bad"})
    with pytest.raises(ValueError, match="Unsafe ZIP member"):
        RasEbfeModels._extract_zip_verified(traversal, tmp_path / "a")

    collision = tmp_path / "collision.zip"
    _zip_tree(collision, {"Input/File.txt": b"a", "input/file.TXT": b"b"})
    with pytest.raises(ValueError, match="Duplicate ZIP extraction target"):
        RasEbfeModels._extract_zip_verified(collision, tmp_path / "b")

    valid = tmp_path / "integrity.zip"
    _zip_tree(valid, {"file.bin": b"verified"})
    destination = tmp_path / "c"
    RasEbfeModels._extract_zip_verified(valid, destination)
    (destination / "file.bin").write_bytes(b"corrupt!")
    with pytest.raises(RuntimeError, match="incomplete"):
        RasEbfeModels._extract_zip_verified(valid, destination)


def test_failure_is_atomic_and_preserves_source_and_existing_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixture_identity
):
    source = _build_delivery(tmp_path, omit_output="AustinOyster.p09.hdf")
    archive = source / "12040205_Models.zip"
    monkeypatch.setitem(fixture_identity, "size_bytes", archive.stat().st_size)
    target = tmp_path / "organized"
    target.mkdir()
    marker = target / "preserve.txt"
    marker.write_text("original")
    source_state = (archive.stat().st_size, archive.stat().st_mtime_ns)

    with pytest.raises(RuntimeError, match="component contract mismatch"):
        RasEbfeModels.organize_austin_oyster(source, target)
    assert marker.read_text() == "original"
    assert source_state == (archive.stat().st_size, archive.stat().st_mtime_ns)
    assert not list(tmp_path.glob(".organized.assembling-*"))


def test_member_count_and_identity_are_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixture_identity
):
    source = _build_delivery(tmp_path)
    archive = source / "12040205_Models.zip"
    monkeypatch.setitem(fixture_identity, "size_bytes", archive.stat().st_size)
    monkeypatch.setattr(RasEbfeModels, "_AUSTIN_OYSTER_OUTER_MEMBER_COUNT", 49)
    with pytest.raises(RuntimeError, match="expected 49 outer file members"):
        RasEbfeModels.organize_austin_oyster(source, tmp_path / "bad-count")

    monkeypatch.setattr(RasEbfeModels, "_AUSTIN_OYSTER_OUTER_MEMBER_COUNT", 48)
    monkeypatch.setitem(fixture_identity, "etag", "wrong-etag")
    with pytest.raises(RuntimeError, match="ETag mismatch"):
        RasEbfeModels.organize_austin_oyster(source, tmp_path / "bad-etag")


def test_hdf_repair_rejects_conflicting_nonempty_prestate(tmp_path: Path):
    for number in range(3, 10):
        _plan_hdf(tmp_path / f"AustinOyster.p{number:02d}.hdf")
    with h5py.File(tmp_path / "AustinOyster.p03.hdf", "r+") as hdf:
        hdf["Geometry"].attrs["Terrain Filename"] = r"C:\other\Terrain.hdf"
    (tmp_path / "AustinOyster.rasmap").write_text(
        'Projection Filename="./NAD_1983_StatePlane_Texas_South_Central.prj"\n'
    )
    with pytest.raises(RuntimeError, match="pre-state conflict"):
        RasEbfeModels._repair_austin_oyster_paths(tmp_path)


def test_hdf_repair_preserves_path_equivalent_repeated_separators(tmp_path: Path):
    for number in range(3, 10):
        _plan_hdf(tmp_path / f"AustinOyster.p{number:02d}.hdf")
    with h5py.File(tmp_path / "AustinOyster.p03.hdf", "r+") as hdf:
        for group_name in (
            "Geometry",
            "Geometry/2D Flow Areas/Perimeter 1",
        ):
            hdf[group_name].attrs["Terrain Filename"] = "..\\\\Terrain\\\\Terrain.hdf"
            hdf[group_name].attrs["Land Cover Filename"] = (
                "..//LANDCOVER//Landcover.tif"
            )
    (tmp_path / "AustinOyster.rasmap").write_text(
        'Projection Filename="./NAD_1983_StatePlane_Texas_South_Central.prj"\n'
    )

    repairs = RasEbfeModels._repair_austin_oyster_paths(tmp_path)

    assert repairs == {
        "hdf_attributes_checked": 28,
        "hdf_attribute_updates": 24,
        "hdf_attributes_already_correct": 4,
        "rasmap_projection_updates": 1,
    }
    with h5py.File(tmp_path / "AustinOyster.p03.hdf", "r") as hdf:
        assert (
            hdf["Geometry"].attrs["Terrain Filename"] == "..\\\\Terrain\\\\Terrain.hdf"
        )


def test_projection_relocation_matches_delivered_location(tmp_path: Path):
    projection_name = "NAD_1983_2011_StatePlane_Texas_South_Central_FIPS_4204_FtUS.prj"
    source = tmp_path / projection_name
    source.write_text("delivered")

    assert RasEbfeModels._relocate_austin_oyster_projection(tmp_path) == 1
    assert not source.exists()
    assert (tmp_path / "Projection" / projection_name).read_text() == "delivered"

    source.write_text("duplicate")
    with pytest.raises(RuntimeError, match="would overwrite"):
        RasEbfeModels._relocate_austin_oyster_projection(tmp_path)


def test_output_relocation_rejects_duplicate_required_basename(tmp_path: Path):
    output_root = tmp_path / "Output"
    input_root = tmp_path / "Input"
    output_root.mkdir()
    input_root.mkdir()
    for number in range(3, 10):
        (output_root / f"AustinOyster.IC.O{number:02d}").write_text("ic")
        _plan_hdf(output_root / f"AustinOyster.p{number:02d}.hdf")
    duplicate = output_root / "duplicate"
    duplicate.mkdir()
    shutil.copy2(
        output_root / "AustinOyster.p03.hdf",
        duplicate / "AustinOyster.p03.hdf",
    )

    with pytest.raises(RuntimeError, match="'AustinOyster.p03.hdf': 2"):
        RasEbfeModels._relocate_austin_oyster_outputs(output_root, input_root)
    assert not list(input_root.iterdir())


def test_all_28_path_equivalent_hdf_attributes_are_preserved(tmp_path: Path):
    for number in range(3, 10):
        hdf_path = tmp_path / f"AustinOyster.p{number:02d}.hdf"
        _plan_hdf(hdf_path)
        with h5py.File(hdf_path, "r+") as hdf:
            for group_name in (
                "Geometry",
                "Geometry/2D Flow Areas/Perimeter 1",
            ):
                hdf[group_name].attrs["Terrain Filename"] = (
                    "..\\\\TERRAIN\\\\Terrain.hdf"
                )
                hdf[group_name].attrs["Land Cover Filename"] = (
                    "..//landcover//Landcover.tif"
                )
    (tmp_path / "AustinOyster.rasmap").write_text(
        'Projection Filename="./NAD_1983_StatePlane_Texas_South_Central.prj"\n'
    )

    repairs = RasEbfeModels._repair_austin_oyster_paths(tmp_path)

    assert repairs["hdf_attributes_checked"] == 28
    assert repairs["hdf_attribute_updates"] == 0
    assert repairs["hdf_attributes_already_correct"] == 28
    with h5py.File(tmp_path / "AustinOyster.p09.hdf", "r") as hdf:
        assert (
            hdf["Geometry"].attrs["Terrain Filename"] == "..\\\\TERRAIN\\\\Terrain.hdf"
        )


def test_public_dispatchers_organize_and_download_austin_oyster(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_identity,
):
    seed = _build_delivery(tmp_path / "seed")
    seed_archive = seed / "12040205_Models.zip"
    monkeypatch.setitem(fixture_identity, "size_bytes", seed_archive.stat().st_size)

    direct = RasEbfeModels.organize_model(
        "austinoyster",
        downloaded_folder=seed,
        output_folder=tmp_path / "direct",
    )
    assert (direct / "agent" / "austin_oyster_manifest.json").is_file()

    download_root = tmp_path / "cache"

    def fake_download(url, destination, **kwargs):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(seed_archive, destination)
        shutil.copy2(
            RasEbfeModels._source_sidecar_path(seed_archive),
            RasEbfeModels._source_sidecar_path(destination),
        )
        return destination

    monkeypatch.setattr(RasEbfeModels, "_download_file", fake_download)
    via_download = RasEbfeModels.download_model(
        "12040205",
        tmp_path / "downloads",
        download_root=download_root,
    )
    assert via_download.success is True
    assert via_download.model_path == (tmp_path / "downloads" / "AustinOyster_12040205")
    assert (via_download.model_path / "agent" / "austin_oyster_manifest.json").is_file()
    assert (download_root / "12040205_AustinOyster" / "12040205_Models.zip").is_file()


def test_source_asset_dispatch_keeps_archive_unextracted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    destination = tmp_path / "12040205_Models.zip"

    def fake_download(url, dest, **kwargs):
        assert dest == destination
        dest.write_bytes(b"archive")
        return dest

    monkeypatch.setattr(RasEbfeModels, "_download_file", fake_download)
    monkeypatch.setattr(
        RasEbfeModels,
        "_download_and_extract",
        lambda *args, **kwargs: pytest.fail("archive must not auto-extract"),
    )

    result = RasEbfeModels.download_source_asset("austin-oyster", "models", tmp_path)
    assert result == destination
