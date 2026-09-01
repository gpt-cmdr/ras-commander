# Hydrofabric Conflation

`RasNetworkConflation` starts with model-extent coverage, preserving the natural
one-model-to-many-edge relationship. NHDPlus, NWM, and NextGen are schema
adapters to the same generic directed-network core.

## Extent-first edge classification

```python
from ras_commander import RasNetworkConflation

coverage = RasNetworkConflation.classify_edges(
    model_footprints=footprints_gdf,
    network_edges=nwm_flowlines_gdf,
    adapter="nwm",
)

edge_coverage_df = coverage.coverage_df
```

`coverage_df` has one row per `(geometry_id, edge_id)` with positive spatial
overlap by default. It reports `inside_length`, full `edge_length`,
`inside_fraction`, and `extent_status` (`inside` or `partial`) while preserving
the full edge geometry and normalized topology fields. Pass
`include_outside=True` when an audit also needs nearby non-intersecting edges.

All spatial inputs must have a CRS. Measurements prefer the model footprint's
projected CRS, an explicitly supplied `analysis_crs`, or an automatically
estimated local UTM CRS. No weighted score is used: the model extent is the
authoritative spatial filter, and every in-domain edge is retained.

This table is the starting point for NWM-sized `RasBreakout1D` models. Select an
`edge_id`, pass its geometry to `select_by_network_edge()`, and retain the
default one-cross-section downstream overlap.

## Advanced reach-edge candidate audit

`conflate()` retains the earlier multi-signal candidate analysis for ambiguous
or poorly aligned networks. It is an advanced QA surface, not the default gate
for extent-based breakout generation. It crosswalks HEC-RAS model footprints,
reach centerlines, and cross sections to candidate flowpaths while retaining
the evidence instead of reducing a failed lookup to a numeric COMID.

```python
result = RasNetworkConflation.conflate(
    model_footprints=footprints_gdf,
    centerlines=reach_centerlines_gdf,
    cross_sections=xs_cut_lines_gdf,
    flowpaths=network_edges_gdf,
    adapter="nwm",
)
```

Measurements use the centerline's projected CRS, an explicitly supplied
`analysis_crs`, or an automatically estimated local UTM CRS when the
centerlines are geographic.

The method returns a `HydrofabricConflationResult` with three GeoDataFrames:

| Property | Contents | Active geometry |
| --- | --- | --- |
| `matches` | One explicit geometry, reach, and cross-section resolution row | HEC-RAS model element |
| `candidates` | Every retained candidate, rank, score component, and reason code | Hydrofabric flowpath |
| `reach_metrics` | Edge/reach association, XS limits, offsets, lengths, coverage, and flags | HEC-RAS reach centerline |
| `huc_intersections` | Optional model-footprint/HUC overlap records | Intersection polygon |

## Match states

`matches.status` is always one of:

- `matched` — the top candidate clears `min_confidence` and the runner-up
  separation clears `ambiguity_margin`;
- `ambiguous` — the best candidates are too close to resolve safely;
- `unmatched` — there is no spatial candidate or the best score is below the
  confidence threshold.

Only `matched` rows receive a `feature_id`. Ambiguous and unmatched rows retain
`best_candidate_feature_id`, `confidence_score`, `reason_codes`, and their full
candidate records, but `feature_id` remains null. This prevents failure states
from being mistaken for real numeric COMIDs.

```python
accepted = result.matches.query("status == 'matched'")
review = result.matches.query("status in ['ambiguous', 'unmatched']")

print(result.summary)
# {'matched': ..., 'ambiguous': ..., 'unmatched': ..., 'total': ...}
```

## Candidate scoring

Reach candidates combine seven evidence groups:

1. flowpath-length overlap with the model footprint;
2. sampled symmetric distance to the reach centerline;
3. directed angular agreement;
4. cross-section intersection coverage;
5. connectivity across adjacent model reaches;
6. stream-order and drainage-area support;
7. agreement between cross-section order along the reach and flowpath.

When an evidence group is unavailable—for example, a reach has no cross
sections—the method removes that group and renormalizes the remaining weights.
Override only the weights that need adjustment:

