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
        assert ds["APCP_surface"].attrs["value_type"] == "cumulative"
        assert ds["APCP_surface"].shape == (4, 2, 2)
        assert pd.Timestamp(ds["time"].values[0]) == times[0] - pd.Timedelta(hours=1)
        np.testing.assert_allclose(ds["APCP_surface"].isel(time=0), 0.0)
        np.testing.assert_allclose(
            ds["APCP_surface"].isel(time=-1),
            precip.sum("time"),
        )
        assert ds.attrs["first_timestep_hours"] == 1.0
        assert ds.attrs["zero_tail_frames"] == 0


def test_mrms_netcdf_extends_flat_cumulative_tail(tmp_path):
    xr = pytest.importorskip("xarray")
    times = pd.date_range("2024-08-09 10:00", periods=2, freq="h")
    precip = xr.DataArray(
        np.array([[[2.0]], [[3.0]]], dtype=float),
        dims=("time", "latitude", "longitude"),
        coords={"time": times, "latitude": [41.0], "longitude": [-77.5]},
        attrs={"units": "mm"},
    )

    nc_path = PrecipMrms.to_ras_netcdf(
        precip,
        tmp_path / "mrms_tail.nc",
        target_crs=None,
        end_time="2024-08-09 14:00",
    )

    with xr.open_dataset(nc_path) as ds:
        assert list(pd.to_datetime(ds["time"].values)) == list(
            pd.date_range("2024-08-09 09:00", "2024-08-09 14:00", freq="h")
        )
        np.testing.assert_allclose(
            ds["APCP_surface"].values[:, 0, 0],
            [0.0, 2.0, 5.0, 5.0, 5.0, 5.0],
        )
        assert ds.attrs["storm_end"] == "2024-08-09T11:00:00"
        assert ds.attrs["forcing_end"] == "2024-08-09T14:00:00"
        assert ds.attrs["zero_tail_frames"] == 3


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


def test_precipitation_animation_separates_rate_and_cumulative_units(
    monkeypatch, tmp_path
):
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg", force=True)
    xr = pytest.importorskip("xarray")

    precip = xr.DataArray(
        np.full((2, 2, 2), 25.4, dtype="float32"),
        dims=("time", "latitude", "longitude"),
        coords={
            "time": pd.date_range("2024-07-08 12:00", periods=2, freq="h"),
            "latitude": [30.0, 29.9],
            "longitude": [-95.5, -95.4],
        },
        attrs={"units": "mm"},
    )
    captured = {}

    def capture_final_frame(fig, update_func, frame_count, output_path, fps, dpi):
        import matplotlib.pyplot as plt

        artists = update_func(frame_count - 1)
        captured["annotation"] = artists[-1].get_text()
        captured["axis_ylabels"] = [axis.get_ylabel() for axis in fig.axes]
        Path(output_path).touch()
        plt.close(fig)

    monkeypatch.setattr(
        PrecipMrms,
        "_save_animation",
        staticmethod(capture_final_frame),
    )

    output = PrecipMrms.animate_precipitation(
        precip,
        tmp_path / "precipitation.mp4",
        units="in/hr",
    )

    assert output.exists()
    assert "Precipitation (in/hr)" in captured["axis_ylabels"]
    assert captured["annotation"].endswith("Mean cumulative: 2.00 in")


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


