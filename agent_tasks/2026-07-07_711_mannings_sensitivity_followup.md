# 711 Manning's Sensitivity Follow-Up

Date: 2026-07-07

Status: **Public example scope closed as of 2026-07-10.** PR #271 refreshed and
landed notebook 711 with local, credential-free defaults. The larger remote and
Sabinal-specific workflow described below remains optional future feature work;
it must be extracted onto a fresh branch if pursued and should not reopen the
closed PR #260 replay.

Context: PR #260 (`codex/docs-notebook-refresh`) was closed as superseded
after its useful logging and notebook slices were extracted into focused PRs.
The only substantial unlanded candidate identified in the remaining PR #260
diff was `examples/711_mannings_sensitivity_multi_interval.ipynb`.

## Current Decision

Do **not** merge or rebase PR #260 to preserve this notebook. Extract the 711
work only if it is still desired, using a fresh branch from current `main`.

The PR #260 version of notebook 711 is a real feature rewrite, not output-only
churn. It expands the notebook from a compact local OAT Manning's n example into
a heavier workflow with:

- environment-driven project and HEC-RAS version configuration;
- optional external project path support;
- RasRemote execution support;
- `GeomLandCover`-based roughness reads;
- `RasMonteCarlo.make_mannings_apply_fn(path="plaintext")` roughness edits;
- cloned geometry association checks and repair logic;
- geometry-preprocessor roughness propagation verification;
- HDF completeness and compute-message checks;
- baseline-anchored POI sensitivity plots;
- spatial/global delta metrics for max WSE, inundation volume, face velocity,
  and arrival time; and
- CSV/GPKG export hooks.

## Risks To Resolve Before Publication

- The branch-side notebook defaults to remote-worker behavior, but the referenced
  `examples/remote_workers_clb_template.json` file is not present. Public
  notebook defaults should be local and credential-free, with remote execution
  explicitly opt-in.
- The reuse-by-title logic is fragile because created plan titles truncate land
  cover names while the parser compares against full `range_table` keys unless a
  registry CSV already exists.
- The spatial/global metrics section is large enough that it should probably be
  extracted into a tested helper or a notebook-derived script before being
  published as an example.
- The notebook currently has no stored outputs. It must be executed and reviewed
  before it is included in the public docs.
- The Sabinal-oriented defaults and HEC-RAS 7.0 DSS finalization note may be
  useful for CLB work, but public example wording should distinguish official
  example-project behavior from external project overrides.

## Recommended Fresh PR Scope

1. Start from current `origin/main`.
2. Cherry-pick or manually port only the useful 711 source-cell ideas from
   `origin/codex/docs-notebook-refresh`.
3. Keep public defaults simple:
   - `RasExamples` project by default;
   - local execution by default;
   - remote execution opt-in through documented environment variables;
   - no dependency on gitignored CLB worker credentials.
4. Move reusable spatial/global metrics logic into a helper if it remains
   longer than a short notebook demonstration.
5. Execute the notebook with HEC-RAS 7.0 or newer.
6. Confirm roughness propagation by checking preprocessed cell Manning's n values
   before interpreting hydraulic deltas.
7. Review outputs for publishable notebook quality before opening or merging the
   PR.

## Validation Evidence From Review

Read-only subagent and local audits compared `origin/main` with
`origin/codex/docs-notebook-refresh` and found:

- notebook source grows from 24 cells to 32 cells;
- code cells grow from 12 to 16;
- both versions have zero stored outputs;
- the changed APIs appear to exist on current `main`;
- the concept is credible, but unexecuted and too broad for the closed docs
  refresh PR; and
- no whole-file copy from PR #260 should be preserved as-is.

## Related PR State

- PR #260: closed as superseded.
- PR #251: left open but held because rerun outputs were not publishable.
