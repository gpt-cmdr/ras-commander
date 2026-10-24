# Hydraulic Subdomains

Split a large 2D parent model, typically rain-on-grid, into breakout subdomains
whose boundaries sit where normal depth holds. Each subdomain can then run on
its own with simple normal-depth and inflow-hydrograph boundaries instead of
backwater-driven forcing.

Placing a model boundary where normal depth can be assumed is standard practice.
What `RasSubdomain` adds is a numerical way to find those places, directly from
the parent's own plan HDF:

- **Pour points:** candidate boundaries come from terrain-derived channels. Each
  pour point is the outlet of a TauDEM stream link (`RasTauDem.delineate`), and
  its contributing area is the union of that link's catchment and every
  catchment upstream.
- **Scoring:** each candidate line is scored against the parent's native
  `Face Flow` and cell stage, through the conveyance of the parent's own face
  property tables.
- **Extent:** each subdomain's extent is traced from the parent's cell-to-cell
  flow.

The method is expected to suit steep and moderate-slope domains. Where backwater
controls (flat, tidal or reservoir-influenced reaches), few lines pass and the
remainder stays large; the search reports that rather than forcing a split.

```python
from ras_commander.terrain import RasTauDem
from ras_commander.subdomain import RasSubdomain

taudem = RasTauDem.delineate("Terrain/dem.tif", "work/taudem",
                             stream_area_sqmi=0.5, cell_size=100.0)
search = RasSubdomain.find_split_lines(
    ["Model.p01.hdf", "Model.p02.hdf"],      # events of one geometry, with native Face Flow
    taudem.streams, taudem.catchments)
partition = RasSubdomain.build_subdomains(search)
partition.subdomains[["subdomain_id", "tier", "upstream_subdomain_ids", "area_sqmi", "labels"]]
```

## Requirements

- **Parent plan HDFs:** one or more events of one geometry, each with native
  `Face Flow` output. Add it with
  `RasPlan.add_hdf_output_variable(plan, "Face Flow")` and rerun the plan.
  Face flow is never estimated from Face Velocity.
- **Units:** US Customary (feet) models only in this release; SI raises
  `NotImplementedError`.
