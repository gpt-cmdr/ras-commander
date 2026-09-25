"""
Tests for RasPrecipHdf and the gridded-precipitation paths of RasUnsteady.

Expected values come from HEC-RAS itself: chunk shapes measured on native imports
(HEC-RAS 6.3.1 and 6.4.1), the accumulation example produced by running HEC-RAS's
own H5RasterWriter, and the unit / data-type vocabulary of its precipitation
parser. The native-parity test at the bottom needs the UPGU3 specimens and is
skipped unless RAS_COMMANDER_PRECIP_SPECIMEN_DIR points at them.
"""

import logging
import os
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import PrecipRasterImportResult, RasPrecipHdf, RasUnsteady

PRECIP_LOGGER = "ras_commander.RasPrecipHdf"
UNSTEADY_LOGGER = "ras_commander.RasUnsteady"
IRD = "Event Conditions/Meteorology/Precipitation/Imported Raster Data"
WKT_5070 = (
    'PROJCS["NAD83 / Conus Albers",GEOGCS["NAD83",DATUM["North_American_Datum_1983",'
    'SPHEROID["GRS 1980",6378137,298.257222101]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433]],PROJECTION["Albers_Conic_Equal_Area"],'
    'UNIT["metre",1]]'
)


# --------------------------------------------------------------------- chunking

@pytest.mark.parametrize(
    "n_times, n_cells, values_chunks, vertical_chunks",
    [
        (240, 15300, (17, 15300), (240, 1093)),   # native HEC-RAS 6.3.1 import (UPGU3)
        (744, 222750, (1, 222750), (744, 353)),   # native HEC-RAS 6.4.1 import (Marcelinas)
        (5, 6, (5, 6), (5, 6)),                   # Davis fixture: both clamp to full extent
    ],
)
def test_chunking_matches_native_hecras(n_times, n_cells, values_chunks, vertical_chunks):
    assert RasPrecipHdf.get_values_chunks(n_times, n_cells) == values_chunks
    assert RasPrecipHdf.get_vertical_chunks(n_times, n_cells) == vertical_chunks


def test_values_chunk_exceeds_one_mib_for_wide_rows():
    # Above 262,144 float cells a single row is > 1 MiB; floor gives 0 and the max(1)
    # clamp keeps one row, so the chunk is larger than the target by design.
    rows, cols = RasPrecipHdf.get_values_chunks(100, 300_000)
    assert (rows, cols) == (1, 300_000)
    assert rows * cols * 4 > 1_048_576


@pytest.mark.parametrize("n_times, n_cells", [(0, 10), (10, 0), (-1, 10)])
def test_chunking_rejects_nonpositive_dimensions(n_times, n_cells):
    with pytest.raises(ValueError):
        RasPrecipHdf.get_values_chunks(n_times, n_cells)
    with pytest.raises(ValueError):
        RasPrecipHdf.get_vertical_chunks(n_times, n_cells)


# ------------------------------------------------------------------------ units

@pytest.mark.parametrize(
    "label, expected",
    [("kg/m^2", "mm"), ("[kg/m^2]", "mm"), ("[kg/(m^2)]", "mm"), ("MM", "mm"),
     ("millimeters", "mm"), ("in", "in"), ("Inches", "in"), (" inch ", "in")],
)
def test_normalize_units(label, expected):
    assert RasPrecipHdf.normalize_units(label) == expected


@pytest.mark.parametrize("label", ["", "   ", None])
def test_normalize_units_rejects_empty(label):
    with pytest.raises(ValueError):
        RasPrecipHdf.normalize_units(label)


@pytest.mark.parametrize(
    "data_type, units, legal",
    [
        ("cumulative", "in", True),
        ("cumulative", "mm", True),
        ("cumulative", "kg/m^2", False),   # legal only under per-cum
        ("per-cum", "kg/m^2", True),
        ("per-avg", "mm", False),          # rate data type needs a rate unit
        ("per-avg", "mm/hr", True),
        ("inst-val", "in/hr", True),
        ("cumulative", "ft", False),
    ],
)
def test_validate_data_type_units(data_type, units, legal):
    if legal:
        RasPrecipHdf.validate_data_type_units(data_type, units)
    else:
        with pytest.raises(ValueError):
            RasPrecipHdf.validate_data_type_units(data_type, units)


