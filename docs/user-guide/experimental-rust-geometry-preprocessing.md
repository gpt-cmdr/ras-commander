---
title: Experimental Rust Geometry Preprocessing
description: Run the experimental Rust 2D geometry preprocessor and prove its equivalence to native HEC-RAS 7.0.1 preprocessing on your own model with the built-in validation harness.
---
# Experimental Rust geometry preprocessing

!!! warning "Experimental: qualify it on your model first"
    The Rust geometry preprocessor is **experimental**. It is not a drop-in
    replacement for native HEC-RAS preprocessing. Before any production use,
    run `GeomPreprocessor.validate_rust_equivalence()` on your own model and
    keep its report. That comparison is the preferred way to qualify the
    experimental workflow. A result on one model, engine build or HEC-RAS
    version does not qualify another. Equivalent property tables are not a
    hydraulic review.

RAS Commander can run an external Rust engine, `ras-preprocess`, that
computes the 2D flow-area property tables native HEC-RAS 7.0.1 writes into
a geometry HDF. It also provides a harness that runs native preprocessing and
the engine side by side on copies of your model and compares every result.
Both entry points are static methods of `GeomPreprocessor`. Every call emits
`ExperimentalWarning`.

| Method | Purpose |
|---|---|
| `GeomPreprocessor.validate_rust_equivalence(project, geom, work_dir=...)` | Qualification: native and Rust preprocessing on separate copies, compared dataset by dataset, with a JSON and markdown evidence report |
| `GeomPreprocessor.compute_rust_experimental(geom_hdf, out_path=...)` | Write the engine's products into a copy of a geometry HDF, with provenance |

## What the engine computes

For every 2D flow area of a complete HEC-RAS 7.0.1 geometry HDF, the engine
computes the products of the four native preprocessing stages:

1. face profiles (`Faces Profile Info`/`Values`) and `FacePoints Elevation`,
   from the terrain and its modifications;
2. `Cells Center Manning's n` and the classification families
   (`Infiltration/...`, `Percent Impervious/...`, sediment bed material);
3. face area-elevation tables (`Faces Area Elevation Info`/`Values`,
   `Faces Minimum Elevation`, `Faces Low Elevation Centroid`);
4. cell volume-elevation tables (`Cells Volume Elevation Info`/`Values`,
   `Cells Minimum Elevation`, `Cells Surface Area`).

It reads the mesh topology and the layer associations of the geometry HDF,
and no stored product. It does not generate meshes, convert geometry from
earlier HEC-RAS versions, or preprocess 1D features. Native HEC-RAS remains
the path for 1D and mixed models and for geometry conversion.

## Get the engine

The engine is not distributed with RAS Commander and is not installed by
`pip`. It is built from the `ras-commander-fast-preprocess` repository, which
is not public. RAS Commander locates the executable in this order:

1. the `engine_exe` argument;
2. the `RAS_COMMANDER_PREPROCESS_EXE` environment variable;
3. `ras-preprocess` on `PATH`.

If none resolves, the call raises `RustPreprocessNotFoundError`. Nothing is
downloaded. The harness records the executable path, its
`ras-preprocess --version` output and its SHA-256 in every report.

## Qualify the engine on your model

`validate_rust_equivalence()` needs HEC-RAS 7.0.1 on Windows for the native
side. HEC-RAS runs only through RAS Commander APIs. The source project is
never written; every step works on copies inside `work_dir`.

```python
from ras_commander import GeomPreprocessor

report = GeomPreprocessor.validate_rust_equivalence(
    r"C:\Models\BaldEagleCrkMulti2D",     # project folder or .prj; not modified
    "09",                                  # geometry number, or a .g## / .g##.hdf name
    work_dir=r"C:\Work\rust-qualification\be09",   # new or empty folder
    engine_exe=r"C:\Tools\ras-preprocess.exe",
    native_repeats=2,                      # repeat native runs to expose nondeterminism
)
print(report.verdict)                      # "equivalent", "not equivalent" or "refused"
print(report.report_markdown)              # evidence to keep with the model
report.to_dataframe()                      # one row per compared dataset
```

The harness runs four steps:

1. **Stage.** Copy the project into `work_dir/staged` without plan result
   HDFs. If the geometry HDF is missing, incomplete or from another HEC-RAS
   version, convert it with `GeomPreprocessor.run_geometry_preprocessor()`
   (geometry-only compute of `plan_number`, or of the first plan that uses the
   geometry). Both sides then start from the same 7.0.1 mesh.