- **Python packages:** geopandas, shapely 2 and pyproj (`pip install ras-commander[full]`).
- **TauDEM:** TauDEM 5 for the stream network (see [Terrain Modules](terrain.md#rastaudem)).

## Finding split lines

`RasSubdomain.find_split_lines(plan_hdf_paths, streams, catchments, *, mesh_name=None, growth_plan_hdf_path=None, criteria=None, link_ids=None)`

1. **Walk-up.** From each pour point whose contributing area is at least
   `min_contributing_area_sqmi`, the search walks up the link (and its larger
   upstream link) in `step_spacing_ft` steps, out to `walk_length_ft`.
2. **Line growth.** At each step a line grows across the valley from the face
   the channel crosses. It follows the faces carrying the most downstream
   volume in the growth event (default: the event with the most volume) and
   stops at the edge of the `wet_depth_ft` wet extent.
3. **Scoring.** In every event the line is scored as a normal-depth boundary.
   Native `Q(t)` across the line is set against the stage of the cell above the
   seed face through `K(z) = sum (1.486/n) A R^(2/3)`, at the best single
   slope. The scores are RMSE, peak error, rising/falling loop width, reverse
   fraction and the share of the contributing area's outflow.
4. **Acceptance.** A line passes in an event when all of these hold:
   - both banks close;
   - reverse flow is at most 5%;
   - RMSE, peak error and loop width are each at most 0.5 ft;
   - the best slope is within 1/3 to 3 times the link slope;
   - the line carries 80% to 120% of the contributing area's outflow.

   A split line must pass in every event at its step and at a neighbouring
   step; the lowest mean RMSE wins.

These defaults are the project-engineer values of 2026-10-14
(`SplitLineCriteria`). `link_ids` limits the search to chosen TauDEM links, for
example one headwater.

`SplitLineSearch.split_lines` (schema `subdomain_split_lines`) holds the
accepted lines. `candidates` (schema `subdomain_split_candidates`) holds every
scored step and event, with the criteria it failed.

## Building subdomains

`RasSubdomain.build_subdomains(search, *, split_line_ids=None)`

- **Footprints:** the footprint of a split line is every cell whose drainage
  path (each cell to the neighbour receiving most of its event volume) crosses
  the line, in any event, with holes filled.
- **Nesting:** footprints nest, and each cell goes to the smallest footprint
  holding it. Tier 1 has nothing upstream; cells no line drains form the
  `remainder`.
- **Outputs:** `subdomains` (schema `subdomain_partition`) and `cell_owner`
  (schema `subdomain_cell_owner`, every physical cell once).

Labels are information, not gates:

- `CLOSED_EDGE_LEAKAGE`: gross exchange across closed edges is over 5% of
  outlet volume.
- `FOOTPRINT_OVERLAP`
- `FOOTPRINT_PARTS_DROPPED`
- `MULTIPART`
- `STRUCTURE_ON_SPLIT_LINE`
- `INTERIOR_SUBDOMAIN`: touches no parent perimeter face (for example a band
  between two split lines on one stem). It can still be cut.
- `HOLES`: a nested subdomain lies wholly inside this one, so this one has a
  hole.

The authoring step refuses `HOLES`, `MULTIPART` and `STRUCTURE_ON_SPLIT_LINE`
in this release.

On the Salt Draw HEC-RAS 6.6 parent (794,332 cells, 1% AEP, native Face Flow)
with TauDEM links at 100 ft and 0.5 sq mi, the search scored 1,304 pour points
in 27,188 walk-up steps. It accepted 148 split lines, which nest into 30
tiers. The search took 16 minutes and the partition 5 more on a workstation;
most of the time goes to streaming the 12.6 GB of face flow.

## Authoring, running and comparing breakouts

```python
breakout_plan = RasSubdomain.plan_breakouts(partition, "01", ras_object=parent, subdomain_ids=["2568"])
assert breakout_plan.is_ready
breakouts = RasSubdomain.apply_breakouts(breakout_plan, "work/breakouts")
checks = RasSubdomain.validate_breakouts(breakouts)
runs = RasSubdomain.compute_subdomains(breakouts, max_workers=2, num_cores=4)
comparison = RasSubdomain.compare_to_parent(breakouts, "Model.p01.hdf")
```

### `plan_breakouts`

`plan_breakouts(partition, plan_number, *, ras_object, perimeter_friction_slope=0.01, subdomain_ids=None)`
writes nothing. Per subdomain it records:

- the exact parent cells to keep;
- the BC lines:
  - the outlet split line as Normal Depth at its fitted slope;
  - one Flow Hydrograph line per upstream subdomain, carrying the parent's own
    flow across that split line until the upstream child has run;
  - Normal Depth along each stretch of the parent perimeter.

Every other edge is a closed wall, as in the parent. It runs
`RasBreakout2D.preflight` against the parent and checks that the parent geometry
HDF is the mesh that was searched. `HOLES`, `MULTIPART` and
`STRUCTURE_ON_SPLIT_LINE` become blocking checks.

### `apply_breakouts`

`apply_breakouts(breakout_plan, dest_folder, *, overwrite_dest=False, hecras_version=None, time_step="parent_minimum")`:

- **Working copy:** copies the parent project to `dest_folder`. The copy roots
  at the smallest folder holding the project file and its RAS Mapper assets
  (so eBFE layouts with `Terrain/` beside `Input/` keep resolving), and leaves
  out parent result HDFs.
- **Per subdomain:**
  - clones plan, geometry and unsteady file (`RasBreakout2D.clone_plan_components`);
  - removes the parent's perimeter BC lines from the cloned geometry;
  - cuts the clone to the exact parent cells in HEC-RAS 6.6
    (`prepare_cloned_geometry(parent_cell_ids=...)`);
  - writes the BC lines and their forcing (`GeomBcLines.replace_bc_lines`).
- **BC line placement:** HEC-RAS can misclassify a line drawn on the perimeter
  or assign a short line to the whole ring. After each full preprocess, a line
  that HEC-RAS rejects, that attaches to no face, that shares faces with
  another line, or that spreads over the whole perimeter moves to its next
  placement. The placements, in order: on the perimeter; offset 1 ft outward
  with ends trimmed; extended 50 ft; following the perimeter 200, 400 or 800 ft
  past each end.
- **Time step:** `time_step="parent_minimum"` fixes each child at the shortest
  step the parent can take, with the Courant-adaptive step off. A child must
  not out-step its parent, whose adaptive step is set by its most restrictive
  cells anywhere in the domain.

### `validate_breakouts`, `compute_subdomains` and `compare_to_parent`

- **`validate_breakouts`** preprocesses every child and checks each line
  against its compiled external faces (schema `subdomain_breakout_checks`).
- **`compute_subdomains`** runs one tier at a time through
  `RasCmdr.compute_parallel`. Before each tier, each upstream child's outlet
  flow is written into the matching inflow line downstream (schema
  `subdomain_compute_runs`).
- **`compare_to_parent`** compares each child cell with the same parent cell
  (schema `subdomain_parent_comparison`):
  - maximum-WSE difference percentiles over cells wet in both;
  - wet-extent IoU;
  - outlet peak, timing, volume and NSE against the parent's native flow
    across the same faces.

### Salt Draw headwater 2568

5.1 sq mi, 2,407 parent cells, 1% AEP. The breakout ran in 1 min on a
workstation (4 cores).

| Child time step | Max-WSE diff p50 / p95 / p99 / max (ft) | Outlet peak | Outlet volume | Outlet NSE |
|---|---|---|---|---|
| Inherited adaptive (30 s, Courant 2) | 0.007 / 0.67 / 1.53 / 3.10 | +2.1% | -0.4% | 0.58 |
| Parent minimum (fixed 15 s), the default | 0.0015 / 0.018 / 0.079 / 0.26 | +2.6% | +2.0% | 0.89 |

The parent dropped to 15 s at 12:03 on the event day, forced by its most
restrictive cells elsewhere in the HUC. The child alone stayed at 30 s until
12:30, and a transient at its wetting front set summary maxima up to 3 ft high.

## Provenance

Ported from fim-commander's rain-on-grid subdomain research on Salt Draw
(HUC-8 13070004, one HEC-RAS 6.6 parent of about 794,000 cells). Six cookie-cut
children plus the main channel reproduced the parent's 1% AEP results:

- **Main channel:** maximum WSE p95 within 0.008 ft over 466,000 cells; HUC
  outlet peak within 0.2%, volume within 0.13%, NSE 0.99999.
- **Wall clock:** the subdomain runs took about 28% less time than the parent
  run.

That research took its pour points from the NextGen hydrofabric. This port uses
TauDEM links and catchments instead.

## Source reference

::: ras_commander.subdomain.RasSubdomain
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - RasSubdomain
        - SplitLineCriteria
        - SplitLineSearch
        - SubdomainPartition

::: ras_commander.subdomain._breakouts
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - SubdomainBreakout
        - SubdomainBreakoutPlan
        - SubdomainBreakoutSet
