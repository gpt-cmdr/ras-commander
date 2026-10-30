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
