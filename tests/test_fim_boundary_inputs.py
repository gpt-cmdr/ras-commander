"""Real-format terrain HDF/TIFF staging and refusal checks; never run HEC-RAS."""

import json
import os

import h5py
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from ras_commander.fim._boundary_inputs import stage_boundary_terrain
from ras_commander.fim.errors import FimEngineError, FimUnsupportedError


@pytest.fixture
def terrain(tmp_path):
    tif, hdf = tmp_path / "source.tif", tmp_path / "terrain.hdf"
    crs = rasterio.crs.CRS.from_epsg(32615)
    with rasterio.open(tif, "w", driver="GTiff", width=513, height=257,
                       count=1, dtype="float32", crs=crs,
                       transform=from_origin(300000, 4000000, 2, 2), nodata=-9999,
                       tiled=True, blockxsize=256, blockysize=256) as raster:
        raster.write(np.ones((257, 513), dtype="float32"), 1)
    with h5py.File(hdf, "w") as handle:
        handle.attrs["Projection"] = np.bytes_(crs.to_wkt())
        group = handle.create_group("Terrain/source")
        group.attrs["File"] = np.bytes_(tif.name)
        level = group.create_group("0")
        mask = np.arange(6 * 65536, dtype="uint8").reshape(6, 65536)
        datatype = h5py.h5t.STD_B8LE.copy()
        dataset = h5py.h5d.create(level.id, b"Mask", datatype, h5py.h5s.create_simple(mask.shape))
        dataset.write(h5py.h5s.ALL, h5py.h5s.ALL, mask, mtype=datatype)
        perimeter = np.arange(6 * 513, dtype="float32").reshape(6, 513)
        perimeter[1, 0], perimeter[1, 1] = -0.0, np.nan
        level["Perimeter"] = perimeter
        handle["Terrain/Stitch TIN Points"] = np.array([[0, 0, 0, 0], [1, 0, 2, 0], [0, 1, 3, 0]], dtype="<f8")
        handle["Terrain/Stitch TIN Triangles"] = np.array([[0, 1, 2]], dtype="<i4")
    return hdf, tif


def _native_bitfields(hdf):
    from ras_commander.fim._boundary_inputs import _native_bitfields
    return _native_bitfields(hdf, "/Terrain/source/0/Mask")


