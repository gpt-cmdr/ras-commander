# eBFE audit document — specification

**Status:** draft for sign-off. Nothing is re-run until this is agreed.
**Audience:** a practicing HEC-RAS engineer, plus downstream automation.
**Supersedes:** the per-HUC markdown emitted by the tranche-01 worker loop.

---

## What this document is for

**To take an engineer from "FEMA delivered a zip" to "this model runs" — and to tell a
machine the same thing.**

It answers four questions, in this order:

1. What is in this study?
2. What does it need that is not here?
3. **Where are its references broken, and what must be done to make it run?**
4. How do I trust any of the above?

Question 3 is the product. Everything else is context for it.

## The signature defect: relative references that escape the bundle

Measured across all of tranche 01: **zero absolute path references.** The campaign spent its
early effort guarding against absolute paths and that guard has never once fired.

The real defect is different and more subtle. FEMA's deliveries carry **relative** references
that were valid on the authoring machine and point *outside* anything that was shipped:

```
Spring.u01   DSS File = ..\..\..\..\HEC-HMS_v43\Spring\100YR.dss
Spring.rasmap            ..\..\..\..\GIS\Working\Spring\Shp\Spring_HUC.shp
```

Four levels up is not inside the delivery. The model opens, the reference resolves to nothing,
and — for a DSS boundary — HEC-RAS raises a modal dialog that hangs an unattended run.

So every reference gets an **escape depth**: how many levels above the model root it reaches.
That single number sorts the problem:

| Escape depth | Meaning | Action class |
|---|---|---|
| 0 | Resolves inside the model folder | none |
| ≥ 1, target present elsewhere in the delivery | Shipped, but not where the model looks | **file movement** or **path correction** |
| ≥ 1, target inside a nested archive | Shipped, still packed | **recursive extraction** |
| ≥ 1, target absent from the delivery | Not shipped | **reconstruction** or **acquisition** |

**This classification is the spine of the document.** It converts "33 missing references" —
which tells an engineer nothing — into a list of actions with known resolutions.

---

## Document structure

**Fixed skeleton. Every section appears in every study, in this order, even when empty.** A
section with nothing to report says so explicitly. 300-odd documents are only comparable if
their shape never varies, and a silently omitted section is indistinguishable from a section
that found nothing.

Every human-readable assertion is backed by a named field in `_audit.json` so automation reads
the same facts the engineer does. Field names are given in `code`.

### 1. Verdict

The first screen. An engineer decides here whether to keep reading.

- Study key, name, state
- **Model type** — 1D / 2D / mixed, steady / unsteady (`model_type`, `flow_regime`)
- **Authored HEC-RAS version** (`authored_version`) — a first-class field, not an artefact of a
  loader log
- Project count, and whether every project opens (`projects_total`, `projects_loaded`)
- **Runnable as delivered?** (`runnable_as_delivered`: `yes` · `after_repair` · `no`)
- If not: the count of blocking actions, and the single most important one

### 2. Model inventory

The "expected elements and whether they are present" table. **By name, not by count** — a
count tells an engineer nothing they can act on.

Per project (`models[]`): the `.prj`, then every plan, geometry, flow and unsteady file with
its number, title and short ID; whether each is registered in the `.prj`; and whether the file
is present on disk. A plan registered but not delivered, or delivered but not registered, is a
finding in its own right and both occur in this corpus.

### 3. Required supporting data

**Fixed rows, always all of them**, because absence is the thing being reported:

| Element | Expected | Delivered | Location | Note |
|---|---|---|---|---|
| Terrain | | | | |
| Land cover / Manning's n | | | | |
| Infiltration | | | | |
| Soils | | | | |
| DSS boundary data | | | | |
| Projection | | | | |
| RASMapper configuration | | | | |
| Results (plan HDFs) | | | | |
| Preprocessed geometry HDF | | | | |

`Expected` is derived from the model itself — a 1D steady model does not expect infiltration,
and reporting it "missing" would be false. **Never report a percentage where the denominator
is one project.** Yes / no / not applicable.

