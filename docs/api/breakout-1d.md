# 1D Breakout Extraction

`RasBreakout1D` creates an independent, steady-flow HEC-RAS project from a
continuous slice of one 1D river reach. Selection and extraction are separate,
so a station range, polygon, network edge, or explicit cross-section set can
feed the same fail-closed writer and validation workflow.

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
