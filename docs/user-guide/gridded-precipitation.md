# Gridded Precipitation

Configure global gridded rainfall with `RasUnsteady`, then validate the solver-facing precipitation through HEC-RAS preprocessing and a completed simulation. Work on an isolated project copy and make input units, interval semantics, timestamps, and model clock explicit.

## Choose the input route

| Input | Public API | Result |
|---|---|---|
| Projected NetCDF | `RasUnsteady.set_gridded_precipitation()` | Meteorology configuration and native imported-raster HDF |
| Projected GeoTIFF bands/files | `RasUnsteady.set_gridded_precipitation_geotiff()` | Durable cumulative NetCDF plus native HDF |
| Projected GRIB/GRIB2 bands/files | `RasUnsteady.set_gridded_precipitation_grib()` | Durable cumulative NetCDF plus native HDF |
| Existing gridded DSS | `RasUnsteady.configure_gridded_dss_precipitation()` | Meteorology configuration referencing the supplied DSS family |

GeoTIFF and GRIB setters return `GriddedPrecipitationImportResult` with source hashes, cache location, translation route, qualification, and HDF receipt. The established NetCDF setter retains its `None` return contract. For lower-level array ingestion, use `RasPrecipGrid` and `RasPrecipHdf`.

Install dependencies from a terminal:

```console
uv pip install -e ".[precip]"
```

DSS product conversion may additionally need HEC-Vortex, HEC-MetVue, or the optional dependencies listed in the product notebook.

## Check version and route qualification

```python
from ras_commander import RasUnsteady

capabilities = RasUnsteady.get_gridded_precipitation_capabilities("6.6")
print(capabilities.qualification_for("geotiff"))
print(capabilities.qualification_for("dss"))
print(capabilities.notes)
```

Global gridded meteorology starts in HEC-RAS 6.0. The separate uniform-per-area boundary in 5.x is a different mechanism; translating to DSS does not add global gridded support. HEC-RAS 6.0–6.1 ignore the optional precipitation ratio, so the API rejects non-unit ratios. Native period-average timing can shift by one interval through 6.3.1; cumulative materialization avoids that source timing path.

Qualification applies to an exact release and input route. Prerelease versions do not inherit stable-release qualification. See the [version matrix](../development/gridded-precipitation-version-matrix.md) for actual runtime evidence and host limitations.

For NetCDF, the default `ras_commander` route (also named `native_hdf`)
qualifies the library-authored native HDF consumed by preprocessing. The
`native` route means HEC-RAS itself importing the GDAL file; its qualification
remains documentation-backed. `netcdf_hdf_qualification` and
`native_netcdf_qualification` report these separately. An `inconclusive`
receipt can mean either a blocked qualification run or an unresolved version;
inspect `hec_ras_version` and the accompanying warnings.

WPC QPF GRIB2 compression is not accepted by native HEC-RAS import through 7.0.1. Use DSS translation as demonstrated in notebook 926. `qpkit 0.1.0`'s `QPFGridOptions.extents` path produced an undersized 2-by-2 grid during qualification, so the notebook crops each source GRIB in its native projection, reopens and verifies it, and calls `kit.qpf_dss.write()` without `extents`. Generic GRIB ingestion requires an installed GDAL reader capable of decoding the selected bands and a grid meeting the requirements below.

## Direct GeoTIFF and GRIB ingestion

Assume `ras` is an initialized, copied project and unsteady file `03` is the intended target:

```python
receipt = RasUnsteady.set_gridded_precipitation_geotiff(
    "03",
    ["rain_1100.tif", "rain_1200.tif", "rain_1300.tif"],
    timestamps=["2024-08-09 11:00", "2024-08-09 12:00", "2024-08-09 13:00"],
    units="mm",
    value_type="amount",
    first_timestep_hours=1.0,
    interpolation="Bilinear",
    ras_object=ras,
)
print(receipt)
```

For a multiband file, pass one path and `bands=[1, 2, 3]`, with one timestamp per selected band. File order is caller-supplied. For GRIB, use `set_gridded_precipitation_grib()` with the same temporal arguments and explicitly selected precipitation bands. Review the product's accumulation semantics, including forecast resets.

These routes require north-up, unrotated, projected square cells and matching grids across the sequence. Reproject unsuitable sources deliberately before import. NoData fails by default; `nodata_policy="zero"` is an explicit choice only when missing pixels legitimately mean no rainfall. Negative rainfall and decreasing cumulative totals are rejected.

