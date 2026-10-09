# Meshing: Generation, Diagnostics and Repair

`GeomMesh` authors computation points and invokes the native RASMapper mesh
engine. Import it from `ras_commander.geom` (also exported at package root).
Use `HdfMesh` to inspect meshes; use `RasCmdr` to compute hydraulic plans.

| Stage | API | Input → output |
|---|---|---|
| Bootstrap points | `generate_computation_points` | Authored perimeter text and spacing -> regular-grid computation points in text; no existing HDF required |
| Compile geometry | [RasCmdr preprocessing](core.md#rascmdr) | Referencing project/plan and authored geometry -> native compiled HDF workspace |
| Author controls | Breakline/refinement methods | Names, spacing and polygons/flowlines → updated text or compiled-HDF controls, as specified per method |
| Check domain | `audit_domain_containment` | Selected 2D area and cell spacing → `DomainContainmentResult` |
| Regenerate mesh | `generate`, `generate_all` | Current compiled HDF, domain, breaklines/refinements and spacing -> `MeshResult` records and updated computation points |
| Build properties | `compute_property_tables` | Mesh and terrain/classification associations → native property tables; Boolean result |
| Check boundary conflicts | `detect_bc_conflicts`, `fix_bc_conflicts` | Compiled perimeter faces and BC lines → conflicts or `BCFixResult`; repair can modify HDF |

```mermaid
flowchart LR
    A[Geometry text and spatial inputs] --> S[Bootstrap points if no mesh exists]
    S --> B[Native geometry preprocessing]
    B --> C[Author and audit mesh controls]
    C --> D[Generate computation points and mesh]
    D --> E[Review repairs and associations]
    E --> F[Build property tables]
    F --> G[Prepare and compute hydraulic plan]
```

`generate_computation_points()` creates a breakline-unaware regular grid from
the authored perimeter. HEC-RAS preprocessing then builds the full mesh.
`GeomMesh.compile_geometry()` is a disabled compatibility shim and never
returns successfully; it is documented below only for compatibility.
RASMapper completion of an existing HDF is not text-to-HDF compilation.

## Diagnose before repairing

| Symptom or question | Inspection | Supported next step |
|---|---|---|
| Missing mesh arrays or older HDF layout | `HdfMesh.diagnose_mesh_layout()` | Inspect capability status and source paths; preprocess a copy when topology is absent. A recovered perimeter does not supply face connectivity. |
| Omitted or ambiguous cell polygons | `HdfMesh.diagnose_mesh_cell_polygons()`; `get_mesh_cell_polygons(strict=True)` | Review native cell/face IDs. The reader does not repair topology or substitute a convex hull. |
| Breakline or structure outside the domain; invalid refinement polygon | `GeomMesh.audit_domain_containment()` | Correct the source controls or perimeter and recompile through ras-commander before regeneration. |
| BC lines near the same perimeter face | `GeomMesh.detect_bc_conflicts()`; `fix_bc_conflicts(dry_run=True)` | Review candidate overlaps; supported repair trims BC endpoints in the copied HDF. |
| Native generation fails | `GeomMesh.generate()` result or raised exception | Review the bounded retry/repair evidence below; persisted perimeter changes have a separate failure contract. |
| Extreme areas, aspect ratios, or face velocities | `RasCheck.check_mesh_quality(plan_hdf, geom_hdf)` | Inspect messages and source outputs; these checks do not select an acceptable mesh resolution. |
| Unusual subgrid sampling settings | `RasCheck.check_subgrid_sampling(geom_file)` | Review geometry-text settings against terrain resolution and the intended study. |

The BC conflict detector uses a geometric proximity buffer of `0.01 * cell_size`.
It is different from `HdfMesh.get_mesh_perimeter_faces()`, which reads native
BC ownership. Use both when association evidence matters. BC repair prefers a
Normal Depth endpoint, otherwise the longer BC. It writes HDF coordinates in
place, does not create a backup or update geometry text, and does not prove that
native associations or a later preprocessing run will preserve the edit. Keep a
project copy, inspect the trims, and recheck native ownership before use.

`RasCheck.check_mesh_quality()` currently compares native areas and velocities
with thresholds named in square feet and feet per second, without converting
SI values. It uses bounding-box aspect ratios, aggregates returned cells under
the first mesh name, and catches some reader failures. Its informational
"no issues" result is not proof that every dataset was inspected. Check layout
and polygon completeness first; interpret thresholds in the actual source
units. General connectivity validation is not implemented by this check.

```python
from pathlib import Path
from ras_commander import HdfMesh, GeomMesh

# Existing compiled geometry; inspection does not alter it.
geom_hdf = Path("review-copy/Model.g01.hdf")
layout = HdfMesh.diagnose_mesh_layout(geom_hdf)
polygon_issues = HdfMesh.diagnose_mesh_cell_polygons(geom_hdf)
print(layout)
print(polygon_issues)

# Set spacing from this model's geometry, in project length units.
cell_size = 100.0
conflicts = GeomMesh.detect_bc_conflicts(geom_hdf, cell_size)
preview = GeomMesh.fix_bc_conflicts(geom_hdf, cell_size, dry_run=True)
print(preview.conflicts_found, preview.modified_hdf)
```

The dry run reports candidates without computing a repair: `conflicts_fixed`
remains zero, and every detected conflict is placed in `unresolvable`. Therefore
`BCFixResult.ok` is false when a dry run finds conflicts. These entries are
unattempted candidates, not evidence that repair is impossible. Inspect
`conflicts_found`, `unresolvable`, and `modified_hdf` explicitly.

Repair and its dry run use a proximity buffer of
`max(0.1, 0.01 * cell_size)` in project length units. The detection-only method
uses `0.01 * cell_size` without that minimum, so the two methods can report
different candidate counts for small cells.

### Repair on a project copy

The following fragment assumes an initialized `review_project` for a disposable
copy, a plan referencing geometry `01`, and a current compiled HDF. Select the
installed runtime explicitly; these values must come from the actual project.

```python
from ras_commander import GeomMesh

result = GeomMesh.generate(
    "01",
    ras_object=review_project,
    hecras_dir=installed_hecras_directory,
    recompile_via_rasexe=True,
)
print(result.status, result.error_message)
print(result.fixes_applied, result.perimeter_repairs)
```

Review text/HDF changes, geometry associations, diagnostics, and final cell
properties before computing a hydraulic plan. A completed mesh is not a
hydraulic validation result.

## Diagnostic method reference

::: ras_commander.hdf.HdfMesh.HdfMesh
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - diagnose_mesh_layout
        - diagnose_mesh_cell_polygons
        - get_mesh_cell_polygons
        - get_mesh_perimeter_faces

::: ras_commander.check.RasCheck.RasCheck
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - check_mesh_quality
        - check_subgrid_sampling

For full check-result and threshold behavior, see the
[quality-assurance guide](../user-guide/quality-assurance.md).

## Runtime and persisted changes

Native mesh generation uses Windows Python, pythonnet and the selected installed
HEC-RAS `RasMapperLib.dll`. The [version matrix and qualification notes](#hec-ras-version-support-for-headless-mesh-generation)
cover 6.0–7.0.1 and the specifically tested Windows-Python-under-Wine setup;
this does not make native Linux Python a supported CLR runtime. Select
`hecras_dir` explicitly for reproducibility: `generate()` otherwise discovers
the newest installation, which need not match the project's version. Use a
fresh process when changing the loaded DLL version.

`generate()` needs a content-current compiled HDF workspace. Its
`recompile_via_rasexe=True` option refreshes missing/stale HDF through the library's
preprocessor and requires an initialized project with a referencing plan.
Computation points are written into geometry text. Automatic perimeter repairs
can also change text and HDF: work on a disposable project copy and inspect
`MeshResult.perimeter_repairs`, backups, displacement and area changes.
See the [repair contract](#repair-persistence-and-failure-contract) for failure semantics.

The domain gate checks breaklines and structures against the exact perimeter
buffered inward by one base-cell spacing. Valid refinement regions can touch
or extend beyond the perimeter. `strict_refinement_containment=True` applies
the earlier inward margin to regions too. BC lines need separate association
and overlap checks.
Property-table success does not prove that intended land-cover assignments were
used: validate associations and inspect final cell properties.

Refinement-region `spacing_dy` is stored for schema fidelity, not evidence of
independent anisotropic Y refinement. Retain the
[release-specific refinement caveats](#hec-ras-refinement-region-caveats)
and [flowline-refinement workflow](../user-guide/flowline-refinement-regions.md)
when designing an authoring workflow. GUI mesh-refresh/import operations are
separate from computation-point generation.

## Examples with retained outputs

- [230 — mesh sensitivity](../notebooks/230_mesh_sensitivity_analysis.md)
- [231 — pipe-network mesh generation](../notebooks/231_pipe_network_mesh_generation.md)
- [232 — Weise sediment mesh sensitivity](../notebooks/232_weise_2d_sediment_mesh_sensitivity.md)

These notebooks retain outputs for their demonstrated models and runtimes;
they do not qualify every geometry, release or hydraulic configuration.

## Repair persistence and failure contract

- `audit_domain_containment(geom_number, mesh_name=..., cell_size=..., ras_object=...)` checks the breakline/structure margin and region validity. `strict_refinement_containment=True` also checks region extents against the inward margin. BC lines require a separate audit.
- `generate(geom_number, mesh_name=..., ras_object=...)` runs that gate before loading native RAS Mapper dependencies.

When the existing automatic-repair loop removes perimeter vertices or applies
Douglas–Peucker simplification, `generate()` writes the repaired perimeter through
`GeomStorage.set_2d_flow_area_perimeter(create_backup=True)`, regenerates initial
computation points, and runs `GeomPreprocessor.run_geometry_preprocessor()` with
`geometry_only=True`, `force=True`, and `clear_geompre=True`. Supply an initialized
`ras_object` with a plan referencing that geometry. Work on a disposable project
copy: repair changes the geometry text and compiled HDF. The loop reloads the HDF,
checks text/HDF consistency and feature containment, then retries within
`max_iterations`. `recompile_via_rasexe` still controls the initial missing/stale
HDF refresh; it is not required for this automatic repair handoff.

`MeshResult.perimeter_repairs` contains one record per persisted repair: `reason`,
`original_perimeter_hash`, `repaired_perimeter_hash`, `max_vertex_displacement`,
`area_change`, and `backup_path`. SHA-256 hashes cover ordered closed XY rings as
compact JSON floating-point pairs, using actual persisted coordinates after
writer rounding. Displacement is the maximum vertex-to-opposite-boundary distance
in both directions, in project length units; signed area change is repaired minus
original polygon area in squared project units. CRS and units remain those of the
project. Evidence is logged before preprocessing so failures remain traceable.
Failed repair handoffs and retries raise `RuntimeError` chained to the original
mesh repair reason, including iteration exhaustion. Ordinary failures before any
repair retain the existing `MeshResult` behavior. These records describe geometry
changes; they do not establish hydraulic acceptance.

- `compute_property_tables(geom_number, mesh_name=..., ras_object=...)` - Compute face profiles, Manning's n assignments, face hydraulic tables, and cell properties against the restored geometry associations. A missing or broken land-cover link emits a non-fatal warning because HEC-RAS may still return success while populating every cell with the 2D area's scalar default.

Before property-table generation, use
`RasMap.list_geometry_associations()` to inspect every compiled geometry and
`RasMap.validate_geometry_associations()` to require the exact terrain and
land-cover paths needed by the workflow. Registration in `.rasmap` does not
prove that a geometry HDF is associated. After preprocessing, validate the
temporary plan HDF; after computation, repeat the check on the final plan HDF
with `HdfLandCover.audit_final_mannings_n()` and explicit cell-center criteria.

## Saved-point compilation and RAS Mapper constraints

`generate()` and `generate_all()` default to
`refinement_region_constraints=False`. Breaklines and structures remain
constraints. Refinement regions shape computation-point generation through
native RAS Mapper, including interior spacing, perimeter spacing, near repeats,
far spacing and protection radius. Region edges are excluded from the mesh
used to classify and repair the saved computation points. Set
`refinement_region_constraints=True` to retain the earlier RAS Mapper mesh
with region-edge constraints.

Qualification with HEC-RAS 6.6 distinguishes a cached RAS Mapper mesh from
a fresh geometry-text point compile. Mapper can retain region-edge constraints
in a compiled HDF; a text-point rebuild can produce different face counts.
An unchanged cache is therefore insufficient evidence of compile agreement.
Point writes refresh `Storage Area 2D PointsPerimeterTime`, and successful
generation persists the face-length ratio used by the repair loop. Native
region generation can also return points outside a smaller flow area;
`generate()` removes outside and boundary points before meshing and records
the removal in `fixes_applied`.

The trimmed 26-point regression has a nine-face cell with breakline constraints
and a seven-face cell with region-edge constraints. The latter reports
`Complete`; the saved-point mesh reports `MaxFacesPerCellExceeded`. This
qualification concerns mesh classification in 6.6. Inspect fresh compiled HDF
face counts and native data errors after preprocessing, particularly with
other releases or internal structures.

HEC's [HEC-RAS 6.6 Mapper manual, 2D Flow Areas](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/6.6/geometry-data/2d-flow-areas)
describes the point-generation controls and Mapper's enforcement workflow.
The saved-point/cache distinction above comes from RAS Commander qualification.

## Carry refinement regions into a child area

Prepare the collection from a content-current source HDF, then replace the
collection in a disposable child geometry:

```python
regions, report = GeomMesh.clip_refinement_regions(
    source_geom,
    child_perimeter,
    min_area=0.0,
)
GeomMesh.replace_refinement_regions(child_geom, regions)
```

Coordinates must use the source CRS and project units. The source remains
unchanged. `replace_refinement_regions()` stages the child HDF update
atomically and makes a backup by default. It retains X/Y spacing, shifts,
perimeter spacing, near repeats, far spacing and protection radius from the
returned mappings. Regenerate points and preprocess the child afterward.

The report has one row per source region: `source_fid`, `name`, `status`,
`reason`, `source_area`, `retained_area`, `output_fids`, `touches_perimeter`
and `below_one_cell_area`. Disconnected intersections become separate regions
with the source name and properties. A line-only intersection is dropped as
`no_polygon_overlap`. Every positive-area fragment is retained by default;
small regions need not generate an interior grid point. A caller-selected
`min_area` drops smaller fragments with a recorded reason. Areas use squared
project units.

Invalid source polygons and interior rings raise by default. To retain a
reviewable report while omitting unsupported source regions, pass
`invalid_regions="drop"` and inspect every dropped row. The replacement writer
rejects holes rather than filling them.

Clipping changes the region extent used as the interior grid origin and adds
new perimeter transitions. Preserving spacing and shift fields does not
reproduce the full region's original points or transitions exactly. A region
that surrounds the child can therefore produce different points when clipped
to the child boundary.

## HEC-RAS Version Support for Headless Mesh Generation

`GeomMesh.generate()` and `GeomMesh.compute_property_tables()` support
**HEC-RAS 6.0 through 7.0.1**, including the 6.7 betas. They run RASMapper's own
mesh engine (`RasMapperLib.dll`) from the HEC-RAS installation they load, so
each release produces its own RASMapper result.

| HEC-RAS | Headless mesh generation | Notes |
|---|---|---|
| 6.6, 6.7 Beta 4, 6.7 Beta 5, 7.0, 7.0.1 | Supported | Full retry ladder, including minimum face-length ratio escalation. |
| 6.3 – 6.5 | Supported | No minimum face-length ratio escalation (see below). |
| 6.0 – 6.2 | Supported | As above. Preprocessing needs every land-cover, infiltration, and sediment file the geometry references (see below). |

**Why older releases need different calls.** Two RasMapperLib members changed
their parameters between releases, and `generate()` adapts to whichever form
the loaded release has:

| RasMapperLib member | 6.0 – 6.2 | 6.3 – 6.3.1 | 6.4.1 – 6.5 | 6.6 and later |
|---|---|---|---|---|
| `MeshFV2D(perimeter, points, breaklines, progress, ...)` constructor | 4 parameters | 4 | 4 | 5 (adds `minFaceLengthRatio`) |
| `PointGenerator.RegenerateMeshPoints` (breakline-aware seeding) | 4 parameters | 6 (adds progress reporters) | 7 (adds `treatInactiveAsNotPresent`) | 7 |
| `RASD2FlowArea.CreatePropertyTables` (used by `compute_property_tables`) | 3 parameters | 4 (adds per-task reporters) | 4 | 4 |

Before 6.6, `MeshFV2D` has no minimum face-length ratio, so `generate()` skips
the ratio-escalation step of its retry ladder. A mesh that 6.6 completes only
after raising the ratio can therefore fail on 6.0 – 6.5; the other retry steps
still apply.

**Known limitations.**

- **HEC-RAS 6.0 – 6.2 and missing referenced files.** If a land-cover,
  infiltration, or sediment file referenced by the geometry is missing,
  HEC-RAS 6.0 – 6.2 skip the geometry during preprocessing without an error,
  and the plan HDF has no 2D mesh. With these releases,
  `RasPreprocess.preprocess_plan()` checks for the files first and fails,
  naming each missing file, instead of reporting success. HEC-RAS 6.3 and
  later preprocess the mesh anyway, so the check does not apply to them.
- **Property-table values differ by release.** `compute_property_tables()`
  writes tables on every supported release, but HEC-RAS changed its
  property-table computation over time. Values from 6.0 – 6.3.1 differ from
  6.4.1 and later, which match each other.
- **Terms and Conditions for Use.** A release must have its TCU accepted for
  the current user before `Ras.exe` can preprocess headlessly.

**Selecting the HEC-RAS version.** Without `hecras_dir`, `generate()` loads the
newest installed release it finds (7.0.1, 7.0, 6.6, 6.7 Beta 5, then 6.5 down
to 6.0), regardless of the project's version. Pass `hecras_dir` to pin the
release. Only one RasMapperLib version can be loaded per Python process.

**Linux / Wine.** The same behavior applies under Wine
(`rascommander/hec-ras-wine-precompute_{version}` images). Loading
RasMapperLib there also requires the `C:\Python311\GDAL` link to the HEC-RAS
`GDAL` folder, prepared from the Linux side.

**How refinement regions were tested.** A region-only A/B test uses the real
`RasExamples` Chippewa_2D project: a 200-ft base mesh (357 cells), followed by a
1,600-ft-square refinement region requesting 40-ft spacing. RAS Mapper must
reload the authored region before regeneration, the refined mesh must contain
2,118 cells, and median nearest-neighbor spacing inside the region must be
40 ft. Native Windows produced the same result on every locally installed 6.x
runtime: 6.0, 6.1, 6.2, 6.3, 6.3.1, 6.5, 6.6, and 6.7 Beta 5. A 6.4/6.4.1
installation was not available for this qualification. The private
`RegenerateMeshPoints` API was also reflected independently in each process:
`activeRegions` is parameter 2 in every tested release; only the documented
trailing argument count changes.

HEC-RAS 6.6 was also qualified under Wine 11.0 on CLB07 using the pinned
`rascommander/hec-ras-wine-precompute_6.6` runtime. Both the RAS Mapper
product-layer writer and the native-schema fallback produced 2,118 generated
computation points (also the HDF `Cell Count`), 2,209 compiled cell-center
rows, 4,376 faces, and 1,600 centers inside the region at exactly 40-ft median
nearest-neighbor spacing; outside-region spacing was 122.327 ft. The run used
an isolated writable prefix and the Linux-side `C:\Python311\GDAL` link noted
above.

## HEC-RAS Refinement-Region Caveats

- **Independent Y spacing is not implemented by HEC-RAS.** RAS Mapper stores
  both X and Y spacing, but the 6.6 Mapper manual labels Cell Spacing Y as
  "not implemented yet." `spacing_dy` is preserved for schema fidelity; do
  not interpret a different Y value as verified anisotropic refinement.
- **HEC-RAS 6.2 GUI row reordering.** HEC documented that reordering the
  Refinement Region Editor table could create duplicate regions and deleting
  those duplicates could crash. The documented workaround was the feature
  `Send...` command; HEC lists the defect as fixed in 6.3. ras-commander does
  not drive that GUI reorder path.
- **HEC-RAS 6.4 breakline interactions.** HEC fixed lost properties after
  splitting breaklines, incorrect one-cell protection-radius behavior when
  breakline/region inclusion was disabled, and some breaklines that failed to
  enforce. Prefer 6.4 or later for models combining these behaviors.
- **HEC-RAS 6.6 perimeter-loss symptom.** HEC documented exceptional cases in
  which a 2D perimeter disappeared and the mesh stopped updating or selecting.
  Product-backed authoring therefore backs up the geometry HDF and requires a
  fresh RAS Mapper reload before reporting success.
- **HEC-RAS 6.7 betas.** Beta 2/3 had an initial mesh-recompute
  "Unknown Error"/arithmetic-overflow issue. Beta 5 passes the region-only
  qualification above, but a stable release is preferable for production.

See HEC's official [6.2 known issues](https://www.hec.usace.army.mil/confluence/rasdocs/raski/6.2),
[6.3 fixes](https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/6.3/resolved-issues),
[6.4 fixes](https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/6.4/resolved-issues),
[6.6 known issues](https://www.hec.usace.army.mil/confluence/rasdocs/raski/6.6),
[7.0's archived beta fixes](https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/7.0/resolved-issues),
and the [6.6 Mapper manual](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/6.6/geometry-data/2d-flow-areas).


## Mesh methods

::: ras_commander.geom.GeomMesh.GeomMesh
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - setup_gdal_bridge
        - audit_domain_containment
        - set_breakline_spacing
        - get_breakline_names
        - set_breakline_name
        - get_breakline_spacing
        - get_refinement_region_names
        - set_refinement_region_name
        - get_refinement_regions
        - set_refinement_region_spacing
        - replace_refinement_regions
        - clip_refinement_regions
        - add_refinement_region
        - add_flowline_refinement_regions
        - compile_geometry
        - get_geometry_association
        - set_geometry_association
        - compute_property_tables
        - generate_computation_points
        - generate
        - generate_all
        - detect_bc_conflicts
        - fix_bc_conflicts

## Result and audit records

For `generate()` and `generate_all()`, inspect `MeshResult.ok`/`status`, error
information and repair evidence rather than cell count alone.

`generate_computation_points()` currently reports successful bootstrap with
`status == "success"`, while `MeshResult.ok` and `bool(result)` recognize only
`"complete"`. For this method, check `status`, `cell_count` and `error_message`
explicitly; a false `ok` alone does not mean bootstrap failed. Its `cell_count`
counts generated points, not a compiled hydraulic mesh.

`DomainContainmentResult.ok` means no recorded containment
violations. `BCFixResult.ok` means no unresolved conflicts in that result; these
are operation-specific states, not hydraulic acceptance criteria.

::: ras_commander.geom.GeomMeshDataclasses.MeshResult
    options:
      heading_level: 3

::: ras_commander.geom.GeomMeshDataclasses.DomainContainmentResult
    options:
      heading_level: 3

::: ras_commander.geom.GeomMeshDataclasses.DomainContainmentViolation
    options:
      heading_level: 3

::: ras_commander.geom.GeomMeshDataclasses.BCConflict
    options:
      heading_level: 3

::: ras_commander.geom.GeomMeshDataclasses.BCFixResult
    options:
      heading_level: 3
