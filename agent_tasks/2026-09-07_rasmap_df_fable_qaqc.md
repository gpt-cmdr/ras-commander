# Claude Code Fable QA/QC: `rasmap_df` provenance PR

**Date:** 2026-09-07

**Reviewer:** Claude Code 2.1.263, `--model fable --effort max`

**Mode:** Read-only (`Read`, `Glob`, `Grep`, and `Bash`; no edit/write tools)

## Fable verdict

**READY WITH NON-BLOCKING FOLLOW-UPS**

Fable reported no blockers and no high-severity findings. It also noted that the
read-only permission harness denied Python execution, so it independently reviewed
the implementation and diffs but did not independently reproduce the test counts
already recorded in the worklog.

## Fable findings (captured before maintainer verification)

### Medium

1. A malformed declaration can prevent valid entries in the same field group from
   being returned. Fable recommended recording the declaration error and continuing
   so valid sibling entries survive, or documenting an all-or-nothing rule.
2. `ras_commander/AGENTS.md` contains a required `rasmap_df` contract bullet but was
   omitted from the PR description's file inventory. The file also has unrelated
   changes and must be staged by hunk.
3. The `RasPrj.initialize()` logging diff includes an unrelated geometry-HDF count
   logging change and must be split during staging or described as part of the PR.
4. The tracked regression fixture checks only part of the 11-column legacy row;
   Fable recommended a stronger equivalence regression and per-case lifecycle
   status assertions.

### Low

1. A well-formed XML document with a non-`RASMapper` root is accepted as `parsed`.
2. `map_layers` and the map-layer helper are initialized in one extraction block
   and reused by later blocks, creating cross-block coupling after an earlier error.
3. `RasPrj.initialize()` logging calls `.iloc[0]` without independently guarding a
   zero-row DataFrame returned by a monkeypatch/subclass.
4. `Path.exists()` is outside the parser's resilience boundary.
5. The fallback expected path in notebook 122 uses the project folder name instead
   of the `.prj` stem.
6. Top-level layer traversal and canonical expected-path construction remain
   duplicated internally.
7. `ras_object` is retained for compatibility but is now unused by `parse_rasmap()`.

## Compatibility observations from Fable

- The frame grows from 11 to 15 columns while preserving the original column order.
- Well-formed files retain the legacy path-resolution and field-value semantics.
- UTF-8 BOM documents move from silent defaults to a real parse, which is a
  corrective legacy-value change worth mentioning.
- `get_infiltration_parameters()` changes from an accidentally broken decorated
  attribute to a working API; explicit missing paths can now fail in the decorator
  with `FileNotFoundError`.
- Implicit missing infiltration lookup changes from accidental `IndexError` to the
  documented contextual `ValueError`.

## Missing tests suggested by Fable

- Pin every lifecycle case to its expected status rather than comparing only the
  set of statuses.
- Cover the remaining per-field error groups and a mixed-validity group.
- Cover empty XML and a non-`RASMapper` root.
- Prove an unrelated partial field error does not block infiltration resolution,
  and prove explicit missing-path behavior.
- Add direct status-gating coverage for `scripts/ebfe_delivery_audit.py`.
- When the external example archive is available, compare pinned legacy values for
  a real extracted 2D project.

## Dirty-worktree warning from Fable

- Stage `RasPrj.py`, `docs/reference/dataframe-reference.md`, and
  `ras_commander/AGENTS.md` interactively by hunk.
- Do not add the untracked qualification subsystem.
- Review the cached diff for LF/CRLF whole-file rewrites before committing.
- Add the new schema module, both focused test modules, and the compact fixture
  explicitly.

## Commands Fable reported running

- `git status --porcelain`, `git diff --stat`, and per-file `git diff`
- `git diff --check`
- `git grep` at `HEAD` for the infiltration decorator
- `git ls-files` / `git grep` to establish qualification-subsystem tracked status

Python tests, archive comparison, and notebook compilation were attempted but
denied by the Claude read-only harness before execution. The primary agent's
verification and resolution record follows in the PR worklog.

## Maintainer verification and resolution

The primary agent checked every finding against the working tree after Fable
returned:

- **Resolved:** malformed top-level land-classification, terrain, reference, and
  basemap declarations now record field errors per declaration and continue.
  Valid siblings are retained. Reference/basemap names remain usable when only
  their corresponding filename/path is malformed.
- **Resolved:** all 11 legacy columns are pinned by the representative fixture;
  lifecycle expectations are asserted per input; mixed-validity siblings have a
  dedicated regression.
- **Resolved:** `MapLayers` lookup and the map-layer helper import no longer depend
  on an earlier extraction block succeeding.
- **Resolved:** the unrelated geometry-HDF logging change was removed from the
  `RasPrj.initialize()` hunk, and status logging now guards an anomalous zero-row
  monkeypatch/subclass result.
- **Resolved:** filesystem existence probing is inside the parser resilience
  boundary, and the compatibility-only `ras_object` parameter is documented.
- **Resolved:** notebook 122 derives the absent fallback from the discovered `.prj`
  stem when possible.
- **Resolved:** `ras_commander/AGENTS.md` is named explicitly in the PR scope notes,
  with hunk-only staging instructions.
- **Resolved after corpus confirmation:** all 326 `.rasmap` files currently under
  this repository have a `RASMapper` root. A well-formed document with another root
  is now a document-level `failed` result and has regression coverage.
- **Resolved:** direct eBFE delivery-audit tests prove that `failed` gates both
  legacy values and raw XML fallback, while `parsed_with_errors` retains unaffected
  delivery fields.
- **Resolved before merge:** shared internal top-level traversal and canonical
  expected-path construction are now centralized and their tracked callers are
  migrated.
- **Resolved before merge:** an archive-available integration test now sweeps every
  `.rasmap` in the locally installed `RasExamples` archive, while skipping cleanly
  in CI environments where that external archive is unavailable.

Post-resolution verification was subsequently expanded after Fable's recheck: 39
targeted review-driven tests passed; the final focused RASMapper/infiltration group
passed 114 tests with 7 intentional skips;
all 326 repository `.rasmap` files returned `parsed` with zero field-error rows;
changed Python files compiled; changed notebook JSON/code cells compiled; Ruff was
clean on every new focused Python module/test; and `git diff --check` passed with
only line-ending normalization warnings.
