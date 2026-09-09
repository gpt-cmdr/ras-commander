# eBFE campaign — Claude Code infrastructure assessment

**Date:** 2026-09-07, after ST-1 completed
**Question:** what reusable skills, agents, hooks and infrastructure would benefit this effort?

## The headline finding: three eBFE skills already exist

Before building anything, note what is already in `.claude/skills/`:

| Existing | Does | Relationship to this campaign |
|---|---|---|
| `ebfe_crawl_s3-catalog` | Crawls FEMA's BLE S3 bucket, caches a catalog by state/HUC | **Superseded in practice.** The acquisition campaign hit a 403 on `?list-type=2` and worked from a catalog + HEAD per object instead. Should be updated with that finding or marked historical. |
| `ebfe_organize_models` | Organizes downloads into the 4-folder structure | **Directly the G4/G5 work.** The worker loop should invoke this, not reimplement it. |
| `ebfe_validate_models` | `init_ras_project()` then checks `plan_df`, `boundary_df`, `rasmap_df` for missing plans, DSS, terrain, HDF | **This is A4a, already written.** The plan described this as new work. It is not. |

Plus the `ebfe-organizer` agent, which already encodes pattern detection, recursive
extraction, path validation and dataframe verification.

**So the first recommendation is a correction, not an addition: extend these three rather
than writing `ebfe_extract.py` / `ebfe_audit.py` around them.** A6 in the plan should be
re-scoped to "extend the existing eBFE skills and the organizer agent" with the specific
deltas below.

## What genuinely does not exist yet

These are real gaps that ST-1 exposed:

| Gap | Where it belongs | Why |
|---|---|---|
| Streaming zip reader for archives with no EOCD | `ebfe_extract.py` (new, library) | Medina `12100302` is 52 GB and `zipfile` refuses it. Nothing in the repo handles this. |
| Two-phase reference scan (`as_delivered` vs `after_standardization`) | extend `ebfe_validate_models` | The diff is the audit's whole value. The existing skill validates one state only. |
| Windows-path projection assertion | `ebfe_extract.py` | Linux never fails on long paths. Nothing asserts the 260-char budget today. |
| Provenance-stamped audit records | worker loop | Commit SHA + dirty-tree state must be in every `_audit.json`. |
| Nested-project discovery | **done** — `RasUtils.find_valid_ras_folders(include_nested=True)` | Shipped 2026-09-07. |
| `rasmap_df` status reporting | see `2026-09-07_rasmap_df_silent_failure.md` | Handed to an external agent. |

## Skills worth adding

**1. `ebfe_audit_data-gaps`** — the missing sibling of the existing three. Runs the two-phase
scan, classifies each reference (`present` · `present_after_rewrite` · `missing_from_delivery`
· `absolute_reference` · `ambiguous` · `external_service` · `size_mismatch`), and emits the
per-HUC markdown plus the three parquet tables. This is the one genuinely new skill; the
others below are lighter.

**2. `ebfe_dispatch_worker`** — the coordinator-side procedure. Encodes what I did by hand
this session: pick the next sub-tranche, brief a subagent with the standing rules (no hashing,
no execution, `include_nested=True`, per-project `ras_object`, three-signal rasmap test),
collect the report path, roll up parquet. Right now that briefing lives in my prompt text and
will drift between dispatches. A skill makes it repeatable across sessions and across whoever
is coordinating.

**3. `proxmox_qualify_worker-host`** — the CLB03/CLB04 recon, generalised. Both recons asked
the same questions (live link speed with `ethtool`, NFS export coverage for the host's IP,
scratch backend and *real* free space, reusable container, fleet-file membership) and both
had to be told to distinguish LIVE-VERIFIED from FROM-CAPTURE. That is a checklist, and
CLB02/CLB07/CLB09 all need it. Belongs in `H:\backups\proxmox` per the standing rule that
Proxmox admin work happens there.

## Agents

Mostly **do not add**. The existing roster is large and the campaign's shape — one subagent
per container, holding that container's state across a tranche — is served by continuing an
agent rather than defining a new type. Continuing the ST-1 worker into ST-2 preserved the
container state, its task-local tooling and its findings; a fresh agent would have re-derived
all of it.

One worth considering:

- **`ebfe-worker`** — a thin agent definition that bakes in the standing rules and the
  report-to-disk contract, so a dispatch is one line instead of a 40-line prompt. Should point
  at the plan and the skills rather than restating them, per the repo's thin-agent convention.

`ebfe-organizer` already exists and should be updated with the ST-1 findings rather than
duplicated.

## Hooks

The repo already has a dispatcher (`scripts/agent_hooks/hook_dispatch.py`) wired for
`SessionStart`, `PreToolUse` and `PermissionRequest`. Two additions would have caught real
problems this session:

**1. `PreToolUse` guard on the immutable raw tree.** `F:\eBFE\raw\` is documented as never
modified (rule 1 in `F:\AGENTS.md`), but nothing enforces it. A guard that refuses writes,
moves and deletes under any `raw\` path — and under `queues/` on the worker — turns a written
rule into an enforced one. Cheap, and the blast radius it protects is 16 TB.

**2. `PreToolUse` warning on hashing.** "No hashing without asking" (D2) is a standing user
instruction that a fresh subagent could easily violate by reflex — `sha256sum`, `Get-FileHash`,
`hashlib` over a corpus path. A warning hook makes the rule self-enforcing rather than
depending on every prompt restating it.

Both are advisory-to-blocking guards on *documented, already-agreed* rules, which is the right
use of a hook: they encode a decision already made, rather than inventing policy.

## Process observations

**Persistent notes on disk are working.** ST-1's report, the task-local `ebfe_st1.py` with its
provenance, and the plan file together meant this session could hand ST-2 to the same agent
with a three-paragraph delta instead of re-explaining the campaign. Keep that pattern:
report + tooling + provenance, all on the NAS, none of it only in a transcript.

**The worker correcting its own scanners was the most valuable thing in ST-1.** Two of its
scanners were wrong (a path heuristic matching every decimal and timestamp, 173,011 false
matches down to the true 1; group discovery at the wrong tree level) and both would have
looked plausible in a parquet rollup. That argues for keeping the "write up what you got wrong"
instruction in every worker brief — it is not boilerplate, it caught two silent
data-quality failures.

**Uncommitted working tree is a live reproducibility hole.** The worker installed the repo
editable and recorded commit `bda1767e` — with **793 uncommitted files**. The SHA does not
identify the build. Either commit before the next tranche or have the worker record a diff
hash alongside the SHA. This is the one open item that affects whether the audit is
reproducible at all.

## Recommended order

1. Re-scope plan section A6 from "write two new modules" to "extend three existing skills
   plus two new modules" — the existing skills do more than the plan credits.
2. Resolve the uncommitted-tree provenance problem before ST-3.
3. Add the two hooks (raw-tree guard, hashing guard) — small, and they encode agreed rules.
4. Add `ebfe_audit_data-gaps` and `ebfe_dispatch_worker` skills once ST-2 confirms the
   audit schema, so they encode a proven contract rather than a proposed one.
5. `proxmox_qualify_worker-host` before qualifying CLB02/07/09.
