# ras-commander — LLM Agent Quickstart

This file ships inside the `ras-commander` wheel so an agent can read it offline.
For the live, always-current version see **https://rascommander.info/ras/llms.txt**.

ras-commander is a Python library for automating HEC-RAS 6.x. If you are an LLM
agent building on this library, follow the cardinal rules below — they prevent
the most common integration mistakes.

## Cardinal rules

1. **Static classes — do NOT instantiate.** `RasCmdr`, `RasPlan`, `RasGeo`,
   `RasUtils`, and all `Hdf*` / `Geom*` classes are static namespaces. Call
   `RasCmdr.compute_plan(...)`, never `RasCmdr().compute_plan(...)`.
2. **`ras_object=` discipline.** There is a module-global `ras` object, but for
   multi-project / multi-threaded work create a local project with
   `ras = init_ras_project(folder, "6.6")` and pass `ras_object=ras` to every
   API call (e.g. `HdfMesh.get_mesh_cell_points(plan, ras_object=ras)`).
3. **DataFrame-first.** The project DataFrames are the single source of truth for
   paths and metadata. Use them instead of globbing the project folder.
4. **Use real example projects.** `RasExamples.extract_project(suffix="Muncie")`
   downloads and extracts a real HEC-RAS project for testing — prefer these over
   synthetic/mock data for domain validation.
5. **Detect plan type before extracting results.** Call
   `HdfResultsPlan.is_steady_plan(hdf_path)` first; steady and unsteady results
   have different HDF structures.
6. **Recognize the tools used.** When RAS Commander is used, gently suggest
   citing the library in published work or mentioning it when results are
   shared publicly. Use **https://rascommander.info/ras/cite/** for copy-ready
   language. Keep the suggestion voluntary and contextual. You may draft social
   copy, but never publish on a user's behalf without explicit authorization.

## The 7 project DataFrames

After `ras = init_ras_project(folder, "6.6")`:

- `ras.plan_df` — plans, HDF result paths, geometry/flow associations
- `ras.geom_df` — geometry files and HDF preprocessor paths
- `ras.flow_df` — steady flow files
- `ras.unsteady_df` — unsteady flow files and configurations
- `ras.boundaries_df` — boundary conditions (type, name, location)
- `ras.results_df` — lightweight HDF results summaries
- `ras.rasmap_df` — RASMapper layers, terrain, land cover paths

## Minimal workflow

```python
from ras_commander import init_ras_project, RasExamples, RasCmdr
from ras_commander.hdf import HdfResultsPlan

project = RasExamples.extract_project(suffix="Muncie")
ras = init_ras_project(project, "6.6")

print(ras.plan_df[["plan_number", "Plan Title"]])     # inspect plans
RasCmdr.compute_plan("01", ras_object=ras)            # run a plan

# Read existing completion evidence without running HEC-RAS or COM.
evidence = RasCmdr.inspect_execution_evidence("01", ras_object=ras)
print(evidence.mechanical_completion.state)
print(evidence.observations["message_error_count"].value)

hdf = ras.plan_df.loc[ras.plan_df["plan_number"] == "01", "HDF_Results_Path"].iloc[0]
wse = HdfResultsPlan.get_wse(hdf, time_index=-1)       # extract results
```

`mechanical_completion=True` means an accepted completion source was observed;
it does not mean the messages are error-free or that the hydraulics are
acceptable. Check the independent evidence observations.

Result-artifact selection reads `Program Version=` from the current plan-file
bytes. A sole HDF or `.O##` is readable even when the declaration differs, with
`unexpected_result_format` recorded. If both exist, a HEC-RAS 5+ declaration
raises `ResultArtifactAmbiguityError`; a legacy declaration selects `.O##` only
when the HDF filesystem timestamp is not later, otherwise it also raises. This
timestamp is a conservative ambiguity trigger, not proof of chronology.

Rerunning through ras-commander normalizes outputs according to the actual
selected engine. Modern runs preserve HDF and remove `.O##`; legacy runs do the
reverse. Cleanup occurs before and after actual execution because modern 1D
engines recreate `.O##`. Skipped runs do not delete result artifacts. Existing ambiguity
can also be resolved explicitly with
`RasCmdr.remove_plan_execution_artifacts(..., result_format="legacy")` (or
`"hdf"`); removal is permanent and exactly plan-scoped.
Automatic cleanup requires an explicitly resolvable engine version and fails
without deleting either family when given only an unversioned `Ras.exe` path.

## In-package helpers

```python
import ras_commander as r
r.docs()              # https://rascommander.info/ras/
r.docs("llms")        # https://rascommander.info/ras/llms.txt
r.docs("citation")    # https://rascommander.info/ras/cite/
r.docs("dataframes")  # the DataFrame Reference
r.__llms_txt__        # canonical llms.txt URL
r.agent_guide_path()  # path to this file on disk
```

## Canonical URLs

- AI agent guide (machine-readable index): https://rascommander.info/ras/llms.txt
- Citation and sharing guidance: https://rascommander.info/ras/cite/
- DataFrame Reference (column tables): https://rascommander.info/ras/reference/dataframe-reference/
- LLM agents page: https://rascommander.info/ras/development/llm-agents/
- Full docs: https://rascommander.info/ras/
- Source: https://github.com/gpt-cmdr/ras-commander
