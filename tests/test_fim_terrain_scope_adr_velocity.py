"""Top-priority source terrain, whole-simulation products and sloping velocity.

Unit tests use synthetic terrain HDFs and a simulated engine method record.
Real-model qualification is opt-in: set RAS_COMMANDER_FIM_SCOPE_CASE to a
JSON document with ``hdf``, ``terrain_hdf``, ``engine``, optional ``terrain``
(the priority-1 TIFF or its canonical copy) and ``references``
(``depth``/``wse``/``velocity`` for Max and ``arrival_time``/``percent_inundated``
native stored maps at ``threshold``). No HEC-RAS execution occurs here.
"""

import json
import os
from pathlib import Path

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")
rasterio = pytest.importorskip("rasterio")

from ras_commander.fim import RasFim, _engine, _terrain_scope, _velocity, _whole_simulation  # noqa: E402
from ras_commander.fim.errors import FimUnsupportedError  # noqa: E402


def _tif(path, width=300, height=260, epsg=26915, seed=0):
    from rasterio.transform import from_origin

    data = np.random.default_rng(seed).random((height, width), dtype=np.float32) * 10
    with rasterio.open(
        path, "w", driver="GTiff", width=width, height=height, count=1, dtype="float32",
        crs=f"EPSG:{epsg}", transform=from_origin(500000, 4000000, 2.0, 2.0), nodata=-9999,
        tiled=True, blockxsize=256, blockysize=256,
    ) as dst:
        dst.write(data, 1)
    return path


def _terrain(root, names, priorities=None, vrt=None, modifications=False, mask_tiles=None):
    """Synthetic terrain HDF ``root/T.hdf`` with sources ``T.<name>.tif``."""
    root = Path(root)
    hdf = root / "T.hdf"
    with h5py.File(hdf, "w") as f:
        terrain = f.create_group("Terrain")
        for i, name in enumerate(names):
            tif = _tif(root / f"T.{name}.tif", seed=i)
            group = terrain.create_group(f"T.{name}")
            group.attrs["File"] = np.bytes_(tif.name)
            if priorities is not None and priorities[i] is not None:
                group.attrs["Priority"] = np.int32(priorities[i])
            tiles = mask_tiles if mask_tiles is not None else 4
            mask = np.zeros((tiles, 65536), dtype=np.uint8)
            mask[:, ::3] = 1
            group.create_group("0").create_dataset("Mask", data=mask)
        if modifications:
            f.create_group("Modifications").create_group("Channel")
    if vrt is not None:
        sources = "".join(
            f'<ComplexSource><SourceFilename relativeToVRT="1">T.{name}.tif</SourceFilename></ComplexSource>'
            for name in vrt
        )
        (root / "T.vrt").write_text(
            f'<VRTDataset rasterXSize="1" rasterYSize="1"><VRTRasterBand>{sources}</VRTRasterBand></VRTDataset>',
            encoding="utf-8",
        )
    return hdf


def test_priority_attribute_selects_priority_zero_and_agrees_with_vrt(tmp_path):
    hdf = _terrain(tmp_path, ["coarse", "channel"], priorities=[1, 0], vrt=["channel", "coarse"])
    info = RasFim.top_priority_terrain_source(hdf)
    assert info["tif"] == (tmp_path / "T.channel.tif").resolve()
    assert info["source_count"] == 2 and info["modified"] is False
    assert info["priority_basis"] == "hdf_priority+vrt_order"
    assert info["sources"] == ["T.channel.tif", "T.coarse.tif"]
    assert info["mask_shape"] == [4, 65536]


def test_legacy_terrain_uses_vrt_order(tmp_path):
    hdf = _terrain(tmp_path, ["a_first_by_name", "z_priority_one"], vrt=["z_priority_one", "a_first_by_name"])
    info = RasFim.top_priority_terrain_source(hdf)
    assert info["source"] == "T.z_priority_one" and info["priority_basis"] == "vrt_order"


