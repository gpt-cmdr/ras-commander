# PR #384 HDF result-view QAQC disposition

PR #384 was merged before its requested independent review gates were run. A
post-merge review therefore treated the merge as unaccepted until a corrective
follow-up could resolve the confirmed findings.

## Independent reviews

### Claude Code Fable

Claude Code 2.1.283 Fable reviewed
`d40552ddf06456993a5303541163b96e713e1426..11bd15b9c19a4e98326edfb360fbdd1289804c37`
read-only. The first maximum-effort invocation was stopped after approximately
twelve minutes without stdout or an output artifact. A documented high-effort
fallback completed and returned **PASS WITH NON-BLOCKING NOTES**.

Fable independently identified:

- an all-zero truncation compatibility change;
- rejection of NumPy integer indexes, including indexes returned by argmax;
- a double-read performance regression on the default eager truncation path;
- implicit spatial-subset truncation semantics and pre-truncation shape;
- documentation, canonical-guidance, and example-coverage gaps.

The ignored local `TASK.md` and `OUTPUT.md` retain the review prompt and report.

After the corrections were committed, Fable re-reviewed the exact follow-up
diff `9a84fb4831dd82f7775f0adda0c45749e4962327..803b18e47` at high effort. Its
final verdict was **PASS WITH NON-BLOCKING NOTES** and it explicitly judged the
diff safe to merge. It confirmed that every original actionable finding and
every API-audit finding was resolved with regression coverage. The remaining
low-severity notes were documentation/polish only: expose `truncate` in the API
documentation's abbreviated signature, spell out reduction/truncation and
repeated-shape-scan costs, and add a future example notebook for the result-view
surface.

### API consistency auditor

The initial independent API audit returned **CHANGES REQUESTED**. In addition to
the shape contract, it found a separate high-severity defect that Fable missed:
`reduce(dtype=np.int32)` cast NaN/infinite values before finite masking and
could silently corrupt min/mean results. It also required logging, flexible HDF
input typing, Literal/overload return narrowing, dtype/Arrow annotations,
complete public docstrings, dtype fingerprint validation, and matching chunk
validation.

The corrected surface received **PASS WITH NOTES** on the full follow-up audit.
The remaining notes—numeric plan-number typing, runtime Arrow annotation
resolution, explicit wrapper selection exceptions, and a test-only cast
warning—were then corrected. A final narrow recheck returned a clean **PASS**
with no remaining blocker or note.

Local ignored reports:

- `.claude/outputs/api-consistency-auditor/2026-09-26-pr384-hdf-result-view-review.md`
- `.claude/outputs/api-consistency-auditor/2026-09-26-pr384-followup-recheck.md`

## Corrections

- `HdfResultView.shape` now matches materialization under truncation.
- All-zero selections retain their full extent, matching the historical eager
  contract.
- Eager materialization reads the selected slab once and trims in memory.
- NumPy/Python integer indexes are accepted; booleans remain invalid.
- Integer reduction dtypes fail clearly before nonfinite values can be cast.
- Batch byte sizing uses the requested output dtype.
- Dataset dtype is validated when a source is reopened.
- Public view methods use repository logging; batch consumption has explicit
  start/finish logging around the generator's actual lifetime.
- HDF input types, Literal overloads, dtype annotations, docstrings, public
  documentation, benchmark coverage, and canonical HDF guidance were updated.

## Verification

- Focused HDF/view suites: **57 passed, 3 skipped**.
- Real Bald Eagle opt-in result-view suite: **22 passed**.
- Real default eager Water Surface output: legacy and corrected SHA-256 values
  match for all `865 x 89,879` Float32 values.
- Corrected default eager path: 1.318/1.323 seconds with 371/365 MiB peak RSS
  delta, eliminating the reviewed 2.95-second double-read regression.
- Direct/eager timestep and bounded/eager maximum checksums match.
- Ruff import/error checks, compile checks, and `git diff --check` pass.
- Normal MkDocs build passes. Strict mode remains blocked by pre-existing
  missing generated-notebook-link warnings.
- Broad HDF collection: 437 passed, 33 skipped, with six unrelated failures:
  four missing optional `rasterstats` dependency checks and two clean-main
  strict-unit-metadata fixture failures.

The corrective follow-up is required even though PR #384 is already merged;
the merged API should not be treated as review-complete without it.
