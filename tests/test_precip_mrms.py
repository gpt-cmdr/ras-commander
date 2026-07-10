from __future__ import annotations

import gzip
from io import BytesIO
from pathlib import Path
import types

import numpy as np
import pandas as pd
import pytest

from ras_commander.precip import PrecipMrms
from ras_commander.precip.VortexCli import VortexCli


class FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=8192):
        for idx in range(0, len(self.content), chunk_size):
            yield self.content[idx : idx + chunk_size]


def _write_stored_map_raster(path, values, transform, crs="EPSG:2871", nodata=-9999):
    import rasterio

    data = np.asarray(values, dtype="float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(data, 1)
    return path


def test_catalog_parses_noaa_s3_listing(monkeypatch):
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
      <IsTruncated>false</IsTruncated>
      <Contents>
        <Key>CONUS/MultiSensor_QPE_01H_Pass2_00.00/20240708/MRMS_MultiSensor_QPE_01H_Pass2_00.00_20240708-120000.grib2.gz</Key>
        <LastModified>2024-07-08T12:58:00.000Z</LastModified>
        <Size>12345</Size>
      </Contents>
      <Contents>
        <Key>CONUS/MultiSensor_QPE_01H_Pass2_00.00/20240708/readme.txt</Key>
        <LastModified>2024-07-08T12:58:00.000Z</LastModified>
        <Size>1</Size>
      </Contents>
    </ListBucketResult>
    """

    def fake_get(url, params=None, timeout=None):
        assert url == PrecipMrms.NOAA_S3_BASE_URL
        assert params["prefix"] == "CONUS/MultiSensor_QPE_01H_Pass2_00.00/20240708/"
        return FakeResponse(xml)

    monkeypatch.setitem(__import__("sys").modules, "requests", types.SimpleNamespace(get=fake_get))

    catalog = PrecipMrms.catalog(
        bounds=(-96.0, 29.0, -95.0, 30.0),
        start_date="2024-07-08 12:00",
        end_date="2024-07-08 12:00",
        source="noaa_s3",
    )

    assert len(catalog) == 1
    row = catalog.iloc[0]
    assert row["source"] == "noaa_s3"
    assert row["product"] == "GaugeCorr_QPE_01H"
    assert row["archive_product"] == "MultiSensor_QPE_01H_Pass2_00.00"
    assert row["filename"].endswith("20240708-120000.grib2.gz")
    assert row["size_bytes"] == 12345
    assert bool(row["compressed"]) is True
    assert row["valid_time"] == pd.Timestamp("2024-07-08 12:00:00")


def test_catalog_parses_iowa_mtarchive_listing(monkeypatch):
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <catalog xmlns="http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0">
      <dataset name="GaugeCorr_QPE_01H">
        <dataset name="GaugeCorr_QPE_01H_00.00_20171220-120000.grib2.gz"
                 urlPath="mtarchive/2017/12/20/mrms/ncep/GaugeCorr_QPE_01H/GaugeCorr_QPE_01H_00.00_20171220-120000.grib2.gz">
          <dataSize units="Kbytes">698.6</dataSize>
          <date type="modified">2017-12-20T13:34:01.420Z</date>
        </dataset>
      </dataset>
    </catalog>
    """

    def fake_get(url, timeout=None):
        assert url.endswith("/mtarchive/2017/12/20/mrms/ncep/GaugeCorr_QPE_01H/catalog.xml")
        return FakeResponse(xml)

    monkeypatch.setitem(__import__("sys").modules, "requests", types.SimpleNamespace(get=fake_get))

    catalog = PrecipMrms.catalog(
        bounds=(-96.0, 29.0, -95.0, 30.0),
        start_date="2017-12-20 12:00",
        end_date="2017-12-20 12:00",
        source="iowa",
    )

    assert len(catalog) == 1
    row = catalog.iloc[0]
    assert row["source"] == "iowa"
    assert row["archive_product"] == "GaugeCorr_QPE_01H"
    assert row["url"].startswith(PrecipMrms.IOWA_FILESERVER_BASE_URL)
    assert row["size_bytes"] == int(698.6 * 1024)


def test_download_decompresses_gzip_to_grib2(monkeypatch, tmp_path):
    payload = b"GRIB-test-payload"
    compressed = BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb") as gz_file:
        gz_file.write(payload)

    catalog = pd.DataFrame(
        [
            {
                "valid_time": pd.Timestamp("2024-07-08 12:00"),
                "source": "noaa_s3",
                "product": "GaugeCorr_QPE_01H",
                "archive_product": "MultiSensor_QPE_01H_Pass2_00.00",
                "url": "https://example.test/mrms.grib2.gz",
                "filename": "MRMS_MultiSensor_QPE_01H_Pass2_00.00_20240708-120000.grib2.gz",
                "size_bytes": len(compressed.getvalue()),
                "last_modified": pd.Timestamp("2024-07-08 12:58"),
                "compressed": True,
            }
        ]
    )

    monkeypatch.setattr(PrecipMrms, "catalog", staticmethod(lambda *args, **kwargs: catalog))

    def fake_get(url, stream=False, timeout=None):
        assert stream is True
        assert url == "https://example.test/mrms.grib2.gz"
        return FakeResponse(compressed.getvalue())

    monkeypatch.setitem(__import__("sys").modules, "requests", types.SimpleNamespace(get=fake_get))

    files = PrecipMrms.download(
        bounds=(-96.0, 29.0, -95.0, 30.0),
        start_time="2024-07-08 12:00",
        end_time="2024-07-08 12:00",
        output_dir=tmp_path,
    )

    assert len(files) == 1
    assert files[0].suffix == ".grib2"
    assert files[0].read_bytes() == payload


def test_to_dss_wraps_vortex_with_mrms_defaults(monkeypatch, tmp_path):
    grib_path = tmp_path / "MRMS_RadarOnly_QPE_01H_00.00_20240708-120000.grib2"
    grib_path.write_bytes(b"GRIB")
    output_dss = tmp_path / "mrms.dss"
    clip_shp = tmp_path / "clip.shp"
    clip_shp.write_text("placeholder")
    calls = []

    def fake_import_gridded(**kwargs):
        calls.append(kwargs)
        output = Path(kwargs["output_dss"])
        output.write_bytes(b"DSS")
        return output

    monkeypatch.setattr(VortexCli, "import_gridded", staticmethod(fake_import_gridded))

    result = PrecipMrms.to_dss(
        [grib_path],
        output_dss,
        clip_shp=clip_shp,
        product="RadarOnly_QPE_01H",
        timeout=123,
    )

    assert result == output_dss
    assert output_dss.exists()
    assert len(calls) == 1
    assert calls[0]["input_files"] == [grib_path]
    assert calls[0]["variables"] == ["RadarOnlyQPE01H_altitude_above_msl"]
    assert calls[0]["clip_shp"] == clip_shp
    assert calls[0]["target_wkt"] == "SHG"
    assert calls[0]["dss_parts"]["A"] == "SHG"
    assert calls[0]["dss_parts"]["B"] == "MRMS_QPE"
    assert calls[0]["dss_parts"]["F"] == "RADARONLY_QPE_01H"
    assert calls[0]["timeout"] == 123


def test_vortex_variables_respect_mrms_product_family():
    assert PrecipMrms._vortex_variables("GaugeCorr_QPE_01H") == [
        "GaugeCorrQPE01H_altitude_above_msl"
    ]
    assert PrecipMrms._vortex_variables("GaugeCorrQPE03H") == [
        "GaugeCorrQPE03H_altitude_above_msl"
    ]
    assert PrecipMrms._vortex_variables("RadarOnly_QPE_06H") == [
        "RadarOnlyQPE06H_altitude_above_msl"
    ]
    assert PrecipMrms._vortex_variables("MultiSensor_QPE_01H_Pass2_00.00") == [
        "MultiSensor_QPE_01H_Pass2_altitude_above_msl"
    ]
    assert PrecipMrms._vortex_variables_for_files(
        "GaugeCorr_QPE_01H",
        [Path("MRMS_MultiSensor_QPE_01H_Pass2_00.00_20240708-120000.grib2")],
    ) == ["MultiSensor_QPE_01H_Pass2_altitude_above_msl"]


def test_timestamp_from_xarray_returns_scalar_for_vector_coord():
    xr = pytest.importorskip("xarray")

    coord = xr.DataArray(
        pd.date_range("2024-07-08 12:00", periods=2, freq="h"),
        dims=("time",),
    )

    timestamp = PrecipMrms._timestamp_from_xarray(coord)

    assert timestamp == pd.Timestamp("2024-07-08 12:00").to_pydatetime()


def test_vortex_finder_accepts_vortex_013_importer_layout(tmp_path):
    vortex_dir = tmp_path / "HEC-Vortex" / "0.13.3"
    (vortex_dir / "bin").mkdir(parents=True)
    (vortex_dir / "lib").mkdir()
    (vortex_dir / "bin" / "importer.bat").write_text("@echo off\n")
    (vortex_dir / "lib" / "vortex-0.13.3.jar").write_text("placeholder")

    assert VortexCli.find_vortex(vortex_dir) == vortex_dir
    assert VortexCli._get_vortex_bat(vortex_dir).name == "importer.bat"


def test_direct_mrms_hyetograph_and_netcdf_exports(tmp_path):
    xr = pytest.importorskip("xarray")

    times = pd.date_range("2024-02-04 00:00", periods=3, freq="h")
    lat = np.array([38.7, 38.6])
    lon = np.array([-121.8, -121.7])
    precip = xr.DataArray(
        np.array(
            [
                [[25.4, 0.0], [0.0, 25.4]],
                [[12.7, 12.7], [12.7, 12.7]],
                [[0.0, 0.0], [25.4, 25.4]],
            ],
            dtype=float,
        ),
        dims=("time", "latitude", "longitude"),
        coords={"time": times, "latitude": lat, "longitude": lon},
        attrs={"units": "mm"},
    )

    hyetograph = PrecipMrms.to_hyetograph(precip)

    assert list(hyetograph.columns) == [
        "time",
        "hour",
        "incremental_depth",
        "cumulative_depth",
    ]
    assert hyetograph["hour"].tolist() == [1.0, 2.0, 3.0]
    assert np.allclose(hyetograph["incremental_depth"], [0.5, 0.5, 0.5])
    assert np.allclose(hyetograph["cumulative_depth"], [0.5, 1.0, 1.5])

    nc_path = PrecipMrms.to_ras_netcdf(
        precip,
        tmp_path / "mrms_qpe.nc",
        target_crs=None,
    )

    assert nc_path.exists()
    with xr.open_dataset(nc_path) as ds:
        assert "APCP_surface" in ds.data_vars
        assert ds["APCP_surface"].attrs["units"] == "mm"
        assert ds["APCP_surface"].shape == precip.shape


def test_animation_helpers_accept_dataarray_and_hdf(monkeypatch, tmp_path):
    gpd = pytest.importorskip("geopandas")
    h5py = pytest.importorskip("h5py")
    pytest.importorskip("matplotlib")
    xr = pytest.importorskip("xarray")
    from shapely.geometry import Point, box

    monkeypatch.setattr(
        PrecipMrms,
        "_add_osm_basemap",
        staticmethod(lambda ax, data_crs: None),
    )

    times = pd.date_range("2024-07-08 12:00", periods=2, freq="h")
    lon = np.linspace(-95.5, -95.0, 5)
    lat = np.linspace(29.5, 30.0, 4)
    precip = xr.DataArray(
        np.arange(2 * 4 * 5, dtype=float).reshape(2, 4, 5),
        dims=("time", "latitude", "longitude"),
        coords={"time": times, "latitude": lat, "longitude": lon},
        attrs={"units": "mm"},
    )
    mesh_boundary = gpd.GeoDataFrame(
        {"mesh_name": ["Demo 2D Area"]},
        geometry=[box(-95.5, 29.5, -95.0, 30.0)],
        crs="EPSG:4326",
    )
    pump_stations = gpd.GeoDataFrame(
        {"Name": ["Demo Pump"]},
        geometry=[Point(-95.25, 29.75)],
        crs="EPSG:4326",
    )

    mesh_name = "Demo 2D Area"
    hdf_path = tmp_path / "synthetic_plan.p01.hdf"
    centers = np.array(
        [
            [-95.5, 29.5],
            [-95.0, 29.5],
            [-95.5, 30.0],
            [-95.0, 30.0],
        ],
        dtype=float,
    )
    depth = np.array(
        [
            [0.1, 0.2, 0.0, 0.3],
            [0.4, 0.1, 0.5, 0.2],
        ],
        dtype="float32",
    )
    with h5py.File(hdf_path, "w") as hdf:
        hdf.attrs["Projection"] = (
            'GEOGCS["WGS 84",DATUM["WGS_1984",'
            'SPHEROID["WGS 84",6378137,298.257223563]],'
            'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
        )
        plan_info = hdf.require_group("Plan Data").require_group("Plan Information")
        plan_info.attrs["Simulation Start Time"] = np.bytes_("08Jul2024 12:00:00")
        geom_root = hdf.require_group("Geometry").require_group("2D Flow Areas")
        dtype = np.dtype([("Name", "S64")])
        geom_root.create_dataset(
            "Attributes",
            data=np.array([(mesh_name.encode("utf-8"),)], dtype=dtype),
        )
        mesh_group = geom_root.require_group(mesh_name)
        mesh_group.create_dataset("Cells Center Coordinate", data=centers)
        ts_root = (
            hdf.require_group("Results")
            .require_group("Unsteady")
            .require_group("Output")
            .require_group("Output Blocks")
            .require_group("Base Output")
            .require_group("Unsteady Time Series")
        )
        ts_root.create_dataset("Time", data=np.array([0.0, 1.0 / 24.0]))
        flow_root = ts_root.require_group("2D Flow Areas").require_group(mesh_name)
        depth_dataset = flow_root.create_dataset("Depth", data=depth)
        depth_dataset.attrs["Units"] = b"ft"

    precip_gif = PrecipMrms.animate_precipitation(
        precip,
        tmp_path / "precip.gif",
        bounds=(-95.5, 29.5, -95.0, 30.0),
        mesh_boundary=mesh_boundary,
        pump_stations=pump_stations,
        add_basemap=True,
        units="mm",
        fps=1,
    )
    flood_gif = PrecipMrms.animate_flood_inundation(
        hdf_path,
        tmp_path / "flood.gif",
        mesh_name=mesh_name,
        mesh_boundary=mesh_boundary,
        pump_stations=pump_stations,
        add_basemap=True,
        crs="EPSG:4326",
        fps=1,
    )
    combined_gif = PrecipMrms.animate_combined(
        precip,
        hdf_path,
        tmp_path / "combined.gif",
        bounds=(-95.5, 29.5, -95.0, 30.0),
        mesh_name=mesh_name,
        mesh_boundary=mesh_boundary,
        pump_stations=pump_stations,
        add_basemap=True,
        precip_crs="EPSG:4326",
        flood_crs="EPSG:4326",
        fps=1,
    )

    for animation_path in (precip_gif, flood_gif, combined_gif):
        assert animation_path.exists()
        assert animation_path.stat().st_size > 0


def test_flood_animation_accepts_stored_map_rasters(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    pytest.importorskip("matplotlib")

    from rasterio.transform import from_origin

    raster_paths = []
    for idx in range(2):
        raster_path = tmp_path / f"Depth (04FEB2024 0{idx} 00 00).Terrain.tif"
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            height=3,
            width=4,
            count=1,
            dtype="float32",
            crs="EPSG:2871",
            transform=from_origin(1000, 2000, 10, 10),
            nodata=-9999,
        ) as dst:
            dst.write(np.full((3, 4), idx + 1, dtype="float32"), 1)
        raster_paths.append(raster_path)

    output = PrecipMrms.animate_flood_inundation_from_rasters(
        raster_paths,
        tmp_path / "flood_rasters.gif",
        times=pd.date_range("2024-02-04", periods=2, freq="h"),
        fps=1,
    )
    raster_stack = PrecipMrms._load_raster_stack(raster_paths)

    assert output.exists()
    assert output.stat().st_size > 0
    assert raster_stack.attrs["crs"] == "EPSG:2871"


def test_load_stored_map_stack_reconciles_mixed_single_raster_grids(tmp_path):
    pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    first = _write_stored_map_raster(
        tmp_path / "frame_0.tif",
        np.full((2, 2), 1.0),
        from_origin(0, 2, 1, 1),
    )
    second = _write_stored_map_raster(
        tmp_path / "frame_1.tif",
        np.full((1, 3), 2.0),
        from_origin(1, 2, 1, 1),
    )

    stack = PrecipMrms.load_stored_map_stack(
        [first, second],
        times=pd.date_range("2024-02-04", periods=2, freq="h"),
        units="ft",
    )

    assert stack.dims == ("time", "y", "x")
    assert stack.shape == (2, 2, 4)
    assert stack.attrs == {"units": "ft", "crs": "EPSG:2871"}
    assert np.count_nonzero(np.isfinite(stack.values[0])) == 4
    assert np.count_nonzero(np.isfinite(stack.values[1])) == 3
    assert np.all(stack.values[0, :, :2] == 1.0)
    assert np.all(stack.values[1, 0, 1:] == 2.0)


def test_load_stored_map_stack_mosaics_every_grouped_tile(tmp_path):
    pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    frames = []
    for frame_index, values in enumerate(((1.0, 2.0), (3.0, 4.0))):
        left = _write_stored_map_raster(
            tmp_path / f"frame_{frame_index}_left.tif",
            np.full((2, 2), values[0]),
            from_origin(0, 2, 1, 1),
        )
        right = _write_stored_map_raster(
            tmp_path / f"frame_{frame_index}_right.tif",
            np.full((2, 2), values[1]),
            from_origin(2, 2, 1, 1),
        )
        frames.append([left, right])

    stack = PrecipMrms.load_stored_map_stack(frames, units="ft")

    assert stack.shape == (2, 2, 4)
    np.testing.assert_allclose(stack.values[0, :, :2], 1.0)
    np.testing.assert_allclose(stack.values[0, :, 2:], 2.0)
    np.testing.assert_allclose(stack.values[1, :, :2], 3.0)
    np.testing.assert_allclose(stack.values[1, :, 2:], 4.0)


def test_load_stored_map_stack_grouped_overlap_preserves_valid_cells(tmp_path):
    pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    transform = from_origin(0, 2, 1, 1)
    earlier = _write_stored_map_raster(
        tmp_path / "earlier.tif",
        np.ones((2, 2)),
        transform,
    )
    later = _write_stored_map_raster(
        tmp_path / "later.tif",
        np.array([[2.0, -9999.0], [-9999.0, 3.0]]),
        transform,
    )

    stack = PrecipMrms.load_stored_map_stack([[earlier, later]])

    assert stack.dtype == np.dtype("float32")
    np.testing.assert_allclose(
        stack.values[0],
        np.array([[2.0, 1.0], [1.0, 3.0]], dtype="float32"),
    )


def test_load_stored_map_stack_honors_explicit_cell_size(tmp_path):
    pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    raster_path = _write_stored_map_raster(
        tmp_path / "frame.tif",
        np.full((4, 4), 5.0),
        from_origin(0, 4, 1, 1),
    )

    stack = PrecipMrms.load_stored_map_stack(
        raster_path,
        cell_size=2,
        resampling="bilinear",
    )

    assert stack.shape == (1, 2, 2)
    np.testing.assert_allclose(stack.coords["x"], [1.0, 3.0])
    np.testing.assert_allclose(stack.coords["y"], [3.0, 1.0])
    np.testing.assert_allclose(stack.values, 5.0)


def test_load_stored_map_stack_rejects_invalid_arguments(tmp_path):
    pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    raster_path = _write_stored_map_raster(
        tmp_path / "frame.tif",
        np.ones((2, 2)),
        from_origin(0, 2, 1, 1),
    )

    with pytest.raises(ValueError, match="at least one frame"):
        PrecipMrms.load_stored_map_stack([])
    with pytest.raises(ValueError, match="at least one raster"):
        PrecipMrms.load_stored_map_stack([[]])
    with pytest.raises(ValueError, match="times length"):
        PrecipMrms.load_stored_map_stack(
            [raster_path],
            times=pd.date_range("2024-02-04", periods=2, freq="h"),
        )
    with pytest.raises(ValueError, match="max_frames"):
        PrecipMrms.load_stored_map_stack(raster_path, max_frames=0)
    with pytest.raises(ValueError, match="cell_size"):
        PrecipMrms.load_stored_map_stack(raster_path, cell_size=0)
    with pytest.raises(ValueError, match="Unsupported resampling"):
        PrecipMrms.load_stored_map_stack(raster_path, resampling="not-a-method")


def test_load_stored_map_stack_rejects_missing_or_mixed_crs(tmp_path):
    pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    transform = from_origin(0, 2, 1, 1)
    projected = _write_stored_map_raster(
        tmp_path / "projected.tif",
        np.ones((2, 2)),
        transform,
    )
    geographic = _write_stored_map_raster(
        tmp_path / "geographic.tif",
        np.ones((2, 2)),
        transform,
        crs="EPSG:4326",
    )
    missing = _write_stored_map_raster(
        tmp_path / "missing.tif",
        np.ones((2, 2)),
        transform,
        crs=None,
    )

    with pytest.raises(ValueError, match="common CRS"):
        PrecipMrms.load_stored_map_stack([projected, geographic])
    with pytest.raises(ValueError, match="no CRS"):
        PrecipMrms.load_stored_map_stack(missing)


def test_load_stored_map_stack_limits_frames_before_opening_files(
    monkeypatch, tmp_path
):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    raster_paths = [
        _write_stored_map_raster(
            tmp_path / f"frame_{index}.tif",
            np.full((2, 2), index, dtype="float32"),
            from_origin(0, 2, 1, 1),
        )
        for index in range(5)
    ]
    times = pd.date_range("2024-02-04", periods=5, freq="h")
    real_open = rasterio.open
    opened_paths = []

    def tracking_open(path, *args, **kwargs):
        opened_paths.append(Path(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(rasterio, "open", tracking_open)

    stack = PrecipMrms.load_stored_map_stack(
        raster_paths,
        times=times,
        max_frames=2,
    )

    assert set(opened_paths) == {raster_paths[0], raster_paths[-1]}
    assert stack.sizes["time"] == 2
    np.testing.assert_array_equal(stack.coords["time"].values, times[[0, -1]].values)


def test_public_animations_route_grouped_rasters_and_forward_grid_options(
    monkeypatch, tmp_path
):
    pytest.importorskip("matplotlib")
    xr = pytest.importorskip("xarray")

    grouped_frames = [[Path("frame_0_a.tif"), Path("frame_0_b.tif")]]
    calls = {}
    flood_output = tmp_path / "flood.gif"

    def fake_raster_animation(raster_files, output_mp4, **kwargs):
        calls["flood"] = (raster_files, output_mp4, kwargs)
        return Path(output_mp4)

    monkeypatch.setattr(
        PrecipMrms,
        "animate_flood_inundation_from_rasters",
        staticmethod(fake_raster_animation),
    )

    result = PrecipMrms.animate_flood_inundation(
        grouped_frames,
        flood_output,
        cell_size=25,
        resampling="bilinear",
    )

    assert result == flood_output
    assert calls["flood"][0] == grouped_frames
    assert calls["flood"][2]["cell_size"] == 25
    assert calls["flood"][2]["resampling"] == "bilinear"

    precip = xr.DataArray(
        np.ones((1, 2, 2), dtype="float32"),
        dims=("time", "y", "x"),
        coords={"time": [pd.Timestamp("2024-02-04")], "y": [1.5, 0.5], "x": [0.5, 1.5]},
        attrs={"units": "mm", "crs": "EPSG:2871"},
    )

    class CombinedRasterRoute(Exception):
        pass

    def fake_loader(raster_files, **kwargs):
        calls["combined"] = (raster_files, kwargs)
        raise CombinedRasterRoute

    monkeypatch.setattr(
        PrecipMrms,
        "load_stored_map_stack",
        staticmethod(fake_loader),
    )

    with pytest.raises(CombinedRasterRoute):
        PrecipMrms.animate_combined(
            precip,
            grouped_frames,
            tmp_path / "combined.gif",
            cell_size=50,
            resampling="cubic",
        )

    assert calls["combined"][0] == grouped_frames
    assert calls["combined"][1]["cell_size"] == 50
    assert calls["combined"][1]["resampling"] == "cubic"