def test_single_source_without_priority_or_vrt(tmp_path):
    info = RasFim.top_priority_terrain_source(_terrain(tmp_path, ["only"]))
    assert info["priority_basis"] == "single_source" and info["source_count"] == 1


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (dict(names=["a", "b"]), "no terrain VRT"),
        (dict(names=["a", "b"], priorities=[0, None], vrt=["a", "b"]), "only some"),
        (dict(names=["a", "b"], priorities=[0, 0], vrt=["a", "b"]), "not 0..1"),
        (dict(names=["a", "b"], priorities=[0, 1], vrt=["b", "a"]), "disagree"),
        (dict(names=["a", "b"], vrt=["a"]), "differ from"),
        (dict(names=["a"], mask_tiles=0), "level-0 Mask"),
    ],
)
def test_unprovable_priority_is_refused(tmp_path, kwargs, message):
    names = kwargs.pop("names")
    if kwargs.get("mask_tiles") == 0:
        hdf = _terrain(tmp_path, names)
        with h5py.File(hdf, "a") as f:
            del f[f"Terrain/T.{names[0]}/0/Mask"]
    else:
        hdf = _terrain(tmp_path, names, **kwargs)
    with pytest.raises(FimUnsupportedError, match=message):
        RasFim.top_priority_terrain_source(hdf)


def test_modified_terrain_is_reported_and_refused_for_mapping(tmp_path):
    hdf = _terrain(tmp_path, ["a"], priorities=[0], modifications=True)
    info = RasFim.top_priority_terrain_source(hdf)
    assert info["modified"] is True and info["modifications"] == ["hdf:Channel"]
    with pytest.raises(FimUnsupportedError, match="modifications"):
        _terrain_scope.resolve(hdf, info["tif"])


def test_rasmap_modification_layers_are_reported(tmp_path):
    hdf = _terrain(tmp_path, ["a"], priorities=[0])
    rasmap = tmp_path / "m.rasmap"
    rasmap.write_text(
        '<RASMapper><Terrains><Layer Name="T" Type="TerrainLayer" Filename=".\\T.hdf">'
        '<Layer Name="Mods" Type="ElevationModificationGroup"><Layer Name="Levee" Type="X"/></Layer>'
        "</Layer></Terrains></RASMapper>",
        encoding="utf-8",
    )
    info = RasFim.top_priority_terrain_source(hdf, rasmap_path=rasmap)
    assert info["modified"] and info["modifications"] == ["rasmap:Levee"] and info["rasmap_checked"]
    other = tmp_path / "other.rasmap"
    other.write_text("<RASMapper><Terrains/></RASMapper>", encoding="utf-8")
    with pytest.raises(FimUnsupportedError, match="does not register"):
        RasFim.top_priority_terrain_source(hdf, rasmap_path=other)


def test_resolve_requires_the_priority_one_tiff_and_stages_its_mask(tmp_path):
    hdf = _terrain(tmp_path, ["coarse", "channel"], priorities=[1, 0], vrt=["channel", "coarse"])
    with pytest.raises(FimUnsupportedError, match="priority-1 source TIFF"):
        _terrain_scope.resolve(hdf, tmp_path / "T.coarse.tif")
    info = _terrain_scope.resolve(hdf, tmp_path / "T.channel.tif")
    field = _terrain_scope.stage(info, tmp_path)
    assert field == {
        "kind": "top_priority_source",
        "source_count": 2,
        "mask": {"path": "terrain_scope_mask.u1", "dtype": "|u1", "shape": [4, 65536]},
    }
    with h5py.File(hdf, "r") as f:
        expected = f["Terrain/T.channel/0/Mask"][:].tobytes()
    assert (tmp_path / "terrain_scope_mask.u1").read_bytes() == expected
    assert _terrain_scope.describe(info)["canonical_copy"] is None


def test_resolve_refuses_mask_tile_count_mismatch(tmp_path):
    hdf = _terrain(tmp_path, ["a"], priorities=[0], mask_tiles=3)
    with pytest.raises(FimUnsupportedError, match="256 x 256"):
        _terrain_scope.resolve(hdf, tmp_path / "T.a.tif")