@pytest.mark.parametrize("data_type", ["", "per-sum", None])
def test_validate_data_type_units_rejects_unknown_data_type(data_type):
    with pytest.raises(ValueError):
        RasPrecipHdf.validate_data_type_units(data_type, "mm")


@pytest.mark.parametrize(
    "label, expected",
    [
        ("mm", "mm"), ("mm/hr", "mm"), ("mm h-1", "mm"), ("kg m-2", "mm"),
        ("kg/m^2", "mm"), ("in", "in"), ("in/hr", "in"), ("inches/hour", "in"),
        ("kg m-2 s-1", None),   # per-second flux: a different time base, not recognized
        ("m", None), ("", None), (None, None),
    ],
)
def test_infer_depth_units(label, expected):
    assert RasPrecipHdf.infer_depth_units(label) == expected


# ----------------------------------------------------------------- accumulation

HOURLY_DEPTHS = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32).reshape(5, 1, 1)
HOURLY_TIMES = pd.date_range("2020-01-01 01:00", periods=5, freq="h")


def test_to_cumulative_default_matches_import_dialog_and_warns(caplog):
    # HEC-RAS's writer on these depths with "First Timestep Duration" blank
    # stores [0, 2, 5, 9, 14]: the first band is the datum and is not delivered.
    with caplog.at_level(logging.WARNING, logger=PRECIP_LOGGER):
        cumulative, times = RasPrecipHdf.convert_to_cumulative(HOURLY_DEPTHS, HOURLY_TIMES, "amount")
    np.testing.assert_array_equal(cumulative.ravel(), [0, 2, 5, 9, 14])
    assert len(times) == 5
    assert any("not delivered" in r.getMessage() for r in caplog.records)


def test_to_cumulative_first_timestep_hours_preserves_first_band():
    # Same writer with a leading band (the dialog's First Timestep Duration) stores
    # [0, 1, 3, 6, 10, 15]: n+1 rows, nothing lost.
    cumulative, times = RasPrecipHdf.convert_to_cumulative(
        HOURLY_DEPTHS, HOURLY_TIMES, "amount", first_timestep_hours=1.0
    )
    np.testing.assert_array_equal(cumulative.ravel(), [0, 1, 3, 6, 10, 15])
    assert times[0] == pd.Timestamp("2020-01-01 00:00")
    assert times[1:] == list(HOURLY_TIMES)


def test_to_cumulative_rate_weights_each_interval():
    rates = np.array([[[4.0]], [[4.0]]], dtype=np.float32)  # mm/hr
    times = pd.date_range("2020-01-01 00:15", periods=2, freq="15min")
    cumulative, _ = RasPrecipHdf.convert_to_cumulative(rates, times, "rate", first_timestep_hours=0.25)
    np.testing.assert_allclose(cumulative.ravel(), [0.0, 1.0, 2.0])


def test_to_cumulative_rate_default_ignores_first_band():
    # Mirrors the legacy RasUnsteady behaviour and test: band 0 carries no weight.
    rates = np.array([[[99.0, 99.0]], [[4.0, 8.0]], [[2.0, 4.0]]], dtype=np.float32)
    times = pd.to_datetime(["2020-01-01 00:00", "2020-01-01 00:15", "2020-01-01 00:45"])
    cumulative, _ = RasPrecipHdf.convert_to_cumulative(rates, times, "rate")
    np.testing.assert_allclose(cumulative[:, 0, :], [[0, 0], [1, 2], [2, 4]])


def test_to_cumulative_amount_and_rate_agree_only_for_hourly_data():
    values = np.array([[[3.0]], [[3.0]], [[3.0]]], dtype=np.float32)
    hourly = pd.date_range("2020-01-01", periods=3, freq="h")
    six_min = pd.date_range("2020-01-01", periods=3, freq="6min")
    amount_h, _ = RasPrecipHdf.convert_to_cumulative(values, hourly, "amount", first_timestep_hours=1.0)
    rate_h, _ = RasPrecipHdf.convert_to_cumulative(values, hourly, "rate", first_timestep_hours=1.0)
    np.testing.assert_allclose(amount_h, rate_h)
    amount_6, _ = RasPrecipHdf.convert_to_cumulative(values, six_min, "amount", first_timestep_hours=0.1)
    rate_6, _ = RasPrecipHdf.convert_to_cumulative(values, six_min, "rate", first_timestep_hours=0.1)
    np.testing.assert_allclose(rate_6, amount_6 * 0.1, rtol=1e-6)


