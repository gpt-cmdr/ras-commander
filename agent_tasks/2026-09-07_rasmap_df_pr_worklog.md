# `rasmap_df` provenance PR worklog

**Date:** 2026-09-07

**Branch:** `codex/rasmap-df-provenance`

**Base:** `origin/main` at `49f1b0f18660ca04d7266e215cda907dcf19a8ef`

## Contract decisions

- `rasmap_df` remains a pandas DataFrame with exactly one row and index `0` in
  every lifecycle state.
- The original 11 columns retain their names, order, value shapes, and path
  normalization behavior.
- Four columns are appended: `rasmap_path`, `rasmap_status`, `rasmap_error`, and
  `rasmap_field_errors`.
- The public statuses are `absent`, `parsed`, `parsed_with_errors`, and `failed`.
- Document-level errors go in `rasmap_error`; declaration/field-level errors are
  accumulated by affected legacy column in `rasmap_field_errors`.
- Missing optional sections and missing referenced assets are not parse errors.
- Parsing remains non-raising and preserves valid sibling declarations after a
  malformed declaration.
- Legacy frames without provenance columns remain usable to internal consumers.

## Follow-ups completed before merge

1. Centralized canonical `<project-name>.rasmap` construction in
   `_rasmap_schema.expected_rasmap_path()` and migrated tracked call sites.
2. Centralized direct `MapLayers/Layer` traversal and made legacy `LandCover`
   and modern `LandCoverLayer` classification consistent.
3. Added `_rasmap_schema.rasmap_dataframe_is_usable()` and migrated tracked
   health checks in `RasPrj`, `RasProject`, `HdfResultsMesh`, ScienceBase
   validation, and the eBFE delivery audit.
4. Migrated all six implicit HDF classification/infiltration lookups to
   `HdfInfiltration._resolve_rasmap_hdf_path()`.
   - `get_infiltration_map()` and `get_infiltration_parameters()` now raise a
     contextual `ValueError` rather than an accidental `IndexError`.
   - The four statistics APIs retain their documented log-and-empty-DataFrame
     recovery behavior.
5. Added an opt-in/archive-available `RasExamples` compatibility sweep over all
   `.rasmap` members plus a compact tracked fixture for deterministic CI.
6. Updated the untracked local `RasQualificationActions` subsystem separately to
   use the shared health/path helpers. The subsystem is intentionally not copied
   wholesale into this PR because it is not present on `main`.
7. Migrated `RasCrossSections` to the shared path/health contract. While doing so,
   restored the pre-existing misplaced body of `_crs_units()` so that its CRS
   fallback remains functional and the touched module is lint-clean.
8. Closed the final API-audit gaps: parser-helper imports now remain inside the
   one-row resilience boundary; `RasPrj` distinguishes module-import failure from
   initialization failure; ScienceBase promotion reports document and field parse
   failures; and `RasProject` inventories each failed field without dropping valid
   sibling assets.
9. Replaced obsolete `.empty`/non-`None` health checks and the nonexistent
   `terrain_file` column in both tracked eBFE validation guides. The spatial-data
   guide now gates explicit infiltration sidecar indexing on `rasmap_status`.

## Consumer behavior

| Consumer | Behavior after this PR |
|---|---|
| `RasPrj.initialize()` | All paths, including import/unexpected failure, produce one provenance row. |
| `RasPrj` path accessors | Return values only from parsed/partially parsed rows; legacy frames remain accepted. |
| `RasProject.inspect_project_assets()` | Does not invent an absent RASMapper asset and reports unusable structured parsing explicitly. |
| `HdfResultsMesh` | Ignores profile paths from absent/failed rows. |
| `RasCrossSections` | Uses the canonical map path and ignores projection defaults from absent/failed rows. |
| ScienceBase validation | Ignores projection defaults from absent/failed rows. |
| eBFE delivery audit | Records parse provenance, gates failed maps, and still handles noncanonical discovered filenames. |
| Infiltration map/parameter readers | Explicit paths bypass project lookup; implicit unusable/missing values raise contextual `ValueError`. |
| Four raster-statistics helpers | Use the same resolver but continue returning an empty DataFrame after a logged lookup problem. |

## Compatibility

This is source-compatible for normal named-column callers. It has two narrow
compatibility effects worth release-note coverage:

- exact 11-column schemas/fixed-width serializers must accept four appended
  columns;
- the rare exceptional `RasPrj.initialize()` fallback changes from zero rows to
  the intended one-row invariant.

Successful legacy access such as
`ras.rasmap_df.iloc[0]["terrain_hdf_path"]` remains unchanged after a caller has
established that the project fixture is valid.

## Review and validation record

- Claude Code 2.1.263, Fable model, maximum effort: two read-only passes; both
  concluded **READY WITH NON-BLOCKING FOLLOW-UPS**, with no blocker or high
  finding. The original reports are preserved beside this worklog.
- The first pass drove sibling-preservation, wrong-root, consumer-gating, and
  stronger test fixes. The second pass confirmed those findings resolved.
- API consistency auditor: the initial infiltration decorator finding and four
  final consumer/resilience/guidance findings were resolved. Its final exact-scope
  re-audit concluded **READY**, with no blocker, high, or medium issues; the five
  directly relevant regressions passed independently.
- Final consolidated consumer suite: **216 passed, 5 skipped**. The skips require
  an unavailable mapped network drive. This covers parser/resolver provenance,
  infiltration APIs, ScienceBase and eBFE audits, project assets, cross sections,
  geometry association, land classification, map layers, terrain display, the
  installed example archive, and the tracked network-path tests.
- Broader relevant suite: **207 passed, 12 skipped, 3 failed**. The three failures
  are pre-existing Windows/Pandas timezone dtype assertions in
  `tests/test_ras_project.py` and reproduce outside this change.
- Full suite: **2676 passed, 61 skipped, 13 failed**. The failures are unrelated
  repository/environment baselines: citation-version drift, two strict HDF test
  fixtures, a RasBenefits direct-writer issue, the same three timezone assertions,
  five process-global CLR version-rebind failures, and one RasPlan sediment
  expectation.
- Parser replay: **327 `.rasmap` files**, with **0 failed** and **0 partial**.
- Installed RasExamples archive compatibility: **32 `.rasmap` files**, all parsed;
  the corpus includes terrain, basemap, results, and modern land-cover forms. The
  tracked compact fixture covers legacy `LandCover` deterministically in CI.
- Notebook JSON and every code cell compile successfully. Modified code-cell
  outputs were cleared; all unrelated stored outputs and execution counts were
  preserved.
- GitHub's first documentation run correctly caught stale generated notebook
  inventory metadata. `examples/notebooks.yml` was regenerated; both the
  generator's `--check` mode and `validate_notebooks_yml.py` now pass locally
  (the validator retains 62 existing warnings and reports 0 errors).
- Ruff passed for all new files and the changed parser/resolver/cross-section,
  geometry-association, and layer-helper modules. `git diff --check` passed (Git
  emitted only configured LF-to-CRLF conversion warnings).
- `mkdocs build --strict` was attempted and stopped on 146 existing warnings from
  absent generated docs/notebooks and the no-history worktree; no documentation
  structure changed in this PR.
- The separate local qualification tests produced **53 passed, 1 failed**; the
  failure is the existing inaccessible `R:/` drive check (`WinError 1272`).