def test_canonical_copy_is_accepted_only_while_pixels_match(tmp_path):
    hdf = _terrain(tmp_path, ["a"], priorities=[0])
    canonical = RasFim.canonicalize_terrain_crs(tmp_path / "T.a.tif", tmp_path / "canon" / "a.tif")
    info = _terrain_scope.resolve(hdf, canonical)
    assert info["canonical_copy"]["path"] == str(Path(canonical).resolve())
    with rasterio.open(tmp_path / "T.a.tif", "r+") as src:
        data = src.read(1)
        data[0, 0] += 1
        src.write(data, 1)
    with pytest.raises(FimUnsupportedError, match="no longer matches"):
        _terrain_scope.resolve(hdf, canonical)
    stray = _tif(tmp_path / "stray.tif")
    with pytest.raises(FimUnsupportedError, match="canonicalize_terrain_crs copy"):
        _terrain_scope.resolve(hdf, stray)


def test_polyline_lengths_replace_curved_faces_only():
    normals = np.array([[1, 0, 9.0], [0, 1, 7.0]])
    facepoints = np.array([[0, 0], [3, 0], [0, 0], [0, 4]], dtype=float)
    face_facepoints = np.array([[0, 1], [2, 3]])
    info = np.array([[0, 0], [0, 2]])
    values = np.array([[0, 1], [0, 3]], dtype=float)
    lengths = _velocity.polyline_lengths(normals, facepoints, face_facepoints, info, values)
    assert lengths.tolist() == [9.0, 4.0]
    with pytest.raises(ValueError, match="exceeds"):
        _velocity.polyline_lengths(normals, facepoints, face_facepoints, np.array([[0, 0], [1, 5]]), values)


def test_engine_refusals_are_unsupported_errors(tmp_path):
    assert _engine.engine_refusal(None, "") is None
    error = _engine.engine_refusal("unsupported: 28 mapped pixels need terrain")
    assert isinstance(error, FimUnsupportedError) and "28 mapped pixels" in str(error)
    out = tmp_path / "out"
    out.mkdir()
    (out / "report.json").write_text(json.dumps({"status": "aborted", "error": "unsupported: wet foreign"}))
    assert isinstance(_engine.read_refusal(out), _engine.EngineRefusal)
    assert _engine.read_refusal(tmp_path / "missing", "io error: disk") is None


@pytest.mark.parametrize(
    "kwargs, error",
    [
        (dict(products=("duration",), threshold=0.5), FimUnsupportedError),
        (dict(products=("arrival_time", "arrival_time"), threshold=0.5), ValueError),
        (dict(products=("velocity",), threshold=0.5), ValueError),
        (dict(products="arrival_time", threshold=0.5), ValueError),
        (dict(threshold=-1.0), ValueError),
        (dict(threshold=float("nan")), ValueError),
        (dict(threshold=True), ValueError),
        (dict(threshold=0.5, allow_unqualified=1), ValueError),
        (dict(threshold=0.5, threads=0), ValueError),
        (dict(threshold=0.5, timeout=0), ValueError),
    ],
)
def test_whole_simulation_rejects_options_before_inputs_are_read(tmp_path, kwargs, error):
    with pytest.raises(error):
        RasFim.map_whole_simulation("absent.hdf", "absent.tif", tmp_path / "out", **kwargs)
    assert not (tmp_path / "out").exists()


@pytest.fixture
def model_files(tmp_path, monkeypatch):
    hdf = tmp_path / "m.p01.hdf"
    hdf.write_bytes(b"")
    tif = _tif(tmp_path / "t.tif")
    scope = {"storage_areas": 0}
    monkeypatch.setattr(RasFim, "validate_2d_model", staticmethod(lambda *a, **k: dict(scope)))
    monkeypatch.setattr(_engine, "find_engine", lambda path=None: Path(tmp_path / "engine.exe"))
    return hdf, tif, scope