def test_to_cumulative_passes_cumulative_through():
    data = np.array([[[0.0]], [[2.0]], [[3.0]]], dtype=np.float32)
    times = pd.date_range("2020-01-01", periods=3, freq="h")
    cumulative, out_times = RasPrecipHdf.convert_to_cumulative(data, times, "cumulative")
    np.testing.assert_array_equal(cumulative, data)
    assert len(out_times) == 3


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(value_type="depth"),
        dict(value_type="amount", first_timestep_hours=0),
        dict(value_type="amount", first_timestep_hours=-1.0),
        dict(value_type="cumulative", first_timestep_hours=1.0),
    ],
)
def test_to_cumulative_rejects_invalid_arguments(kwargs):
    with pytest.raises(ValueError):
        RasPrecipHdf.convert_to_cumulative(HOURLY_DEPTHS, HOURLY_TIMES, **kwargs)


def test_to_cumulative_rejects_non_increasing_times():
    times = pd.to_datetime(["2020-01-01 01:00", "2020-01-01 01:00"])
    with pytest.raises(ValueError, match="strictly increasing"):
        RasPrecipHdf.convert_to_cumulative(HOURLY_DEPTHS[:2], times, "amount")


# ------------------------------------------------------------------------- grid

def test_orient_north_up_flips_south_first_and_east_first_sources():
    # y ascending (south first), x descending (east first)
    values = np.array([[[1, 2], [3, 4]]], dtype=np.float32)  # rows: y=0.5, y=1.5
    x = np.array([10.5, 9.5])
    y = np.array([0.5, 1.5])
    oriented, x_out, y_out = RasPrecipHdf.orient_north_up(values, x, y)
    np.testing.assert_array_equal(oriented[0], [[4, 3], [2, 1]])
    np.testing.assert_array_equal(y_out, [1.5, 0.5])
    np.testing.assert_array_equal(x_out, [9.5, 10.5])


def test_orient_north_up_leaves_north_up_source_unchanged():
    values = np.arange(6, dtype=np.float32).reshape(1, 2, 3)
    oriented, _, _ = RasPrecipHdf.orient_north_up(values, [0.5, 1.5, 2.5], [1.5, 0.5])
    np.testing.assert_array_equal(oriented, values)


def test_grid_from_coords_returns_cell_edges():
    left, top, cellsize, rows, cols = RasPrecipHdf.get_grid_from_coords(
        [1000.0, 3000.0, 5000.0], [2000.0, 0.0]
    )
    # Values verified against the Davis GUI import: Raster Left 0.0, Raster Top 3000.0
    assert (left, top, cellsize, rows, cols) == (0.0, 3000.0, 2000.0, 2, 3)


def test_grid_from_coords_rejects_non_square_and_irregular_grids():
    with pytest.raises(ValueError, match="not square"):
        RasPrecipHdf.get_grid_from_coords([0.5, 1.5, 2.5], [0.0, 2.0])
    with pytest.raises(ValueError, match="regularly spaced"):
        RasPrecipHdf.get_grid_from_coords([0.0, 1.0, 3.0], [0.0, 1.0])


def test_grid_from_coords_rejects_non_monotonic_coordinates():
    # Equal absolute spacing but out of order: would otherwise place cells wrongly.
    with pytest.raises(ValueError, match="monotonic"):
        RasPrecipHdf.get_grid_from_coords([0.5, 1.5, 0.5], [0.5, 1.5])


def test_grid_from_coords_single_cell_needs_default(caplog):
    with pytest.raises(ValueError, match="1 x 1"):
        RasPrecipHdf.get_grid_from_coords([0.5], [0.5])
    with caplog.at_level(logging.WARNING, logger=PRECIP_LOGGER):
        left, top, cellsize, _, _ = RasPrecipHdf.get_grid_from_coords(
            [0.5], [0.5], default_cell_size=2000.0
        )
    assert cellsize == 2000.0
    assert (left, top) == (0.5 - 1000.0, 0.5 + 1000.0)
    assert any("1 x 1" in r.getMessage() for r in caplog.records)


# ----------------------------------------------------------------------- writer

def _cumulative(n_times, rows, cols):
    increments = np.ones((n_times, rows, cols), dtype=np.float32)
    increments[0] = 0.0
    return np.cumsum(increments, axis=0, dtype=np.float32)


