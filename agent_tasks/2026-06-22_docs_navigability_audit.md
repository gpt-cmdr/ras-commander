# rascommander.info — Documentation Navigability & Usability Audit

**Date:** 2026-06-22
**Scope:** Full audit of the rascommander.info docs site (umbrella `/` + `/ras` `/hms` `/mcp`
`/hydro` `/qgis`) for navigability, consistency, and usability, plus the two reported defects
(empty homepage left menu; example notebooks missing numbers / not grouped in the left menu).

The umbrella deployment infra lives in `ras-commander-docs`; **the nav, theme features, and page
content for `/ras` live in this repo** (`gpt-cmdr/ras-commander`). The build pulls this repo at
deploy time, so navigation fixes land here.

---

## Shipped in this PR (the two discrete fixes)

### 1. Empty homepage left menu — FIXED
**Root cause:** `mkdocs.yml` `theme.features` had `navigation.tabs`, which promotes top-level nav
items to a tab bar and shows only the *active tab's children* in the left sidebar. `Home` is a lone
top-level leaf with no children, so the `/ras/` homepage sidebar collapsed to just "Home" + the
page's own H2 headings.
**Fix:** removed `navigation.tabs` and `navigation.expand`. The full section tree now renders in the
left sidebar on every page (homepage included); groups stay collapsible so the large notebook tree
is scannable.

### 2. Example notebooks: numbers + sequential + groupings in the left menu — FIXED
**Root cause:** on `main` the `Example Notebooks` nav is deliberately collapsed to a single
`Overview` entry (see the docstring in `generate_examples_index.py`): the team avoids hand-authoring
~120 nav entries because they go stale and reference notebooks that don't exist on `main`. The
notebooks were surfaced only as a table on the overview page, and titles were rendered with the
leading number **stripped** (`derive_title`/`prettify_filename`).
**Fix (generate from disk at build time — single source of truth, never stale):**
- New shared module `.claude/scripts/_docs_notebook_common.py` holds the title/numbering/section
  logic so the overview table and the left-nav can't drift.
- `prepare_notebooks_for_docs.py` now **injects** the `Example Notebooks` nav block from
  `examples/*.ipynb`: numbered labels (`100 - Using RasExamples`), grouped by hundreds with
  descriptive headings (`100s - Initialization & Execution` … `900s - Data Integration &
  Forecasting`), sequential within each group. It replaces the lone `Overview` entry at build time;
  the source `mkdocs.yml` stays collapsed (design intent preserved). Labels are YAML double-quoted
  (notebook H1s contain `:`/`&`).
- `generate_examples_index.py` now shows the number in each overview-table title and uses the same
  descriptive group headings.
- No `ras-commander-docs` change needed: `build.sh` (`ras` profile) already runs both scripts.

**Validated locally:** 124 notebooks → valid YAML, 9 groups + Overview, nav entry count == notebook
count, full `mkdocs.yml` parses, sibling sections preserved.

**Note:** `docs/examples/index.md` is a build artifact (regenerated every deploy) and is intentionally
NOT regenerated in this PR to avoid coupling the diff to local notebook drift. It refreshes on the
next build after merge.

---

## Backlog — not in this PR (ranked; from the audit)

### Notebook hygiene
- **Duplicate notebook numbers (5 collisions / 10 notebooks):** `116`, `211`, `315`, `918`, `919`
  each used by two different notebooks. With numbers now shown, these appear as two same-numbered
  entries. Resolving means renaming the source `.ipynb` (+ any references). Candidates to renumber:
  `116_monte_carlo_uncertainty`, `211_fixit_blocked_obstructions`, `315_validating_dss_paths`,
  `918_model_validation_with_usgs`, `919_stofs3d_coastal_boundary`.

### Content / editorial (HIGH)
- **Internal pages shipping publicly:** `docs/DOCUMENTATION_PLAN.md` and `docs/AGENTS.md` build into
  the live site (reachable by URL, not in nav). Add to `exclude_docs` or relocate. `docs/ebfe_models.md`
  is orphaned — add to nav or fold into the eBFE user-guide page.
- **Cognitive Infrastructure half-broken:** `mkdocs.yml` `exclude_docs` hides `agents.md`/`skills.md`/
  `commands.md`, but `cognitive-infrastructure/index.md` describes and links to them. Either publish
  them (+nav) or trim the index so it doesn't dangle pointers.
- **Contradictory scale numbers:** notebook count is variously "109", "30+", "50+", "25+" across
  `index.md`, `quickstart.md`, `about/clb-engineering.md`, `development/llm-development.md`. The "30+"
  on the landing page badly undersells ~120 notebooks. Pick one number (now derivable from disk).
- **`plan_df` column names contradict** between the table and the examples in
  `getting-started/project-initialization.md` (`HDF_Results_Path` vs `hdf_path`, `Plan Title` vs
  `plan_title`) — breaks copy-paste. Also verify `max_workers` vs `num_workers` between
  `quickstart.md` and `parallel-compute/index.md`. Reconcile against `reference/dataframe-reference.md`.

### Content / editorial (MEDIUM)
- Landing page doesn't funnel new users to Install → Quick Start; grid cards aren't clickable links.
- `examples/index.md` overview has no "start here" guided path for a ~120-notebook library.
- `user-guide/overview.md` H1 says "Architecture Overview" but nav labels it "Overview".
- ~4 near-verbatim copies of the CLB marketing paragraph; de-duplicate to one canonical statement.
- Mixed heading case repo-wide (standardize Title Case); a few untagged code fences in
  `reference/file-formats.md`.
- *Positive:* no TODO/placeholder/stub content; API, parallel-compute, file-formats overviews strong;
  getting-started sequence is sound.

### Design / UX — these belong in `ras-commander-docs` (infra), not here
- **Switcher has no link back to `/`** (umbrella landing). `hub_url` is already injected into
  `extra` but unused — easy add to `theme/overrides/partials/clb-switcher.html`.
- **Audit the other 4 products' `theme.features`** for the same empty-menu pattern (nothing enforces
  consistency across products since the overlay can't set `theme.features`).
- Landing cards are hand-maintained, duplicating `products.yml` taglines (drift risk) — generate them.
- No cross-product search (per-product indexes) — known federated-model limitation; roadmap note.
- Landing page sets no logo; switcher font is very small (0.66rem).