### 4. From delivered to runnable — the action list

**The core of the document.** An ordered, executable sequence. Each action:

| Field | Meaning |
|---|---|
| `order` | Execution order. Dependencies are real: extraction precedes movement, movement precedes path correction. |
| `kind` | `recursive_extraction` · `file_movement` · `path_correction` · `reconstruction` · `acquisition` |
| `target` | The file acted on, relative to the model root |
| `from` → `to` | For movements and path corrections |
| `archive` / `member` | For recursive extraction — which archive, which member, what nesting depth |
| `source` | For reconstruction — what it is rebuilt from. **Never fabricate**; if there is no source, this is `acquisition`. |
| `reason` | `broken_relative_reference` · `nested_archive` · `separately_delivered` · `not_delivered` |
| `escape_depth` | Levels above model root the original reference reached |
| `evidence` | `source_file:locator` — precise enough to find again |
| `confidence` | `resolved` (target located) · `inferred` (best match, needs review) |
| `blocking` | Whether the model fails to open or run without it |

Rendered for a human as numbered steps in plain language, with the machine fields available
per step. An engineer should be able to follow it by hand; a ras-commander helper should be
able to execute it without re-deriving anything.

**A missing `Terrain.hdf` is critical data missing, not a reconstruction.** Terrain
modifications (channel cuts, levees, polygon overrides) are stored inside that HDF and
referenced from the `.rasmap`, and it is unlikely any of these models was produced without at
least one. Rebuilding from delivered DEM rasters therefore yields a terrain that runs but is
not the one the model was calibrated against. The audit records `terrain.modifications` (every
modification element under each `.rasmap` terrain layer, and the `/Modifications/` group of any
delivered HDF) and emits **two** actions when the HDF is absent -- `reconstruction` (to run)
and a blocking `acquisition` (for fidelity) -- plus a `critical_missing` entry that the verdict
shows and the webmap hatches distinctly.

**What RASMapper actually writes (observed on tranche 01, 2026-09-09).** Terrain modifications
are `<Layer>` elements nested under the terrain layer and distinguished by `Type`:
`TerrainLayer` → `<Layer Type="ElevationModificationGroup" Name="Modifications">` →
`<Layer Type="GroundLineModificationLayer">` (with `<DefaultModificationType Value="1|2"/>`) or
`<Layer Type="PolygonElevationModificationLayer">`, each holding a
`<Layer Type="ElevationControlPointLayer" Name="Control Points">`. The words *Channel*, *Levee*,
*Override* never appear in the XML; every layer's `Filename` is the terrain HDF. Inside the HDF,
`/Modifications/<name>` groups carry attributes `Type` (`Levee`, `Polygon`), `Subtype` (`Channel`),
`Priority`, with `Attributes`, `Polyline Info/Parts/Points` and `Profile Info/Values` datasets;
names seen: `Channels`, `CutThrough`, `Polygons`, `Fill Sinks`. In 9 of 11 units the terrain HDF is
not at the `.rasmap`'s relative path but beside the project (FEMA's `Input/` relocation) — the
capture searches up two levels, as `check_terrain` does.

**Empirical rate: 6 of 11 RASMapper units carry modifications** (`12070205` 15 elements,
`12100201` 5, `12100302` 5, `12030102` 5, `13070007` 5), 5 carry none. The prior "unlikely any
model was produced without one" is about half right — but **both units with an absent
`Terrain.hdf` are in the modified half, and the `.rasmap` proves it.** So criticality is decided
by *referenced* modifications; `_unknown` stays an honest unknown rather than "likely lost".

**Recursive extraction deserves its own treatment.** Tranche 01 measured 21 nested archives in
a single study, and nesting that collapses a duplicated directory prefix. Record depth, the
containing archive, and the collapse, because a naive extractor produces a doubled path and a
model that cannot find its own files.

### 5. What is still missing