def _write(path, data, times=None, **overrides):
    if times is None:
        times = pd.date_range("2020-01-01", periods=data.shape[0], freq="h")
    kwargs = dict(
        raster_left=-1000.0, raster_top=5000.0, cell_size=250.0,
        projection=WKT_5070, units="in", require_met_bc_block=False,
    )
    kwargs.update(overrides)
    return RasPrecipHdf.write_gridded_precip_raster(
        path, data, times, kwargs.pop("raster_left"), kwargs.pop("raster_top"),
        kwargs.pop("cell_size"), kwargs.pop("projection"), kwargs.pop("units"), **kwargs
    )


def test_writer_reproduces_native_storage_layout(tmp_path):
    data = _cumulative(20, 40, 1000)  # 40,000 cells: Values chunks split in time
    hdf = tmp_path / "Model.u01.hdf"
    result = _write(hdf, data)

    assert isinstance(result, PrecipRasterImportResult) and result
    assert result.created_hdf and not result.skipped and not result.dry_run
    assert result.shape == (20, 40_000)
    assert result.values_chunks == (6, 40_000)       # floor(1048576 / 160000)
    assert result.vertical_chunks == (20, 13_108)    # ceil(1048576 / 80)

    with h5py.File(hdf, "r") as f:
        group = f[IRD]
        assert set(group.keys()) == {"Values", "Values (Vertical)"}
        assert dict(group.attrs) == {}
        expected_flat = data.reshape(20, 40_000)
        for name, chunks in (("Values", (6, 40_000)), ("Values (Vertical)", (20, 13_108))):
            ds = group[name]
            assert ds.dtype == np.dtype("<f4")
            assert ds.shape == (20, 40_000)
            assert ds.chunks == chunks
            assert ds.maxshape == (None, None)
            assert ds.compression == "gzip" and ds.compression_opts == 1
            assert ds.shuffle is False and ds.fletcher32 is False
            assert np.isnan(ds.fillvalue)
            np.testing.assert_array_equal(ds[...], expected_flat)

        attrs = group["Values"].attrs
        assert set(attrs.keys()) == {
            "NoData", "Raster Rows", "Raster Cols", "Raster Left", "Raster Top",
            "Raster Cellsize", "Storage Configuration", "GUID", "Version", "Times",
            "Time Series Data Type", "Rate Time Units", "Units", "Data Type", "Projection",
        }
        assert attrs["Raster Rows"] == np.int32(40) and type(attrs["Raster Rows"]) is np.int32
        assert attrs["Raster Cols"] == np.int32(1000)
        assert type(attrs["Raster Left"]) is np.float64 and attrs["Raster Left"] == -1000.0
        assert type(attrs["NoData"]) is np.float32 and attrs["NoData"] == -9999.0
        assert attrs["Times"].dtype == np.dtype("S19") and len(attrs["Times"]) == 20
        assert attrs["Times"][0] == b"2020-01-01 00:00:00"
        # Exact case matters: HEC-RAS matches this ordinally and reads anything else as Rate.
        assert attrs["Time Series Data Type"] == b"Amount"
        assert attrs["Units"] == b"in"
        assert attrs["Data Type"] == b"cumulative"
        assert attrs["Storage Configuration"] == b"Sequential"
        assert attrs["Version"] == b"1.0"
        assert attrs["Rate Time Units"] == b"Hour"
        assert attrs["GUID"] == group["Values (Vertical)"].attrs["GUID"]
        assert len(attrs["GUID"]) == 36


def test_writer_omits_nodata_and_projection_when_none(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger=PRECIP_LOGGER):
        _write(tmp_path / "M.u01.hdf", _cumulative(3, 2, 2), nodata=None, projection=None)
    with h5py.File(tmp_path / "M.u01.hdf", "r") as f:
        keys = set(f[IRD]["Values"].attrs.keys())
    assert "NoData" not in keys and "Projection" not in keys
    assert len(keys) == 13
    assert any("No projection" in r.getMessage() for r in caplog.records)


def test_writer_normalizes_kg_per_m2_to_mm(tmp_path):
    result = _write(tmp_path / "M.u01.hdf", _cumulative(3, 2, 2), units="kg/m^2")
    assert result.units == "mm"
    with h5py.File(tmp_path / "M.u01.hdf", "r") as f:
        assert f[IRD]["Values"].attrs["Units"] == b"mm"