def test_terrain_raster_is_warped_to_flood_grid_with_nodata_preserved(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    xr = pytest.importorskip("xarray")
    from rasterio.transform import from_origin

    terrain_path = tmp_path / "terrain.tif"
    terrain = np.arange(36, dtype="float32").reshape(6, 6)
    terrain[0, 0] = -9999
    with rasterio.open(
        terrain_path,
        "w",
        driver="GTiff",
        height=6,
        width=6,
        count=1,
        dtype="float32",
        crs="EPSG:2871",
        transform=from_origin(0, 6, 1, 1),
        nodata=-9999,
    ) as dst:
        dst.write(terrain, 1)

    flood = xr.DataArray(
        np.ones((2, 2, 3), dtype="float32"),
        dims=("time", "y", "x"),
        coords={
            "time": pd.date_range("2024-02-04", periods=2, freq="h"),
            "y": [4.5, 3.5],
            "x": [1.5, 2.5, 3.5],
        },
        attrs={"crs": "EPSG:2871"},
    )

    overlay = PrecipMrms._prepare_terrain_data(
        terrain_path,
        target_data=flood,
    )

    assert overlay["values"].shape == (2, 3)
    assert overlay["extent"] == (1.0, 4.0, 3.0, 5.0)
    assert overlay["origin"] == "upper"
    assert overlay["crs"] == "EPSG:2871"
    assert np.isfinite(overlay["values"]).all()


def test_raw_terrain_array_requires_exact_flood_grid_shape():
    xr = pytest.importorskip("xarray")
    flood = xr.DataArray(
        np.ones((1, 2, 3), dtype="float32"),
        dims=("time", "y", "x"),
        coords={"time": [pd.Timestamp("2024-02-04")], "y": [1.5, 0.5], "x": [0.5, 1.5, 2.5]},
        attrs={"crs": "EPSG:2871"},
    )

    with pytest.raises(ValueError, match="must match the animation grid shape"):
        PrecipMrms._prepare_terrain_data(
            np.ones((4, 4), dtype=float),
            target_data=flood,
        )


def test_terrain_raster_is_reprojected_when_crs_differs(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    xr = pytest.importorskip("xarray")
    from rasterio.transform import from_origin

    terrain_path = tmp_path / "geographic_terrain.tif"
    with rasterio.open(
        terrain_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(-1, 1, 0.5, 0.5),
    ) as dst:
        dst.write(np.arange(16, dtype="float32").reshape(4, 4), 1)

    flood = xr.DataArray(
        np.ones((1, 2, 2), dtype="float32"),
        dims=("time", "y", "x"),
        coords={
            "time": [pd.Timestamp("2024-02-04")],
            "y": [50000.0, -50000.0],
            "x": [-50000.0, 50000.0],
        },
        attrs={"crs": "EPSG:3857"},
    )

    overlay = PrecipMrms._prepare_terrain_data(terrain_path, target_data=flood)

    assert overlay["values"].shape == (2, 2)
    assert overlay["crs"] == "EPSG:3857"
    assert np.isfinite(overlay["values"]).all()


def test_hillshade_retains_terrain_nodata_mask():
    terrain = np.array([[np.nan, 1.0], [2.0, 3.0]])

    shaded = PrecipMrms._hillshade(terrain)

    assert np.isnan(shaded[0, 0])
    assert np.isfinite(shaded[1, 1])


def test_flood_animation_uses_aligned_terrain_extent(monkeypatch, tmp_path):
    rasterio = pytest.importorskip("rasterio")
    pytest.importorskip("matplotlib")
    xr = pytest.importorskip("xarray")
    from rasterio.transform import from_origin

    terrain_path = tmp_path / "large_terrain.tif"
    with rasterio.open(
        terrain_path,
        "w",
        driver="GTiff",
        height=20,
        width=20,
        count=1,
        dtype="float32",
        crs="EPSG:2871",
        transform=from_origin(0, 20, 1, 1),
    ) as dst:
        dst.write(np.arange(400, dtype="float32").reshape(20, 20), 1)

    flood = xr.DataArray(
        np.ones((1, 2, 3), dtype="float32"),
        dims=("time", "y", "x"),
        coords={"time": [pd.Timestamp("2024-02-04")], "y": [11.5, 10.5], "x": [5.5, 6.5, 7.5]},
        attrs={"crs": "EPSG:2871"},
    )
    captured = {}

    def capture(fig, update_func, frame_count, output_path, fps, dpi):
        captured["extents"] = [tuple(image.get_extent()) for image in fig.axes[0].images]
        captured["shapes"] = [np.asarray(image.get_array()).shape for image in fig.axes[0].images]
        Path(output_path).touch()

    monkeypatch.setattr(PrecipMrms, "_save_animation", staticmethod(capture))
    output = PrecipMrms.animate_flood_inundation(
        flood,
        tmp_path / "aligned.mp4",
        terrain=terrain_path,
    )

    assert output.exists()
    assert captured["extents"] == [(5.0, 8.0, 10.0, 12.0)] * 2
    assert captured["shapes"] == [(2, 3), (2, 3)]


def test_hdf_flood_animation_rejects_silently_ignored_terrain(tmp_path):
    with pytest.raises(ValueError, match="HDF point-cloud animation route"):
        PrecipMrms.animate_flood_inundation(
            tmp_path / "results.p01.hdf",
            tmp_path / "flood.mp4",
            terrain=tmp_path / "terrain.tif",
        )


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
    assert stack.attrs == {
        "units": "ft",
        "crs": "EPSG:2871",
        "grid_bounds": (0.0, 4.0, 0.0, 2.0),
    }
    assert np.count_nonzero(np.isfinite(stack.values[0])) == 4
    assert np.count_nonzero(np.isfinite(stack.values[1])) == 3
    assert np.all(stack.values[0, :, :2] == 1.0)
    assert np.all(stack.values[1, 0, 1:] == 2.0)
    assert PrecipMrms._data_extent(stack) == ((0.0, 4.0, 0.0, 2.0), "upper")


def test_public_extent_is_treated_as_pixel_edges():
    data = PrecipMrms._coerce_grid_data(
        np.ones((1, 2, 4), dtype=float),
        extent=(1000.0, 1040.0, 1970.0, 2000.0),
    )

    np.testing.assert_allclose(data.coords["x"], [1005.0, 1015.0, 1025.0, 1035.0])
    np.testing.assert_allclose(data.coords["y"], [1977.5, 1992.5])
    assert PrecipMrms._data_extent(data) == (
        (1000.0, 1040.0, 1970.0, 2000.0),
        "lower",
    )


def test_stored_map_stack_normalizes_south_up_bounds(tmp_path):
    pytest.importorskip("rasterio")
    from affine import Affine

    raster_path = _write_stored_map_raster(
        tmp_path / "south_up.tif",
        np.arange(6, dtype="float32").reshape(2, 3),
        Affine(10.0, 0.0, 1000.0, 0.0, 10.0, 1970.0),
    )

    stack = PrecipMrms.load_stored_map_stack(raster_path)

    assert stack.attrs["grid_bounds"] == (1000.0, 1030.0, 1970.0, 1990.0)
    assert PrecipMrms._data_extent(stack) == (
        (1000.0, 1030.0, 1970.0, 1990.0),
        "lower",
    )
    np.testing.assert_array_equal(
        stack.values[0],
        np.arange(6, dtype="float32").reshape(2, 3),
    )


@pytest.mark.parametrize(
    ("transform", "message"),
    [
        (pytest.param((-1.0, 0.0, 2.0, 0.0, -1.0, 2.0), "West-up", id="west-up")),
        (pytest.param((1.0, 0.1, 0.0, 0.0, -1.0, 2.0), "Rotated", id="rotated")),
    ],
)
def test_stored_map_stack_rejects_unrepresentable_transforms(
    tmp_path, transform, message
):
    pytest.importorskip("rasterio")
    from affine import Affine

    raster_path = _write_stored_map_raster(
        tmp_path / f"{message.lower()}.tif",
        np.ones((2, 2), dtype="float32"),
        Affine(*transform),
    )

    with pytest.raises(ValueError, match=message):
        PrecipMrms.load_stored_map_stack(raster_path)


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


def test_combined_alignment_selects_interval_covering_hydraulic_time():
    source = pd.to_datetime(["2024-01-01 01:00", "2024-01-01 02:00"])
    target = pd.to_datetime(
        ["2024-01-01 00:30", "2024-01-01 01:00", "2024-01-01 01:05"]
    )

    indices, status = PrecipMrms._align_precipitation_frames(
        source,
        target,
        alignment="covering_interval",
        interval="1h",
        coverage_policy="error",
    )

    assert indices.tolist() == [0, 0, 1]
    assert status.tolist() == ["covering_interval"] * 3


def test_covering_interval_enforces_start_exclusive_end_inclusive():
    source = pd.to_datetime(["2024-01-01 01:00", "2024-01-01 02:00"])

    indices, _ = PrecipMrms._align_precipitation_frames(
        source,
        pd.DatetimeIndex([
            pd.Timestamp("2024-01-01 00:00") + pd.Timedelta(1, unit="ns"),
            pd.Timestamp("2024-01-01 01:00"),
            pd.Timestamp("2024-01-01 02:00"),
        ]),
        alignment="covering_interval",
        interval="1h",
        coverage_policy="error",
    )

    assert indices.tolist() == [0, 0, 1]
    with pytest.raises(ValueError, match="outside precipitation source coverage"):
        PrecipMrms._align_precipitation_frames(
            source,
            pd.to_datetime(["2024-01-01 00:00"]),
            alignment="covering_interval",
            interval="1h",
            coverage_policy="error",
        )


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (["2024-01-01 01:00", "2024-01-01 03:00"], "internal gap"),
        (["2024-01-01 01:00", "2024-01-01 01:30"], "overlap"),
    ],
)
def test_covering_interval_rejects_gaps_overlaps_and_irregular_cadence(
    source, message
):
    with pytest.raises(ValueError, match=message):
        PrecipMrms._align_precipitation_frames(
            pd.to_datetime(source),
            pd.to_datetime(["2024-01-01 01:15"]),
            alignment="covering_interval",
            interval="1h",
            coverage_policy="hold",
        )


