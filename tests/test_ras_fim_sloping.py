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
