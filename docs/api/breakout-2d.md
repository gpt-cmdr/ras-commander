# 2D Breakout Geometry Preparation

`RasBreakout2D` prepares the geometry and project associations for a contained
breakout of an existing pure-2D, unsteady HEC-RAS model. The API separates the
repeatable geometry work from unresolved hydraulic boundary-condition design.

The preparation workflow does **not** compute a plan or author a breakout
boundary condition. It inventories the source boundaries, copies the complete
unsteady file byte-for-byte, and returns parent-face flux evidence for later
engineering review.

## Qualify the proposed child domain

```python
from pathlib import Path

from ras_commander import Breakout2DSpec, RasBreakout2D, RasPrj, init_ras_project

source_ras = RasPrj()
init_ras_project(
    Path(r"D:\models\UPGU3"),
    "6.6",
    ras_object=source_ras,
    load_results_summary=False,
)

spec = Breakout2DSpec(
    source_plan="08",
    source_2d_area="UPGU3_2DArea",
    child_boundary=Path("huc12_121002010305.geojson"),
    breakout_id="HUC12-121002010305",
)
preflight = RasBreakout2D.preflight(spec, ras_object=source_ras)
preflight.checks
preflight.feature_actions
preflight.existing_boundaries
```

`preflight()` fails closed unless the selected plan is unsteady and pure 2D,
the source geometry contains exactly one 2D flow area, the named area is
unique, the child polygon is valid and contained by the
parent, and no unsupported structure or reference-point edit is required. It
classifies child-perimeter segments as inherited parent perimeter or artificial
cuts. Breaklines, reference lines, and refinement regions are classified as
keep, clip, or drop against a one-base-cell inward trim plus a small numeric
round-trip guard. Existing geometry BC lines and unsteady boundary records are
classified as `preserve`.

## Clone associations and prepare geometry

Initialize a separate, disposable project copy before calling the mutation
methods:

```python
working_ras = RasPrj()
init_ras_project(
    Path(r"D:\working\UPGU3_breakout"),
    "6.6",
    ras_object=working_ras,
    load_results_summary=False,
)

clone = RasBreakout2D.clone_plan_components(
    preflight,
    ras_object=working_ras,
    plan_title="HUC12 breakout geometry prep",
    plan_short_id="HUC12_PREP",
    geometry_title="HUC12 breakout geometry",
)

prepared = RasBreakout2D.prepare_cloned_geometry(
    preflight,
    clone,
    ras_object=working_ras,
    refresh_hdf=True,
    remesh=True,
    compute_property_tables=False,
    timeout=1200,
)

assert clone.boundaries_unchanged
assert prepared.boundaries_unchanged
```

The clone operation creates new geometry, unsteady, and plan files; associates
the cloned plan with the new `g##` and `u##`; makes that plan current; and
registers the cloned geometry as a RASMapper geometry layer. It verifies both
plan associations by readback and proves the complete unsteady clone is
byte-identical with SHA-256. Before cloning, it also requires a separate
working project and verifies the working plan, geometry text, geometry HDF, and
unsteady source files against the qualified source with SHA-256.

Geometry preparation edits only the cloned geometry. It replaces the 2D
perimeter, trims mesh-owned features, performs the exact text-to-HDF refresh,
replaces refinement regions, regenerates computation cells, and audits domain
containment. The exact import transaction also protects and restores every
non-target geometry HDF because RASMapper can update older registered
geometries while opening a project. HEC-RAS may be opened for the exact
geometry import, but the hydraulic solver is never invoked. Install the
declared `gui` and `mesh` optional dependency groups when enabling the exact
refresh and remesh steps.

## Review parent-face flux locations

```python
flux = RasBreakout2D.review_parent_boundary_flux(
    preflight,
    minimum_peak_flow=100.0,
    minimum_volume_fraction=0.0001,
)

flux.faces       # every reviewed parent face and significance metrics
flux.zones       # adjacent, same-direction candidate locations
flux.face_flow_outward  # positive leaves the child; negative enters it
```

The review prefers stored parent Face Flow. When native Face Flow is
unavailable, it derives normal flow from face-normal velocity and the
face-area-versus-stage relationship. The result orients every series outward
from the proposed child and groups adjacent significant faces that share the
same dominant direction. A zone is review evidence only: it has no assigned
HEC-RAS boundary type and does not modify a geometry or unsteady file.

## Upper Guadalupe 3 qualification

The example notebook
[`956_ebfe_2d_breakout_geometry_preparation.ipynb`](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/956_ebfe_2d_breakout_geometry_preparation.ipynb)
uses plan 08 and HUC12 `121002010305` as a real-data qualification case. The
read-only preflight identified a 200-foot base cell, a contained 24.73-square-
mile child polygon, and 1,701 reviewed feature actions:

| Feature | Action | Count |
| --- | --- | ---: |
| Geometry BC lines | preserve | 4 |
| Unsteady boundary records | preserve | 4 |
| Breaklines | keep / clip / drop | 132 / 10 / 1,534 |
| Reference lines | keep / clip / drop | 1 / 1 / 13 |
| 2D mesh area | replace | 1 |
| Refinement regions | drop | 1 |

The existing `u01` inventory contains `Inflow_from_UPGU2` (Flow Hydrograph),
`Outflow_to_UPGU4` (Normal Depth), `BC_1` (Normal Depth), and `BC_2` (Normal
Depth). Those records are parent-model inputs. Preserving them proves source
fidelity; it does not make them suitable for the breakout.

At the demonstration thresholds above, the already-computed parent result
yielded 1,051 child-partition faces, 51 significant faces, and 22 combined
same-direction candidate zones. No boundary condition was created or changed,
and no hydraulic plan was rerun.

For rapid visual review, the notebook also shades the full parent with the
terrain-derived minimum elevation at each parent mesh cell, outlines a
review-scale p08 maximum-inundation boundary derived from wet parent cell
centers (`maximum depth > 0.1 ft`), and provides overall and detail maps of
candidate flux zones with outward-direction arrows. These are review figures
derived from existing HDF data, not new model results.

## Next steps: boundary conditions remain unresolved

Boundary-condition work is intentionally deferred to a separate reviewed
workflow. That work must:

1. decide which artificial-cut candidate zones need hydraulic forcing;
2. select the appropriate type for each location without inferring it solely
   from the direction or magnitude of parent Face Flow;
3. source and time-align any parent flow or stage series;
4. offset and trim geometry BC lines so adjacent records cannot bind the same
   face; and
5. run and validate the breakout against the parent using a common terrain and
   aligned raster products where the meshes differ.

::: ras_commander.RasBreakout2D.RasBreakout2D
    options:
      show_source: false
      members:
        - normalize_child_boundary
        - classify_boundary_segments
        - preflight
        - clone_plan_components
        - prepare_cloned_geometry
        - select_parent_boundary_faces
        - review_parent_boundary_flux