@pytest.mark.parametrize("interval", ["0h", "-1h", pd.NaT])
def test_covering_interval_requires_finite_positive_duration(interval):
    with pytest.raises(ValueError, match="finite positive duration"):
        PrecipMrms._align_precipitation_frames(
            pd.to_datetime(["2024-01-01 01:00"]),
            pd.to_datetime(["2024-01-01 00:30"]),
            alignment="covering_interval",
            interval=interval,
        )


@pytest.mark.parametrize(
    "target",
    [
        ["2024-01-01 01:00", "2024-01-01 01:00"],
        ["2024-01-01 02:00", "2024-01-01 01:00"],
        ["2024-01-01 01:00", None],
    ],
)
def test_combined_alignment_requires_valid_ordered_unique_target_times(target):
    with pytest.raises(ValueError, match="target_times must"):
        PrecipMrms._align_precipitation_frames(
            pd.to_datetime(["2024-01-01 01:00", "2024-01-01 02:00"]),
            pd.to_datetime(target),
        )


def test_combined_alignment_rejects_empty_target_and_source_nat():
    with pytest.raises(ValueError, match="target_times must contain"):
        PrecipMrms._align_precipitation_frames(
            pd.to_datetime(["2024-01-01 01:00"]),
            pd.DatetimeIndex([]),
        )
    with pytest.raises(ValueError, match="source_times must contain only finite"):
        PrecipMrms._align_precipitation_frames(
            pd.DatetimeIndex([pd.NaT]),
            pd.to_datetime(["2024-01-01 01:00"]),
        )


