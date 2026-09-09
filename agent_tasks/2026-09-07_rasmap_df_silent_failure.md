# `rasmap_df` reports success and failure identically

**Type:** correctness / observability defect
**Files:** `ras_commander/RasMap.py`, `ras_commander/RasPrj.py`, `ras_commander/_land_classification_helper.py`
**Found:** 2026-09-07, auditing FEMA eBFE HUC 12090301 (2,378 projects)
**Wanted:** a PR

---

## Summary

`ras.rasmap_df` cannot distinguish a project with **no** `.rasmap`, a project with a
**malformed** `.rasmap`, and a project with a **valid** `.rasmap`. All three produce a
DataFrame of exactly one row with the same columns. Every failure is downgraded to a log
line and an empty default value. A caller holding only the DataFrame has no way to tell
"this model has no terrain configured" from "this model's terrain block failed to parse."

This was proven empirically by planting corruption in a copy of a real project and loading
all three states: identical shape, identical row count, indistinguishable content.

## Why it matters

RASMapper configuration is where terrain, land cover, infiltration and soil layers are
declared. In the FEMA eBFE corpus those layers ship *separately* from the RAS project and are
frequently missing — measured presence is 30–53% depending on layer. Quantifying that gap is
the entire point of the audit consuming this API.

With the current behavior, a study whose `.rasmap` files are all unparseable reports
**exactly the same numbers** as a study that legitimately ships no RASMapper configuration:
0% terrain, 0% land cover, 0% infiltration. One is a data gap in the delivery. The other is a
gap in our parsing. They are not the same finding and must not be reported as the same
number.

---

## Root cause

### 1. `rasmap_df` is a single-row-by-design schema, so row count discriminates nothing

`_land_classification_helper.empty_rasmap_dataframe()` (`:291`) returns one row:

```python
pd.DataFrame({
    "projection_path": [None],
    "profile_lines_path": [[]],
    ...
    "current_settings": [{}],
})
```

`RasMap.parse_rasmap()` builds its working dict from that same helper
(`data = _lch.empty_rasmap_dataframe().to_dict(orient="list")`) and mutates `data[field][0]`
in place. **A fully successful parse also returns exactly one row.** Any check of the form
`len(rasmap_df)`, `rasmap_df.empty`, or `if rasmap_df is not None` is therefore meaningless —
it is `1`, `False`, and `True` in every state including total failure.

### 2. Five distinct outcomes collapse to the same value

| Condition | Site | Logged at | Returns |
|---|---|---|---|
| No `.rasmap` found for project | `RasMap.initialize_rasmap_df` `:995` | `warning` | 1-row empty |
| `.rasmap` path does not exist | `RasMap.parse_rasmap` `:286` | `error` | 1-row empty |
| Content is not XML (no leading `<`) | `parse_rasmap` `:298` | `error` | 1-row empty |
| `ET.ParseError` | `parse_rasmap` `:304` | `error` | 1-row empty |
| Any other exception | `RasPrj.initialize` `:207` | `error` | **0-row** empty |

### 3. Per-field failures are silent and partial

`parse_rasmap` wraps **eight** independent extraction blocks in `except Exception` (lines
319, 332, 354, 368, 384, 400, and the settings block), each logging `warning` and leaving
that one field at its empty default. So a `.rasmap` that parses as XML but has a malformed
terrain block yields `terrain_hdf_path == []` — byte-identical to a project that genuinely
declares no terrain. This is the most damaging case because it is *partial*: the row looks
populated and healthy, and one field is quietly empty.

### 4. Bonus inconsistency

The `RasPrj.initialize` fallbacks (`:202` and `:207`) build
`pd.DataFrame(columns=[...])` — **zero rows**, while every other path returns **one row**.
The column names match, the shape does not. Any downstream `rasmap_df.iloc[0]` raises
`IndexError` in that one branch and works everywhere else. These should route through
`empty_rasmap_dataframe()`.

---

## What the fix should achieve

The DataFrame must carry enough provenance to answer, per project, without consulting logs:

1. Was a `.rasmap` file found? Where?
2. Did it parse?
3. If it parsed, did every field extract cleanly, or did some fail?

Suggested shape — **additive columns only**, so the existing 11 columns and all current
callers keep working unchanged:

| Column | Type | Meaning |
|---|---|---|
| `rasmap_path` | `str \| None` | The file actually read, or `None` if none found |
| `rasmap_status` | `str` | `absent` · `not_found` · `not_xml` · `parse_error` · `parsed` · `parsed_with_errors` |
| `rasmap_field_errors` | `dict` | `{field_name: error_message}` for the per-field `except` blocks; empty when clean |

With those, `absent` versus `parse_error` versus `parsed` is a column lookup, and
`parsed_with_errors` surfaces the partial case that is currently invisible.

Also fix the zero-row/one-row inconsistency in `RasPrj.initialize` by returning
`_lch.empty_rasmap_dataframe()` in both fallback branches.

Design latitude is fine — an enum instead of strings, a separate accessor, a
`ValidationReport` (the repo has `ras_commander/RasValidation.py` with
`ValidationSeverity`/`ValidationResult`/`ValidationReport` and this is arguably a natural fit).
What is not negotiable is that **success and failure must be distinguishable from the
returned object alone.**

## Constraints

- **Backward compatible.** The 11 existing columns keep their names, order and semantics.
  Callers doing `rasmap_df['terrain_hdf_path'][0]` must not break.
- **Do not make parsing stricter.** The goal is to *report* failure, not to start raising on
  models that load today. A malformed `.rasmap` should still yield a usable row.
- Follow the repo's static-class and `@log_call` conventions; `pathlib.Path` for paths.

## Tests to include

Build a real project via `RasExamples.extract_project()`, then copy it and plant each state:

1. **Absent** — delete the `.rasmap`. Expect `rasmap_status == "absent"`.
2. **Not XML** — write `not xml at all` into the `.rasmap`. Expect `not_xml`.
3. **Malformed XML** — truncate mid-tag. Expect `parse_error`.
4. **Valid** — untouched. Expect `parsed`, `rasmap_field_errors == {}`, and the same field
   values the current code produces (regression guard).
5. **Partial** — valid XML with a corrupted terrain block only. Expect `parsed_with_errors`
   with `terrain_hdf_path` in `rasmap_field_errors`, and the *other* fields still populated.

Assert in every case that the three states are **mutually distinguishable from the returned
DataFrame alone**, with no reference to log output. That assertion is the point of the PR.

Per `.claude/rules/commit-policy.md`: this touches existing functions rather than adding new
public API, so a notebook is not required — but `ras_commander/AGENTS.md` should note the new
columns if they are added to the public `rasmap_df` contract.

## Reproduction

```python
from ras_commander import init_ras_project, RasExamples
import shutil, pathlib

src = RasExamples.extract_project("BaldEagleCrkMulti2D", suffix="rasmap_probe")

for state in ("absent", "not_xml", "parse_error", "valid"):
    dst = pathlib.Path(f"{src}_{state}")
    shutil.rmtree(dst, ignore_errors=True); shutil.copytree(src, dst)
    rmap = next(dst.glob("*.rasmap"), None)
    if state == "absent":       rmap.unlink()
    elif state == "not_xml":    rmap.write_text("not xml at all")
    elif state == "parse_error":rmap.write_text("<RASMapper><Terr")

    ras = init_ras_project(dst, "6.6")
    print(state, len(ras.rasmap_df), ras.rasmap_df['terrain_hdf_path'][0])
    # today: every state prints the same row count and the same empty terrain list
```