@pytest.mark.parametrize("units", ["mm/hr", "ft", ""])
def test_writer_rejects_units_hecras_cannot_load(tmp_path, units):
    with pytest.raises(ValueError):
        _write(tmp_path / "M.u01.hdf", _cumulative(3, 2, 2), units=units)
    assert not (tmp_path / "M.u01.hdf").exists()


def test_writer_rejects_bad_shape_and_times(tmp_path):
    hdf = tmp_path / "M.u01.hdf"
    with pytest.raises(ValueError, match="3-D"):
        _write(hdf, np.zeros((3, 4), dtype=np.float32))
    with pytest.raises(ValueError, match="entries"):
        _write(hdf, _cumulative(3, 2, 2), times=pd.date_range("2020-01-01", periods=2, freq="h"))
    with pytest.raises(ValueError, match="cell_size"):
        _write(hdf, _cumulative(3, 2, 2), cell_size=0.0)


def test_writer_warns_when_first_row_is_not_the_datum(tmp_path, caplog):
    data = _cumulative(3, 2, 2) + 1.0
    with caplog.at_level(logging.WARNING, logger=PRECIP_LOGGER):
        _write(tmp_path / "M.u01.hdf", data)
    assert any("never delivered" in r.getMessage() for r in caplog.records)


def test_writer_requires_met_bc_block_for_durability(tmp_path):
    hdf = tmp_path / "M.u01.hdf"
    data = _cumulative(3, 2, 2)

    with pytest.raises(FileNotFoundError):
        _write(hdf, data, require_met_bc_block=True)

    (tmp_path / "M.u01").write_text("Flow Title=x\nPrecipitation Mode=Disable\n", encoding="utf-8")
    with pytest.raises(ValueError, match="destroyed on the next save"):
        _write(hdf, data, require_met_bc_block=True)
    assert not hdf.exists()

    (tmp_path / "M.u01").write_text(
        "Flow Title=x\nPrecipitation Mode=Enable\nMet BC=Precipitation|Mode=Gridded\n",
        encoding="utf-8",
    )
    assert _write(hdf, data, require_met_bc_block=True)


def test_writer_supports_precipitation_only(tmp_path):
    with pytest.raises(ValueError, match="precipitation"):
        _write(tmp_path / "M.u01.hdf", _cumulative(3, 2, 2), met_variable="Wind Speed")
    assert not (tmp_path / "M.u01.hdf").exists()


def test_writer_rejects_non_ascii_projection(tmp_path):
    with pytest.raises(ValueError, match="ASCII"):
        _write(tmp_path / "M.u01.hdf", _cumulative(3, 2, 2), projection='PROJCS["Réseau"]')
    assert not (tmp_path / "M.u01.hdf").exists()


def test_writer_does_not_modify_callers_array(tmp_path):
    values = np.array([[[1.0]], [[2.0]]], dtype=np.float32)
    snapshot = values.copy()
    RasPrecipHdf.convert_to_cumulative(values, pd.date_range("2020-01-01", periods=2, freq="h"),
                                       "amount", first_timestep_hours=1.0)
    np.testing.assert_array_equal(values, snapshot)


def test_writer_dry_run_writes_nothing(tmp_path):
    hdf = tmp_path / "M.u01.hdf"
    result = _write(hdf, _cumulative(4, 3, 3), dry_run=True)
    assert result.dry_run and result.success
    assert result.values_chunks == (4, 9)
    assert not hdf.exists()


def test_writer_overwrite_false_skips_existing_payload(tmp_path):
    hdf = tmp_path / "M.u01.hdf"
    _write(hdf, _cumulative(3, 2, 2))
    second = _write(hdf, _cumulative(5, 2, 2), overwrite=False)
    assert second.skipped and not second.created_hdf
    with h5py.File(hdf, "r") as f:
        assert f[IRD]["Values"].shape == (3, 4)

    replaced = _write(hdf, _cumulative(5, 2, 2), overwrite=True)
    assert not replaced.skipped
    with h5py.File(hdf, "r") as f:
        assert f[IRD]["Values"].shape == (5, 4)


def test_writer_default_does_not_overwrite(tmp_path):
    hdf = tmp_path / "M.u01.hdf"
    _write(hdf, _cumulative(3, 2, 2))
    assert _write(hdf, _cumulative(5, 2, 2)).skipped


