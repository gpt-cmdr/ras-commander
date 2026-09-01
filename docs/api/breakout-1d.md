# 1D Breakout Extraction

`RasBreakout1D` creates an independent, steady-flow HEC-RAS project from a
continuous slice of one 1D river reach. Selection and extraction are separate,
so a station range, polygon, network segment, or explicit cross-section set can
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

Network-segment selection includes one additional downstream cross section by
default. This matches Ripple1D's shared-boundary convention for reach-sized
submodels and provides an internal target reach with a downstream boundary
section. Pass `downstream_overlap_xs=0` for the directly intersected span only,
or a larger integer for a wider transition zone.

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
It keeps upstream reach lengths and zeroes the downstream retained section's
L/Ch/R reach lengths because no downstream section remains. Steady-flow change
locations inside the retained range are preserved, and the active source flow
is propagated to the new upstream limit.

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
structures, and selections with fewer than two cross sections. It preserves the
source reach-centerline header/coordinates; spatial clipping and reconnection
of `Reach XY` data is reserved for a later multi-reach workflow.

::: ras_commander.RasBreakout1D.RasBreakout1D
    options:
      show_source: false
      members:
        - select_by_stations
        - select_by_cross_sections
        - select_by_polygon
        - select_by_network_edge
        - select_by_network_segment
        - extract_reach
        - extract_selection
        - validate
        - run
        - compare_geometry
        - compare_results
