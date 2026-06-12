# LLM Agent Guide

This page is the canonical, copy-runnable landing page for **LLM agents** building on
RAS Commander. It is intentionally dense: install, the cardinal rules, and complete recipes
you can paste and run.

!!! tip "Machine-readable docs"
    A curated index of this site is published at
    [`https://rascommander.info/llms.txt`](https://rascommander.info/llms.txt), with the full
    concatenated corpus at
    [`https://rascommander.info/llms-full.txt`](https://rascommander.info/llms-full.txt).
    Most pages are also mirrored as raw markdown (append `.md` to the page URL).

## Install

```bash
pip install ras-commander
```

RAS Commander automates an **installed HEC-RAS** (`Ras.exe`). Execution recipes require
HEC-RAS on Windows; parsing/extraction recipes work anywhere the result files exist.

## Cardinal rules

1. **Static classes — call, don't instantiate.** `RasCmdr`, `RasPlan`, `RasGeometry`,
   `RasUnsteady`, and every `Hdf*` class are static namespaces. Call methods directly:
   `RasCmdr.compute_plan("01")`, **not** `RasCmdr().compute_plan(...)`. The only object you
   instantiate (indirectly) is the project object via `init_ras_project()`.

2. **DataFrame-first.** After `init_ras_project()`, the project metadata lives in pandas
   DataFrames: `plan_df`, `geom_df`, `flow_df`, `unsteady_df`, `boundaries_df`, `rasmap_df`,
   `results_df`. Use them as the source of truth for file paths, plan/geometry linkage, and
   boundary inventory instead of globbing the folder. See the
   [DataFrame Reference](../reference/dataframe-reference.md) for every column.

3. **`ras_object=` discipline for multi-project work.** A global `ras` object is convenient
   for a single project. The moment you work with more than one project, capture the object
   returned by `init_ras_project(...)` and pass it explicitly:
   `RasCmdr.compute_plan("01", ras_object=my_ras)`. Mixing the global with a second project is
   the most common agent bug.

4. **`RasExamples.extract_project(...)` for real test data.** Do not invent or mock HEC-RAS
   projects. Extract a bundled, real project. Use `suffix=` to get an isolated copy you can
   mutate without colliding with other runs:
   `RasExamples.extract_project("Muncie", suffix="_run1")`.

5. **Detect steady vs unsteady before extracting results.** Steady and unsteady HDF results
   have different structures. Call `HdfResultsPlan.is_steady_plan(hdf_path)` first.

6. **Normalize plan/geometry numbers.** `"1"`, `"01"`, `"p01"`, and `Path("Model.p01")` all
   resolve to plan `01`. Most APIs accept any of these; `RasUtils.normalize_ras_number()`
   makes it explicit.

## Recipe 1 — Initialize and inspect plans

```python
from ras_commander import init_ras_project, RasExamples

# Extract a real bundled project to an isolated copy
project_path = RasExamples.extract_project("Muncie", suffix="_inspect")

# init_ras_project returns the project object (also sets the global `ras`)
my_ras = init_ras_project(project_path, "6.6")

# DataFrame-first inspection
print(my_ras.plan_df[["plan_number", "Plan Title", "geometry_number",
                      "unsteady_number", "flow_type"]])
print(my_ras.geom_df[["geom_number", "geom_title", "has_2d_mesh",
                      "num_cross_sections"]])

# Which plans already have computed HDF results?
computed = my_ras.plan_df[my_ras.plan_df["HDF_Results_Path"].notna()]
print(f"{len(computed)} of {len(my_ras.plan_df)} plans have HDF results")
```

## Recipe 2 — Compute a plan, then verify success

```python
from ras_commander import init_ras_project, RasExamples, RasCmdr

project_path = RasExamples.extract_project("Muncie", suffix="_compute")
my_ras = init_ras_project(project_path, "6.6")

# Execute to a separate destination folder so the source stays immutable
success = RasCmdr.compute_plan(
    "01",
    dest_folder=str(project_path) + "_results",
    overwrite_dest=True,
    ras_object=my_ras,
)
print(f"Execution {'succeeded' if success else 'failed'}")

# Refresh and read the results summary (completion, errors, runtime)
my_ras.update_results_df(["01"])
print(my_ras.results_df[["plan_number", "completed", "has_errors",
                         "runtime_complete_process_hours"]])
```

## Recipe 3 — Extract maximum WSE from a 2D mesh

```python
from ras_commander import init_ras_project, RasExamples
from ras_commander.hdf import HdfResultsPlan, HdfResultsMesh

# A 2D example with computed results
project_path = RasExamples.extract_project("BaldEagleCrkMulti2D", suffix="_wse")
my_ras = init_ras_project(project_path, "6.6")

# Pick a plan that has results
plan_number = my_ras.plan_df[my_ras.plan_df["HDF_Results_Path"].notna()] \
                    ["plan_number"].iloc[0]

# Steady and unsteady results differ — detect first
hdf_path = my_ras.plan_df.set_index("plan_number") \
                  .loc[plan_number, "HDF_Results_Path"]
if HdfResultsPlan.is_steady_plan(hdf_path):
    raise RuntimeError("This recipe expects an unsteady 2D plan")

# Maximum water surface elevation per mesh cell (GeoDataFrame, one row per cell)
max_ws = HdfResultsMesh.get_mesh_max_ws(plan_number, ras_object=my_ras)
print(max_ws.columns.tolist())
print(f"Peak WSE across mesh: {max_ws['maximum_water_surface'].max():.2f} ft")
```

## Recipe 4 — Audit boundary conditions and DSS paths

```python
from ras_commander import init_ras_project, RasExamples

project_path = RasExamples.extract_project("BaldEagleCrkMulti2D", suffix="_bc")
my_ras = init_ras_project(project_path, "6.6")

bc = my_ras.boundaries_df

# Inventory by type
print(bc["bc_type"].value_counts())

# DSS-backed boundaries with their parsed pathname parts
dss = bc[bc["Use DSS"] == "True"]
print(dss[["unsteady_number", "bc_type", "river_reach_name",
           "dss_part_b", "dss_part_c", "DSS File"]])
```

## Where to go next

- [DataFrame Reference](../reference/dataframe-reference.md) — every column of every
  project DataFrame, with dtypes and meanings (the #1 thing an integrating agent cannot
  introspect without running HEC-RAS).
- [HDF Data Extraction](../user-guide/hdf-data-extraction.md) — mesh/cross-section result APIs.
- [Plan Execution](../user-guide/plan-execution.md) — parallel compute, destination folders.
- [API Reference](../api/index.md) — full class/method signatures from docstrings.
