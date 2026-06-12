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
notebooks to markdown). It only uses the Python standard library
(json, re, pathlib, datetime) so it runs under a bare ``python3`` with no
extra dependencies.

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
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

GITHUB_BLOB_BASE = "https://github.com/gpt-cmdr/ras-commander/blob/main/examples"


# ---------------------------------------------------------------------------
# Title derivation
# ---------------------------------------------------------------------------

def _load_notebook(notebook_path: Path) -> Optional[dict]:
    try:
        with notebook_path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _cell_source_lines(cell: dict) -> List[str]:
    """Return a notebook cell's source as a list of text lines.

    nbformat stores ``source`` either as a single string or a list of strings.
    """
    source = cell.get("source", "")
    if isinstance(source, list):
        text = "".join(source)
    else:
        text = source
    return text.splitlines()


def prettify_filename(name: str) -> str:
    """Fallback title from a notebook basename (no extension).

    Drops a leading numeric prefix (e.g. ``116`` or ``911a``), replaces
    underscores with spaces, and Title-Cases the result. Deterministic.
    """
    stem = re.sub(r"^\d+[a-zA-Z]?_", "", name)
    stem = stem.replace("_", " ").strip()
    if not stem:
        stem = name.replace("_", " ").strip()
    return stem.title()


def derive_title(notebook_path: Path, nb: Optional[dict]) -> str:
    """Title = first markdown cell's first ``# `` H1, else prettified filename."""
    name = notebook_path.stem
    if nb is not None:
        for cell in nb.get("cells", []):
            if cell.get("cell_type") != "markdown":
                continue
            for line in _cell_source_lines(cell):
                stripped = line.strip()
                if stripped.startswith("# "):
                    return stripped[1:].strip()
            # First markdown cell had no H1; keep scanning later markdown cells
            # in case the title lives further down (still deterministic).
    return prettify_filename(name)


# ---------------------------------------------------------------------------
# Section grouping
# ---------------------------------------------------------------------------

def section_for(name: str) -> Tuple[int, str]:
    """Return ``(sort_key, label)`` section bucket for a notebook basename.

    The leading run of digits in the filename prefix (e.g. ``911a_...`` -> 911,
    ``116_...`` -> 116) is bucketed by hundreds into ``100s``..``900s``. Names
    without a numeric prefix fall into a trailing "Other" bucket.
    """
    m = re.match(r"^(\d+)", name)
    if not m:
        return (10_000, "Other")
    n = int(m.group(1))
    bucket = (n // 100) * 100
    return (bucket, f"{bucket}s")


# ---------------------------------------------------------------------------
# Runtime calculation (stdlib json only)
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
        nb = _load_notebook(nb_path)
        title = derive_title(nb_path, nb)
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
    )

    summary = (
        f"*{total_rows} notebooks indexed - {rows_with_runtime} with runtime "
        f"data, {total_rows - rows_with_runtime} without.*\n"
    )

    markdown = intro + summary + "\n" + "\n\n".join(section_blocks) + "\n"
    return markdown, total_rows, rows_with_runtime


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
    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
