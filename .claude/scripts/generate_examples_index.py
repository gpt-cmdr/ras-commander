#!/usr/bin/env python3
"""
Generate the table-based "Example Notebooks" index page for the docs.

This script regenerates ``docs/examples/index.md`` as a set of per-section
markdown tables (one row per example notebook). For each notebook it emits:

* Notebook  - display title linked to the rendered docs page
              (``../notebooks/<name>.md`` which mkdocs serves at /notebooks/<name>/)
* Source    - link to the source ``.ipynb`` on GitHub
* Runtime   - total cell-execution wall time summed from the notebook's
              per-cell ``metadata.execution`` timestamps, or ``N/A`` when the
              notebook was committed without execution outputs.

It is meant to run during the docs build, AFTER
``.claude/scripts/prepare_notebooks_for_docs.py`` (which converts the
notebooks to markdown). The table page uses only the Python standard library
so it runs under a bare ``python3``.

It ALSO emits the gallery data surface (docs overhaul Workstream 1, W1.2):

* ``docs/examples/index.json`` -- structured gallery data grouped by series
  (title, summary, tags, difficulty, runtime, data_project, thumbnail per
  notebook), consumed by the filterable card gallery (W4.1) and by agents.
* ``docs/assets/thumbs/<id>.png`` -- a thumbnail per notebook, copied from the
  first figure of the rendered notebook when available.

Curated metadata (title/summary/tags/difficulty/...) is read from
``examples/notebooks.yml`` (the source of truth seeded by
``generate_notebooks_metadata.py``) when present; the on-disk notebook list and
the computed runtime remain authoritative. ``notebooks.yml`` parsing needs
PyYAML (a docs-build dependency via mkdocs); if it is unavailable the JSON
gracefully falls back to disk-derived titles.

The notebook list is sourced directly from disk
(``sorted(examples_dir.glob("*.ipynb"))``) -- NOT from the mkdocs.yml nav.
The published site builds from ``main``, where the Example Notebooks nav block
is collapsed to a single "Overview" entry and any populated nav (on a feature
branch) references notebooks that do not exist on ``main``. Sourcing from disk
guarantees the table reflects exactly the notebooks that ship with the build:
every ``.ipynb`` present, with no phantom rows.

Per-notebook display titles come from the notebook's first markdown ``# `` H1;
if absent, the filename is prettified (numeric prefix dropped, underscores ->
spaces, Title Case). Sections are grouped by the leading integer in the
filename prefix, bucketed into ``100s``/``200s``/.../``900s``.

Usage:
    python .claude/scripts/generate_examples_index.py
"""

import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

# Shared title / numbering / section logic, also used by prepare_notebooks_for_docs.py
# (which injects the left-nav) so the overview table and the sidebar never drift.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _docs_notebook_common import (  # noqa: E402
    derive_title,
    load_notebook,
    numbered_title,
    section_for,
)

GITHUB_BLOB_BASE = "https://github.com/gpt-cmdr/ras-commander/blob/main/examples"


# ---------------------------------------------------------------------------
# Runtime calculation (stdlib only)
# ---------------------------------------------------------------------------