def test_writer_preserves_other_hdf_content(tmp_path):
    hdf = tmp_path / "M.u01.hdf"
    with h5py.File(hdf, "w") as f:
        f.create_dataset("Event Conditions/Unsteady/Keep", data=[1, 2, 3])
    result = _write(hdf, _cumulative(3, 2, 2))
    assert not result.created_hdf
    with h5py.File(hdf, "r") as f:
        np.testing.assert_array_equal(f["Event Conditions/Unsteady/Keep"][...], [1, 2, 3])
        assert IRD in f


# ----------------------------------------------------------- RasUnsteady facade

MINIMAL_U01 = (
    "Flow Title=test\n"
    "Program Version=6.31\n"
    "Use Restart= 0 \n"
    "Precipitation Mode=Disable\n"
    "Met BC=Precipitation|Mode=None\n"
    "Met BC=Precipitation|Expanded View=-1\n"
    "{ratio_line}"
    "Met BC=Precipitation|Gridded Source=DSS\n"
)


def _write_netcdf(path, values, times, x, y, units):
    xr = pytest.importorskip("xarray")
    ds = xr.Dataset(
        data_vars={
            "precipitation": (("time", "y", "x"), np.asarray(values, dtype=np.float32),
                              {"units": units, "grid_mapping": "spatial_ref"}),
            "spatial_ref": ((), np.int32(0), {"spatial_ref": WKT_5070, "crs_wkt": WKT_5070}),
        },
        coords={"time": pd.to_datetime(times), "x": np.asarray(x, dtype=np.float64),
                "y": np.asarray(y, dtype=np.float64)},
    )
    ds.to_netcdf(path, engine="netcdf4")
    return path


def _project(tmp_path, ratio_line=""):
    (tmp_path / "Precipitation").mkdir()
    u01 = tmp_path / "Model.u01"
    u01.write_text(MINIMAL_U01.format(ratio_line=ratio_line), encoding="utf-8")
    ras_object = SimpleNamespace(
        project_folder=tmp_path, project_name="Model", check_initialized=lambda: None
    )
    return u01, ras_object


def _two_cell_netcdf(tmp_path, units="in"):
    return _write_netcdf(
        tmp_path / "Precipitation" / "storm.nc",
        values=[[[1.0, 2.0]], [[3.0, 4.0]], [[5.0, 6.0]]],
        times=["2020-01-01 00:06", "2020-01-01 00:12", "2020-01-01 00:18"],
        x=[1000.0, 3000.0], y=[500.0], units=units,
    )


def test_set_gridded_precipitation_writes_units_ratio_and_creates_hdf(tmp_path):
    u01, ras_object = _project(tmp_path)
    _two_cell_netcdf(tmp_path)

    RasUnsteady.set_gridded_precipitation(
        u01, "Precipitation/storm.nc", interpolation="Nearest", ras_object=ras_object,
        units="in", value_type="amount", first_timestep_hours=0.1, ratio=1.0,
    )

    text = u01.read_text(encoding="utf-8")
    assert "Met BC=Precipitation|Gridded Source=GDAL Raster File(s)" in text
    assert "Met BC=Precipitation|Ratio=1\n" in text
    lines = text.splitlines()
    assert lines.index("Met BC=Precipitation|Ratio=1") == \
        lines.index("Met BC=Precipitation|Expanded View=-1") + 1

    hdf = Path(str(u01) + ".hdf")
    assert hdf.exists()  # created, not skipped with a warning
    with h5py.File(hdf, "r") as f:
        values = f[IRD]["Values"]
        assert values.attrs["Units"] == b"in"
        assert values.shape == (4, 2)  # n+1 rows: first interval preserved
        np.testing.assert_allclose(values[...], [[0, 0], [1, 2], [4, 6], [9, 12]])
        assert f["Event Conditions/Meteorology/Precipitation"].attrs["Ratio"] == np.float32(1.0)


def test_set_gridded_precipitation_warns_about_existing_ratio(tmp_path, caplog):
    u01, ras_object = _project(tmp_path, ratio_line="Met BC=Precipitation|Ratio=0.8937\n")
    _two_cell_netcdf(tmp_path)
    with caplog.at_level(logging.WARNING, logger=UNSTEADY_LOGGER):
        RasUnsteady.set_gridded_precipitation(
            u01, "Precipitation/storm.nc", ras_object=ras_object, units="in",
            value_type="amount", first_timestep_hours=0.1,
        )
    assert "Met BC=Precipitation|Ratio=0.8937" in u01.read_text(encoding="utf-8")
    assert any("Ratio=0.8937" in r.getMessage() for r in caplog.records)


