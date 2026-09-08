# Make `rasmap_df` parse outcomes observable

## Summary

- preserve the existing single-row frame and first 11 columns
- append explicit file, lifecycle, document-error, and per-field-error provenance
- keep partial parsing non-raising while preserving valid sibling layers
- normalize exceptional initialization fallbacks to the same one-row shape
- centralize expected-path, top-level-layer, status-health, and HDF lookup logic
- migrate tracked downstream consumers and all six infiltration/statistics APIs
- document the contract and show provenance-first use in the two QA/QC notebooks

## Compatibility

Normal named-column access is unchanged. The additive frame width changes from
11 to 15 columns, and the rare zero-row initialization fallback is corrected to
one row. Exact-schema/positional consumers must account for those changes.

## User-facing example

```python
summary = ras.rasmap_df.iloc[0]

if summary["rasmap_status"] == "failed":
    raise RuntimeError(summary["rasmap_error"])
if summary["rasmap_status"] == "absent":
    print("No map:", summary["rasmap_path"])
else:
    print(summary["terrain_hdf_path"])
```

`len`, `.empty`, and non-`None` are shape/existence observations, not parser
health checks.

## Validation

- 216 focused tests passed with 5 mapped-drive skips across parser, consumers,
  HDF lookup, map-layer, geometry-association, archive compatibility, and
  ScienceBase promotion behavior
- 327 repository `.rasmap` files replayed with no failed or partial parses
- 32 files from the installed RasExamples archive parsed across terrain, basemap,
  results, and modern land-cover forms
- both modified notebooks compile as JSON and Python
- parser/resolver/cross-section changes and new tests pass Ruff
- two Claude Code Fable reviews found no blocker or high-severity issue
- the API consistency auditor's final pass found no blocker, high, or medium issue

The full suite produced 2676 passed, 61 skipped, and 13 unrelated baseline or
environment failures. See `2026-09-07_rasmap_df_pr_worklog.md` for categorization,
the documentation build result, and the independent review record.