def _parse_ts(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _notebook_level_runtime(nb: dict) -> Optional[float]:
    """Authoritative total wall time stamped by the executor at notebook level.

    The Symphony visible notebook runner records the full execution wall time and
    stamps it as ``metadata.execution_runtime_seconds``. This is the most reliable
    source because ``jupyter nbconvert --execute`` does not always populate per-cell
    ``metadata.execution`` timestamps (the stdlib parser below then sees nothing and
    falls back to ``N/A``). Prefer this when present.
    """
    value = nb.get("metadata", {}).get("execution_runtime_seconds")
    if isinstance(value, bool):  # bool is an int subclass — reject it explicitly
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    return None


def compute_runtime_seconds(nb: Optional[dict]) -> Optional[float]:
    """Total execution wall time for a parsed notebook, from the best available source.

    Source precedence (first hit wins):
      1. ``metadata.execution_runtime_seconds`` — total wall time stamped by the
         Symphony runner (authoritative; survives nbconvert dropping cell timing).
      2. Per-cell ``metadata.execution`` timestamp deltas summed across code cells
         (JupyterLab / nbclient ``record_timing``).
      3. Per-cell ``metadata.papermill.duration`` summed (papermill executions).

    Returns total seconds, or ``None`` when no timing of any kind is present
    (-> rendered as ``N/A``).
    """
    if nb is None:
        return None

    # 1) Authoritative notebook-level total.
    stamped = _notebook_level_runtime(nb)
    if stamped is not None:
        return stamped

    # 2) + 3) Per-cell timing: execution timestamps, else papermill duration.
    total = 0.0
    found_any = False
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        meta = cell.get("metadata", {})

        execution = meta.get("execution")
        if execution:
            start_raw = execution.get("iopub.execute_input") or execution.get(
                "iopub.status.busy"
            )
            end_raw = execution.get("iopub.status.idle") or execution.get(
                "shell.execute_reply"
            )
            start = _parse_ts(start_raw) if start_raw else None
            end = _parse_ts(end_raw) if end_raw else None
            if start is not None and end is not None:
                found_any = True
                duration = (end - start).total_seconds()
                total += duration if duration > 0 else 0.0
                continue

        papermill = meta.get("papermill")
        if isinstance(papermill, dict):
            duration = papermill.get("duration")
            if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0:
                found_any = True
                total += float(duration)

    if not found_any:
        return None
    return total


def format_runtime(seconds: Optional[float]) -> str:
    """Human-readable runtime: ``N s`` / ``N.N min`` / ``N.N h`` / ``N/A``."""
    if seconds is None:
        return "N/A"
    if seconds < 60:
        return f"{int(round(seconds))} s"
    if seconds < 3600:
        return f"{seconds / 60:.1f} min"
    return f"{seconds / 3600:.1f} h"


# ---------------------------------------------------------------------------
# Page rendering
# ---------------------------------------------------------------------------

def build_index_markdown(examples_dir: Path) -> Tuple[str, int, int]:
    """Build the index.md content from notebooks on disk.

    Returns ``(markdown, total_rows, rows_with_runtime)``.
    """
    notebooks = sorted(examples_dir.glob("*.ipynb"))

    grouped: dict = {}
    section_order: List[Tuple[int, str]] = []

    total_rows = 0
    rows_with_runtime = 0

    for nb_path in notebooks:
        name = nb_path.stem
        nb = load_notebook(nb_path)
        title = numbered_title(name, derive_title(nb_path, nb))
        seconds = compute_runtime_seconds(nb)
        runtime = format_runtime(seconds)
        if seconds is not None:
            rows_with_runtime += 1
        total_rows += 1

        sort_key, label = section_for(name)
        key = (sort_key, label)
        if key not in grouped:
            grouped[key] = []
            section_order.append(key)

        notebook_link = f"[{title}](../notebooks/{name}.md)"
        source_link = f"[.ipynb]({GITHUB_BLOB_BASE}/{name}.ipynb)"
        grouped[key].append((name, f"| {notebook_link} | {source_link} | {runtime} |"))

    # Ascending by bucket; within a group sort by filename.
    section_order.sort(key=lambda k: k[0])

    section_blocks: List[str] = []
    for key in section_order:
        rows = [row for _name, row in sorted(grouped[key], key=lambda r: r[0])]
        block = [
            f"## {key[1]}",
            "",
            "| Notebook | Source | Runtime |",
            "| --- | --- | --- |",
        ]
        block.extend(rows)
        section_blocks.append("\n".join(block))

    intro = (
        "# Example Notebooks\n\n"
        "These are the canonical, runnable examples for ras-commander. Each row "
        "links to the rendered documentation page and to the source `.ipynb` on "
        "GitHub. **Runtime** is the summed cell-execution wall time captured the "
        "last time the notebook was executed (`N/A` means the notebook was "
        "committed without execution outputs).\n\n"
        "See [Example Projects](example-projects.md) for the CRS-valid source "
        "catalog and MapLibre review contract for ras2cng-exported model "
        "bundles.\n\n"
        "!!! tip \"New here? Start with the 100s.\"\n"
        "    Run **100 → 101 → 110** for the core initialize → inspect → execute "
        "loop, then branch into the series that matches your work: **200s** geometry "
        "& calibration, **300s** unsteady & DSS, **400s** HDF results, **900s** data "
        "integration & forecasting.\n\n"
    )

    summary = (
        f"*{total_rows} notebooks indexed - {rows_with_runtime} with runtime "
        f"data, {total_rows - rows_with_runtime} without.*\n"
    )

    markdown = intro + summary + "\n" + "\n\n".join(section_blocks) + "\n"
    return markdown, total_rows, rows_with_runtime


# ---------------------------------------------------------------------------
# Gallery data (index.json) + thumbnails -- metadata from examples/notebooks.yml
# ---------------------------------------------------------------------------

SERIES_NAMES = {
    100: "Initialization & Execution", 200: "Geometry & Calibration",
    300: "Unsteady & DSS", 400: "HDF Results", 500: "Remote Execution",
    600: "Floodplain Mapping", 700: "Sensitivity & Precipitation",
    800: "Quality Assurance", 900: "Data Integration",
    950: "eBFE Delivery Validation", 960: "Cloud-Native Export",
}


def _series_of(name: str) -> int:
    """Series bucket, distinguishing the 950s/960s bands (notebooks.yml convention)."""
    m = re.match(r"^(\d+)", name)
    if not m:
        return 10_000
    n = int(m.group(1))
    if 950 <= n < 960:
        return 950
    if 960 <= n < 1000:
        return 960
    return (n // 100) * 100


def load_yml_meta(repo_root: Path) -> dict:
    """{id: metadata} from examples/notebooks.yml, or {} if absent / PyYAML missing."""
    path = repo_root / "examples" / "notebooks.yml"
    if not path.exists():
        return {}
    try:
        import yaml  # docs-build dependency via mkdocs; optional under bare python3
    except ImportError:
        print("  (PyYAML unavailable -- gallery JSON falls back to disk-derived titles)")
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {n["id"]: n for n in data.get("notebooks", []) if "id" in n}


def find_thumbnail(repo_root: Path, name: str) -> Optional[str]:
    """Copy the first figure of the rendered notebook -> docs/assets/thumbs/<id>.png.

    Best-effort: the figure files only exist after prepare_notebooks_for_docs.py runs,
    so locally (no converted notebooks) this returns None and the card shows no image.
    """
    figdir = repo_root / "docs" / "notebooks" / f"{name}_files"
    if not figdir.is_dir():
        return None
    pngs = sorted(figdir.glob("*.png"))
    if not pngs:
        return None
    thumbs = repo_root / "docs" / "assets" / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(pngs[0], thumbs / f"{name}.png")
    except OSError:
        return None
    return f"assets/thumbs/{name}.png"


def build_gallery(examples_dir: Path, repo_root: Path) -> Tuple[list, int]:
    """Records grouped by series for index.json.

    Notebook LIST + computed runtime come from disk (authoritative); curated
    title/summary/tags/difficulty/data_project come from notebooks.yml when present.
    """
    meta_by_id = load_yml_meta(repo_root)
    groups: dict = {}
    total = 0
    for nb_path in sorted(examples_dir.glob("*.ipynb")):
        name = nb_path.stem
        meta = meta_by_id.get(name, {})
        if meta.get("excluded"):
            continue
        nb = load_notebook(nb_path)
        seconds = compute_runtime_seconds(nb)
        series = meta.get("series") or _series_of(name)
        g = groups.setdefault(series, {
            "series": series,
            "series_name": meta.get("series_name") or SERIES_NAMES.get(series, f"{series}s"),
            "notebooks": [],
        })
        g["notebooks"].append({
            "id": name,
            "title": meta.get("title") or derive_title(nb_path, nb),
            "summary": meta.get("summary", ""),
            "tags": meta.get("tags", []),
            "difficulty": meta.get("difficulty"),
            "est_runtime": meta.get("est_runtime") or (format_runtime(seconds) if seconds is not None else None),
            "runtime_seconds": round(seconds, 1) if seconds is not None else None,
            "data_project": meta.get("data_project"),
            "thumbnail": find_thumbnail(repo_root, name),
            "url": f"../notebooks/{name}.md",
        })
        total += 1
    for g in groups.values():
        g["notebooks"].sort(key=lambda n: n["id"])
    return [groups[k] for k in sorted(groups)], total


def write_index_json(repo_root: Path, groups: list, total: int) -> int:
    payload = {"schema": "rascmdr.examples-gallery/1", "count": total, "series": groups}
    out = repo_root / "docs" / "examples" / "index.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return sum(1 for g in groups for n in g["notebooks"] if n["thumbnail"])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    script_dir = Path(__file__).resolve().parent  # .claude/scripts/
    repo_root = script_dir.parent.parent  # repo root

    examples_dir = repo_root / "examples"
    output_path = repo_root / "docs" / "examples" / "index.md"

    print("=" * 60)
    print("Generating Example Notebooks index page")
    print("=" * 60)
    print(f"examples: {examples_dir}")
    print(f"output:   {output_path}")
    print()

    if not examples_dir.is_dir():
        print(f"ERROR: examples directory not found at {examples_dir}")
        return 1

    markdown, total_rows, with_runtime = build_index_markdown(examples_dir)
    if total_rows == 0:
        print("ERROR: no notebooks found on disk.")
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")

    print(f"Wrote {output_path}")
    print(f"  Rows:            {total_rows}")
    print(f"  With runtime:    {with_runtime}")
    print(f"  Without runtime: {total_rows - with_runtime}")

    # Gallery data surface (W1.2): index.json + thumbnails, metadata from notebooks.yml.
    groups, gallery_total = build_gallery(examples_dir, repo_root)
    thumbs = write_index_json(repo_root, groups, gallery_total)
    print(f"Wrote {repo_root / 'docs' / 'examples' / 'index.json'}")
    print(f"  Gallery notebooks: {gallery_total} in {len(groups)} series")
    print(f"  Thumbnails:        {thumbs}")
    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
