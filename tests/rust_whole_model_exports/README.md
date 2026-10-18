# Whole-model qualification

Use the verified combined source snapshot plus coordinator review-adapter fixes.
The second patch registers `validate_export_wkb`; it must survive any future
binding integration. This packet edits no shared writer, tiler, or registration
source. Its Rust harness calls the common library directly and is test-only.

Prepare the complete immutable local models with `prepare.py` in the sibling
benchmark directory. The stored versions/expected valid counts are 7.0/4425,
6.6/18066 and 5.0.7/340246, with 2 explicit source omissions in the last. The final
region fixture contains all 72 retained stored 7.0 regions, without repetition.
Source extraction uses ras-commander APIs; no model computation or adjacency
classification is run. The metadata-iteration patch is therefore unnecessary.

The benchmark runner uses three samples per small complete model/region case;
the largest case permits one labeled sample per route/format. All feature
geometries, composite identities and representative typed columns reopen and
compare independently for every sample, including Arrow. FGB's spatial sorting
is accounted for by composite keys. Indexed FGB/GPKG, Parquet Snappy with 65536-row groups and
JSON decimal precision 15 are deliberate baseline settings. Source timestamps
become integer milliseconds in the Python FGB/JSON baseline to match Rust policy.

The routes differ deliberately: `adapter` includes the reviewed Python adapter's
IPC spool/CRS/transform work; `ipc` uses prepared IPC directly; `direct` preloads
resident native Arrow batches before timing export_batches; `python` uses
PyArrow/GeoPandas/GDAL. The direct route avoids IPC during the writer timer but
does not avoid IPC transfer or claim bounded total memory. Prepared tables are
eager in Python too. The controller monitors each fresh process every 20 ms with
process RSS and output/temp directory sizes. It may miss short-lived disk peaks.
Before-verification OS peaks are recorded separately from all-process peaks.
Direct-route independent verification runs in the controller, outside child wall
time; compare writer/preparation timings rather than treating process wall
numbers as equivalent end-to-end timings.

Diagnostic wrappers time actual adapter IPC writer API calls, exact staged bytes
at native entry, and the borrowed WKB validator. No shared function implementation
is replaced. Internal dependency compression/index stages remain grouped in
native write/finalization metrics. Cold/warm cProfile probes are separate from
the benchmark medians. Early samples can overlap host build/regression activity;
do not infer a hardware-independent speedup from these operational measurements.

Tests also demonstrate the contract's existing cross-batch duplicate-ID limit:
one-row batches with duplicate composite keys are accepted by the writer. The
qualification verifier rejects them, and real producer inputs are audited globally.
That explicit producer precondition is not silently upgraded to a writer guarantee.

The distinct extraction tests verify required-native execution (counted native
calls and forbidden Python polygonizer), full normalized-coordinate equality
on7.0/6.6, and the explicit5.0.7native rejection. A test recognizing the rejection
is not a successful native extraction qualification for that model.

## Integration opt-in

These checks consume generated prepared models and benchmark reports, not committed test data. Set `$env:RAS_RUN_WHOLE_MODEL_EXPORT_TESTS="1"` only after the documented preparation/measurement steps. Without it the module skips explicitly; skips are not successful model qualification. Worker historical13passes refer to the fully prepared worker environment.