def test_combined_alignment_distinguishes_hold_error_and_authorized_dry_tail():
    source = pd.to_datetime(["2024-01-01 01:00", "2024-01-01 02:00"])
    target = pd.to_datetime(["2024-01-01 00:30", "2024-01-01 02:30"])

    held, held_status = PrecipMrms._align_precipitation_frames(
        source,
        target,
        coverage_policy="hold",
    )
    assert held.tolist() == [0, 1]
    assert held_status.tolist() == ["held outside source coverage"] * 2

    with pytest.raises(ValueError, match="outside precipitation source coverage"):
        PrecipMrms._align_precipitation_frames(
            source,
            target,
            coverage_policy="error",
        )

    dry_indices, dry_status = PrecipMrms._align_precipitation_frames(
        source,
        pd.to_datetime(["2024-01-01 01:00", "2024-01-01 02:30"]),
        coverage_policy="dry_tail",
    )
    assert dry_indices.tolist() == [0, -1]
    assert dry_status.tolist() == ["latest_completed", "authorized dry tail"]

    with pytest.raises(ValueError, match="not before"):
        PrecipMrms._align_precipitation_frames(
            source,
            pd.to_datetime(["2024-01-01 00:30"]),
            coverage_policy="dry_tail",
        )


def test_combined_interval_amount_label_and_dry_tail_are_explicit(monkeypatch, tmp_path):
    pytest.importorskip("matplotlib")
    xr = pytest.importorskip("xarray")
    precip = xr.DataArray(
        np.array([[[25.4]], [[50.8]]], dtype="float32"),
        dims=("time", "y", "x"),
        coords={
            "time": pd.to_datetime(["2024-01-01 01:00", "2024-01-01 02:00"]),
            "y": [0.5],
            "x": [0.5],
        },
        attrs={
            "units": "mm",
            "crs": "EPSG:2871",
            "grid_bounds": (0.0, 1.0, 0.0, 1.0),
        },
    )
    flood = xr.DataArray(
        np.ones((2, 1, 1), dtype="float32"),
        dims=("time", "y", "x"),
        coords={
            "time": pd.to_datetime(["2024-01-01 01:05", "2024-01-01 02:30"]),
            "y": [0.5],
            "x": [0.5],
        },
        attrs={"crs": "EPSG:2871", "grid_bounds": (0.0, 1.0, 0.0, 1.0)},
    )
    captured = {}

    def capture(fig, update_func, frame_count, output_path, fps, dpi):
        artists = update_func(frame_count - 1)
        captured["precip"] = np.asarray(artists[0].get_array()).copy()
        captured["title"] = artists[-1].get_text()
        captured["labels"] = [axis.get_ylabel() for axis in fig.axes]
        Path(output_path).touch()

    monkeypatch.setattr(PrecipMrms, "_save_animation", staticmethod(capture))
    output = PrecipMrms.animate_combined(
        precip,
        flood,
        tmp_path / "combined.mp4",
        precip_value_semantics="interval_amount",
        precip_alignment="covering_interval",
        precip_interval="1h",
        coverage_policy="dry_tail",
    )

    assert output.exists()
    assert np.all(captured["precip"] == 0)
    assert "authorized dry tail" in captured["title"]
    assert "Precipitation interval amount (in)" in captured["labels"]