def test_set_gridded_precipitation_replaces_existing_ratio(tmp_path):
    u01, ras_object = _project(tmp_path, ratio_line="Met BC=Precipitation|Ratio=0.8937\n")
    _two_cell_netcdf(tmp_path)
    RasUnsteady.set_gridded_precipitation(
        u01, "Precipitation/storm.nc", ras_object=ras_object, units="in",
        value_type="amount", first_timestep_hours=0.1, ratio=1.0,
    )
    text = u01.read_text(encoding="utf-8")
    assert "Ratio=0.8937" not in text
    assert text.count("Met BC=Precipitation|Ratio=") == 1


@pytest.mark.parametrize(
    "kwargs, error",
    [
        (dict(units="mm/hr"), ValueError),
        (dict(ratio=0.0), ValueError),
        (dict(value_type="depth"), ValueError),
        (dict(first_timestep_hours=-2.0), ValueError),
        (dict(netcdf_path="Precipitation/missing.nc"), FileNotFoundError),
    ],
)
def test_set_gridded_precipitation_fails_before_touching_text(tmp_path, kwargs, error):
    u01, ras_object = _project(tmp_path)
    _two_cell_netcdf(tmp_path)
    before = u01.read_bytes()
    netcdf = kwargs.pop("netcdf_path", "Precipitation/storm.nc")
    kwargs = {"units": "in", **kwargs}
    with pytest.raises(error):
        RasUnsteady.set_gridded_precipitation(u01, netcdf, ras_object=ras_object, **kwargs)
    assert u01.read_bytes() == before
    assert not Path(str(u01) + ".hdf").exists()


def test_set_gridded_precipitation_rejects_unreadable_netcdf(tmp_path):
    # Previously the .u## was switched to GDAL Raster File(s) and the HDF import was
    # skipped with a warning, leaving the model configured for gridded precipitation
    # with no payload - a run with zero rain and no error.
    u01, ras_object = _project(tmp_path)
    placeholder = tmp_path / "Precipitation" / "storm.nc"
    placeholder.write_text("", encoding="utf-8")
    before = u01.read_bytes()
    with pytest.raises((ValueError, OSError)):
        RasUnsteady.set_gridded_precipitation(
            u01, "Precipitation/storm.nc", ras_object=ras_object
        )
    assert u01.read_bytes() == before
    assert not Path(str(u01) + ".hdf").exists()


def test_set_gridded_precipitation_rejects_units_contradicting_metadata(tmp_path):
    # The NetCDF declares inches; the default units="mm" would deliver it 25.4x small.
    u01, ras_object = _project(tmp_path)
    _two_cell_netcdf(tmp_path, units="in")
    before = u01.read_bytes()
    with pytest.raises(ValueError, match="25.4"):
        RasUnsteady.set_gridded_precipitation(
            u01, "Precipitation/storm.nc", ras_object=ras_object, value_type="amount",
            first_timestep_hours=0.1,
        )
    assert u01.read_bytes() == before
    assert not Path(str(u01) + ".hdf").exists()


def test_set_gridded_precipitation_rejects_missing_dataset_name(tmp_path):
    u01, ras_object = _project(tmp_path)
    _two_cell_netcdf(tmp_path)
    before = u01.read_bytes()
    with pytest.raises(ValueError, match="not found"):
        RasUnsteady.set_gridded_precipitation(
            u01, "Precipitation/storm.nc", ras_object=ras_object, units="in",
            dataset_name="APCP_surface",
        )
    assert u01.read_bytes() == before


def test_set_gridded_precipitation_hdf_failure_leaves_text_untouched(tmp_path, monkeypatch):
    # e.g. the HDF held open by RAS Mapper: the .u## must not be left pointing at
    # gridded precipitation with no payload behind it.
    u01, ras_object = _project(tmp_path)
    _two_cell_netcdf(tmp_path)
    before = u01.read_bytes()

    def _locked(*args, **kwargs):
        raise OSError("Unable to open file (file is locked)")

    monkeypatch.setattr(RasPrecipHdf, "write_gridded_precip_raster", staticmethod(_locked))
    with pytest.raises(OSError):
        RasUnsteady.set_gridded_precipitation(
            u01, "Precipitation/storm.nc", ras_object=ras_object, units="in",
            value_type="amount", first_timestep_hours=0.1,
        )
    assert u01.read_bytes() == before


