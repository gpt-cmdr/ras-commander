"""Real-model raw sloping qualification; native maps must be supplied explicitly.

Set RAS_COMMANDER_SLOPING_CASE to a local JSON document with hdf, terrain,
engine, profiles and references (profile -> depth/wse paths). No HEC-RAS
execution or dataset download occurs in these tests.
"""

import json
import os
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture
def sloping_case():
    filename = os.environ.get("RAS_COMMANDER_SLOPING_CASE")
    if not filename:
        pytest.skip(
            "set RAS_COMMANDER_SLOPING_CASE for real native sloping qualification"
        )
    document = json.loads(Path(filename).read_text(encoding="utf-8"))
    for key in ("hdf", "terrain", "engine", "profiles", "references"):
        assert key in document
    return document


@pytest.mark.parametrize("threads", [1, 4])
def test_real_sloping_raw_masks_and_float_bits(sloping_case, threads, tmp_path):
    import rasterio
    from rasterio.features import rasterize
    from rasterio.windows import from_bounds
    from ras_commander import HdfMesh, RasFim

    case = sloping_case
    result = RasFim.map_sloping_profiles(
        case["hdf"],
        case["terrain"],
        tmp_path / "maps",
        profiles=case["profiles"],
        engine_path=case["engine"],
        threads=threads,
        max_working_mib=case.get("max_working_mib", 4096),
        write_floodplain=False,
    )
    cells = HdfMesh.get_mesh_cell_polygons(case["hdf"], strict=True)
    assert list(result.profile) == list(case["profiles"])
    assert result.attrs["performance"]["engine_report"]["status"] == "complete"
    assert result.attrs["performance"]["profile_views_prepared"] == (
        len(HdfMesh.get_mesh_area_names(case["hdf"]))
        if any(isinstance(v, int) for v in case["profiles"].values())
        else 0
    )
    for product in result.itertuples():
        for name, filename in (("depth", product.depth_tif), ("wse", product.wse_tif)):
            with rasterio.open(filename) as candidate:
                actual = candidate.read(1, masked=True)
                footprint = (
                    rasterize(
                        ((g, 1) for g in cells.geometry),
                        out_shape=candidate.shape,
                        transform=candidate.transform,
                        fill=0,
                        dtype="uint8",
                    )
                    > 0
                )
                with rasterio.open(
                    case["references"][product.profile][name]
                ) as reference:
                    assert candidate.crs == reference.crs
                    assert candidate.dtypes == reference.dtypes == ("float32",)
                    window = from_bounds(*candidate.bounds, reference.transform)
                    assert abs(window.col_off - round(window.col_off)) < 1e-6
                    assert abs(window.row_off - round(window.row_off)) < 1e-6
                    window = window.round_offsets().round_lengths()
                    assert np.allclose(
                        tuple(reference.window_transform(window)),
                        tuple(candidate.transform),
                        rtol=0,
                        atol=1e-8,
                    )
                    expected = reference.read(
                        1, window=window, boundless=True, masked=True
                    )
            actual_valid = ~np.ma.getmaskarray(actual) & np.isfinite(actual.data)
            expected_valid = ~np.ma.getmaskarray(expected) & np.isfinite(expected.data)
            assert not actual_valid[~footprint].any()
            np.testing.assert_array_equal(
                actual_valid[footprint], expected_valid[footprint]
            )
            common = actual_valid & footprint
            assert common.any(), (
                "qualification requires nonempty valid reference coverage"
            )
            np.testing.assert_array_equal(
                actual.data[common].view("u4"), expected.data[common].view("u4")
            )