def test_native_selected_tiles_preserve_raw_bits_and_full_stitch_connectivity(terrain, tmp_path, monkeypatch):
    from ras_commander import fast_hdf
    from ras_commander.fim import _boundary_inputs
    hdf, tif = terrain
    native_bits = _native_bitfields(hdf)
    calls = []
    read = fast_hdf.read_dataset
    open_raster = rasterio.open

    class MetadataOnlyRaster:
        def __init__(self, *args, **kwargs):
            self.raster = open_raster(*args, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.raster.__exit__(*args)

        def __getattr__(self, name):
            if name == "read":
                pytest.fail("TIFF pixels must stay lazy in the Rust reader")
            return getattr(self.raster, name)

    def bounded(dataset, selection, **kwargs):
        assert kwargs["backend"] == "rust"
        assert (selection[0].stop - selection[0].start) * dataset.shape[1] * dataset.dtype.itemsize <= 65536
        calls.append(dataset.name)
        return read(dataset, selection, **kwargs)

    monkeypatch.setattr(_boundary_inputs, "_SLAB_BYTES", 65536)
    monkeypatch.setattr(fast_hdf, "read_dataset", bounded)
    monkeypatch.setattr(rasterio, "open", MetadataOnlyRaster)
    output = tmp_path / "staged"
    result = stage_boundary_terrain(hdf, tif, output, selected_tiles=[5, 1])
    assert result["selected_tiles"] == [1, 5]
    assert result["tile_grid"] == [2, 3]
    assert result["tile_shape"] == [256, 256]
    assert result["shape"] == [257, 513]
    json.dumps(result, allow_nan=False)
    with h5py.File(hdf) as handle:
        for key in ["mask", "perimeter", "stitch_points", "stitch_triangles"]:
            descriptor = result[key]
            expected = handle[descriptor["dataset"]][...]
            if key in {"mask", "perimeter"}:
                expected = expected[[1, 5]]
            actual = np.fromfile(output / descriptor["path"], dtype=descriptor["dtype"]).reshape(descriptor["shape"])
            assert actual.tobytes() == expected.tobytes()
    # Tiles 1 and 5 are two one-row mask slabs; without native bitfield
    # support they are read through h5py, not the native reader.
    assert len(calls) == (6 if native_bits else 4)
    assert result["staged_bytes"] == sum(p.stat().st_size for p in output.iterdir())
    assert not list(output.glob("*.partial"))
    assert not list(output.glob("*terrain*.bin"))  # TIFF pixels are never staged.


@pytest.mark.parametrize("selection", [[0, 0], [-1], [6], [True], [1.0], [], "0"])
def test_bad_tile_ids_refuse_before_numeric_reads(terrain, tmp_path, monkeypatch, selection):
    from ras_commander import fast_hdf
    monkeypatch.setattr(fast_hdf, "read_dataset", lambda *a, **k: pytest.fail("numeric read before validation"))
    with pytest.raises(ValueError, match="selected_tiles"):
        stage_boundary_terrain(*terrain, tmp_path / "out", selected_tiles=selection)


def test_budget_and_multiple_sources_refuse_before_numeric_reads(terrain, tmp_path, monkeypatch):
    from ras_commander import fast_hdf
    monkeypatch.setattr(fast_hdf, "read_dataset", lambda *a, **k: pytest.fail("numeric read before admission"))
    with pytest.raises(FimUnsupportedError, match="budget"):
        stage_boundary_terrain(*terrain, tmp_path / "out", max_staged_bytes=1)
    with h5py.File(terrain[0], "a") as handle:
        handle.create_group("Terrain/second").attrs["File"] = np.bytes_("second.tif")
    with pytest.raises(FimUnsupportedError, match="found 2.*second.tif"):
        stage_boundary_terrain(*terrain, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_existing_staged_inputs_are_preserved(terrain, tmp_path, monkeypatch):
    from ras_commander import fast_hdf
    monkeypatch.setattr(fast_hdf, "read_dataset", lambda *a, **k: pytest.fail("read before collision check"))
    output = tmp_path / "out"
    output.mkdir()
    retained = output / "boundary-mask.bin"
    retained.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        stage_boundary_terrain(*terrain, output)
    assert retained.read_bytes() == b"existing"
    assert len(list(output.iterdir())) == 1


@pytest.mark.parametrize("failure", ["engine", "index", "changed"])
def test_failure_cleans_all_owned_staging_files(terrain, tmp_path, monkeypatch, failure):
    from ras_commander import fast_hdf
    from ras_commander.fim import _boundary_inputs
    hdf, tif = terrain
    if failure == "index":
        with h5py.File(hdf, "a") as handle:
            handle["Terrain/Stitch TIN Triangles"][0, 0] = 3
    read = fast_hdf.read_dataset

    def injected(dataset, selection, **kwargs):
        if failure == "engine":
            raise fast_hdf.FastHdfError("Required native bitfield reader refused")
        result = read(dataset, selection, **kwargs)
        if failure == "changed":
            stat = tif.stat()
            os.utime(tif, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000))
        return result

    monkeypatch.setattr(fast_hdf, "read_dataset", injected)
    error, message = {"engine": (fast_hdf.FastHdfError, "refused"),
                      "index": (ValueError, "triangle index"),
                      "changed": (FimEngineError, "source changed")}[failure]
    output = tmp_path / "out"
    output.mkdir()
    (output / "unrelated.txt").write_text("retain")
    with pytest.raises(error, match=message):
        stage_boundary_terrain(hdf, tif, output)
    assert [p.name for p in output.iterdir()] == ["unrelated.txt"]


@pytest.mark.parametrize("mutation", ["crs", "file", "shape"])
def test_metadata_mismatch_refuses(terrain, tmp_path, monkeypatch, mutation):
    from ras_commander import fast_hdf
    monkeypatch.setattr(fast_hdf, "read_dataset", lambda *a, **k: pytest.fail("read mismatched metadata"))
    with h5py.File(terrain[0], "a") as handle:
        if mutation == "crs":
            handle.attrs["Projection"] = np.bytes_(rasterio.crs.CRS.from_epsg(32616).to_wkt())
        elif mutation == "file":
            handle["Terrain/source"].attrs["File"] = np.bytes_(terrain[0].name)
        else:
            del handle["Terrain/source/0/Perimeter"]
            handle["Terrain/source/0/Perimeter"] = np.zeros((5, 513), dtype="float32")
    with pytest.raises(FimUnsupportedError):
        stage_boundary_terrain(*terrain, tmp_path / "out")


def test_non_square_tiff_refuses_before_payload_reads(terrain, tmp_path, monkeypatch):
    from ras_commander import fast_hdf
    monkeypatch.setattr(fast_hdf, "read_dataset", lambda *a, **k: pytest.fail("read unsupported TIFF"))
    with rasterio.open(terrain[1], "r+") as raster:
        raster.transform = from_origin(300000, 4000000, 2, 3)
    with pytest.raises(FimUnsupportedError, match="square float32"):
        stage_boundary_terrain(*terrain, tmp_path / "out")


@pytest.mark.parametrize("kind", ["nonempty", "dataset", "soft", "dangling_soft",
    "external", "dangling_external", "soft_dataset"])
def test_modifications_refuse_before_numeric_reads(terrain, tmp_path, monkeypatch, kind):
    from ras_commander import fast_hdf
    monkeypatch.setattr(fast_hdf, "read_dataset", lambda *a, **k:
                        pytest.fail("Numeric read before modifications rejection"))
    with h5py.File(terrain[0], "a") as handle:
        if kind == "nonempty":
            group = handle.create_group("Modifications")
            child = group.create_group("Disabled edit")
            child.attrs["Enabled"] = False  # No inference from enabled flags.
        elif kind == "dataset":
            handle.create_dataset("Modifications", data=np.array([], dtype="uint8"))
        elif kind == "soft":
            handle.create_group("EmptyTarget")
            handle["Modifications"] = h5py.SoftLink("/EmptyTarget")
        elif kind == "dangling_soft":
            handle["Modifications"] = h5py.SoftLink("/MissingTarget")
        elif kind == "soft_dataset":
            handle["TargetDataset"] = np.array([], dtype="uint8")
            handle["Modifications"] = h5py.SoftLink("/TargetDataset")
        elif kind == "external":
            other = tmp_path / "external.hdf"
            with h5py.File(other, "w") as external:
                external.create_group("EmptyTarget")
            handle["Modifications"] = h5py.ExternalLink(other.name, "/EmptyTarget")
        else:
            handle["Modifications"] = h5py.ExternalLink("missing-external.hdf", "/Missing")
    with pytest.raises(FimUnsupportedError, match="/Modifications"):
        stage_boundary_terrain(*terrain, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("state", ["absent", "empty", "hard_alias"])
def test_modifications_absent_or_empty_group_provenance(terrain, tmp_path, monkeypatch, state):
    from ras_commander import fast_hdf
    if state != "absent":
        with h5py.File(terrain[0], "a") as handle:
            if state == "hard_alias":
                handle["Modifications"] = handle.create_group("EmptyAlias")
            else:
                handle.create_group("Modifications")
    # Isolate the metadata gate from native-extension availability. Other
    # tests qualify required-native reads; this stub is test-only payload IO.
    monkeypatch.setattr(fast_hdf, "read_dataset", lambda dataset, selection, **kwargs:
                        dataset[selection])
    result = stage_boundary_terrain(*terrain, tmp_path / "out", selected_tiles=[0])
    expected = "absent" if state == "absent" else "empty"
    assert result["modifications"] == dict(path="/Modifications", state=expected,
        link_type="absent" if state == "absent" else "hard")
    json.dumps(result, allow_nan=False)


def test_optional_real_public_terrain_metadata(tmp_path):
    """Set RAS_FIM_BOUNDARY_TERRAIN_HDF/TIFF to an immutable public fixture."""
    hdf, tif = os.getenv("RAS_FIM_BOUNDARY_TERRAIN_HDF"), os.getenv("RAS_FIM_BOUNDARY_TERRAIN_TIFF")
    if not hdf or not tif:
        pytest.skip("Set public terrain HDF/TIFF paths for native qualification")
    result = stage_boundary_terrain(hdf, tif, tmp_path, selected_tiles=[0])
    assert result["selected_tiles"] == [0]
    with h5py.File(hdf) as handle:
        for key in ["mask", "perimeter", "stitch_points", "stitch_triangles"]:
            descriptor = result[key]
            if descriptor is None:
                continue
            dataset = handle[descriptor["dataset"]]
            reference = dataset[:1] if key in {"mask", "perimeter"} else dataset[...]
            actual = np.fromfile(tmp_path / descriptor["path"], dtype=descriptor["dtype"]).reshape(descriptor["shape"])
            assert actual.tobytes() == reference.tobytes()


def _untag(tif):
    with rasterio.open(tif) as src:
        profile, data = src.profile, src.read()
    profile.pop("crs", None)
    tif.unlink()
    with rasterio.open(tif, "w", **profile) as dst:
        dst.write(data)
    with rasterio.open(tif) as src:
        assert not src.crs


def _payload_reads(monkeypatch):
    from ras_commander import fast_hdf
    monkeypatch.setattr(fast_hdf, "read_dataset", lambda dataset, selection, **kwargs: dataset[selection])


def test_untagged_tiff_takes_the_terrain_hdf_projection(terrain, tmp_path, monkeypatch):
    """A RAS Mapper source with no CRS tags (a CRS without an EPSG code) is staged
    in its terrain HDF's Projection, which becomes the request crs_wkt."""
    from pyproj import CRS
    hdf, tif = terrain
    esri = CRS.from_user_input("ESRI:102630")
    with h5py.File(hdf, "a") as handle:
        handle.attrs["Projection"] = esri.to_wkt().encode()
    _untag(tif)
    _payload_reads(monkeypatch)
    result = stage_boundary_terrain(hdf, tif, tmp_path / "out", selected_tiles=[0])
    assert CRS.from_wkt(result["crs_wkt"]).equals(esri)


def test_untagged_tiff_without_a_projection_is_refused(terrain, tmp_path, monkeypatch):
    from ras_commander import fast_hdf
    hdf, tif = terrain
    with h5py.File(hdf, "a") as handle:
        del handle.attrs["Projection"]
    _untag(tif)
    monkeypatch.setattr(fast_hdf, "read_dataset", lambda *a, **k: pytest.fail("read without a CRS"))
    with pytest.raises(FimUnsupportedError, match="stored projected CRS"):
        stage_boundary_terrain(hdf, tif, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_empty_stitch_arrays_are_no_stitch_tin(terrain, tmp_path, monkeypatch):
    """Single-source terrains store (0, 0) stitch arrays; they are staged as absent
    (previously refused as an unsupported shape), as effective terrain treats them."""
    hdf, tif = terrain
    with h5py.File(hdf, "a") as handle:
        for name in ("Points", "Triangles"):
            del handle[f"Terrain/Stitch TIN {name}"]
            handle.create_dataset(f"Terrain/Stitch TIN {name}", shape=(0, 0), dtype="<f4")
    _payload_reads(monkeypatch)
    result = stage_boundary_terrain(hdf, tif, tmp_path / "out", selected_tiles=[0])
    assert result["stitch_points"] is None and result["stitch_triangles"] is None


def test_one_empty_stitch_array_still_refuses(terrain, tmp_path, monkeypatch):
    from ras_commander import fast_hdf
    hdf, tif = terrain
    with h5py.File(hdf, "a") as handle:
        del handle["Terrain/Stitch TIN Triangles"]
        handle.create_dataset("Terrain/Stitch TIN Triangles", shape=(0, 0), dtype="<f4")
    monkeypatch.setattr(fast_hdf, "read_dataset", lambda *a, **k: pytest.fail("read malformed stitch"))
    with pytest.raises(FimUnsupportedError, match="shape or dtype"):
        stage_boundary_terrain(hdf, tif, tmp_path / "out")


def test_strict_links_refuse_soft_linked_empty_stitch_arrays(terrain, tmp_path, monkeypatch):
    """Strict link checks precede the empty-array skip: soft-linked empty stitch
    arrays are refused, never dereferenced and dropped."""
    from ras_commander.fim._boundary_inputs import _boundary_specs
    hdf, _ = terrain
    with h5py.File(hdf, "a") as handle:
        for name in ("Points", "Triangles"):
            del handle[f"Terrain/Stitch TIN {name}"]
            handle.create_dataset(f"Empty {name}", shape=(0, 0), dtype="<f4")
            handle[f"Terrain/Stitch TIN {name}"] = h5py.SoftLink(f"/Empty {name}")
    with h5py.File(hdf, "r") as handle:
        source = handle["Terrain/source"]
        with pytest.raises(FimUnsupportedError, match="Linked terrain boundary metadata"):
            _boundary_specs(handle, source, [0], 6, strict_links=True)
        # Without strict links the same arrays are no stitch TIN.
        specs = _boundary_specs(handle, source, [0], 6, strict_links=False)
        assert "stitch_points" not in specs and "stitch_triangles" not in specs


# ---------------------------------------------- stored-map boundary ground

def _perimeters(values, nodata=-9999.0):
    """RAS Mapper's level-0 tile perimeters: the next tile's first column and row."""
    height, width = values.shape
    rows, cols = -(-height // 256), -(-width // 256)
    out = np.full((rows * cols, 513), nodata, dtype="float32")
    for t in range(rows * cols):
        r0, c0 = (t // cols) * 256, (t % cols) * 256
        if c0 + 256 < width:
            n = min(256, height - r0)
            out[t, :n] = values[r0:r0 + n, c0 + 256]
        if r0 + 256 < height:
            n = min(257, width - c0)
            out[t, 256:256 + n] = values[r0 + 256, c0:c0 + n]
    return out


@pytest.fixture
def modified(tmp_path):
    """A single-source terrain with a modification layer and its stored-map
    effective terrain (a raised block across tile column 256 and row 256)."""
    from ras_commander.fim._effective_terrain import RECEIPT_SCHEMA
    crs = rasterio.crs.CRS.from_epsg(32615)
    rows, cols = np.mgrid[0:300, 0:520]
    values = (100 + 0.01 * rows + 0.02 * cols).astype("float32")
    values[290:, :10] = -9999.0
    profile = dict(driver="GTiff", width=520, height=300, count=1, dtype="float32", crs=crs,
                   transform=from_origin(300000, 4000000, 2, 2), nodata=-9999,
                   tiled=True, blockxsize=256, blockysize=256)
    tif, hdf = tmp_path / "source.tif", tmp_path / "terrain.hdf"
    with rasterio.open(tif, "w", **profile) as raster:
        raster.write(values, 1)
    with h5py.File(hdf, "w") as handle:
        handle.attrs["Projection"] = np.bytes_(crs.to_wkt())
        group = handle.create_group("Terrain/source")
        group.attrs["File"] = np.bytes_(tif.name)
        level = group.create_group("0")
        level["Mask"] = np.full((6, 65536), 255, dtype="uint8")
        level["Perimeter"] = _perimeters(values)
        handle.create_group("Modifications/Raise").attrs["Name"] = b"Raise"
    effective = values.copy()
    effective[250:262, 250:262] += 5.0
    out = tmp_path / "effective.tif"
    with rasterio.open(out, "w", **profile) as raster:
        raster.write(effective, 1)
    receipt = {"schema": RECEIPT_SCHEMA, "basis": "stored_map", "output": str(out),
               "terrain_hdf": str(hdf), "sources_in_priority_order": [tif.name]}
    (tmp_path / "effective.tif.json").write_text(json.dumps(receipt))
    return hdf, tif, out, values, effective


def _stub_reads(monkeypatch):
    from ras_commander import fast_hdf
    monkeypatch.setattr(fast_hdf, "read_dataset", lambda dataset, selection, **kwargs: dataset[selection])


def test_stored_map_ground_stages_modified_perimeters(modified, tmp_path, monkeypatch):
    from ras_commander.fim._boundary_inputs import stored_map_terrain
    hdf, tif, effective, values, changed = modified
    _stub_reads(monkeypatch)
    stored = stored_map_terrain(effective, hdf)
    assert stored["source"] == tif.resolve()
    result = stage_boundary_terrain(hdf, stored["source"], tmp_path / "out", effective_terrain=effective)
    staged = np.fromfile(tmp_path / "out" / result["perimeter"]["path"], dtype="<f4").reshape(6, 513)
    expected = _perimeters(changed)
    assert np.array_equal(staged, expected)
    # Tile 0's column 256 (rows 250..255) and row 256 (columns 250..256),
    # tile 1's row 256 (columns 256..261) and tile 3's column 256 (rows 256..261).
    assert result["modifications"]["state"] == "applied"
    assert result["modifications"]["perimeter_samples_replaced"] == 6 + 7 + 6 + 6
    assert result["modifications"]["basis"] == "stored_map"
    json.dumps(result, allow_nan=False)


def test_modifications_without_stored_map_ground_still_refuse(modified, tmp_path, monkeypatch):
    hdf, tif, *_ = modified
    _stub_reads(monkeypatch)
    with pytest.raises(FimUnsupportedError, match="stored-map effective terrain"):
        stage_boundary_terrain(hdf, tif, tmp_path / "out")


def test_stored_map_receipt_is_checked(modified, tmp_path):
    from ras_commander.fim._boundary_inputs import stored_map_terrain
    hdf, tif, effective, *_ = modified
    sidecar = tmp_path / "effective.tif.json"
    receipt = json.loads(sidecar.read_text())
    assert stored_map_terrain(tif, hdf) is None  # an original source has no receipt
    for change, message in ((dict(basis="export"), "stored-map effective terrain"),
                            (dict(terrain_hdf=str(tmp_path / "other.hdf")), "another output or terrain HDF"),
                            (dict(sources_in_priority_order=["a.tif", "b.tif"]), "single-source"),
                            (dict(sources_in_priority_order=["missing.tif"]), "missing")):
        sidecar.write_text(json.dumps(dict(receipt, **change)))
        with pytest.raises(FimUnsupportedError, match=message):
            stored_map_terrain(effective, hdf)
    sidecar.write_text(json.dumps(receipt))
    later = effective.stat().st_mtime_ns + 10**9
    os.utime(hdf, ns=(later, later))
    with pytest.raises(FimUnsupportedError, match="changed after"):
        stored_map_terrain(effective, hdf)


def test_stored_map_ground_must_keep_valid_cells_and_tile_history(modified, tmp_path, monkeypatch):
    hdf, tif, effective, values, changed = modified
    _stub_reads(monkeypatch)
    with rasterio.open(effective, "r+") as raster:
        data = raster.read(1)
        data[0, 0] = -9999.0
        raster.write(data, 1)
    with pytest.raises(FimUnsupportedError, match="valid cells"):
        stage_boundary_terrain(hdf, tif, tmp_path / "a", effective_terrain=effective)
    with rasterio.open(effective, "r+") as raster:
        raster.write(changed, 1)
    with h5py.File(hdf, "a") as handle:
        perimeter = handle["Terrain/source/0/Perimeter"]
        row = perimeter[0]
        row[10] += 1.0
        perimeter[0] = row
    with pytest.raises(FimUnsupportedError, match="perimeters differ"):
        stage_boundary_terrain(hdf, tif, tmp_path / "b", effective_terrain=effective)