2. **Rust.** Copy the staged project to `work_dir/rust`. Overwrite every stored
   floating-point product with NaN, run the engine in native-compatible mode,
   and write its products back through the guarded writer described
   [below](#use-the-products), restamping `Property Tables Last Computed`
   as `compute_rust_experimental()` does. Overwriting the stored products shows that the
   engine computed every value it wrote: a product it read would turn its
   output non-finite and fail validation.
3. **Native.** Copy the staged project to `work_dir/native` and run
   `RasMap.recompute_property_tables()` `native_repeats` times. Each run starts
   from a fresh copy of the staged geometry HDF whose float products are NaN.
   A value RAS Mapper leaves unrecomputed, for example an area it skipped while
   still reporting success, stops the harness with `RustPreprocessError`.
   That NaN is never compared as native output.
4. **Compare.** Compare every dataset of every 2D area: products and the
   topology that neither side should change. `Info`/`Values` tables are
   compared per owner, so a face whose profile gains a point is reported as
   that face.

If the engine refuses the input, the harness stops after step 2, skips the
native runs, and returns `verdict="refused"` with the engine's message in
`report.refusal`.

### Read the report

Each dataset row reports:

| Column | Meaning |
|---|---|
| `status` | `bitwise`, `within_tolerance`, `matches_other_native_run`, `different`, `missing_native` or `missing_rust` |
| `n_different`, `max_abs_diff`, `max_ulp` | Values not bitwise equal; largest absolute difference in dataset units; largest float32 units-in-the-last-place distance |
| `id_kind`, `n_ids_different`, `ids_different` | Cells, faces or face points with any difference, and the first of them (`max_ids`, default 20) |
| `labels` | Known native behaviours that bear on the dataset (see [Known native defects](#known-native-defects)) |

The verdict is `equivalent` only when every dataset passes. The default
criterion is bitwise. Pass `tolerance=0.01` for an absolute bar in dataset
units, for example 0.01 ft on elevations. A mapping sets a bar per dataset,
for example `{"Faces Minimum Elevation": 0.01, "*": 0.0}`. Integer datasets,
such as `Info` tables and classification indices, are always compared exactly,
and a change in a face's or cell's row count always fails.

The report also attaches:

- the engine's own per-stage `--compare` check against native run 1
  (`engine_compare=True`);
- area attributes that differ between the two files, for information.
  Both sides stamp `Property Tables Last Computed` with their own completion
  time, so it always differs. The Rust side keeps `Property Tables LC Hash`
  from the staged input, so it differs whenever native's input-derived hash
  differs from the input's (see [Currency attributes](#currency-attributes));
- a **Stage 2 infiltration and impervious coverage** section whenever
  `Infiltration/...` or `Percent Impervious/...` datasets are present. The
  engine's `--compare` checks Stage 2 only through
  `Cells Center Manning's n`, so it does not compare these arrays. The dataset
  table compares the arrays the engine computed. A family dataset the engine
  does not compute (for example `Infiltration/Properties`) keeps the staged
  input on the Rust side. It is shown with category `carried` and listed as
  not compared, because equal values there prove nothing about the engine.
  The engine's workstream P (in progress) adds Stage 2 infiltration and
  impervious coverage to `--compare` and the harness; until then, reports do
  not cover those arrays through the engine's own check;
- with `include_corrected=True`, the corrected mode's departure from native
  (D-4, D-5) as a separate table that does not affect the verdict.

The JSON (`rust_equivalence_report.json`) and markdown
(`rust_equivalence_report.md`) files in `work_dir` are the evidence to keep.
The native and Rust geometry HDFs are kept beside them. With
`keep_work=False` the project copies are removed and the HDFs are kept.

### Results on the RasExamples projects

The current engine build produced these results on 2026-11-28: `ras-preprocess
0.1.0`, built from source revision `9ab2592`, SHA-256 `025b41df…4e6f07`.
The native side was HEC-RAS 7.0.1. All three cases ran in the integration
tests, `tests/test_rust_preprocess_integration.py`.

| Model | Native runs | Datasets compared | Verdict | Wall time |
|---|---:|---|---|---:|
| BaldEagleCrkMulti2D g09 (19,597 cells, 37,594 faces; SCS infiltration and percent impervious) | 2 | 37, all bitwise: 20 products, 16 inputs and `Infiltration/Properties` (carried, not computed by the engine); 8 of the 9 Stage 2 family datasets compared as engine output | equivalent | 224 s |
| Muncie g02 with a SetValue polygon terrain modification crossing 195 faces and 96 cells | 1 | 28 (12 products), all bitwise | equivalent | 36 s |
| Muncie g02 with a rotated ellipse terrain modification (30°, 200 × 80 ft) | — | none | refused: ``Basin (Type="Circle" …): rotated ellipse (30 degrees, radii 200 x 80); its native Stage 1 face intersection is not reproduced`` | 15 s |

The previous build (`26ca082`) gave the same verdicts. On it, the corrected
mode was also bitwise on Bald Eagle g09, where Composite LC and Multiple Face
Mann n are off, and a second native run on the Muncie case agreed with the
first. The host was shared with other HEC-RAS jobs during the `9ab2592` runs.

Each wall time includes staging and the native 7.0.1 conversion of the
geometry, which was authored in an earlier HEC-RAS version.

## Use the products

Run `compute_rust_experimental()` only on a model whose qualification report
is `equivalent` for the same engine build and options.

```python
result = GeomPreprocessor.compute_rust_experimental(
    r"C:\Work\model\Model.g09.hdf",           # complete HEC-RAS 7.0.1 geometry HDF
    out_path=r"C:\Work\model-rust\Model.g09.hdf",
    engine_exe=r"C:\Tools\ras-preprocess.exe",
)
result.engine.sha256, result.options, result.writeback["datasets_changed"]
```

- The engine opens the source read-only and resolves the terrain and layers
  relative to it. The products go into a copy at `out_path`.
  `in_place=True` writes the source itself, keeping a
  `<name>.pre-rust.bak` backup beside it.
- **Default mode: `native_compatible=True`.** It reproduces native HEC-RAS
  7.0.1, including defects D-4 and D-5, and it is the mode the harness
  qualifies, so a qualified model gets the tables the harness proved. The
  engine's own default is its corrected mode; RAS Commander does not use it
  unless you pass `native_compatible=False`, which departs from native
  wherever those defects act.
- **`restamp_currency=True` (the default)** sets each written area's
  `Property Tables Last Computed` the way native recomputation does. See
  [Currency attributes](#currency-attributes). The choice is recorded in
  `result.options["restamp_currency"]`, and `result.currency` holds the
  stamp and each area's before and after value.
- The writer refuses any `File Version` other than `HEC-RAS 7.0.1 June 2026`
  and any geometry that is not `Complete Geometry=True`. It writes only
  datasets that already exist and never creates a dataset or an attribute.
  The only attribute it writes is the currency stamp above. Before writing,
  it validates the products: finite, positive cell
  Manning's n; contiguous `Info` tables; strictly increasing elevations;
  volume curves that start at 0; ghost-cell conventions; and every cell
  minimum at or below each adjacent face minimum. Every write is read back
  exactly. The receipt lists the SHA-256 of every dataset before and after,
  which proves that no other dataset changed. It also lists a before/after
  snapshot of every attribute in the file, which proves that only the
  currency stamps changed. The file is restored from its backup on any
  failure.
- The result records the engine path, version and SHA-256, the options, the
  exact command, the engine's report, the write-back receipt and the source
  SHA-256.

## Currency attributes

When native HEC-RAS 7.0.1 recomputes property tables
(`RasMap.recompute_property_tables`), it changes exactly two attributes. The
evidence is an attribute-only diff of every object in the geometry HDF before
and after two consecutive native runs, on Muncie g02 and Bald Eagle g09. No
root, `Geometry` or layer attribute changes, and no dataset outside the
products changes.

| Attribute | Where | What native writes | Rust write-back (`restamp_currency=True`) |
|---|---|---|---|
| `Property Tables Last Computed` | each recomputed 2D area | The local wall-clock time at which the area's tables completed, `DDMONYYYY HH:MM:SS` with an upper-case English month (for example `27NOV2026 22:59:52`), stored as an 18-byte fixed-length string | **Restamped.** Set to the local time of the write-back, in the same format. It is written through the existing attribute, so its stored type is unchanged, and read back exactly. An area without the attribute is left without it. |
| `Property Tables LC Hash` | areas with a land-cover association | A 32-byte SHA-256 derived from the land-cover inputs. Native rewrites it only when its value differs from the stored one. | **Kept from the source, with a warning.** |

Native builds the LC hash over RasMapperLib's hash of the calibration-region
feature layer, each region's class-to-n map, the land-cover names and the base
n values. That construction is not specified exactly enough to reproduce, and
the engine does not compute it, so RAS Commander does not guess it. When an
area carries the hash, `compute_rust_experimental()` keeps the source value,
records it in `result.currency["not_restamped"]` and emits
`ExperimentalWarning`. The stored hash is a currency signal: native reports
"Mesh property tables are current" only while it matches the inputs. A Rust
result is therefore current exactly when its source geometry HDF was current.
After a land-cover or calibration-region edit, run native preprocessing first.

`restamp_currency=False` writes no attribute at all, as earlier builds of this
feature did.

### Evidence that HEC-RAS accepts the Rust tables

These checks ran on HEC-RAS 7.0.1 on 2026-11-27, through RAS Commander APIs
only, with engine build `9ab2592`:

| Check | Muncie g02 (plan 03) | Bald Eagle g09 (plan 03) |
|---|---|---|
| `RasCurrency.is_geom_preprocessing_current()` after the write-back | current | current |
| Native RAS Mapper on a copy of the Rust result | "Mesh property tables are current." | "Mesh property tables are current." |
| `RasCmdr.compute_plan()` on the Rust result | "Mesh property tables are current."; completed | "BaldEagleCr: Mesh property tables are current."; completed |
| Geometry HDF datasets and attributes after the plan compute | unchanged (restamp kept) | attributes unchanged (restamp and LC hash kept); 2D area datasets unchanged |
| Plan HDF property tables | byte-identical to the Rust tables | byte-identical to the Rust tables |

On Bald Eagle, the LC hash discriminates. The same Rust write-back applied
to the geometry HDF straight from the native 7.0.1 conversion keeps that
file's hash, and RAS Mapper then reports "Manning's n calibration regions have
changed". Native behaves the same way on its own output: the first native plan
compute writes a hash that the next native plan compute finds stale ("Refreshed
association-derived tables without rebuilding cell volume tables"). The
Rust result inherits whatever currency its source had. Every plan compute,
native or Rust, also rewrites `Geometry/Land Cover (Manning's n)/Internal
Cells`. That dataset lies outside the 2D area products and the Rust write-back
does not touch it.

Each case starts from the state native itself accepts. The geometry was
converted to 7.0.1 with `GeomPreprocessor.run_geometry_preprocessor()`, as
the harness stages it, and the plan was then computed natively twice. On
Muncie, the second native compute reported the tables current. On Bald
Eagle, it refreshed the association-derived tables and the LC hash, and the
Rust write-back started from that refreshed file. The
first native plan compute after a conversion rebuilds the tables itself
("Property tables do not exist"), whatever they contain. On Muncie, a project
plan-computed twice without the explicit conversion was still rebuilt on the
second run. Check the compute messages of your own workflow. On Muncie, every check also passed with
`restamp_currency=False`: HEC-RAS 7.0.1 does not compare
`Property Tables Last Computed`, and it does not compare the file
modification time either. The restamp keeps the stamp
truthful rather than changing the verdict. On these models the Rust tables
are bitwise equal to native, so the checks show that the write-back leaves the
file in a state HEC-RAS accepts. They do not show what HEC-RAS does with
tables that differ from native.

## Supported and refused inputs

The engine reproduces HEC-RAS 7.0.1 only. It refuses inputs whose native
rules it does not reproduce and names what it refused. RAS Commander raises
`RustPreprocessRefusedError` and never falls back to another method. The
harness reports such a case as `refused`.

| Input | Status |
|---|---|
| Geometry HDF | Complete HEC-RAS 7.0.1 geometry HDF with 2D flow areas. Earlier versions need native conversion; the harness converts the staged copy. |
| Terrain | Registered HEC-RAS terrain HDF with tiled, north-up GeoTIFF sources with square tiles, including stitch TINs. Other layouts are refused. |
| Layer associations | Land cover, infiltration, percent impervious and sediment bed material, resolved from the geometry HDF's association attributes. Native HEC-RAS can also resolve a stale association through the `.rasmap`; the engine refuses it and names the missing file. Repair the association first. |
| Manning's n | Point sampling, `LCMann Table` overrides, calibration regions, Composite LC and Multiple Face Mann n (with D-4 and D-5; see below). |
| Terrain modifications (the terrain HDF's `/Modifications`) | Supported, including modifications that cross faces: constant-value polygons, polygons with control points, circles and unrotated ellipses (SetValue, SetIfHigher, SetIfLower), and channel and levee ground lines with profiles. |
| Refused modifications | Rotated non-circular ellipses; Encroachment Polygon, Levee1, Pier, Tree, Rectangle and Triangle types; polygons whose elevations come from their vertex Z values; named ground-line systems that have layer control points. A terrain with one refused layer is refused as a whole. |

The engine's qualification beyond these example projects is recorded in its
own repository. It covered the RasExamples 2D geometries, eBFE models and
larger 2D models, and found bitwise agreement or departures that the defect
register below explains.

## Known native defects

Native HEC-RAS 7.0.1 preprocessing has defects that the engine corrects by
default. Each correction has a native-compatible mode for bitwise
comparison with HEC-RAS. RAS Commander uses that mode by default. The harness
labels these cases in its report rather than hiding them.

| ID | Where | Native behavior | Engine default | RAS Commander default (native-compatible) |
|---|---|---|---|---|
| D-4 | Composite LC (cell-average Manning's n and classification parameters) | The per-worker cell mask is never cleared, so a cell's average includes pixels set by earlier cells in its 4,000-cell chunk. About one cell in nine changes on the Bald Eagle Composite LC fixture. Native output depends on the worker limit. | Corrected (empty mask per cell) | Reproduced; equals native at worker limits 1, 2 and 4. `RasMap.recompute_property_tables()` runs one worker. |
| D-5 | Multiple Face Mann n | Base `LCMann Table` overrides are dropped from face profiles when the calibration-table row count differs from the land-cover class count. | Corrected (overrides applied) | Reproduced |
| L-1 | Faces with more than 1,000 profile points | Native integrates them with an unsynchronized parallel loop, so its output is not reproducible. | Deterministic serial integration | Same; the harness lists such faces |
| N-1 | Polygon modifications with control points | A race on a shared quadtree: some native runs give different values on faces and cells crossing the polygon, or stop in Stage 1. | The uncorrupted result | Same; repeat native runs to expose it |
| N-2 | Stage 1 tile-piece order | Under the default .NET thread pool, the order of tied profile points follows thread scheduling. | Ascending tile order, which equals native under RAS Commander's one-worker pool | Same |
| N-3 | Stitch-TIN edge order | Depends on a process-assigned runtime type id. Observed stable. | The observed value | Same |

Defects D-1 to D-3 concern the property-table currency hash, Green-Ampt
optional variables and overlapping calibration regions. The engine keeps
native behavior for them. For D-1, the engine's register says the LC hash is
never reported current. On Bald Eagle g09, a repeat native recompute did
report it current (see [Currency attributes](#currency-attributes)). The hash
a native plan compute writes on a freshly converted geometry is the one that
reads as stale.

With `native_repeats > 1`, the harness compares native runs with each other.
It labels datasets on which they disagree (N-1, N-2) and passes a Rust dataset
that equals any one of them (`matches_other_native_run`). A single native run
cannot expose native nondeterminism.

## Limitations

- **One HEC-RAS version and one native producer.** The native reference is
  HEC-RAS 7.0.1 RAS Mapper recomputation (`RasMap.recompute_property_tables`).
  Comparison against the plan-compute preprocessor is out of scope for this
  feature; it is being prepared separately. The harness does not run the
  unsteady solver.
- **Stage 2 infiltration and impervious coverage.** The engine's `--compare`
  covers Stage 2 only through `Cells Center Manning's n`. The engine's
  workstream P (in progress) adds infiltration and impervious coverage to
  `--compare` and the harness, so current reports do not cover those arrays
  through the engine's own check. The report says so whenever those datasets
  are present, and it lists any family dataset the engine does not compute as
  not compared.
- **Stale-success dependency.** RAS Mapper can exit successfully after
  skipping an area. The harness detects this independently by overwriting the
  stored products before each native run. The matching fix in
  `RasMap.recompute_property_tables()`, which requires each area's "tables
  complete" report, is in a separate change.
- **2D only.** 1D cross sections, storage areas and 1D structure tables are
  not computed or compared. Datasets outside `Geometry/2D Flow Areas` are not
  compared.
- **LC hash.** `Property Tables LC Hash` is kept from the source, not
  recomputed (see [Currency attributes](#currency-attributes)). Use a source
  geometry HDF that native preprocessing left current, and check the compute
  messages for "Mesh property tables are current".

## Exceptions

| Exception | Raised when |
|---|---|
| `RustPreprocessNotFoundError` | The engine executable cannot be located |
| `RustPreprocessRefusedError` | The engine refuses the input; `.refusal` holds its message |
| `RustPreprocessError` | Unsupported geometry version or state, engine failure, failed product validation, or an unrecomputed native value in the harness |

See the [geometry API reference](../api/geometry.md#experimental-rust-geometry-preprocessing)
for signatures and result classes.