def test_invalid_timestep_publishes_no_products(sloping_case, tmp_path):
    from ras_commander import RasFim

    case = sloping_case
    output = tmp_path / "failed"
    with pytest.raises((IndexError, ValueError)):
        RasFim.map_sloping_profiles(
            case["hdf"],
            case["terrain"],
            output,
            profiles={"invalid": 2**60},
            engine_path=case["engine"],
            max_working_mib=case.get("max_working_mib", 4096),
        )
    assert not list(output.glob("*.tif"))
    manifest = json.loads((output / "fim_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "aborted"
    assert all(p["status"] == "failed" for p in manifest["profiles"])


def test_timestep_mapping_does_not_require_max_summary(sloping_case, tmp_path):
    import shutil
    import h5py
    from ras_commander import HdfMesh, HdfResultsMesh, RasFim
    from scripts.benchmarks.fim_sloping_compare import compare_raw

    case = sloping_case
    choices = [
        (name, index)
        for name, index in case["profiles"].items()
        if isinstance(index, int)
    ]
    if not choices:
        pytest.skip("case contains no timestep reference")
    name, index = choices[0]
    copied = tmp_path / "timesteps.p02.hdf"
    shutil.copy2(case["hdf"], copied)
    meshes = HdfMesh.get_mesh_area_names(copied)
    # Only the disposable test copy is altered. The recorded source/reference
    # remain immutable; removing an unused summary must not affect timestep maps.
    with h5py.File(copied, "r+") as source:
        for mesh in meshes:
            dataset = HdfResultsMesh.get_mesh_summary_output_group(
                source, mesh, "Maximum Water Surface"
            )
            del source[dataset.name]
    result = RasFim.map_sloping_profiles(
        copied,
        case["terrain"],
        tmp_path / "time-only",
        profiles={name: index},
        engine_path=case["engine"],
        threads=4,
        max_working_mib=case.get("max_working_mib", 4096),
    )
    cells = HdfMesh.get_mesh_cell_polygons(copied, strict=True)
    for band, path in (
        ("depth", result.iloc[0].depth_tif),
        ("wse", result.iloc[0].wse_tif),
    ):
        metrics = compare_raw(path, case["references"][name][band], cells)
        assert metrics["common"] > 0
        assert all(
            metrics[key] == 0
            for key in ("extra", "missing", "different", "outside_footprint")
        )


@pytest.mark.parametrize("fault", ["header", "report"])
def test_invalid_engine_protocol_aborts_delivery(
    sloping_case, tmp_path, monkeypatch, fault
):
    import subprocess
    import sys
    from ras_commander import RasFim
    from ras_commander.fim import _sloping
    from ras_commander.fim.errors import FimEngineError

    original = subprocess.Popen
    program = """
import json,pathlib,struct,sys
request=json.loads(pathlib.Path(sys.argv[1]).read_text())
if sys.argv[3]=='header':
    print('invalid json',flush=True)
else:
    pixels=request['window'][2]*request['window'][3]
    for profile in request['profiles']:
        print(json.dumps(dict(id=profile['id'],status='complete',pixels=pixels)),flush=True)
        sys.stdout.buffer.write(struct.pack('<f',float('nan'))*pixels*2)
        sys.stdout.buffer.flush()
    output=pathlib.Path(sys.argv[2]);output.mkdir()
    (output/'report.json').write_text('invalid json')
"""

    def launch(arguments, *args, **kwargs):
        if len(arguments) > 1 and arguments[1] == "sloping":
            arguments = [
                sys.executable,
                "-c",
                program,
                arguments[2],
                arguments[3],
                fault,
            ]
        return original(arguments, *args, **kwargs)

    monkeypatch.setattr(_sloping.subprocess, "Popen", launch)
    case = sloping_case
    output = tmp_path / fault
    with pytest.raises(
        FimEngineError,
        match="Invalid sloping stream header JSON|Missing or invalid sloping engine report",
    ):
        RasFim.map_sloping_profiles(
            case["hdf"],
            case["terrain"],
            output,
            profiles={"Max": "Max"},
            engine_path=case["engine"],
            threads=4,
            max_working_mib=case.get("max_working_mib", 4096),
        )
    assert not list(output.glob("*.tif"))
    manifest = json.loads((output / "fim_manifest.json").read_text())
    assert manifest["status"] == "aborted"
    assert all(p["status"] == "failed" for p in manifest["profiles"])


def test_template_grid_preserves_native_pixels_and_layout(sloping_case, tmp_path):
    import rasterio
    from ras_commander import HdfMesh, RasFim
    from scripts.benchmarks.fim_sloping_compare import compare_raw

    case = sloping_case
    name = next(iter(case["profiles"]))
    reference = case["references"][name]
    template = tmp_path / "grid-only.tif"
    with rasterio.open(reference["depth"]) as source:
        profile = source.profile.copy()
    # No native pixel data are copied into this template or the mapper.
    with rasterio.open(template, "w", **profile):
        pass
    result = RasFim.map_sloping_profiles(
        case["hdf"],
        case["terrain"],
        tmp_path / "native-grid",
        profiles={name: case["profiles"][name]},
        template_raster=template,
        engine_path=case["engine"],
        threads=4,
        max_working_mib=case.get("max_working_mib", 4096),
    )
    cells = HdfMesh.get_mesh_cell_polygons(case["hdf"], strict=True)
    for band, path in [
        ("depth", result.iloc[0].depth_tif),
        ("wse", result.iloc[0].wse_tif),
    ]:
        with rasterio.open(path) as actual, rasterio.open(reference[band]) as expected:
            assert actual.shape == expected.shape
            assert actual.transform == expected.transform
            assert actual.nodata == expected.nodata
            assert actual.compression == expected.compression
            assert actual.block_shapes == expected.block_shapes
        metrics = compare_raw(
            path,
            reference[band],
            cells,
            full_grid=result.attrs["model_scope"]["storage_areas"] == 0,
        )
        assert metrics["common"] > 0
        assert all(
            metrics[k] == 0
            for k in ("extra", "missing", "different", "outside_footprint")
        )
    assert result.iloc[0].col_off == result.iloc[0].row_off == 0


def test_template_nodata_collision_is_not_silently_filtered(sloping_case, tmp_path):
    import rasterio
    from ras_commander import RasFim
    from ras_commander.fim.errors import FimUnsupportedError

    case = sloping_case
    name = next(iter(case["profiles"]))
    reference = case["references"][name]
    template = tmp_path / "collision.tif"
    baseline = RasFim.map_sloping_profiles(
        case["hdf"],
        case["terrain"],
        tmp_path / "collision-baseline",
        profiles={name: case["profiles"][name]},
        engine_path=case["engine"],
        threads=4,
        max_working_mib=case.get("max_working_mib", 4096),
    )
    with rasterio.open(baseline.iloc[0].wse_tif) as source:
        for _, window in source.block_windows(1):
            data = source.read(1, window=window, masked=True).compressed()
            if len(data):
                value = float(data[0])
                break
        else:
            pytest.fail("collision fixture requires finite mapped WSE")
    with rasterio.open(reference["wse"]) as source:
        profile = source.profile.copy()
    profile["nodata"] = value
    with rasterio.open(template, "w", **profile):
        pass
    output = tmp_path / "collision-output"
    with pytest.raises(FimUnsupportedError, match="nodata collides"):
        RasFim.map_sloping_profiles(
            case["hdf"],
            case["terrain"],
            output,
            profiles={name: case["profiles"][name]},
            template_raster=template,
            engine_path=case["engine"],
            threads=4,
            max_working_mib=case.get("max_working_mib", 4096),
        )
    assert not list(output.glob("*.tif"))
    assert json.loads((output / "fim_manifest.json").read_text())["status"] == "aborted"


@pytest.mark.parametrize("threads", [1, 4])
def test_real_additional_sloping_options(threads, tmp_path):
    """External case list covers native option combinations and changing profiles."""
    from ras_commander import RasFim, HdfMesh
    from scripts.benchmarks.fim_sloping_compare import compare_raw

    filename = os.environ.get("RAS_COMMANDER_SLOPING_OPTIONS_CASES")
    if not filename:
        pytest.skip(
            "set RAS_COMMANDER_SLOPING_OPTIONS_CASES for native option qualification"
        )
    cases = json.loads(Path(filename).read_text(encoding="utf-8"))
    assert cases
    for index, case in enumerate(cases):
        if case.get("use_depth_weighted_faces", False):
            continue
        options = {
            key: case[key]
            for key in (
                "render_mode",
                "reduce_shallow_to_horizontal",
            )
        }
        first = next(iter(case["profiles"]))
        manifest = RasFim.map_sloping_profiles(
            case["hdf"],
            case["terrain"],
            tmp_path / str(index),
            profiles=case["profiles"],
            engine_path=case["engine"],
            threads=threads,
            writer_threads=threads,
            template_raster=case["references"][first]["depth"],
            max_working_mib=case.get("max_working_mib", 4096),
            **options,
        )
        method = manifest.attrs["performance"]["engine_report"]["method"]
        assert method["method_id"] == "rasmapper-sloping-with-faces/1"
        assert (
            method["options"]["UseDepthWeightedFaces"]
            is False
        )
        assert method["options"]["ShallowBehaviorMode"] == (
            "ReduceToHorizontal" if options["reduce_shallow_to_horizontal"] else "None"
        )
        cells = HdfMesh.get_mesh_cell_polygons(case["hdf"], strict=True)
        for product in manifest.itertuples():
            for band, path in (("depth", product.depth_tif), ("wse", product.wse_tif)):
                metrics = compare_raw(
                    path,
                    case["references"][product.profile][band],
                    cells,
                    full_grid=True,
                )
                assert metrics["common"] > 0
                assert all(
                    metrics[key] == 0
                    for key in ("extra", "missing", "different", "outside_footprint")
                ), (index, product.profile, band, metrics)


@pytest.mark.parametrize(
    "options",
    [
        dict(render_mode="unknown"),
        dict(reduce_shallow_to_horizontal=True),
        dict(writer_threads=0),
        dict(max_inflight_profiles=0),
        dict(max_inflight_profiles=True),
        dict(max_inflight_profiles=65),
        dict(max_inflight_profiles=1.5),
        dict(writer_threads=True),
        dict(writer_threads=65),
        dict(writer_threads=1.5),
    ],
)
def test_sloping_options_rejected_before_inputs_are_read(options, tmp_path):
    from ras_commander import RasFim

    with pytest.raises(ValueError):
        RasFim.map_sloping_profiles(
            "absent.hdf", "absent.tif", tmp_path / "out", **options
        )
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("mask_kind", ["bbox", "polygon"])
def test_real_enhanced_catalog_mask_preserves_native_pixels(tmp_path, mask_kind):
    from ras_commander import RasFim, HdfMesh
    from scripts.benchmarks.fim_sloping_compare import compare_raw
    from shapely.geometry import Polygon, box

    filename = os.environ.get("RAS_COMMANDER_SLOPING_OPTIONS_CASES")
    if not filename:
        pytest.skip(
            "set RAS_COMMANDER_SLOPING_OPTIONS_CASES for enhanced AOI qualification"
        )
    cases = json.loads(Path(filename).read_text(encoding="utf-8"))
    case = next(
        c
        for c in cases
        if c["reduce_shallow_to_horizontal"]
        and not c["use_depth_weighted_faces"]
        and any(isinstance(v, int) for v in c["profiles"].values())
    )
    cells = HdfMesh.get_mesh_cell_polygons(case["hdf"], strict=True)
    left, bottom, right, top = cells.total_bounds
    if mask_kind == "bbox":
        dx, dy = right - left, top - bottom
        bounds = (left + dx * 0.2, bottom + dy * 0.2,
                  right - dx * 0.2, top - dy * 0.2)
        polygon = box(*bounds)
        mask_options = {"bbox": bounds}
    else:
        polygon = Polygon([(left, bottom), (left, top), (right, bottom)])
        mask_options = {"polygon": polygon}
    result = RasFim.map_sloping_profiles(
        case["hdf"],
        case["terrain"],
        tmp_path / mask_kind,
        profiles=case["profiles"],
        engine_path=case["engine"],
        threads=4,
        max_working_mib=4096,
        **mask_options,
        aoi_crs=cells.crs,
        render_mode="slopingPretty",
        reduce_shallow_to_horizontal=True,
    )
    assert len(result) == len(case["profiles"])
    for profile, row in zip(case["profiles"], result.itertuples(), strict=True):
        for band, path in (("depth", row.depth_tif), ("wse", row.wse_tif)):
            metrics = compare_raw(path, case["references"][profile][band], cells, polygon)
            assert metrics["common"] > 0
            assert all(
                metrics[key] == 0
                for key in ("extra", "missing", "different", "outside_footprint")
            )


@pytest.mark.parametrize("inflight,threads", [(2, 4), (4, 4), (4, 1)])
@pytest.mark.parametrize("enhanced", [False, True])
def test_real_concurrent_timesteps_preserve_order_bits_and_masks(
    sloping_case, tmp_path, inflight, threads, enhanced
):
    from ras_commander import RasFim, HdfMesh
    from scripts.benchmarks.fim_sloping_compare import compare_raw

    case = sloping_case
    if enhanced:
        filename = os.environ.get("RAS_COMMANDER_SLOPING_OPTIONS_CASES")
        if not filename:
            pytest.skip("set enhanced native timestep cases for concurrency qualification")
        cases = json.loads(Path(filename).read_text(encoding="utf-8"))
        case = next(c for c in cases if c["reduce_shallow_to_horizontal"]
                    and not c["use_depth_weighted_faces"]
                    and sum(isinstance(v, int) for v in c["profiles"].values()) >= 2)
    timesteps = [(name, index) for name, index in case["profiles"].items() if isinstance(index, int)]
    assert len(timesteps) >= 2
    first, last = timesteps[0], timesteps[-1]
    profiles = {last[0]: last[1], first[0]: first[1], "repeat": last[1]}
    result = RasFim.map_sloping_profiles(
        case["hdf"], case["terrain"], tmp_path / "batch", profiles=profiles,
        engine_path=case["engine"], threads=threads, max_inflight_profiles=inflight,
        render_mode="slopingPretty" if enhanced else "sloping",
        reduce_shallow_to_horizontal=enhanced,
        writer_threads=1, max_working_mib=4096,
    )
    report = result.attrs["performance"]["engine_report"]
    assert report["requested_inflight_profiles"] == inflight
    assert report["effective_inflight_profiles"] == min(inflight, threads, len(profiles))
    assert [unit["id"] for unit in report["profiles"]] == list(profiles)
    assert list(result.profile) == list(profiles)
    references = case["references"]
    cells = HdfMesh.get_mesh_cell_polygons(case["hdf"], strict=True)
    for product in result.itertuples():
        reference_name = last[0] if product.profile == "repeat" else product.profile
        for band, path in (("depth", product.depth_tif), ("wse", product.wse_tif)):
            metrics = compare_raw(path, references[reference_name][band], cells)
            assert metrics["common"] > 0
            assert all(metrics[k] == 0 for k in ("extra", "missing", "different", "outside_footprint"))


def test_later_concurrent_batch_failure_removes_earlier_products(sloping_case, tmp_path, monkeypatch):
    from ras_commander import RasFim
    from ras_commander.fim import _sloping
    from ras_commander.fim.errors import FimEngineError

    original = _sloping._write_array
    written = []
    def corrupt_later_profile(path, values):
        if Path(path).name == "values-2-0.bin":
            values = np.array(values, copy=True)
            values[0] = np.nan
        return original(path, values)
    write_products = RasFim._write_products
    def observe_products(*args, **kwargs):
        result = write_products(*args, **kwargs)
        written.append(result)
        return result
    monkeypatch.setattr(_sloping, "_write_array", corrupt_later_profile)
    monkeypatch.setattr(RasFim, "_write_products", staticmethod(observe_products))
    case = sloping_case
    output = tmp_path / "aborted"
    with pytest.raises(FimEngineError):
        RasFim.map_sloping_profiles(
            case["hdf"], case["terrain"], output,
            profiles={"first": "Max", "second": "Max", "bad": "Max", "last": "Max"},
            engine_path=case["engine"], threads=4, max_inflight_profiles=2,
            max_working_mib=4096,
        )
    assert len(written) == 2  # Exercise cleanup after successful streamed delivery.
    assert not list(output.glob("*.tif"))
    manifest = json.loads((output / "fim_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "aborted"
    assert all(p["status"] == "failed" for p in manifest["profiles"])


@pytest.mark.parametrize("use_template", [False, True])
def test_real_sloping_compression_workers_preserve_values_and_scope(
    sloping_case, tmp_path, monkeypatch, use_template
):
    import rasterio
    from rasterio.env import get_gdal_config
    from ras_commander import RasFim, HdfMesh
    from ras_commander.fim import _products, _sloping_products
    from scripts.benchmarks.fim_sloping_compare import compare_raw

    case = sloping_case
    name = next(iter(case["profiles"]))
    reference = case["references"][name]
    observed = []
    module = _sloping_products if use_template else _products
    method = "write_array" if use_template else "write_raster"
    original = getattr(module, method)

    def record(*args, **kwargs):
        observed.append(str(get_gdal_config("GDAL_NUM_THREADS")))
        return original(*args, **kwargs)

    monkeypatch.setattr(module, method, record)
    previous = get_gdal_config("GDAL_NUM_THREADS")
    with rasterio.Env(GDAL_NUM_THREADS="2"):
        result = RasFim.map_sloping_profiles(
            case["hdf"],
            case["terrain"],
            tmp_path / "workers",
            profiles={name: case["profiles"][name]},
            engine_path=case["engine"],
            threads=1,
            writer_threads=4,
            template_raster=reference["depth"] if use_template else None,
            max_working_mib=case.get("max_working_mib", 4096),
        )
        assert str(get_gdal_config("GDAL_NUM_THREADS")) == "2"
    assert get_gdal_config("GDAL_NUM_THREADS") == previous
    assert observed == ["4", "4"]
    assert (
        json.loads((tmp_path / "workers/fim_manifest.json").read_text())["options"][
            "writer_threads"
        ]
        == 4
    )
    cells = HdfMesh.get_mesh_cell_polygons(case["hdf"], strict=True)
    for band, path in (
        ("depth", result.iloc[0].depth_tif),
        ("wse", result.iloc[0].wse_tif),
    ):
        metrics = compare_raw(
            path,
            reference[band],
            cells,
            full_grid=use_template
            and result.attrs["model_scope"]["storage_areas"] == 0,
        )
        assert metrics["common"] > 0
        assert all(
            metrics[key] == 0
            for key in ("extra", "missing", "different", "outside_footprint")
        )
        with rasterio.open(path) as actual:
            if use_template:
                with rasterio.open(reference[band]) as native:
                    assert actual.compression == native.compression
                    assert actual.block_shapes == native.block_shapes
                    assert actual.transform == native.transform
                    assert actual.tags(ns="IMAGE_STRUCTURE").get(
                        "PREDICTOR"
                    ) == native.tags(ns="IMAGE_STRUCTURE").get("PREDICTOR")
            else:
                assert actual.compression.value.upper() == "LZW"
                assert not actual.is_tiled


@pytest.mark.parametrize("use_template", [False, True])
def test_sloping_writer_failure_restores_worker_scope_and_aborts(
    sloping_case, tmp_path, monkeypatch, use_template
):
    import rasterio
    from rasterio.env import get_gdal_config
    from ras_commander import RasFim
    from ras_commander.fim import _products, _sloping_products

    case = sloping_case
    name = next(iter(case["profiles"]))
    module = _sloping_products if use_template else _products

    def fail(*args, **kwargs):
        assert str(get_gdal_config("GDAL_NUM_THREADS")) == "4"
        raise RuntimeError("forced scoped compression failure")

    monkeypatch.setattr(module, "write_array" if use_template else "write_raster", fail)
    output = tmp_path / "failed"
    previous = get_gdal_config("GDAL_NUM_THREADS")
    with rasterio.Env(GDAL_NUM_THREADS="2"):
        with pytest.raises(RuntimeError, match="scoped compression failure"):
            RasFim.map_sloping_profiles(
                case["hdf"],
                case["terrain"],
                output,
                profiles={name: case["profiles"][name]},
                engine_path=case["engine"],
                threads=1,
                writer_threads=4,
                template_raster=case["references"][name]["depth"]
                if use_template
                else None,
                max_working_mib=case.get("max_working_mib", 4096),
            )
        assert str(get_gdal_config("GDAL_NUM_THREADS")) == "2"
    assert get_gdal_config("GDAL_NUM_THREADS") == previous
    assert not list(output.glob("*.tif"))
    assert json.loads((output / "fim_manifest.json").read_text())["status"] == "aborted"


@pytest.mark.parametrize("method", ["map_sloping_profiles", "prepare_sloping_model"])
def test_deferred_option_is_not_a_public_argument(method, tmp_path):
    from ras_commander import RasFim

    with pytest.raises(TypeError, match="use_depth_weighted_faces"):
        args = ["absent.hdf", "absent.tif"]
        if method == "map_sloping_profiles":
            args.append(tmp_path / "out")
        getattr(RasFim, method)(*args, use_depth_weighted_faces=True)
    assert not (tmp_path / "out").exists()