Use `source_timezone` and `model_timezone` together when converting clocks; otherwise supply timestamps already on the model clock. Cache reuse checks source bytes, interpretation settings, values, time, coordinates, projection, transform, and units. Keep the returned NetCDF in the model package for subsequent HEC-RAS saves/reimports.

## MRMS hourly QPE

`PrecipMrms.to_ras_netcdf()` writes the safe cumulative contract for hourly
MRMS QPE. It prepends a zero cumulative frame one interval before the first
valid time so HEC-RAS does not use the first nonzero amount as its datum. Pass
`end_time` to repeat the final cumulative surface through the plan end:

```python
from ras_commander.precip import PrecipMrms

mrms_netcdf = PrecipMrms.to_ras_netcdf(
    mrms_stack,
    ras.project_folder / "Precipitation" / "mrms_qpe.nc",
    first_timestep_hours=1.0,
    end_time=simulation_end,
)
RasUnsteady.set_gridded_precipitation(
    "03", mrms_netcdf, dataset_name="APCP_surface",
    units="mm", value_type="cumulative", ras_object=ras,
)
```

MRMS QPE valid times are interval-ending. A 10:00 QPE frame represents the
09:00–10:00 interval, so a simulation intended to include that frame must
start no later than 09:00. Notebook 924 demonstrates and verifies this timing
against the temporary and completed plan HDFs. Starting the plan at 10:00
correctly excludes that pre-simulation interval.

## AORC historical rainfall

Use the implemented `PrecipAorc.download()` API with WGS84 bounds or a supported extent input. Earlier documentation incorrectly advertised `retrieve_aorc_data()`, `extract_by_watershed()`, and `aggregate_to_interval()`; these are not public methods.

```python
from pathlib import Path
from ras_commander.precip import PrecipAorc

netcdf = PrecipAorc.download(
    bounds=(-77.71, 41.01, -77.25, 41.22),
    start_time="2024-08-09 11:00",
    end_time="2024-08-09 13:00",
    output_path=Path(ras.project_folder) / "Precipitation" / "aorc.nc",
    target_crs="EPSG:5070",
    resolution=2000.0,
)
RasUnsteady.set_gridded_precipitation(
    "03", netcdf, dataset_name="APCP_surface",
    units="mm", value_type="amount", first_timestep_hours=1.0,
    ras_object=ras,
)
```

