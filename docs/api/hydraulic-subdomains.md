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
