# Coastal water levels and stage authoring

Use `CoastalBoundary.extract_wse_at_point()` to inspect NOAA STOFS-3D-Atlantic station water levels. The returned `datetime`, `wse_m` and `wse_ft` columns describe the same source elevations; changing meters to feet does **not** transform the vertical datum.

```python
from ras_commander.boundaries import CoastalBoundary

files = CoastalBoundary.download_stofs3d("working/stofs-current", file_type="points")
wse = CoastalBoundary.extract_wse_at_point(files[0], lat=29.35, lon=-94.77)
print(wse.attrs["source_datum"])
print(wse.attrs["datum_evidence"])
```

Keep each downloaded cycle in a separate directory: the NOAA filename contains the cycle hour but not the date. Pass an exact file path to extraction when retaining multiple cycles. `units` accepts only `"feet"` and `"meters"`; extraction retains both columns for compatibility. Meter units must be declared in the source NetCDF. Peak-only `maxele` output is not a stage time series.

## Product version and datum

STOFS-3D-Atlantic runs daily at **12 UTC**, with **24 hours of nowcast and up to 96 hours of forecast**. Station output is at six-minute intervals. See the [NOAA product description](https://repository.library.noaa.gov/view/noaa/71553) for schedule and [NOAA's operational configuration](https://polar.ncep.noaa.gov/estofs/atl.htm) for current output details.

NOAA implemented v3.1 at the August 17, 2026 12 UTC cycle. Station NetCDF then changed to **local mean sea level (LMSL)**; gridded output remains **xGEOID20b** and station SHEF remains **MLLW**. Archived products can differ. The real April 2026 sample used in notebook 923 explicitly declares NAVD88 in its `zeta` attributes. That archive does not establish the datum of a current download.

The extractor preserves recognized datum metadata in `wse.attrs`. When the file does not identify a supported datum, it returns `source_datum="unknown"` with a warning. A caller who independently verifies the product may supply `source_datum=`; contradictory recognized file metadata raises an error. The API does not infer datum from coordinates, filename or today's product description.

## Experimental stage-file authoring

`generate_stage_bc()` is an **experimental file-authoring helper**. It replaces an existing inline stage table at an unambiguous boundary, validates regular time spacing, and writes values in the chosen units. It does not establish model suitability, perform a geodetic transformation, synchronize the plan or hydrograph start date, or execute/validate HEC-RAS. Use a working copy and configure those model settings with the `RasUnsteady` and `RasPlan` APIs before computing.

```python
# Only after independently verifying the model and source use the same datum:
CoastalBoundary.generate_stage_bc(
    wse, "working/model/Model.u01", "Downstream",
    units="meters",
    target_datum=wse.attrs["source_datum"],
    datum_adjustment_ft=0.0,
)
```

`datum_adjustment_ft` is always in **feet**, including when `units="meters"`. The helper adds that offset after converting it to the output units: a +1 ft offset adds +0.3048 m to meter elevations. Positive offsets increase the written stage.

For different known source and target datums, provide an independently established local correction and describe its source in `datum_adjustment_source=`. This is a caller-supplied additive correction, not a general NAVD88/LMSL/MLLW transformation; a location-independent offset may be unsuitable. A verified zero correction between differing labels also requires provenance. Unknown source datum with a specified target is rejected. Legacy calls without `target_datum` still write with a warning that the target is unverified.

The helper requires an existing inline `Stage Hydrograph` and rejects DSS-active targets, ambiguous locations, invalid units, nonfinite elevations and irregular timestamps. Use `RasUnsteady` to configure boundary type/DSS state first. The API does not check that selected units match the HEC-RAS project: the caller must verify that contract.

Notebook [923](../examples/index.md) retains authentic extraction and unit-conversion output from the archived NOAA sample. Its plots show source water levels, not results of a fresh coastal HEC-RAS simulation. Tests cover metadata, arithmetic, rejection paths and stage-table serialization; they do not qualify a hydraulic forecast.
