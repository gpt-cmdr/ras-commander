# 1D Breakout Extraction

`RasBreakout1D` creates an independent, steady-flow HEC-RAS project from a
continuous slice of one 1D river reach. Selection and extraction are separate,
so a station range, polygon, network edge, or explicit cross-section set can
feed the same fail-closed writer and validation workflow.

## Catalog multiple source models

Use `catalog_sources()` before planning a network edge that may cross more than
one source project. Caller-defined IDs remain stable throughout coverage,
seam, and later geometry-provenance tables.

```python
from ras_commander import RasBreakout1D

catalog = RasBreakout1D.catalog_sources(
    {
        "ble-upstream": upstream_ras,
        "ble-downstream": downstream_ras,
    },
    model_footprints=footprints_gdf,
    analysis_crs="EPSG:2277",
)

catalog.write("working/ble-breakout-source-catalog")
```

`source_models` values must be initialized `RasPrj` instances with steady 1D
plans. The returned `Breakout1DSourceCatalog` contains:

| Property | Contents |
| --- | --- |
| `models_df` | Project/plan/geometry/flow paths, exact geometry hash, units, version, and profile schema |
| `footprints_gdf` | Deduplicated model footprints used by extent-first coverage |
| `centerlines_gdf` | River centerlines with globally unique composite reach IDs |
| `cross_sections_gdf` | GIS cut lines with globally unique composite XS IDs |

Supplied footprints are authoritative. Without them, the catalog prefers the
geometry-HDF footprint and falls back to the convex hull of legacy text-file
centerlines and cut lines. A projected CRS is required. Exact duplicate
geometry hashes remain visible in `models_df` through `duplicate_of` but are
excluded from the spatial tables by default.

Catalog persistence uses one ordinary Parquet table and three GeoParquet
tables; it does not require GeoPackage, SQLite, or a long-running database.
Load it later with `Breakout1DSourceCatalog.read()`.

## Plan one network edge across multiple models

`plan_network_edge()` turns model footprints into candidates, then confirms the
best source reach in each model with deliberately small, interpretable checks:
at least two cross-section intersections, station sequence agreement with the
directed edge, an optional mean centerline-offset limit, and a fail-closed
cross-model handoff check. It does not invoke the advanced seven-signal
conflation scorer.

```python
plan = RasBreakout1D.plan_network_edge(
    catalog,
    nwm_flowlines_gdf,
    edge_id="5790954",
    adapter="nwm",
    max_centerline_offset=500.0,
    max_cross_centerline_xs=1,
)

print(plan.status)
print(plan.reach_assignments_df)
print(plan.source_slices_df)
print(plan.seams_df)
print(plan.handoff_diagnostics_df)
```

The `Breakout1DPlan` keeps the full audit trail:

| Property | Contents |
| --- | --- |
| `reach_assignments_df` | Best reach per footprint candidate, confirmation status, and reason codes |
| `edge_coverage` | Directed coverage parts after rejecting footprint-only false positives |
| `source_slices_df` | Minimum-switch upstream-to-downstream source ownership intervals |
| `seams_df` | Overlap, touching, or gap transitions with a provisional handoff point |
| `handoff_diagnostics_df` | Centerline continuity plus IDs and counts of source cross sections intersecting both selected centerlines |
| `source_models_df` | Distinct source projects selected by the interval plan, ordered upstream to downstream |

The network geometry's coordinate order defines direction. Cross-section river
stations must decrease as edge measure increases; a conflicting sequence is
rejected explicitly. A footprint can contribute multiple disconnected
coverage slices, so plan output reports both distinct model count and slice
count.

For every cross-model seam, `plan_network_edge()` checks the complete source
cross-section sets against both selected centerlines. The default permits at
most one cross section to intersect both lines. Two or more produce
`plan.status == "multi_source_handoff_conflict"`, `plan.join_ready == False`,
and the reason code `MULTIPLE_XS_INTERSECT_BOTH_CENTERLINES`. This rejects the
former overlapping tributary/main-stem example before a writer can treat it as
an adjacent source reach. Set `max_cross_centerline_xs` explicitly only when a
different reviewed threshold is warranted.

An overlap midpoint is only an extent-planning seam. Before a combined geometry
is written, the next-stage geometry assembler must choose a centerline
intersection or documented nearest connection, remove duplicate/overlapping cut
lines, preserve complete geometry blocks and flow-change locations, reconcile
stations, and validate profile and units compatibility.

## Select a reach slice

```python
from ras_commander import RasBreakout1D

selection = RasBreakout1D.select_by_stations(
    source_geometry_file,
    river="White River",
    reach="Main Stem",
    upstream_station=24000,
    downstream_station=12000,
)
```

Other selectors accept:

- a contiguous cross-section station set with `select_by_cross_sections()`;
- a Shapely polygon intersecting the desired cut lines with
  `select_by_polygon()`;
- a Shapely network edge and optional search tolerance with
  `select_by_network_edge()` (`select_by_network_segment()` is an alias).

Polygon and network geometries must use the geometry file's coordinate system.
An omitted river/reach is accepted only when the selection resolves to exactly
one reach.