```python
result = RasHydrofabric.conflate(
    footprints_gdf,
    reach_centerlines_gdf,
    xs_cut_lines_gdf,
    flowpaths_gdf,
    weights={
        "centerline_distance": 0.30,
        "xs_intersections": 0.25,
    },
    min_confidence=0.60,
    ambiguity_margin=0.08,
)
```

Candidate columns expose both normalized component scores and raw evidence such
as `centerline_mean_distance`, `angular_difference_deg`,
`xs_intersection_count`, `stream_order`, and `drainage_area`.

## Cross-section measures

Accepted cross-section rows include:

- `flowpath_measure` — distance from the flowpath geometry start;
- `flowpath_measure_fraction` — normalized measure from 0 to 1;
- `flowpath_measure_from_end` — distance from the flowpath geometry end;
- `measure_method` — `intersection` or `nearest`;
- `offset_distance` — zero for a direct intersection, otherwise the nearest
  offset.

The units are those of `result.analysis_crs`.

## Reach limits, offsets, lengths, and flags

`result.reach_metrics` is the extraction-oriented network-edge ↔ RAS-reach
table. For the best edge candidate it reports:

- `upstream_xs_id` and `downstream_xs_id`, ordered from the directed network
  geometry start to its end;
- `coverage_start`, `coverage_end`, and the intervening `coverage_ratio`;
- RAS-centerline and network lengths between those sections, plus their ratio;
- centerline-offset distribution statistics at intersecting sections;
- thalweg-offset statistics when thalweg point geometry is supplied;
- explicit ambiguous, eclipsed, divergent, and insufficient-coverage flags.

Supply thalweg points as a keyed GeoDataFrame:

```python
result = RasNetworkConflation.conflate(
    footprints_gdf,
    reach_centerlines_gdf,
    xs_cut_lines_gdf,
    network_edges_gdf,
    thalweg_points=xs_thalweg_points_gdf,
    adapter=custom,
    min_coverage=0.50,
)
```

The thalweg layer must contain unique `reach_id`/`xs_id` Point rows. As a
convenience, a point-valued `thalweg_point` column on the cross-section frame is
also accepted. `centerline_offset` compares the RAS-centerline/XS crossing to
the network/XS crossing; `thalweg_offset` compares the supplied thalweg point
to the network/XS crossing.

An edge is marked `eclipsed` when it has no two distinct intersecting sections,
which is the network-neutral condition needed before a topology-specific
adapter walks neighboring edges. Divergence is evaluated from normalized
`from_node`/`to_node` fields; `connectivity_evaluable=False` keeps missing
connectivity from being silently treated as a non-divergence. Coverage below
`min_coverage` receives an `INSUFFICIENT_COVERAGE` reason code.

## Hydrofabric adapters

Pass `adapter="auto"` or select a built-in schema explicitly:

| Adapter | Typical identifier | Common normalized fields |
| --- | --- | --- |
| `nhdplus` | `COMID` | `StreamOrde`, `TotDASqKm`, node IDs, Hydroseq |
| `nwm` | `id` / `feature_id` | `toid`, `order`, `areasqkm`, hydroseq |
| `nextgen` | `feature_id` / `flowpath_id` | downstream/nexus IDs, order, drainage area, sequence |

For another schema, supply a custom adapter:

```python
from ras_commander import HydrofabricAdapter, RasNetworkConflation

custom = HydrofabricAdapter(
    name="agency_flowpaths",
    feature_id_fields=("agency_reach_id",),
    to_feature_id_fields=("downstream_reach_id",),
    stream_order_fields=("strahler",),
    drainage_area_fields=("drainage_sq_km",),
)

result = RasNetworkConflation.conflate(
    footprints_gdf,
    reach_centerlines_gdf,
    xs_cut_lines_gdf,
    agency_flowpaths_gdf,
    adapter=custom,
)
```

::: ras_commander.RasHydrofabric.RasNetworkConflation
    options:
      show_source: false
      members:
        - get_adapter
        - classify_edges
        - conflate