def test_whole_simulation_refuses_storage_areas_and_missing_capability(model_files, tmp_path, monkeypatch):
    hdf, tif, scope = model_files
    scope["storage_areas"] = 1
    with pytest.raises(FimUnsupportedError, match="storage areas"):
        RasFim.map_whole_simulation(hdf, tif, tmp_path / "a", threshold=0.5)
    scope["storage_areas"] = 0
    monkeypatch.setattr(_engine, "engine_method", lambda engine: {"horizontal": {}})
    with pytest.raises(FimUnsupportedError, match="native-whole-simulation-horizontal/1"):
        RasFim.map_whole_simulation(hdf, tif, tmp_path / "b", threshold=0.5)
    monkeypatch.setattr(_engine, "engine_method", lambda engine: {
        "whole_simulation": {"method_id": _whole_simulation.METHOD_ID},
        "horizontal": {"method_id": "horizontal-cell-constant/1"},
    })
    with pytest.raises(FimUnsupportedError, match="horizontal-cell-constant/2"):
        RasFim.map_whole_simulation(hdf, tif, tmp_path / "c", threshold=0.5)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (dict(velocity=True, render_mode="slopingPretty"), "plain sloping"),
        (dict(velocity=True, template_raster="x.tif"), "template_raster"),
        (dict(terrain_hdf="T.hdf", render_mode="slopingPretty"), "plain sloping"),
    ],
)
def test_sloping_scope_and_velocity_refusals_precede_reads(model_files, tmp_path, kwargs, message):
    hdf, tif, _ = model_files
    with pytest.raises(FimUnsupportedError, match=message):
        RasFim.map_sloping_profiles(hdf, tif, tmp_path / "out", **kwargs)
    assert not (tmp_path / "out").exists()


def test_sloping_velocity_rejects_supplied_profiles_and_non_bool(model_files, tmp_path):
    import pandas as pd

    hdf, tif, _ = model_files
    with pytest.raises(FimUnsupportedError, match="face velocities"):
        RasFim.map_sloping_profiles(hdf, tif, tmp_path / "a", velocity=True,
                                    wsel_profiles=pd.DataFrame())
    with pytest.raises(ValueError, match="boolean"):
        RasFim.map_sloping_profiles(hdf, tif, tmp_path / "b", velocity=1)


def test_sloping_capability_and_storage_area_refusals(model_files, tmp_path, monkeypatch):
    hdf, tif, scope = model_files
    method = {"sloping": {"method_id": "rasmapper-plain-sloping/1", "stream_outputs": True}}
    monkeypatch.setattr(_engine, "engine_method", lambda engine: method)
    with pytest.raises(FimUnsupportedError, match="rasmapper-sloping-velocity/0"):
        RasFim.map_sloping_profiles(hdf, tif, tmp_path / "a", velocity=True)
    (tmp_path / "terrain").mkdir()
    terrain_hdf = _terrain(tmp_path / "terrain", ["a"], priorities=[0])
    source = tmp_path / "terrain" / "T.a.tif"
    with pytest.raises(FimUnsupportedError, match="top-priority-source-footprint/1"):
        RasFim.map_sloping_profiles(hdf, source, tmp_path / "b", terrain_hdf=terrain_hdf)
    scope["storage_areas"] = 2
    with pytest.raises(FimUnsupportedError, match="storage areas"):
        RasFim.map_sloping_profiles(hdf, source, tmp_path / "c", terrain_hdf=terrain_hdf)
    assert not any((tmp_path / name).exists() for name in ("a", "b", "c"))


def test_horizontal_terrain_hdf_requires_rust_backend(tmp_path):
    import geopandas as gpd
    from shapely.geometry import box

    hdf = _terrain(tmp_path, ["a"], priorities=[0])
    cells = gpd.GeoDataFrame({"cell_idx": [0], "wsel_1": [1.0]}, geometry=[box(0, 0, 1, 1)], crs="EPSG:26915")
    with pytest.raises(FimUnsupportedError, match="Rust backend"):
        RasFim.map_horizontal_profiles(cells, tmp_path / "T.a.tif", tmp_path / "out",
                                       backend="numpy", terrain_hdf=hdf)