AORC precipitation is the one-hour accumulation ending at its timestamp, in kg/m² liquid equivalent (numerically mm of water). See [NOAA's AORC methods, section 5.1](https://www.weather.gov/media/owp/operations/aorc_v1_1_methods.pdf). `PrecipAorc.download()` preserves the caller's hour-level bounds instead of expanding them to whole calendar days. `PrecipAorc.create_storm_plans()` uses these explicit semantics for cloned storm plans and requests its first AORC frame at `sim_start + 1 hour`, allowing the HDF authoring path to place a zero cumulative baseline at `sim_start`. Check timestamp continuity and source coverage; a gap is not a zero-rainfall observation. The first timestamp above represents 10:00–11:00, so a corresponding plan should start at 10:00.

Use `PrecipAorc.get_storm_catalog()` and `create_storm_plans()` for catalog workflows (notebooks 900 and 901). Notebook 900 executes one deterministic catalog event and verifies the exact forcing window, durable import HDF, temporary plan HDF, completed cell precipitation, hydraulic output, runtime messages, and BCO mass balance. Select the event, resolution, and model assumptions using source documentation and project requirements.

## Interval semantics

| `value_type` | Meaning | Example |
|---|---|---|
| `amount` | Depth during the interval ending at this timestamp | AORC hourly accumulation; MRMS hourly QPE |
| `rate` | Depth per hour over the interval | Atlas 14 ABM export in mm/hr |
| `cumulative` | Running depth total | Already accumulated forcing |

The explicit `units` argument is the **depth unit** (`"mm"` or `"in"`), including when `value_type="rate"`. The latter means depth per hour. Do not pass `units="mm/hr"` as the explicit depth-unit override.

`first_timestep_hours` is the HEC-RAS import dialog's First Timestep Duration. Without it, the first band establishes time zero and is not delivered; the library warns if this drops nonzero precipitation. A source containing an explicit zero baseline, such as the ABM export in notebook 727, should leave this argument `None`. Units describe the source, not the project's unit system; HEC-RAS converts during preprocessing.

## Gridded DSS handoff

```python
RasUnsteady.configure_gridded_dss_precipitation(
    "03",
    dss_filename="Precipitation/forecast.dss",
    dss_pathname=reviewed_dss_pathname,
    interpolation="Bilinear",
    ratio=1.0,
    ras_object=ras,
)
```

Use a cataloged pathname from the intended grid family and verify coverage, interval, units, and data type. `ratio=1.0` explicitly clears an inherited scale factor. This function configures the model; it does not create DSS grids. Notebook 728 demonstrates extending a forcing window with a derivative DSS file.

## Precompute and post-compute validation

```python
from ras_commander import RasPreprocess, RasCmdr, HdfResultsPlan, RasPlan
import h5py
import numpy as np

prepared = RasPreprocess.preprocess_plan("06", ras_object=ras, max_wait=600)
assert bool(prepared), prepared.error
with h5py.File(prepared.tmp_hdf_path, "r") as hdf:
    values = hdf["Event Conditions/Meteorology/Precipitation/Values"][:]
    times = hdf["Event Conditions/Meteorology/Precipitation/Timestamp"][:]
assert values.ndim == 2 and values.shape[0] == len(times)
assert np.isfinite(values).all() and np.max(values) > 0  # Expected wet event

result = RasCmdr.compute_plan(
    "06", ras_object=ras, force_rerun=True, verify=True,
    hdf_output_variables=["Cell Hydraulic Depth", "Cell Precipitation Rate",
                          "Cell Cumulative Precipitation Depth"],
)
assert bool(result), result
plan_hdf = str(RasPlan.get_plan_path("06", ras_object=ras)) + ".hdf"
print(HdfResultsPlan.get_compute_messages_hdf_only(plan_hdf))
```

The imported unsteady HDF is authoring evidence. The temporary plan HDF is the precompute source of truth, and the completed final plan HDF is the post-compute source of truth. Do not manually relocate datasets. Compare preprocessed interval depths/timestamps against intended forcing in project units, then inspect final per-cell rainfall and hydraulic response. The assertions above are basic wet-event checks, not a volume or coverage proof. Manual review of all runtime messages and rainfall/result maps remains advisable.

## Examples and scope

| Notebook | Demonstration |
|---|---|
| 727 | Atlas 14 spatial/uniform comparison, figures, precompute checks, compute diagnostics, hydraulic results |
| 728 | Model-covering DSS derivative with source-hash preservation, three explicit dry intervals, temporary/final HDF plateau checks, HEC-RAS 7.0 compute, and hydraulic figure |
| 729 | Direct GeoTIFF on RasExamples, temporary HDF, final rainfall/hydraulic response, figures |
| 900 / 901 | AORC catalog and plan creation with precompute checks |
| 914 | Archived 48-hour AORC event with source-to-temporary/final-HDF checks, hydraulic diagnostics, and a timezone-correct USGS stage comparison; explicitly diagnostic rather than calibration validation because historical boundaries and operations are not bundled |
| 915 | Executed forecast orchestration/readiness guide with a timezone-explicit cycle manifest, current API-signature checks, and a visual audit of the canonical HRRR, STOFS-3D, MRMS, and WPC artifacts; not independent format/version qualification |
| 916 | Archived HRRR 15Z forecast to 18 native DSS grids; no-rain/forecast compute, temporary and final HDF forcing checks, active-cell spatial comparison, hydraulic response, convergence map, and manual diagnostics |
| 917 | Two archived MRMS events: spatial DSS catalog/map inspection followed by an intentionally area-averaged precipitation-boundary comparison, exact final-HDF forcing checks, runtime diagnostics, hydraulic/pump figures, and animations; not global gridded qualification |
| 924 | MRMS NetCDF rain-on-grid with precompute and final model checks |
| 926 | Complete current WPC cycle, verified native-projection crop, 28-grid DSS catalog, objective wettest 24-hour window, temporary/final HDF forcing checks, no-rain/event HEC-RAS 7.0 runs, hydraulic/convergence figures, and manual diagnostics |

Notebook 722 directs readers to the implemented Atlas 14 workflow instead of obsolete placeholders and raw meteorology edits. Updated source cells do not imply every live product was rerun on every HEC-RAS release; the version matrix records actual evidence.
