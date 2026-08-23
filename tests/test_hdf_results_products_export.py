"""C06b hydraulic-product export tests.

Synthetic HDFs in this module are generated only as pytest artifacts inside
temporary directories; they are not HEC-RAS model output. Opt-in integration
tests read pre-existing producer HDFs without changing them and generate only
ras-commander derivative product packages in pytest temporary directories.
No test in this module runs HEC-RAS.
"""

import hashlib
import json
import logging
import os
from pathlib import Path

import h5py
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import rasterio
import xarray as xr
from pyproj import CRS

from ras_commander import HdfResultsMesh, HdfResultsProducts
from ras_commander.hdf._HdfResultsProductRenderers import _ProductRenderers

SERIES_BASE = (
    "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
)
SUMMARY_BASE = (
    "Results/Unsteady/Output/Output Blocks/Base Output/Summary Output"
)
EXPECTED_PARQUET_SCHEMA = pa.schema(
    [
        pa.field("time", pa.timestamp("ns"), nullable=True),
        pa.field("bc_name", pa.string(), nullable=True),
        pa.field("variable", pa.string(), nullable=True),
        pa.field("value", pa.float64(), nullable=True),
        pa.field("units", pa.string(), nullable=True),
        pa.field("area_2d", pa.string(), nullable=True),
    ]
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_export_hdf(
    path: Path,
    *,
    stored_depth: bool = False,
    negative_depth: bool = False,
) -> None:
    """Generate a compact synthetic result-shaped HDF for contract tests."""
    with h5py.File(path, "w") as hdf_file:
        hdf_file.attrs["Projection"] = CRS.from_epsg(3451).to_wkt()
        hdf_file.attrs["Units System"] = "US Customary"
        hdf_file.attrs["File Version"] = "synthetic-test-fixture"
        geometry = hdf_file.create_group("Geometry")
        geometry.attrs["SI Units"] = False
        event = hdf_file.create_group("Event Conditions")
        event.attrs["Completed Successfully"] = True
        plan_info = hdf_file.create_group("Plan Data/Plan Information")
        plan_info.attrs["Simulation Start Time"] = "18Sep2019 13:00:00"
        summary = hdf_file.create_group("Results/Unsteady/Summary")
        summary.attrs["Computation Time Total"] = 1.25
        summary.attrs["Solution"] = "synthetic contract fixture"
        volume = summary.create_group("Volume Accounting")
        volume.attrs["Volume Error Percent"] = 0.05
        hdf_file.create_dataset(
            "Results/Summary/Compute Messages (text)",
            data=np.bytes_(
                "Synthetic test messages\n"
                "18Sep2019 13:00:00 maximum iteration 7\n"
                "Complete Process\n"
            ),
        )

        attributes = np.asarray(
            [(b"Mesh", 2)],
            dtype=[("Name", "S16"), ("Cell Count", "i4")],
        )
        hdf_file.create_dataset(
            "Geometry/2D Flow Areas/Attributes",
            data=attributes,
        )
        geometry_base = "Geometry/2D Flow Areas/Mesh"
        hdf_file.create_dataset(
            f"{geometry_base}/Perimeter",
            data=np.asarray(
                [
                    [-1.0, -1.0],
                    [2.0, -1.0],
                    [2.0, 2.0],
                    [-1.0, 2.0],
                ],
                dtype=np.float64,
            ),
        )
        hdf_file.create_dataset(
            f"{geometry_base}/Cells Center Coordinate",
            data=np.asarray([[0.0, 0.0], [1.0, 1.0]], dtype=np.float64),
        )
        hdf_file.create_dataset(
            f"{geometry_base}/Cells Face and Orientation Info",
            data=np.asarray([[0, 2], [2, 2]], dtype=np.int32),
        )
        hdf_file.create_dataset(
            f"{geometry_base}/Cells Face and Orientation Values",
            data=np.asarray(
                [[0, 1], [1, 1], [1, -1], [2, 1]],
                dtype=np.int32,
            ),
        )
        hdf_file.create_dataset(
            f"{SERIES_BASE}/Time Date Stamp (ms)",
            data=np.asarray(
                [b"18Sep2019 13:00:00.000", b"18Sep2019 14:00:00.000"],
                dtype="S24",
            ),
        )
        hdf_file.create_dataset(
            f"{SERIES_BASE}/Time Date Stamp",
            data=np.asarray(
                [b"18Sep2019 13:00:00", b"18Sep2019 14:00:00"],
                dtype="S24",
            ),
        )
        water_surface = np.asarray(
            [[-10.0, -8.0], [-9.0, -7.0]],
            dtype=np.float32,
        )
        hdf_file.create_dataset(
            f"{SERIES_BASE}/2D Flow Areas/Mesh/Water Surface",
            data=water_surface,
        )
        hdf_file.create_dataset(
            f"{SERIES_BASE}/2D Flow Areas/Mesh/Face Velocity",
            data=np.asarray(
                [[1.0, 2.0, np.nan], [-3.0, 1.0, 4.0]],
                dtype=np.float32,
            ),
        )
        if stored_depth:
            depth = np.asarray(
                [[2.0, 0.0], [4.0, 1.0]],
                dtype=np.float32,
            )
            if negative_depth:
                depth[:, 0] = np.asarray([-2.0, -1.0], dtype=np.float32)
            hdf_file.create_dataset(
                f"{SERIES_BASE}/2D Flow Areas/Mesh/Depth",
                data=depth,
            )
        else:
            hdf_file.create_dataset(
                f"{geometry_base}/Cells Minimum Elevation",
                data=np.asarray([-12.0, -8.0], dtype=np.float32),
            )

        maximum_wse = hdf_file.create_dataset(
            f"{SUMMARY_BASE}/2D Flow Areas/Mesh/Maximum Water Surface",
            data=np.asarray(
                [[-9.0, -7.0], [1.0 / 24.0, 1.0 / 24.0]],
                dtype=np.float32,
            ),
        )
        maximum_wse.attrs["Row Variables"] = np.asarray(
            [b"Value", b"Time"]
        )
        hdf_file.create_dataset(
            f"{SUMMARY_BASE}/2D Flow Areas/Mesh/"
            "Cell Maximum Water Surface Error",
            data=np.asarray([0.01, 0.02], dtype=np.float32),
        )


class _SliceOnlyDataset:
    def __init__(self, values: np.ndarray):
        self._values = values
        self.shape = values.shape
        self.ndim = values.ndim
        self.dtype = values.dtype
        self.keys = []

    def __getitem__(self, key):
        assert isinstance(key, tuple)
        assert len(key) == 2
        assert isinstance(key[0], slice)
        assert isinstance(key[1], slice)
        self.keys.append(key)
        return self._values[key]


def test_pyarrow_is_a_required_core_dependency():
    setup_text = Path("setup.py").read_text(encoding="utf-8")

    install_requires = setup_text.split("install_requires=[", 1)[1].split(
        "],",
        1,
    )[0]
    assert "'pyarrow>=14.0'" in install_requires
    assert "'geoparquet': []" in setup_text


def test_velocity_reduction_is_bounded_slice_only():
    values = np.asarray(
        [
            [1.0, np.nan, -3.0],
            [-2.0, np.inf, 1.0],
            [4.0, -5.0, -np.inf],
            [3.0, 2.0, 0.0],
            [np.nan, -1.0, 8.0],
        ],
        dtype=np.float32,
    )
    dataset = _SliceOnlyDataset(values)

    result = _ProductRenderers.reduce_temporal_max_abs(
        dataset,
        max_chunk_bytes=24,
        max_chunk_rows=2,
    )

    assert np.array_equal(result, np.asarray([4.0, 5.0, 8.0]))
    assert len(dataset.keys) == 3
    assert all(key[0].stop - key[0].start <= 2 for key in dataset.keys)


def test_velocity_reduction_chunks_faces_when_one_row_exceeds_budget():
    values = np.arange(35, dtype=np.float32).reshape(5, 7) - 17.0
    dataset = _SliceOnlyDataset(values)

    result = _ProductRenderers.reduce_temporal_max_abs(
        dataset,
        max_chunk_bytes=16,
        max_chunk_rows=32,
    )

    assert np.array_equal(result, np.max(np.abs(values), axis=0))
    assert len(dataset.keys) > values.shape[0]
    assert all(key[1].stop - key[1].start <= 4 for key in dataset.keys)


def test_raster_grid_rejects_excessive_total_cell_count():
    with pytest.raises(ValueError, match="bounded-memory limit"):
        _ProductRenderers.grid_spec(
            (0.0, 0.0, 5000.0, 5000.0),
            resolution=1.0,
            max_dimension=5000,
        )


def test_raster_grid_preserves_exact_square_resolution():
    grid = _ProductRenderers.grid_spec(
        (10.0, 20.0, 13.0, 25.0),
        resolution=2.0,
        max_dimension=64,
    )

    assert grid["width"] == 2
    assert grid["height"] == 3
    assert grid["resolution"] == (2.0, 2.0)
    assert grid["bbox"] == (10.0, 19.0, 14.0, 25.0)
    assert grid["transform"].a == 2.0
    assert grid["transform"].e == -2.0


def test_arrow_hydrograph_writer_accepts_one_available_variable(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "synthetic-boundary.p01.hdf"
    output = tmp_path / "hydraulic-hydrographs.parquet"
    with h5py.File(source, "w") as hdf_file:
        hdf_file.create_group(f"{SERIES_BASE}/Boundary Conditions/Flow BC")
    dataset = xr.Dataset(
        data_vars={
            "flow": (
                ("time", "bc_name"),
                np.asarray([[1.0], [2.0]], dtype=np.float64),
            )
        },
        coords={
            "time": np.asarray(
                ["2019-09-18T13:00:00", "2019-09-18T14:00:00"],
                dtype="datetime64[ns]",
            ),
            "bc_name": ["Flow BC"],
            "flow_units": ("bc_name", ["cfs"]),
            "area_2d": ("bc_name", ["Mesh"]),
        },
    )
    monkeypatch.setattr(
        "ras_commander.hdf._HdfResultsProductRenderers."
        "HdfResultsMesh.get_boundary_conditions_timeseries",
        lambda _source: dataset,
    )

    metadata = _ProductRenderers.write_hydrographs(source, output)

    table = pq.read_table(output)
    assert table.schema.remove_metadata() == EXPECTED_PARQUET_SCHEMA
    columns = table.to_pydict()
    assert [str(value) for value in columns.pop("time")] == [
        "2019-09-18 13:00:00",
        "2019-09-18 14:00:00",
    ]
    assert columns == {
        "bc_name": ["Flow BC", "Flow BC"],
        "variable": ["flow", "flow"],
        "value": [1.0, 2.0],
        "units": ["cfs", "cfs"],
        "area_2d": ["Mesh", "Mesh"],
    }
    assert metadata["variables"] == ["flow"]
    assert metadata["units"] == {"flow": ["cfs"]}
    assert metadata["empty_reason"] is None


def test_export_generates_deterministic_arrow_and_geospatial_package(
    tmp_path,
    caplog,
):
    source = tmp_path / "synthetic.p01.hdf"
    first = tmp_path / "products-a"
    second = tmp_path / "products-b"
    _write_export_hdf(source)
    source_before = _sha256(source)

    with caplog.at_level(logging.INFO):
        first_manifest = HdfResultsProducts.export(
            source,
            first,
            max_dimension=64,
            include_preview=False,
        )
    second_manifest = HdfResultsProducts.export(
        source,
        second,
        max_dimension=64,
        include_preview=False,
    )

    assert source_before == _sha256(source)
    assert first_manifest == second_manifest
    assert first_manifest["source"]["access"] == "read_only"
    assert first_manifest["product_package"] == {
        "generated_by": "ras-commander",
        "artifact_type": "derived_hydraulic_products",
        "hec_ras_model_output_generated": False,
    }
    assert first_manifest["status"]["hydraulic_qaqc"] == "not_evaluated"
    assert first_manifest["omissions"] == [
        {"asset_key": "preview", "reason": "disabled_by_request"}
    ]
    expected_files = {
        asset["href"] for asset in first_manifest["assets"].values()
    } | {HdfResultsProducts.MANIFEST_FILENAME}
    assert {path.name for path in first.iterdir()} == expected_files
    assert "maximum-depth-preview.png" not in expected_files
    assert {
        path.name: _sha256(path) for path in first.iterdir()
    } == {
        path.name: _sha256(path) for path in second.iterdir()
    }
    qaqc = json.loads(
        (first / "numerical-qaqc.json").read_text(encoding="utf-8")
    )
    assert qaqc["acceptance"] == "not_evaluated"
    wse_error = qaqc["mesh"]["maximum_water_surface_error"]
    assert wse_error["datasets"] == [
        f"{SUMMARY_BASE}/2D Flow Areas/Mesh/"
        "Cell Maximum Water Surface Error"
    ]
    assert wse_error["maximum"] == pytest.approx(0.02)
    assert wse_error["missing_meshes"] == []
    assert wse_error["row_count"] == 2

    table = pq.read_table(first / "hydraulic-hydrographs.parquet")
    assert table.schema.remove_metadata() == EXPECTED_PARQUET_SCHEMA
    assert table.num_rows == 0
    assert (
        first_manifest["assets"]["hydraulic-hydrographs"]["table"][
            "empty_reason"
        ]
        == "no_boundary_series_in_result"
    )

    raster_metadata = []
    for filename in (
        "maximum-wse.tif",
        "maximum-depth.tif",
        "maximum-velocity.tif",
    ):
        with rasterio.open(first / filename) as raster:
            raster_metadata.append(
                (raster.crs, raster.transform, raster.shape, raster.nodata)
            )
            assert raster.tags()["generated_by"] == "ras-commander"
            assert raster.tags()["source_access"] == "read-only"
    assert raster_metadata[1:] == raster_metadata[:-1]
    with rasterio.open(first / "maximum-wse.tif") as raster:
        finite_wse = raster.read(1, masked=True).compressed()
        assert finite_wse.size > 0
        assert np.max(finite_wse) < 0.0

    footprint = json.loads(
        (first / "result-footprint.geojson").read_text(encoding="utf-8")
    )
    assert footprint["type"] == "FeatureCollection"
    mesh_names = [
        feature["properties"]["mesh_name"]
        for feature in footprint["features"]
    ]
    assert mesh_names == ["Mesh"]
    assert "generated ras-commander hydraulic product package" in caplog.text.lower()
    assert "no HEC-RAS model output was created or modified" in caplog.text


def test_export_rejects_negative_stored_depth_without_publishing(tmp_path):
    source = tmp_path / "negative-depth.p01.hdf"
    output = tmp_path / "products"
    _write_export_hdf(source, stored_depth=True, negative_depth=True)
    source_before = _sha256(source)

    with pytest.raises(ValueError, match="finite negative"):
        HdfResultsProducts.export(
            source,
            output,
            max_dimension=64,
            include_preview=False,
        )

    assert not output.exists()
    assert _sha256(source) == source_before


def test_export_detects_nodata_collision_after_float32_normalization(tmp_path):
    source = tmp_path / "source.p01.hdf"
    output = tmp_path / "products"
    _write_export_hdf(source)

    with pytest.raises(ValueError, match="collides with valid result data"):
        HdfResultsProducts.export(
            source,
            output,
            max_dimension=64,
            nodata=-9.0000001,
            include_preview=False,
        )

    assert not output.exists()


def test_export_rejects_nodata_outside_float32_range(tmp_path):
    source = tmp_path / "source.p01.hdf"
    _write_export_hdf(source)

    with pytest.raises(ValueError, match="representable as float32"):
        HdfResultsProducts.export(
            source,
            tmp_path / "products",
            max_dimension=64,
            nodata=1e100,
            include_preview=False,
        )


def test_export_generates_optional_preview_as_derived_artifact(tmp_path):
    source = tmp_path / "source.p01.hdf"
    output = tmp_path / "products"
    repeated_output = tmp_path / "products-repeated"
    _write_export_hdf(source)

    manifest = HdfResultsProducts.export(
        source,
        output,
        max_dimension=64,
    )
    repeated_manifest = HdfResultsProducts.export(
        source,
        repeated_output,
        max_dimension=64,
    )

    preview = output / "maximum-depth-preview.png"
    assert preview.is_file()
    assert preview.stat().st_size > 0
    assert manifest["assets"]["preview"]["href"] == preview.name
    assert manifest["assets"]["preview"]["sha256"] == _sha256(preview)
    assert manifest["omissions"] == []
    assert repeated_manifest == manifest
    assert _sha256(repeated_output / preview.name) == _sha256(preview)


def test_export_never_replaces_existing_directory(tmp_path):
    source = tmp_path / "source.p01.hdf"
    output = tmp_path / "products"
    _write_export_hdf(source)
    output.mkdir()
    sentinel = output / "owned-by-caller.txt"
    sentinel.write_bytes(b"preserve me")

    with pytest.raises(FileExistsError):
        HdfResultsProducts.export(source, output, max_dimension=64)

    assert sentinel.read_bytes() == b"preserve me"
    assert list(output.iterdir()) == [sentinel]


def test_missing_source_does_not_create_output_parent(tmp_path):
    output = tmp_path / "new-parent" / "products"

    with pytest.raises(FileNotFoundError):
        HdfResultsProducts.export(tmp_path / "missing.p01.hdf", output)

    assert not output.parent.exists()


def test_publication_uses_manifest_as_last_completion_marker(tmp_path, monkeypatch):
    stage = tmp_path / "stage"
    output = tmp_path / "products"
    stage.mkdir()
    (stage / "asset-a").write_bytes(b"a")
    (stage / "asset-b").write_bytes(b"b")
    (stage / HdfResultsProducts.MANIFEST_FILENAME).write_bytes(b"manifest")
    manifest = {
        "assets": {
            "a": {"href": "asset-a"},
            "b": {"href": "asset-b"},
        }
    }
    actual_link = os.link
    order = []

    def recording_link(source, destination):
        order.append(Path(source).name)
        actual_link(source, destination)

    monkeypatch.setattr(os, "link", recording_link)

    HdfResultsProducts._publish_package(stage, output, manifest)

    assert order == [
        "asset-a",
        "asset-b",
        HdfResultsProducts.MANIFEST_FILENAME,
    ]


def test_publication_failure_removes_only_owned_links(tmp_path, monkeypatch):
    stage = tmp_path / "stage"
    output = tmp_path / "products"
    stage.mkdir()
    for name in ("asset-a", "asset-b", HdfResultsProducts.MANIFEST_FILENAME):
        (stage / name).write_bytes(name.encode())
    manifest = {
        "assets": {
            "a": {"href": "asset-a"},
            "b": {"href": "asset-b"},
        }
    }
    actual_link = os.link
    calls = 0

    def failing_link(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected hard-link failure")
        actual_link(source, destination)

    monkeypatch.setattr(os, "link", failing_link)

    with pytest.raises(OSError, match="injected hard-link failure"):
        HdfResultsProducts._publish_package(stage, output, manifest)

    assert not output.exists()
    assert all((stage / name).is_file() for name in (
        "asset-a",
        "asset-b",
        HdfResultsProducts.MANIFEST_FILENAME,
    ))


def test_concurrent_output_claim_is_preserved(tmp_path, monkeypatch):
    source = tmp_path / "source.p01.hdf"
    output = tmp_path / "products"
    _write_export_hdf(source)
    publish = HdfResultsProducts._publish_package

    def concurrently_claiming_publish(stage, destination, manifest):
        destination.mkdir()
        (destination / "competitor.txt").write_bytes(b"competitor")
        publish(stage, destination, manifest)

    monkeypatch.setattr(
        HdfResultsProducts,
        "_publish_package",
        concurrently_claiming_publish,
    )

    with pytest.raises(FileExistsError):
        HdfResultsProducts.export(
            source,
            output,
            max_dimension=64,
            include_preview=False,
        )

    assert (output / "competitor.txt").read_bytes() == b"competitor"
    assert list(output.iterdir()) == [output / "competitor.txt"]


def test_post_publication_source_mismatch_removes_generated_package(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source.p01.hdf"
    output = tmp_path / "products"
    _write_export_hdf(source)
    source_before = _sha256(source)
    verify = HdfResultsProducts._require_unchanged_source

    def failing_final_checkpoint(
        source_path,
        *,
        expected_size,
        expected_hash,
        checkpoint,
    ):
        if checkpoint == "after publication":
            raise RuntimeError("injected source mismatch")
        verify(
            source_path,
            expected_size=expected_size,
            expected_hash=expected_hash,
            checkpoint=checkpoint,
        )

    monkeypatch.setattr(
        HdfResultsProducts,
        "_require_unchanged_source",
        failing_final_checkpoint,
    )

    with pytest.raises(RuntimeError, match="injected source mismatch"):
        HdfResultsProducts.export(
            source,
            output,
            max_dimension=64,
            include_preview=False,
        )

    assert not output.exists()
    assert _sha256(source) == source_before
    assert not list(tmp_path.glob(".products-*"))


@pytest.mark.integration
def test_export_existing_producer_hdfs_read_only(tmp_path):
    configured = os.environ.get("RAS_COMMANDER_PRODUCTS_EXPORT_HDFS", "")
    paths = [Path(value) for value in configured.split(os.pathsep) if value]
    if not paths:
        pytest.skip(
            "Set RAS_COMMANDER_PRODUCTS_EXPORT_HDFS for real product coverage"
        )

    for index, source in enumerate(paths):
        source_before = _sha256(source)
        output = tmp_path / f"producer-products-{index}"
        manifest = HdfResultsProducts.export(
            source,
            output,
            max_dimension=64,
            include_preview=False,
        )

        assert _sha256(source) == source_before
        assert manifest["source"]["sha256"] == source_before
        assert manifest["source"]["access"] == "read_only"
        assert manifest["product_package"][
            "hec_ras_model_output_generated"
        ] is False
        assert (output / HdfResultsProducts.MANIFEST_FILENAME).is_file()
        table = pq.read_table(output / "hydraulic-hydrographs.parquet")
        assert table.schema.remove_metadata() == EXPECTED_PARQUET_SCHEMA
        table_metadata = manifest["assets"]["hydraulic-hydrographs"]["table"]
        if source.name == "DavisStormSystem.p02.hdf":
            assert table.num_rows == 434
            assert table_metadata["variables"] == ["flow", "stage"]
            assert table_metadata["empty_reason"] is None
            producer_series = (
                HdfResultsMesh.get_boundary_conditions_timeseries(source)
            )
            table_frame = table.to_pandas()
            for variable in ("flow", "stage"):
                observed = table_frame.loc[
                    table_frame["variable"] == variable,
                    ["time", "bc_name", "value"],
                ].sort_values(["time", "bc_name"], kind="stable")
                expected = (
                    producer_series[variable]
                    .to_dataframe(name="value")
                    .reset_index()
                    .sort_values(["time", "bc_name"], kind="stable")
                )
                assert observed["time"].tolist() == expected["time"].tolist()
                assert observed["bc_name"].tolist() == (
                    expected["bc_name"].astype(str).tolist()
                )
                assert np.allclose(
                    observed["value"].to_numpy(dtype=float),
                    expected["value"].to_numpy(dtype=float),
                    equal_nan=True,
                )
            qaqc = json.loads(
                (output / "numerical-qaqc.json").read_text(encoding="utf-8")
            )
            wse_error = qaqc["mesh"]["maximum_water_surface_error"]
            assert wse_error["row_count"] == 2977
            assert wse_error["maximum"] == pytest.approx(0.00999111)
            assert wse_error["missing_meshes"] == []
        if source.name == "Spring.p06.hdf":
            assert table.num_rows == 0
            assert table_metadata["variables"] == []
            assert table_metadata["empty_reason"] == (
                "no_boundary_series_in_result"
            )
            assert manifest["completion_evidence"][
                "event_conditions_completed_successfully"
            ] is None
        for filename in (
            "maximum-wse.tif",
            "maximum-depth.tif",
            "maximum-velocity.tif",
        ):
            with rasterio.open(output / filename) as raster:
                assert raster.tags()["generated_by"] == "ras-commander"
                assert raster.tags()["source_access"] == "read-only"
        assert _sha256(source) == source_before
