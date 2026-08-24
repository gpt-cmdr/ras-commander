# Dam Breach Analysis

RAS Commander separates stored breach configuration from computed breach
results:

| Class | Source | Purpose |
|---|---|---|
| `RasBreach` | Plan text (`.p##`) | Discover, read, create, and update stored breach definitions |
| `HdfStruc` | Plan HDF (`.p##.hdf`) | Discover SA/2D connections and available breach-result datasets |
| `HdfResultsBreach` | Plan HDF (`.p##.hdf`) | Extract structure and breach result time series and summaries |

Stored definitions, stored activation, and computed results are different
states. A retained definition may be inactive, and the presence of a breach
result dataset does not by itself prove that a breach initiated during a run.

## Inspect Stored Breach Definitions

`list_breach_structures_plan()` returns one dictionary per `Breach Loc`
definition, not a list of structure-name strings:

```python
from ras_commander import RasBreach, init_ras_project

init_ras_project("/path/to/project", "6.5")

definitions = RasBreach.list_breach_structures_plan("01")
for definition in definitions:
    print(
        definition["structure"],
        definition["river"],
        definition["reach"],
        definition["station"],
        definition["is_active"],
    )
```

Each dictionary has `structure`, `river`, `reach`, `station`, and
`is_active`. The `is_active` value is the local stored `Breach Loc` flag; it is
not evidence that the breach initiated during a computation.

Named definitions can be read through `read_breach_block()`:

```python
named = [item for item in definitions if item["structure"]]
if named:
    structure_name = named[0]["structure"]
    block = RasBreach.read_breach_block("01", structure_name)

    print(block["structure_name"])
    print(block["is_active"])
    print(block["river"], block["reach"], block["station"])
    print(block["values"])      # raw named values, including Breach Geom
    print(block["table_rows"])  # parsed progression/downcutting tables
```

Some older 1D plans contain unnamed river/reach/station definitions. They are
included in the list output. Passing `structure_name=""` to the existing read
or mutation methods selects the first unnamed definition. That selector is
ambiguous when a plan contains multiple unnamed definitions, just as duplicate
named definitions currently resolve to the first match.

## Update Stored Parameters

For individual fields in the ten-value `Breach Geom` record, use
`set_breach_geom()`:

```python
RasBreach.set_breach_geom(
    "01",
    "Dam1",
    initial_width=100.0,
    final_bottom_elev=850.0,
    left_slope=1.0,
    right_slope=1.0,
    formation_method=1,
    formation_time=2.0,
)
```

The geometry fields, in order, are `centerline`, `initial_width`,
`final_bottom_elev`, `left_slope`, `right_slope`, `active`, `weir_coef`,
`top_elev`, `formation_method`, and `formation_time`. In the raw CSV,
formation time is field index 9. Prefer the named setter instead of editing
that position directly.

`active=` in `set_breach_geom()` updates the activation-like field stored in
`Breach Geom`. To update the local `Breach Loc` flag returned as `is_active`,
use `update_breach_block(is_active=...)`:

```python
RasBreach.update_breach_block("01", "Dam1", is_active=False)
```

Use `update_breach_block()` for complete CSV records, tables, and advanced
parameters:

```python
RasBreach.update_breach_block(
    "01",
    "Dam1",
    method=9,
    dlb_methods=[9, 0, 0, 0, 0, 0, 0],
    dlb_soil_type=2,
    dlb_soil_properties=[1.5, 0.001, 35.0, 0.35, 18000, 5000, 30.0],
    dlb_core_soil_type=3,
    dlb_cover_option=1,
    dlb_cover_soil_properties=[1.0, 0.001, 30.0, 0.35, 18000, 4000, 28.0],
    dlb_breach_direction=0,
    user_growth_flag=1,
    user_growth_ratio=1.5,
    mass_wasting_option=1,
)
```

Other supported keyword groups are `geom_values`, `start_values`,
`progression_mode`, `progression_pairs`, `downcutting_pairs`,
`widening_pairs`, and `calculator_data`. These methods modify the plan file;
work on an owned project copy and keep the default backup behavior.

Create a new stored block with an explicit target, then configure it through
the same setters:

```python
RasBreach.create_breach_block(
    "01",
    "Dam1",
    river="Big River",
    reach="Upper",
    station="5000",
    is_active=True,
)
RasBreach.set_breach_geom(
    "01",
    "Dam1",
    initial_width=25.0,
    final_bottom_elev=850.0,
    formation_method=1,
    formation_time=2.0,
)
```

## Extract Computed HDF Results

The result readers accept either a plan number or a plan-HDF path. First use
`HdfStruc` to inspect the names stored in the HDF; those names can differ from
the plan-text names:

```python
from ras_commander import HdfResultsBreach, HdfStruc

connections = HdfStruc.list_sa2d_connections("01")
breach_info = HdfStruc.get_sa2d_breach_info("01")
print(connections)
print(breach_info)
```

### Combined Time Series

```python
ts = HdfResultsBreach.get_breach_timeseries("01", "Dam1")
print(ts.columns)

ts.plot(x="datetime", y="breach_flow")
```

For one requested structure, the combined DataFrame columns are:

```text
datetime, total_flow, weir_flow, breach_flow, hw, tw, bottom_width,
bottom_elevation, left_slope, right_slope, breach_velocity, breach_flow_area
```

When multiple structures are returned, a `structure` column is also present.

### Individual Result Families

`get_structure_variables()` returns:

```text
datetime, [structure], total_flow, weir_flow, hw, tw
```

`get_breaching_variables()` returns:

```text
datetime, [structure], hw, tw, bottom_width, bottom_elevation, left_slope,
right_slope, breach_flow, breach_velocity, breach_flow_area
```

Here `[structure]` means the column is included when multiple structures are
returned.

### Summary

```python
summary = HdfResultsBreach.get_breach_summary("01", "Dam1")
if not summary.empty:
    row = summary.iloc[0]
    print(row["max_total_flow"])
    print(row["max_breach_flow"])
    print(row["final_breach_width"])
```

The summary DataFrame can contain `structure`, `breach_initiated`,
`breach_at_time`, `breach_at_date`, `max_total_flow`,
`max_total_flow_time`, `max_breach_flow`, `max_breach_flow_time`,
`final_breach_width`, `final_breach_depth`, `max_hw`, and `max_tw`.
The current `breach_initiated` field mirrors the HDF breach-dataset indicator;
do not treat it as independent proof of the physical initiation event.

## Project-Level Discovery

After project initialization, `plan_df` provides two lightweight counts:

```python
ras.plan_df[[
    "plan_number",
    "breach_definition_count",
    "breach_active_count",
]]
```

`breach_definition_count` counts parsed stored definitions.
`breach_active_count` counts definitions whose local stored `is_active` flag
is true. Zero means the plan was successfully inspected and no matching rows
were found; a null count means inspection failed. Use `RasBreach` for the
structure-level details.

## See Also

- [420_breach_results_extraction.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/420_breach_results_extraction.ipynb) - Breach parameter and HDF-result examples
- [HDF Data Extraction](hdf-data-extraction.md) - General HDF access
- [Plan Execution](plan-execution.md) - Running plans on isolated project copies
