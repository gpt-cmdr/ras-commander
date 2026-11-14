"""Notebook 731's native DSS export route, without Java.

Notebook 731 writes a shared-pattern Atlas 14 design storm to a Float32 interval NetCDF on the
model clock, then projects it to SHG DSS. Its ``DSS_EXPORT_ROUTE = "native"`` option runs the
``ras-commander-fast-dss`` gridded importer instead of HEC-Vortex. This test builds the same
NetCDF from NOAA's published Texas region 3 temporal curve, runs the importer with the notebook's
arguments, and reads every record back through ``RasDss`` on the native backend.

A run of the notebook itself on a public example (NewOrleansMetro with NOAA's Volume 9 grid)
wrote 144 records equal cell for cell to the HEC-Vortex 0.13.3 route; that run is recorded in
the notebook qualification report, not here, because it needs downloaded NOAA data and Vortex.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

xr = pytest.importorskip("xarray")
pytest.importorskip("hms_commander")
gridded = pytest.importorskip("ras_commander_fast_dss.gridded")

from ras_commander import RasDss  # noqa: E402
from ras_commander.dss import _backend  # noqa: E402
from ras_commander.precip.Atlas14HyetographGrid import Atlas14HyetographGrid  # noqa: E402

pytestmark = pytest.mark.skipif(
    not callable(getattr(gridded, "import_gridded", None)),
    reason="ras-commander-fast-dss has no gridded importer",
)

OFFICIAL_TEMPORAL_CSV = Path(__file__).parent / "data" / "atlas14_temporal" / "tx_3_24h_temporal.csv"
SIMULATION_START = datetime(2024, 10, 2, 0, 0)
DURATION_HOURS, INTERVAL_MINUTES = 24, 30
PARTS = {"A": "SHG", "B": "DESIGN", "C": "PRECIPITATION", "F": "ATLAS14_SHARED"}


def _storm(tmp_path: Path) -> xr.Dataset:
    cache = tmp_path / "atlas14-cache"
    cache.mkdir()
    (cache / "tx_3_24h_temporal.csv").write_text(OFFICIAL_TEMPORAL_CSV.read_text(encoding="utf-8"), encoding="utf-8")
    # A 0.30 by 0.30 degree NOAA-like depth grid (30 arc-second cells) with a smooth gradient and
    # one missing cell, so the warp sees an edge and a hole.
    x = -95.30 + 0.0083333 * (np.arange(36) + 0.5)
    y = 29.90 - 0.0083333 * (np.arange(36) + 0.5)
    depth = 14.0 + 0.04 * np.add.outer(np.arange(36), np.arange(36)) / 2.0
    depth[20, 5] = np.nan
    nc = Atlas14HyetographGrid.generate_from_depth_grid(
        depth, x=x, y=y, source_crs="EPSG:4269", ari_years=100,
        storm_duration_hours=DURATION_HOURS, timestep_minutes=INTERVAL_MINUTES,
        state="tx", region=3, quartile="All Cases", probability_column="50%",
        output_netcdf=tmp_path / "shared_pattern_native.nc", cache_dir=cache,
        depth_frequency_basis="PDS",
    )
    with xr.open_dataset(nc, engine="scipy", decode_times=False) as opened:
        return opened.load()


def _model_clock_float32(storm: xr.Dataset, path: Path) -> Path:
    """Notebook 731 section 4, for a plan that ends with the storm."""
    forcing = storm[["precip_incremental", "time_bounds", "spatial_ref"]].copy(deep=True)
    forcing["precip_incremental"] = forcing.precip_incremental.astype("float32")
    forcing.precip_incremental.attrs.update(
        units="in", cell_methods="time: sum", long_name="precipitation",
        standard_name="lwe_thickness_of_precipitation_amount", grid_mapping="spatial_ref",
    )
    clock = "hours since " + SIMULATION_START.strftime("%Y-%m-%d %H:%M:%S")
    forcing.time.attrs.update(units=clock, calendar="standard", bounds="time_bounds", axis="T", standard_name="time")
    forcing.time_bounds.attrs.update(units=clock, calendar="standard")
    forcing.to_netcdf(path, engine="scipy")
    return path


@pytest.fixture
def native_backend(monkeypatch):
    monkeypatch.delenv(_backend.ENV_VAR, raising=False)
    monkeypatch.setattr(RasDss, "backend", "native")

    def _no_jvm():
        raise AssertionError("the native route must not configure the JVM")

    monkeypatch.setattr(RasDss, "_configure_jvm", staticmethod(_no_jvm))


def test_notebook_731_native_route_keeps_intervals_units_and_shared_curve(tmp_path, native_backend):
    storm = _storm(tmp_path)
    fractions = storm.temporal_fraction.values
    float32_nc = _model_clock_float32(storm, tmp_path / "shared_pattern_float32_model_clock.nc")
    dss_path = tmp_path / "shared_pattern_shg.dss"

    # The notebook's call, argument for argument.
    imported = gridded.import_gridded(
        [float32_nc], dss_path, variable="precip_incremental",
        target_crs="SHG", cell_size=2000, method="bilinear", parts=PARTS, align="vortex",
    )
    assert len(imported.records) == len(fractions) == DURATION_HOURS * 60 // INTERVAL_MINUTES

    catalog = RasDss.get_catalog(dss_path)
    frames = sorted((RasDss.read_grid(dss_path, p) for p in catalog.pathname), key=lambda f: f["start_time"])
    assert len(frames) == len(fractions)
    step = timedelta(minutes=INTERVAL_MINUTES)
    for i, frame in enumerate(frames):
        assert pd.Timestamp(frame["start_time"]) == SIMULATION_START + i * step
        assert pd.Timestamp(frame["end_time"]) == SIMULATION_START + (i + 1) * step
        assert frame["units"].upper() == "IN" and frame["data_type"].upper() == "PER-CUM"
        assert frame["cell_size"] == 2000 and frame["shape"] == frames[0]["shape"]
        assert frame["metadata"]["origin"] == frames[0]["metadata"]["origin"]
        parts = frame["pathname"].strip("/").split("/")
        assert (parts[0], parts[1], parts[2], parts[5]) == ("SHG", "DESIGN", "PRECIPITATION", "ATLAS14_SHARED")

    values = np.stack([frame["data"] for frame in frames]).astype(np.float64)
    finite = np.isfinite(values[0])
    assert finite.sum() > 20, "the warp left too few valid cells to test"
    np.testing.assert_array_equal(np.isfinite(values), np.broadcast_to(finite, values.shape))
    assert np.nanmin(values) >= 0
    # The notebook's own tolerance: Float32 storage and reprojection, one shared curve.
    total = values[:, finite].sum(axis=0)
    np.testing.assert_allclose(values[:, finite], fractions[:, None] * total[None, :], rtol=5e-6, atol=1e-7)
    assert 13.5 < float(total.min()) and float(total.max()) < 16.0


def test_notebook_731_native_route_refuses_the_unsnapped_origin_by_default(tmp_path):
    storm = _storm(tmp_path)
    float32_nc = _model_clock_float32(storm, tmp_path / "forcing.nc")
    errors = pytest.importorskip("ras_commander_fast_dss.exceptions")
    with pytest.raises(errors.DssUnsupportedRecordError, match="not on whole cells"):
        gridded.import_gridded(
            [float32_nc], tmp_path / "refused.dss", variable="precip_incremental",
            target_crs="SHG", cell_size=2000, method="bilinear", parts=PARTS,
        )
    assert not (tmp_path / "refused.dss").exists()
