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


def test_load_raster_stack_reconciles_mixed_stored_map_grids(tmp_path):
    rasterio = pytest.importorskip("rasterio")

    from rasterio.transform import from_origin

    first = tmp_path / "Depth (01JAN2024 00 00 00).terrain-a.tif"
    with rasterio.open(
        first,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs="EPSG:2871",
        transform=from_origin(0, 20, 10, 10),
        nodata=-9999,
    ) as dst:
        dst.write(np.array([[1.0, 2.0], [3.0, -9999.0]], dtype="float32"), 1)

    second = tmp_path / "Depth (01JAN2024 00 05 00).terrain-b.tif"
    with rasterio.open(
        second,
        "w",
        driver="GTiff",
        height=1,
        width=3,
        count=1,
        dtype="float32",
        crs="EPSG:2871",
        transform=from_origin(10, 30, 10, 10),
        nodata=-9999,
    ) as dst:
        dst.write(np.array([[4.0, 5.0, 6.0]], dtype="float32"), 1)

    raster_stack = PrecipMrms._load_raster_stack(
        [first, second],
        times=pd.date_range("2024-01-01", periods=2, freq="5min"),
        name="depth",
        units="ft",
    )

    assert raster_stack.shape == (2, 3, 4)
    assert raster_stack.attrs["crs"] == "EPSG:2871"
    np.testing.assert_allclose(raster_stack.coords["x"].values, [5.0, 15.0, 25.0, 35.0])
    np.testing.assert_allclose(raster_stack.coords["y"].values, [25.0, 15.0, 5.0])

    first_frame = raster_stack.isel(time=0).values
    second_frame = raster_stack.isel(time=1).values
    np.testing.assert_allclose(first_frame[1:, :2], [[1.0, 2.0], [3.0, np.nan]], equal_nan=True)
    np.testing.assert_allclose(second_frame[0, 1:], [4.0, 5.0, 6.0])
    assert np.isnan(second_frame[1:, :]).all()
