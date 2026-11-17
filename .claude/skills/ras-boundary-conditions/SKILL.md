---
name: ras-boundary-conditions
description: "Inspect, prepare, attach, and validate HEC-RAS flow/stage hydrographs, normal-depth boundaries, rating curves, gate schedules, and DSS links. Use for boundary inventories, changes, or HMS-to-RAS handoffs."
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
---

# HEC-RAS boundary conditions

Own the hydraulic boundary assignment and its plan linkage. Meteorological conversion belongs to `ras-meteorological-forcings`; rain-on-grid authoring belongs to `ras-gridded-precipitation`.

## Plan and inspect

Read the boundary-condition and applicable coastal topics in [HEC planning references](https://github.com/gpt-cmdr/ras-commander/blob/main/docs/development/hec-planning-references.md) before selecting boundary types, initial conditions, or downstream assumptions. Select the target HEC-RAS version; identify datum and model clock explicitly. A manual describes engine behavior, not proof that a particular library writer exists.

Read [workflow evidence](references/workflow-evidence.md) for the relevant boundary operation. Record installed `ras-commander` and optional DSS-engine versions, then inspect current public signatures. Initialize the project through RAS Commander and use `plan_df`, `boundaries_df`, and the public unsteady APIs to identify the owning unsteady file and exact location. Distinguish read-only metadata from editable inputs. Do not select the first matching row when locations repeat across plans.

## Prepare, attach, and verify

- Preserve the source project; make authorized edits on a disposable project copy. For supported boundary deletion use the staged-project `RasUnsteady.delete_boundary` contract, preview and exact identity/digest checks; other legacy writers may modify their target in place.
- Inventory boundary type, location, inline versus DSS state, active filename/pathname, units, datum, time basis, simulation/warmup coverage, QMult/QMin, and initial-stage settings where applicable. Preserve unrelated gates and meteorology.
- Use current public `RasUnsteady` setters for the requested boundary. Write DSS through `RasDss`, read back the exact record, and then attach its reviewed reference. Never replace project parsing/writing with ad hoc text edits.
- Reinitialize/read back the edited owner and verify plan linkage, assignment, series values, units, coverage, multipliers, and state transitions. Correlation can suggest an HMS-to-RAS match; it does not establish the physical correspondence.
- If preprocessing or compute is authorized, use `RasPreprocess`/`RasCmdr` and inspect solver-facing inputs, boundary results and compute messages. Do not invoke `Ras.exe` directly. Report whether evidence stops at saved inputs, preprocessing, or a completed run.

Return the boundary-to-source assignment table, changed artifact paths, before/after checks, engine/library versions, and unresolved hydraulic assumptions. An available pathname or successful write alone is not model-consumption evidence.
