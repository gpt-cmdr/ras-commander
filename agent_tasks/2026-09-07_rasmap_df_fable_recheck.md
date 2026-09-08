# Claude Code Fable recheck: `rasmap_df` provenance PR

**Date:** 2026-09-07

**Reviewer:** Claude Code 2.1.263, Fable, maximum effort

## Verdict

**READY WITH NON-BLOCKING FOLLOW-UPS**

Fable found no regression in the parser, `RasPrj` fallback, infiltration resolver,
or eBFE audit. It marked all four original medium findings resolved and six of the
seven original low findings resolved. Its remaining internal-deduplication follow-up
was subsequently completed before merge.

## Recheck findings and final disposition

- **Medium — eBFE test import portability:** The new test imported
  `scripts.ebfe_delivery_audit`, but `scripts/` is not a package and the import can
  depend on how pytest is launched. **Resolved:** the test now loads the standalone
  script with `importlib.util.spec_from_file_location`.
- **Low — possibly unbound `land_columns`:** The error-key list was inside the
  `try` whose `except` referenced it. **Resolved:** it is initialized before the
  `try`.
- **Low — value plus field error / last-writer-wins:** A malformed unknown
  land-classification declaration conservatively marks all three classification
  path columns, even if a valid sibling populated one. Repeated errors also
  overwrote earlier details. **Resolved:** infiltration resolution is value-first,
  so valid sibling candidates remain usable, and repeated messages for a column
  are accumulated rather than overwritten. A two-method regression pins the
  value-first behavior.
- **Low — notebook `.prj` ambiguity:** A root-level projection `.prj` could win a
  simple glob. **Resolved:** notebook 122 now uses `RasPrj.find_ras_prj()`, the
  library's content-aware project-file discovery.
- **Low — duplicated traversal/path construction:** **Resolved after this recheck.**
  Shared helpers now own canonical expected-path construction and top-level
  `MapLayers/Layer` traversal, and tracked call sites use them.

Fable could not execute Python under its read-only harness. It statically confirmed
that the then-current counts were internally consistent. After the final recheck
fixes, the primary agent ran the expanded review-focused modules (**39 passed**)
and the complete focused group (**114 passed, 7 skipped**), plus compilation,
notebook, Ruff, corpus, and diff checks recorded in the worklog.

## Dirty-tree reminder

`ras_commander/AGENTS.md` requires splitting the combined hunk so the unrelated
model-sources bullet is not staged. `RasPrj.py` and the DataFrame reference also
contain extensive unrelated worktree changes. Use `python -m pytest` from this
checkout: the checkout's `.venv` editable metadata points at another repository
path, and the global `pytest` console launcher does not import this checkout's
`ras_commander` package reliably.
