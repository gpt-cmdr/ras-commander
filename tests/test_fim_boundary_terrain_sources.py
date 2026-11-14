"""Original TIFF/HDF mosaic preparation, without executing native engines."""

from pathlib import Path

import h5py
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from ras_commander.fim import _boundary_inputs, _boundary_terrain_sources as sources
from ras_commander.fim.errors import FimEngineError, FimUnsupportedError


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    from ras_commander import fast_hdf
    calls = []

    def read(dataset, selection, **kwargs):
        assert kwargs["backend"] == "rust"
        calls.append(dataset.name)
        return dataset[selection]

    monkeypatch.setattr(fast_hdf, "read_dataset", read)
    monkeypatch.setattr(_boundary_inputs, "_native_bitfields", lambda *args: False)
    monkeypatch.setattr(sources._engine, "terrain_identity", lambda engine, path, crs, pin, **kw:
                        {"path": str(path), "epsg": 6588, "crs_identity": {"kind": "epsg"}})
    return calls


def make_terrain(tmp_path, *, count=2, track_order=False, priorities=(20, 10), crs=6588):
    hdf = tmp_path / "terrain.hdf"
    crs = rasterio.crs.CRS.from_epsg(crs)
    # Deliberately reverse lexical and creation order. Priority chooses z first.
    names = ["a-source", "z-source"][:count]
    with h5py.File(hdf, "w") as handle:
        handle.attrs["Projection"] = np.bytes_(crs.to_wkt())
        terrain = handle.create_group("Terrain", track_order=track_order)
        for index, name in enumerate(names):
            tiff = tmp_path / f"{name}.tif"
            with rasterio.open(tiff, "w", driver="GTiff", width=257, height=256,
                    count=1, dtype="float32", crs=crs, nodata=-9999,
                    transform=from_origin(3000000 + index * 257, 10000000, 1, 1),
                    tiled=True, blockxsize=256, blockysize=256) as raster:
                raster.write(np.full((256, 257), index, dtype="float32"), 1)
            group = terrain.create_group(name)
            group.attrs["File"] = np.bytes_(tiff.name)
            if priorities[index] is not None:
                group.attrs["Priority"] = priorities[index]
            level = group.create_group("0")
            level["Mask"] = np.full((2, 65536), index + 1, dtype="uint8")
            level["Perimeter"] = np.full((2, 513), index + 3, dtype="float32")
        terrain["Stitch TIN Points"] = np.array([[0, 0, 0, 0], [1, 0, 2, 0], [0, 1, 3, 0]], dtype="<f8")
        terrain["Stitch TIN Triangles"] = np.array([[0, 1, 2]], dtype="<i4")
    primary = tmp_path / ("z-source.tif" if count == 2 and priorities == (20, 10) else "a-source.tif")
    return hdf, primary


def stage(terrain, root, **kwargs):
    return sources.stage_native_terrain_sources(*terrain, root, engine_path="unused.exe", threads=2,
            model_crs="EPSG:6588", max_staged_bytes=kwargs.pop("max_staged_bytes", 2**22),
            timeout=5, **kwargs)


def test_two_sources_preserve_native_priority_full_tiles_and_single_global_tin(tmp_path, no_native):
    terrain = make_terrain(tmp_path, track_order=True)
    result = stage(terrain, tmp_path / "out")
    assert [x["raw_group_name"] for x in result["source_identities"]] == ["z-source", "a-source"]
    assert [x["raw_priority"] for x in result["source_identities"]] == [10, 20]
    assert [x["effective_index"] for x in result["source_identities"]] == [0, 1]
    assert [x["native_group_index"] for x in result["source_identities"]] == [1, 0]
    assert all(len(x["sha256"]) == 64 for x in result["source_identities"])
    primary, extra = result["terrain_metadata"], result["additional_terrains"][0]
    assert primary["selected_tiles"] == extra["terrain_metadata"]["selected_tiles"] == [0, 1]
    assert primary["stitch_points"] and primary["stitch_triangles"]
    assert extra["terrain_metadata"]["stitch_points"] is None
    assert extra["terrain_metadata"]["stitch_triangles"] is None
    assert extra["terrain"] == str((tmp_path / "a-source.tif").resolve())
    assert Path(extra["terrain_metadata"]["mask"]["path"]).is_absolute()
    assert np.fromfile(tmp_path / "out" / primary["mask"]["path"], dtype="uint8").tolist() == [2] * (2 * 65536)
    assert np.fromfile(extra["terrain_metadata"]["mask"]["path"], dtype="uint8").tolist() == [1] * (2 * 65536)
    assert no_native.count("/Terrain/Stitch TIN Points") == 1
    assert no_native.count("/Terrain/Stitch TIN Triangles") == 1
    assert result["staged_bytes"] == sum(p.stat().st_size for p in (tmp_path / "out").rglob("*.bin"))


def test_single_source_matches_existing_stage_byte_for_byte(tmp_path):
    terrain = make_terrain(tmp_path, count=1)
    old = _boundary_inputs.stage_boundary_terrain(*terrain, tmp_path / "old")
    result = stage(terrain, tmp_path / "new")
    assert result["terrain_metadata"] == old
    assert not result["additional_terrains"]
    for path in (tmp_path / "old").iterdir():
        assert path.read_bytes() == (tmp_path / "new" / path.name).read_bytes()


