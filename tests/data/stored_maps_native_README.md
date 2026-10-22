# Native stored-map control

`stored_maps_native_manifest.json` pins one externally retained Ether Hollow
case mapped with HEC-RAS 7.0.1 on 2026-10-22. It contains metadata and hashes;
model data and generated rasters remain outside the repository.

Set `RAS_STORED_MAP_FIXTURE_ROOT` to the retained directory containing `project`
and `rasters`, then run:

```sh
python -m pytest tests/test_stored_maps_native_contract.py -q
```

Without the variable, tests skip explicitly. Configured missing or changed files
fail. Tests read files only; they never run a model or launch mapping helpers.
CI collection without fixtures does not establish native qualification.

## Native generation

The source was the retained twenty-minute Bingham Ether Hollow run with five
stored output times: 0, 5, 10, 15 and 20 minutes. A separate complete project copy
was mapped through `RasProcess.store_maps`, with explicit HEC-RAS 7.0.1,
`terrain_name="Terrain"`, `render_mode="horizontal"`, and a 180-second timeout
per helper call. No hydraulic computation was repeated. Threshold 0.5 uses the
model's vertical feet. Native helper and mapping-library hashes are pinned.

Three arrival/duration/percent rasters and four pairs of timestep WSE/depth
rasters were generated. The initial all-dry timestep returned an empty
dictionary. All 10,201 physical cells independently have initial WSE equal to
their native minimum elevation; ghost minima are NaN. Each helper call completed
in less than thirteen seconds. Execution receipts and scripts are retained with
the external corpus. Source and copied result HDF hashes remained unchanged.

All eleven output rasters have the selected terrain's exact grid, origin and
resolution, equivalent CRS, and NoData -9999. At all valid timestep pixels,
rendered WSE minus depth equals the registered terrain pixel. The independent
wetness oracle uses those native rendered depths with strict `depth > 0.5`,
not nearest-cell depth or a new hydraulic solution.

All three products have 21,292 valid pixels, exactly the union of wet output
samples. Percent equals `100 * wet_count / 5`. Arrival matches the first wet
stored time; duration matches last wet minus first wet for the observed
single-period patterns. Time values agree within 1e-6 hours. Three pixels wet
only at minute 15 have zero duration and 20 percent. Pixels with no wet sample,
including unmapped pixels, retain NoData rather than a zero percent value.

## Limits

This control qualifies this case, HEC-RAS version, horizontal rendering mode,
selected terrain and regular five-sample schedule. It does not qualify sloping
rendering, threshold equality, irregular intervals, initially wet conditions,
multiple wet periods, general recession-window branches, alternative origins,
or subinterval interpolation. It does not reinterpret duration as percent times
elapsed simulation time. Native completion does not establish convergence,
calibration or engineering acceptance.

Notebook 125 uses a different Bald Eagle workflow and has no retained executed
outputs. This fixture does not execute that notebook or supply its missing
outputs. No production stored-map or execution policy changes are included.