def test_update_precipitation_hdf_invalid_units_leave_hdf_untouched(tmp_path):
    (tmp_path / "Precipitation").mkdir()
    nc = _two_cell_netcdf(tmp_path, units="mm")
    hdf = tmp_path / "Model.u01.hdf"
    with h5py.File(hdf, "w"):
        pass
    with pytest.raises(ValueError):
        RasUnsteady._update_precipitation_hdf(
            hdf_path=hdf, netcdf_path=nc, netcdf_rel_path=".\\Precipitation\\storm.nc",
            units="mm/hr",
        )
    with h5py.File(hdf, "r") as f:
        assert "Event Conditions" not in f


def test_read_netcdf_orients_south_first_source_north_up(tmp_path):
    (tmp_path / "Precipitation").mkdir()
    nc = _write_netcdf(
        tmp_path / "Precipitation" / "south_first.nc",
        values=[[[5.0], [7.0]], [[5.0], [7.0]]],   # y=0.5 (south) -> 5, y=1.5 (north) -> 7
        times=["2020-01-01 01:00", "2020-01-01 02:00"],
        x=[0.5], y=[0.5, 1.5], units="mm",
    )
    payload = RasUnsteady._read_netcdf_precipitation(nc, value_type="cumulative")
    assert payload["raster_top"] == 2.0
    np.testing.assert_array_equal(payload["cumulative"][:, 0, 0], [7.0, 7.0])
    np.testing.assert_array_equal(payload["cumulative"][:, 1, 0], [5.0, 5.0])


def test_read_netcdf_raises_for_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        RasUnsteady._read_netcdf_precipitation(tmp_path / "absent.nc")


# ------------------------------------------------ native HEC-RAS 6.3.1 parity

SPECIMEN_DIR = os.environ.get("RAS_COMMANDER_PRECIP_SPECIMEN_DIR")
_specimens = Path(SPECIMEN_DIR) if SPECIMEN_DIR else None


@pytest.mark.skipif(
    _specimens is None
    or not all((_specimens / n).exists() for n in ("UPGU3.p01.hdf", "UPGU3.u08.hdf", "UPGU3.u09.hdf")),
    reason="Set RAS_COMMANDER_PRECIP_SPECIMEN_DIR to a folder with the UPGU3 native specimens",
)
def test_reproduces_native_hecras_631_import(tmp_path):
    """
    UPGU3.u08 / .u09 were produced by the HEC-RAS 6.3.1 GUI importing the same NetCDF
    as inches and as millimetres. The source field is p01's materialized precipitation.
    """
    with h5py.File(_specimens / "UPGU3.p01.hdf", "r") as f:
        source = f["Event Conditions/Meteorology/Precipitation/Values"][...]
    with h5py.File(_specimens / "UPGU3.u08.hdf", "r") as f8, \
            h5py.File(_specimens / "UPGU3.u09.hdf", "r") as f9:
        native8, native9 = f8[IRD]["Values"], f9[IRD]["Values"]
        a = native8.attrs
        rows, cols = int(a["Raster Rows"]), int(a["Raster Cols"])
        times = pd.to_datetime([t.decode() for t in a["Times"]])

        # Units are the only difference between the two imports.
        np.testing.assert_array_equal(native8[...], native9[...])
        assert a["Units"] == b"in" and native9.attrs["Units"] == b"mm"

        cumulative, out_times = RasPrecipHdf.convert_to_cumulative(
            source.reshape(-1, rows, cols), times, "amount"
        )
        np.testing.assert_array_equal(cumulative.reshape(native8.shape), native8[...])

        out = tmp_path / "UPGU3.u08.hdf"
        RasPrecipHdf.write_gridded_precip_raster(
            out, cumulative, out_times, float(a["Raster Left"]), float(a["Raster Top"]),
            float(a["Raster Cellsize"]), a["Projection"].decode(), "in",
            nodata=None, require_met_bc_block=False,
        )
        with h5py.File(out, "r") as mine:
            for name in ("Values", "Values (Vertical)"):
                ours, theirs = mine[IRD][name], f8[IRD][name]
                assert ours.chunks == theirs.chunks
                assert ours.maxshape == theirs.maxshape
                assert (ours.compression, ours.compression_opts) == \
                    (theirs.compression, theirs.compression_opts)
                assert ours.dtype == theirs.dtype
                np.testing.assert_array_equal(ours[...], theirs[...])
            assert set(mine[IRD]["Values"].attrs.keys()) == set(a.keys())