def test_old_route_still_refuses_mosaics(tmp_path, no_native):
    with pytest.raises(FimUnsupportedError, match="exactly one"):
        _boundary_inputs.stage_boundary_terrain(*make_terrain(tmp_path), tmp_path / "out")
    assert no_native == []


def missing_projection_vrt(terrain, *, crs="EPSG:6588", names=("a-source.tif", "z-source.tif")):
    import xml.etree.ElementTree as ET
    with h5py.File(terrain[0], "a") as handle:
        del handle.attrs["Projection"]
    root = ET.Element("VRTDataset", rasterXSize="514", rasterYSize="256")
    ET.SubElement(root, "SRS").text = rasterio.crs.CRS.from_user_input(crs).to_wkt()
    band = ET.SubElement(root, "VRTRasterBand", dataType="Float32", band="1")
    for name in names:
        source = ET.SubElement(band, "ComplexSource")
        ET.SubElement(source, "SourceFilename", relativeToVRT="1").text = name
        ET.SubElement(source, "SourceBand").text = "1"
    vrt = terrain[0].with_suffix(".vrt")
    ET.ElementTree(root).write(vrt, encoding="utf-8")
    return vrt


def test_native_missing_hdf_projection_binds_actual_registered_vrt_and_all_sources(tmp_path):
    terrain = make_terrain(tmp_path)
    vrt = missing_projection_vrt(terrain)
    result = stage(terrain, tmp_path / "out")
    evidence = result["terrain_crs_evidence"]
    assert evidence["kind"] == "registered-vrt-source-identity/1"
    assert evidence["path"] == str(vrt)
    assert evidence["sha256"] == sources.digest(vrt)
    assert evidence["source_files"] == [row["path"] for row in result["source_identities"]]
    assert result["terrain_metadata"]["stitch_points"]


@pytest.mark.parametrize("bad", ["missing", "crs", "source", "absolute", "scaled", "malformed"])
def test_missing_hdf_projection_requires_consistent_plain_vrt_before_hash_or_reads(tmp_path, monkeypatch, no_native, bad):
    terrain = make_terrain(tmp_path)
    vrt = missing_projection_vrt(terrain, crs="EPSG:2278" if bad == "crs" else "EPSG:6588",
        names=("wrong.tif", "z-source.tif") if bad == "source" else ("a-source.tif", "z-source.tif"))
    if bad == "missing":
        vrt.unlink()
    elif bad == "absolute":
        vrt.write_text(vrt.read_text().replace('relativeToVRT="1"', 'relativeToVRT="0"'))
    elif bad == "scaled":
        vrt.write_text(vrt.read_text().replace("</ComplexSource>", "<ScaleRatio>2</ScaleRatio></ComplexSource>"))
    elif bad == "malformed":
        vrt.write_text("<VRTDataset>")
    monkeypatch.setattr(sources, "digest", lambda path: pytest.fail("hash before VRT CRS/source admission"))
    with pytest.raises(FimUnsupportedError, match="Projection"):
        stage(terrain, tmp_path / "out")
    assert not (tmp_path / "out").exists() and no_native == []


def test_deterministic_missing_projection_contract_is_preserved(tmp_path):
    terrain = make_terrain(tmp_path, count=1)
    missing_projection_vrt(terrain, names=("a-source.tif",))
    with pytest.raises(FimUnsupportedError, match="Projection is missing"):
        _boundary_inputs.stage_boundary_terrain(*terrain, tmp_path / "old")
    assert not (tmp_path / "old").exists()


def test_primary_must_be_native_first_before_hash_or_output(tmp_path, monkeypatch, no_native):
    hdf, _ = make_terrain(tmp_path)
    monkeypatch.setattr(sources, "digest", lambda path: pytest.fail("hash before ordering admission"))
    with pytest.raises(FimUnsupportedError, match="Primary TIFF"):
        stage((hdf, tmp_path / "a-source.tif"), tmp_path / "out")
    assert no_native == [] and not (tmp_path / "out").exists()


@pytest.mark.parametrize("priorities", [(None, None), (10, 10), (None, 10)])
def test_creation_indexed_ambiguous_order_refuses(tmp_path, priorities, no_native):
    with pytest.raises(FimUnsupportedError, match="Creation-indexed"):
        stage(make_terrain(tmp_path, track_order=True, priorities=priorities), tmp_path / "out")
    assert no_native == []


def test_missing_priority_preserves_name_native_order_without_sorting_priority(tmp_path):
    result = stage(make_terrain(tmp_path, priorities=(None, -20)), tmp_path / "out")
    assert [x["raw_group_name"] for x in result["source_identities"]] == ["a-source", "z-source"]
    assert result["source_identities"][0]["raw_priority"] == -1