Everything the action list cannot resolve. **Listed in full, grouped by kind** — DSS,
terrain tiles, shapefiles, results — with the referencing file and the raw value as delivered.
Deduplicated: one undelivered shapefile referenced by forty layers is one finding, with a
count, not forty rows.

Where a whole class is missing for one reason, say the reason once. Tranche 01's 177
`MISSING_REFERENCE` entries in one study were a single undelivered `Shapefiles\` folder.

#### Every reported deficiency is reviewed before it is called one

Tranche 01 showed that a "missing" reference can be a gap in *our* analysis as easily as a
gap in the delivery: a detector said "no infiltration layer referenced" for a study whose
rasmap referenced `InfiltrationDC.hdf` twenty-two times. So every `MISSING_REFERENCE` and
every `acquisition` element carries a review verdict before it is reported:

| `review.verdict` | Meaning | Where it appears |
|---|---|---|
| `real` | Independently confirmed absent from the delivery | Sections 5 and 6 |
| `analysis_gap` | Found in the delivery after all -- other path, other case, nested archive, or a detector disagreeing with the rows | Section 5 under *Reclassified during review*; **never** section 6; corrected recipe added to section 4 |
| `unverifiable` | Cannot be settled in the audit environment (e.g. DSS pathname with no bridge) | Section 5, flagged as unconfirmed |
| unreviewed | Not yet checked | Verdict says *provisional* |

**The review must use a different code path than the scanner that produced the gap**, or it is
circular. The primary method is an archive-member match: enumerate every member of every
delivered archive (including nested ones) with the library `StreamingZipReader.probe()` and
match the missing reference's basename, case-insensitively. Present anywhere means
`analysis_gap`. Cross-detector consistency (`supporting_elements` vs the reference rows vs
`terrain.projects[]`) is the second method.

The verdict row reports `N reported: R real, A were gaps in our analysis, U unverifiable`.
**R is the honest deficiency count** and the only one the webmap or downstream planning may
use. A large A on tranche 01 is not a failure; it is why tranche 01 ran first.

### 6. What you must obtain

The engineer's shopping list: the external data required, why, and — where known — where it
comes from. This is section 5 turned into instructions.

### 7. Provenance and method

Demoted to an appendix, complete and unchanged: gates, verification, throughput, code build
identity, worker, timings. A reviewer must still be able to verify how every conclusion was
reached; an engineer must not have to read past it.

---

## Rules for the renderer

- **Lives in the library or a skill, never in a worker's task-local script.** Format drift
  between studies is a defect, and worker-local rendering is how it happens.
- **One renderer, one schema.** The markdown is generated *from* `_audit.json`; the two cannot
  disagree because only one is authored.
- **Engineer's vocabulary.** "Boundary conditions", not `boundaries_df`. "The project failed to
  open", not `INIT_FAILED`. Internal identifiers belong in the appendix and the JSON.
- **No percentages over small denominators.** Counts and explicit yes/no.
- **Empty sections say "none", never disappear.**
- **Every claim traceable.** Any statement about a file names the file.

## Capture fields to add before re-running

Not in today's `_audit.json`, required by this spec:

| Field | Why |
|---|---|
| Plan / geometry / flow / unsteady **names, numbers, titles, short IDs** | Section 2 needs names; only counts are stored today |
| `authored_version` | Currently recoverable only from an incidental loader error string |
| Land cover, infiltration, soils **explicit present/absent** | Only aggregate percentages today |
| `escape_depth` per reference | The classification this whole document rests on |
| `expected` per supporting element, derived from model type | So "missing" is never asserted about something the model never wanted |
| Nested archive **depth, container and prefix collapse** | Section 4 recursive-extraction steps |
| `blocking` per action | Separates "will not open" from "cosmetic" |

Everything else the spec needs is already captured and needs only re-rendering.

## Open question for sign-off

Section 4 assumes actions are **replayable against a fresh extraction of the raw archive** —
that is what makes the recipe durable while the extracted tree is disposable. Confirm that is
the intended contract: the audit is a recipe a future worker executes, not a description of
what one worker once did.