Network-edge selection includes one additional downstream cross section by
default. This matches Ripple1D's shared-boundary convention for reach-sized
submodels and provides an internal target reach with a downstream boundary
section. Pass `downstream_overlap_xs=0` for the directly intersected span only,
or a larger integer for a wider transition zone.

Optional `upstream_buffer_distance` and `downstream_buffer_distance` values
expand a network-edge selection using the source geometry's main-channel reach
lengths. These values use HEC-RAS reach-length/model units; by contrast,
`tolerance` uses the network geometry's spatial coordinate-system units.
Expansion retains the first cross section at or beyond each requested distance
and stops at the available upstream or downstream terminus.

## Separate computation and inundation domains

Use `select_domains_by_network_edge()` when a model should retain hydraulic
transition length without expanding its published inundation footprint:

```python
domains = RasBreakout1D.select_domains_by_network_edge(
    source_geometry_file,
    target_edge.geometry,
    river="White River",
    reach="Main Stem",
    inside_fraction=target_edge.inside_fraction,
)

computation_selection = domains.computation_selection
inundation_selection = domains.inundation_selection
```

When `inside_fraction` indicates that the network edge is fully inside the
model, omitted buffer distances default to 10% of the full source-reach main
channel length upstream and 25% downstream. Explicit distances override those
defaults independently. Partial edges receive no automatic distance buffer.

The inundation selection remains the directly intersected span plus one shared
downstream cross section by default. The computation selection always contains
that strict export selection and extends to the first cross section meeting each
hydraulic buffer distance, or to the source-model terminus. This allows the
larger project to absorb boundary effects while a later raster-clipping step
uses the smaller, overlapping export domain.

`inundation_overlap_xs` records the requested overlap and
`inundation_overlap_xs_applied` records how many downstream sections were
available before the model terminus. The `*_buffer_applied` distances report
only the hydraulic distance expansion; they do not count the strict raster
overlap that is unioned into the computation selection.

## Extract and validate

```python
result = RasBreakout1D.extract_selection(
    source_ras,
    r"D:\models\white_river_breakout",
    selection,
    plan_number="01",
    destination_name="white_river_breakout",
    boundary_mode="auto",
)

assert result.validation.is_valid
print(result.project_file)
print(result.boundary_provenance)
```

The destination receives its own `.prj`, `.p01`, `.g01`, and `.f01` files and
an initialized `RasPrj`. The geometry writer preserves complete retained
cross-section and inline-structure blocks, including Manning's n, bank
stations, levees, ineffective areas, blocked obstructions, and HTAB settings.
It clips the one-reach `Reach XY` centerline to the retained boundary-section
crossings, keeps upstream reach lengths, and zeroes the downstream retained
section's L/Ch/R reach lengths because no downstream section remains.
Steady-flow change locations inside the retained range are preserved, and the
active source flow is propagated to the new upstream limit.

The validation dataframe checks project/plan/geometry/flow relationships,
retained stations and blocks, flow profiles and change locations, reach-length
termination, boundary data, and source-geometry immutability. Use
`result.validation.raise_for_errors()` when validating separately.

## Downstream boundaries

`boundary_mode` controls an internal downstream cut:

| Mode | Behavior |
| --- | --- |
| `auto` | Use source steady-plan WSE results when available; otherwise preserve the source boundary and record the fallback. |
| `source_results` | Require usable steady-plan HDF results and write known WSE values by profile. |
| `preserve` | Preserve the source reach boundary. |

Pass `downstream_boundary={...}` to explicitly override those modes with a
boundary definition accepted by `RasSteady.write_flow_file()`.

## Run and compare

Execution is always routed through `RasCmdr`:

```python
compute_result = RasBreakout1D.run(result, verify=True)

geometry_delta = RasBreakout1D.compare_geometry(
    source_geometry_file,
    result.geometry_file,
    result.selection,
)

results_delta = RasBreakout1D.compare_results(
    source_plan_hdf,
    destination_plan_hdf,
    result.selection,
)
```

`compare_geometry()` reports exact retained cross-section payload agreement and
whether intervening structure blocks match. `compare_results()` reports numeric
differences at retained cross sections for matching steady profiles after both
plans have completed.

## MVP boundaries

The initial workflow intentionally fails closed for multi-reach or junction
selections, non-contiguous cross sections, unsteady or sediment plans, lateral
structures, and selections with fewer than two cross sections. The one-reach
writer clips `Reach XY` only when both retained boundary cut lines intersect the
source centerline; otherwise it preserves the source header. Multi-reach
centerline clipping and reconnection remain outside the MVP.

::: ras_commander.RasBreakout1D.RasBreakout1D
    options:
      show_source: false
      members:
        - catalog_sources
        - plan_network_edge
        - select_by_stations
        - select_by_cross_sections
        - select_by_polygon
        - select_by_network_edge
        - select_domains_by_network_edge
        - select_network_edge_domains
        - select_by_network_segment
        - extract_reach
        - extract_selection
        - validate
        - run
        - compare_geometry
        - compare_results