@pytest.mark.parametrize("problem", ["budget", "second-shape", "per-source-tin", "modifications", "soft-link", "missing", "traversal", "priority"])
def test_all_metadata_refusals_precede_hash_numeric_and_outputs(tmp_path, monkeypatch, no_native, problem):
    terrain = make_terrain(tmp_path)
    with h5py.File(terrain[0], "a") as h:
        if problem == "second-shape":
            del h["Terrain/a-source/0/Perimeter"]
            h["Terrain/a-source/0/Perimeter"] = np.zeros((1, 513), dtype="float32")
        elif problem == "per-source-tin":
            h["Terrain/a-source/Stitch TIN Points"] = np.zeros((0, 4))
        elif problem == "modifications":
            h.create_group("Modifications/edit")
        elif problem == "soft-link":
            del h["Terrain/a-source/0/Mask"]
            h["Terrain/a-source/0/Mask"] = h5py.SoftLink("/Terrain/z-source/0/Mask")
        elif problem == "missing":
            h["Terrain/a-source"].attrs["File"] = np.bytes_("missing.tif")
        elif problem == "traversal":
            h["Terrain/a-source"].attrs["File"] = np.bytes_("../a-source.tif")
        elif problem == "priority":
            h["Terrain/a-source"].attrs["Priority"] = 1.5
    monkeypatch.setattr(sources, "digest", lambda path: pytest.fail("hash before all metadata admission"))
    with pytest.raises(FimUnsupportedError):
        stage(terrain, tmp_path / "out", max_staged_bytes=200000 if problem == "budget" else 2**22)
    assert no_native == [] and not (tmp_path / "out").exists()


def test_crs_must_be_actual_survey_feet_before_hash(tmp_path, monkeypatch, no_native):
    terrain = make_terrain(tmp_path, crs=32615)
    monkeypatch.setattr(sources, "digest", lambda path: pytest.fail("hash before CRS"))
    with pytest.raises(FimUnsupportedError, match="Projection"):
        stage(terrain, tmp_path / "out")
    with pytest.raises(FimUnsupportedError, match="US survey feet"):
        sources.stage_native_terrain_sources(*terrain, tmp_path / "out", engine_path="unused",
            threads=1, model_crs=32615, max_staged_bytes=2**22, timeout=None)
    assert no_native == []


def test_later_source_failure_cleans_only_owned_payloads(tmp_path, monkeypatch):
    terrain = make_terrain(tmp_path)
    output = tmp_path / "out"
    output.mkdir()
    retained = output / "retained.txt"
    retained.write_text("keep")
    original = _boundary_inputs.stage_boundary_terrain

    def fail(*args, **kwargs):
        if Path(args[1]).name == "a-source.tif":
            raise FimEngineError("forced second source failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(_boundary_inputs, "stage_boundary_terrain", fail)
    with pytest.raises(FimEngineError, match="forced"):
        stage(terrain, output)
    assert list(output.iterdir()) == [retained]
    assert retained.read_text() == "keep"


def test_late_collision_precedes_all_reads(tmp_path, no_native):
    terrain = make_terrain(tmp_path)
    destination = tmp_path / "out" / "terrain-source-0001"
    destination.mkdir(parents=True)
    retained = destination / "boundary-mask.bin"
    retained.write_bytes(b"retain")
    with pytest.raises(FileExistsError):
        stage(terrain, destination.parent)
    assert retained.read_bytes() == b"retain" and no_native == []


def test_post_stage_same_stat_content_change_detected_and_rolled_back(tmp_path, monkeypatch):
    terrain = make_terrain(tmp_path)
    original = sources.digest
    calls = {}

    def changed(path):
        calls[path] = calls.get(path, 0) + 1
        value = original(path)
        return "0" * 64 if calls[path] > 1 else value

    monkeypatch.setattr(sources, "digest", changed)
    with pytest.raises(FimEngineError, match="content changed"):
        stage(terrain, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("bad", ["dtype", "tile-size", "other-crs", "dangling-global-tin", "external-link"])
def test_additional_source_header_and_global_links_prevalidated(tmp_path, no_native, bad):
    terrain = make_terrain(tmp_path)
    if bad in {"dtype", "tile-size", "other-crs"}:
        tiff = tmp_path / "a-source.tif"
        with rasterio.open(tiff) as raster:
            profile = raster.profile
        if bad == "dtype":
            profile["dtype"] = "int16"
        elif bad == "tile-size":
            profile["blockxsize"] = 128
        else:
            profile["crs"] = "EPSG:2278"
        with rasterio.open(tiff, "w", **profile) as raster:
            raster.write(np.ones((256, 257), dtype=profile["dtype"]), 1)
    else:
        with h5py.File(terrain[0], "a") as handle:
            if bad == "dangling-global-tin":
                for key in ("Stitch TIN Points", "Stitch TIN Triangles"):
                    del handle[f"Terrain/{key}"]
                    handle[f"Terrain/{key}"] = h5py.SoftLink("/missing")
            else:
                handle["Terrain/external"] = h5py.ExternalLink("missing.hdf", "/Terrain")
    with pytest.raises(FimUnsupportedError):
        stage(terrain, tmp_path / "out")
    assert no_native == [] and not (tmp_path / "out").exists()