def test_public_combined_grid_route_rejects_internal_precipitation_gap(tmp_path):
    xr = pytest.importorskip("xarray")
    precip = xr.DataArray(
        np.ones((2, 2, 2), dtype="float32"),
        dims=("time", "y", "x"),
        coords={
            "time": pd.to_datetime(["2024-01-01 01:00", "2024-01-01 03:00"]),
            "y": [1.5, 0.5],
            "x": [0.5, 1.5],
        },
        attrs={"units": "mm", "crs": "EPSG:2871"},
    )
    flood = xr.DataArray(
        np.ones((1, 2, 2), dtype="float32"),
        dims=("time", "y", "x"),
        coords={
            "time": pd.to_datetime(["2024-01-01 01:30"]),
            "y": [1.5, 0.5],
            "x": [0.5, 1.5],
        },
        attrs={"crs": "EPSG:2871"},
    )

    with pytest.raises(ValueError, match="internal gap"):
        PrecipMrms.animate_combined(
            precip,
            flood,
            tmp_path / "gap.mp4",
            precip_value_semantics="interval_amount",
            precip_alignment="covering_interval",
            precip_interval="1h",
            coverage_policy="error",
        )


def test_public_combined_hdf_route_rejects_internal_precipitation_gap(
    monkeypatch, tmp_path
):
    xr = pytest.importorskip("xarray")
    precip = xr.DataArray(
        np.ones((2, 2, 2), dtype="float32"),
        dims=("time", "y", "x"),
        coords={
            "time": pd.to_datetime(["2024-01-01 01:00", "2024-01-01 03:00"]),
            "y": [1.5, 0.5],
            "x": [0.5, 1.5],
        },
        attrs={"units": "mm", "crs": "EPSG:2871"},
    )
    monkeypatch.setattr(
        PrecipMrms,
        "_load_hdf_flood_points",
        staticmethod(lambda **_: {
            "values": np.ones((1, 1), dtype=float),
            "times": pd.to_datetime(["2024-01-01 01:30"]),
            "x": np.array([0.5]),
            "y": np.array([0.5]),
            "units": "ft",
            "crs": "EPSG:2871",
        }),
    )

    with pytest.raises(ValueError, match="internal gap"):
        PrecipMrms.animate_combined(
            precip,
            tmp_path / "results.p01.hdf",
            tmp_path / "gap-hdf.mp4",
            precip_value_semantics="interval_amount",
            precip_alignment="covering_interval",
            precip_interval="1h",
            coverage_policy="error",
        )