def test_manifest_schemas_match_columns():
    from ras_commander.schemas import DATAFRAME_SCHEMAS

    declared = [c["name"] for c in DATAFRAME_SCHEMAS["fim_whole_simulation_manifest"]["columns"]]
    assert declared == list(_whole_simulation.MANIFEST_COLUMNS)
    assert "velocity_tif" in RasFim.MANIFEST_COLUMNS


def test_public_signatures_expose_new_controls():
    import inspect

    sloping = inspect.signature(RasFim.map_sloping_profiles).parameters
    assert sloping["terrain_hdf"].default is None and sloping["velocity"].default is False
    assert inspect.signature(RasFim.map_horizontal_profiles).parameters["terrain_hdf"].default is None
    whole = inspect.signature(RasFim.map_whole_simulation).parameters
    assert whole["products"].default == ("arrival_time", "percent_inundated")
    assert whole["threshold"].default is inspect.Parameter.empty
    assert whole["allow_unqualified"].default is False
    for name in ("top_priority_terrain_source", "map_whole_simulation"):
        assert isinstance(RasFim.__dict__[name], staticmethod)


# ---------------------------------------------------------------------------
# Opt-in real-model qualification against native stored maps.
# ---------------------------------------------------------------------------

@pytest.fixture
def scope_case():
    filename = os.environ.get("RAS_COMMANDER_FIM_SCOPE_CASE")
    if not filename:
        pytest.skip("set RAS_COMMANDER_FIM_SCOPE_CASE for real native qualification")
    return json.loads(Path(filename).read_text(encoding="utf-8"))


def _bits(candidate, reference):
    from rasterio.windows import from_bounds

    with rasterio.open(candidate) as a, rasterio.open(reference) as b:
        window = from_bounds(*a.bounds, transform=b.transform).round_offsets().round_lengths()
        native = b.read(1, window=window, boundless=True, fill_value=b.nodata)
        ours = a.read(1)
        native_valid = (native != b.nodata) & np.isfinite(native)
        outside = int((b.read(1) != b.nodata).sum() - native_valid.sum())
    valid = np.isfinite(ours)
    both = valid & native_valid
    return (
        int(np.count_nonzero(valid ^ native_valid)) + outside,
        int(np.count_nonzero(ours[both].view(np.uint32) != native[both].astype(np.float32).view(np.uint32))),
    )


def test_real_sloping_on_priority_one_source_matches_native(scope_case, tmp_path):
    case = scope_case
    terrain = case.get("terrain") or RasFim.top_priority_terrain_source(case["terrain_hdf"])["tif"]
    result = RasFim.map_sloping_profiles(
        case["hdf"], terrain, tmp_path / "maps", terrain_hdf=case["terrain_hdf"],
        velocity="velocity" in case["references"], engine_path=case["engine"], threads=4,
        max_working_mib=case.get("max_working_mib", 4096),
    )
    row = result.iloc[0]
    assert result.attrs["terrain_scope"]["method_id"] == _terrain_scope.METHOD_ID
    assert _bits(row.depth_tif, case["references"]["depth"]) == (0, 0)
    assert _bits(row.wse_tif, case["references"]["wse"]) == (0, 0)
    if "velocity" in case["references"]:
        masks, bits = _bits(row.velocity_tif, case["references"]["velocity"])
        assert masks <= case.get("velocity_mask_tolerance", 0)
        assert bits <= case.get("velocity_bit_tolerance", 0)


def test_real_whole_simulation_matches_native(scope_case, tmp_path):
    case = scope_case
    terrain = case.get("whole_simulation_terrain") or case.get("terrain")
    kwargs = {} if case.get("whole_simulation_terrain") else {"terrain_hdf": case["terrain_hdf"]}
    result = RasFim.map_whole_simulation(
        case["hdf"], terrain, tmp_path / "adr", threshold=case["threshold"],
        engine_path=case["engine"], threads=4, max_working_mib=case.get("max_working_mib", 4096),
        **kwargs,
    )
    for row in result.itertuples():
        assert row.status == "complete"
        assert _bits(row.tif, case["references"][row.product]) == (0, 0)
