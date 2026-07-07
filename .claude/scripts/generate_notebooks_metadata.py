#!/usr/bin/env python3
"""
generate_notebooks_metadata.py -- bootstrap / refresh examples/notebooks.yml.

`examples/notebooks.yml` is the **single source of truth** for example-notebook metadata that
drives the docs gallery, learning paths, cross-links, and the llms.txt surface (docs overhaul
Workstream 1). Hand-authoring ~120 entries from scratch is error-prone, so this script seeds the
file from signals already in the repo and is **merge-aware** -- safe to re-run as notebooks are
added or renamed:

    * FACTUAL fields are always refreshed from the live notebook/source:
        title*, series, series_name, functions_used, data_project, code_cells, executed_cells
      (*title only refreshed if the entry has no human-set title yet)
    * CURATION fields are filled only when missing, never overwritten:
        summary, tags, difficulty, est_runtime, hec_refs, learning_paths, excluded

So the workflow is: run once to seed -> humans curate the curation fields -> re-run anytime to
pick up new notebooks and refreshed signals without losing curation.

Derivation sources (no notebook_inventory.csv dependency -- it is not on main):
    * title    : first markdown H1 in the notebook (fallback: prettified id)
    * summary  : README "Recommended Entry Points" one-liner if present, else first paragraph
                 after the H1 (trimmed)
    * functions_used : regex over code cells for ras_commander public API usage
    * data_project   : first RasExamples.extract_project("...") argument, if any
    * code/executed cells : counted directly from the .ipynb

Usage:  python .claude/scripts/generate_notebooks_metadata.py [--check]
        --check : exit non-zero if the file would change (for CI drift detection)

Stdlib + PyYAML (already a docs-build dependency via mkdocs).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_ROOT / "examples"
README = EXAMPLES_DIR / "README.md"
OUT = EXAMPLES_DIR / "notebooks.yml"

SERIES_NAMES = {
    100: "Initialization & Execution",
    200: "Geometry & Calibration",
    300: "Unsteady & DSS",
    400: "HDF Results",
    500: "Remote Execution",
    600: "Floodplain Mapping",
    700: "Sensitivity & Precipitation",
    800: "Quality Assurance",
    900: "Data Integration",
    950: "eBFE Delivery Validation",
    960: "Cloud-Native Export",
}

# Field order written per entry (factual first, then curation, then provenance counts).
FIELD_ORDER = [
    "id", "filename", "title", "series", "series_name",
    "summary", "tags", "difficulty", "est_runtime", "data_project",
    "functions_used", "hec_refs", "learning_paths", "excluded",
    "code_cells", "executed_cells",
]
FACTUAL = {"filename", "series", "series_name", "functions_used",
           "data_project", "code_cells", "executed_cells"}
# title is refreshed only if not human-set (tracked via _title_auto marker absence)

# Coarse difficulty seed by series band (curation field -- humans refine).
DIFFICULTY_BY_SERIES = {
    100: "beginner", 200: "intermediate", 300: "intermediate", 400: "intermediate",
    500: "advanced", 600: "intermediate", 700: "intermediate", 800: "advanced",
    900: "advanced", 950: "advanced", 960: "advanced",
}

# Topical tag seeds: substring (in id+title) -> tag. Humans curate from here.
TAG_RULES = [
    ("2d", "2d"), ("1d", "1d"), ("unsteady", "unsteady"), ("steady", "steady"),
    ("geom", "geometry"), ("hdf", "hdf"), ("result", "results"),
    ("precip", "precipitation"), ("atlas14", "precipitation"), ("hyetograph", "precipitation"),
    ("mrms", "precipitation"), ("usgs", "usgs"), ("gauge", "usgs"),
    ("calibrat", "calibration"), ("breach", "breach"), ("floodway", "floodway"),
    ("encroach", "floodway"), ("parallel", "remote"), ("remote", "remote"),
    ("worker", "remote"), ("ssh", "remote"), ("aws", "remote"), ("docker", "remote"),
    ("slurm", "remote"), ("cloud", "cloud-native"), ("cog", "cloud-native"),
    ("pmtiles", "cloud-native"), ("parquet", "cloud-native"), ("ras2cng", "cloud-native"),
    ("ebfe", "ebfe"), ("ble", "ebfe"), ("fema", "ebfe"),
    ("monte_carlo", "sensitivity"), ("sensitivity", "sensitivity"),
    ("permutation", "sensitivity"), ("optimization", "sensitivity"),
    ("terrain", "terrain"), ("execution", "execution"), ("compute", "execution"),
    ("dss", "dss"), ("rasmapper", "rasmapper"), ("infiltration", "infiltration"),
]

SYM_RE = re.compile(r"\b((?:Ras|Hdf|Geom)[A-Z]\w+)\.(\w+)")
RAS_ATTR_RE = re.compile(r"\bras\.(\w+)")
EXTRACT_RE = re.compile(r"""extract_project\(\s*["']([^"']+)["']""")


def series_of(num: int) -> int:
    if 950 <= num < 960:
        return 950
    if num >= 960:
        return 960
    return (num // 100) * 100


def parse_readme_oneliners() -> dict:
    """{filename: one-line description} from README 'Recommended Entry Points'."""
    out = {}
    if not README.exists():
        return out
    for line in README.read_text(encoding="utf-8").splitlines():
        # - [123_x.ipynb](123_x.ipynb) - description.   (also handles multiple links per line)
        m = re.match(r"^\s*-\s+(.*\.ipynb.*?)\s+-\s+(.+)$", line)
        if not m:
            continue
        links, desc = m.group(1), m.group(2).strip().rstrip(".")
        for fn in re.findall(r"\[([^\]]+\.ipynb)\]", links):
            out.setdefault(fn, desc)
    return out


def first_markdown(nb: dict) -> str:
    for c in nb.get("cells", []):
        if c.get("cell_type") == "markdown":
            return "".join(c.get("source", []))
    return ""


def derive_title(md: str, nb_id: str) -> str:
    for line in md.splitlines():
        line = line.strip()
        if line.startswith("# "):
            t = line[2:].strip()
            # Drop a leading "Example NNN:" / "NNN:" prefix for a clean title.
            t = re.sub(r"^(Example\s+)?\d{2,3}\s*[:\-]\s*", "", t)
            return t.strip()
    return nb_id.split("_", 1)[-1].replace("_", " ").title()


def derive_summary(md: str) -> str:
    """First non-heading paragraph after the H1, trimmed to one line."""
    lines = md.splitlines()
    body = []
    seen_h1 = False
    for line in lines:
        s = line.strip()
        if s.startswith("#"):
            seen_h1 = True
            continue
        if seen_h1:
            if not s:
                if body:
                    break
                continue
            body.append(s)
    text = " ".join(body)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 240:
        text = text[:237].rstrip() + "..."
    return text


def derive_functions(nb: dict) -> list:
    syms = set()
    for c in nb.get("cells", []):
        if c.get("cell_type") != "code":
            continue
        code = "".join(c.get("source", []))
        for cls, meth in SYM_RE.findall(code):
            if not meth.startswith("_"):          # public API only
                syms.add(f"{cls}.{meth}")
        for attr in RAS_ATTR_RE.findall(code):
            if not attr.startswith("_"):
                syms.add(f"ras.{attr}")
    return sorted(syms)


def derive_data_project(nb: dict) -> str | None:
    for c in nb.get("cells", []):
        if c.get("cell_type") != "code":
            continue
        m = EXTRACT_RE.search("".join(c.get("source", [])))
        if m:
            return m.group(1)
    return None


def seed_tags(nb_id: str, title: str, series: int) -> list:
    hay = f"{nb_id} {title}".lower()
    tags = []
    for needle, tag in TAG_RULES:
        if needle in hay and tag not in tags:
            tags.append(tag)
    return sorted(tags)


def count_cells(nb: dict) -> tuple[int, int]:
    code = [c for c in nb.get("cells", []) if c.get("cell_type") == "code"]
    executed = sum(1 for c in code if c.get("outputs"))
    return len(code), executed


def build_entry(path: Path, existing: dict, readme: dict) -> dict:
    nb = json.loads(path.read_text(encoding="utf-8"))
    nb_id = path.stem
    num = int(re.match(r"^(\d{2,3})", nb_id).group(1)) if re.match(r"^(\d{2,3})", nb_id) else 0
    series = series_of(num)
    md = first_markdown(nb)
    code_cells, executed_cells = count_cells(nb)

    e = dict(existing)  # start from any curated entry
    e["id"] = nb_id
    e["filename"] = path.name
    # Factual refresh:
    e["series"] = series
    e["series_name"] = SERIES_NAMES.get(series, f"{series}s")
    e["functions_used"] = derive_functions(nb)
    e["data_project"] = derive_data_project(nb)
    e["code_cells"] = code_cells
    e["executed_cells"] = executed_cells
    # title: refresh only if not present (so humans can override)
    if not e.get("title"):
        e["title"] = derive_title(md, nb_id)
    # Curation fill-if-missing:
    if not e.get("summary"):
        e["summary"] = readme.get(path.name) or derive_summary(md)
    if not e.get("tags"):
        e["tags"] = seed_tags(nb_id, e["title"], series)
    if not e.get("difficulty"):
        e["difficulty"] = DIFFICULTY_BY_SERIES.get(series, "intermediate")
    e.setdefault("est_runtime", None)
    e.setdefault("hec_refs", [])
    e.setdefault("learning_paths", [])
    e.setdefault("excluded", False)
    # Re-order keys deterministically.
    return {k: e[k] for k in FIELD_ORDER if k in e}


def load_existing() -> dict:
    if not OUT.exists():
        return {}
    data = yaml.safe_load(OUT.read_text(encoding="utf-8")) or {}
    return {n["id"]: n for n in data.get("notebooks", []) if "id" in n}


def render(notebooks: list) -> str:
    header = (
        "# notebooks.yml -- single source of truth for example-notebook metadata.\n"
        "#\n"
        "# Seeded + refreshed by .claude/scripts/generate_notebooks_metadata.py (merge-aware: it\n"
        "# refreshes factual fields and only FILLS MISSING curation fields -- it never overwrites\n"
        "# human edits). Curate: summary, tags, difficulty, est_runtime, hec_refs, learning_paths.\n"
        "# Drives the gallery (generate_examples_index.py), learning paths, cross-links, llms.txt.\n"
    )
    body = yaml.safe_dump(
        {"notebooks": notebooks},
        sort_keys=False, allow_unicode=True, default_flow_style=False, width=100,
    )
    return header + body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if the file would change")
    args = ap.parse_args()

    existing = load_existing()
    readme = parse_readme_oneliners()
    paths = sorted(p for p in EXAMPLES_DIR.glob("*.ipynb"))
    notebooks = [build_entry(p, existing.get(p.stem, {}), readme) for p in paths]

    rendered = render(notebooks)
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != rendered:
            print(f"[notebooks.yml] OUT OF DATE -- re-run generate_notebooks_metadata.py", file=sys.stderr)
            return 1
        print("[notebooks.yml] up to date")
        return 0

    OUT.write_text(rendered, encoding="utf-8")
    curated = sum(1 for n in notebooks if n.get("summary"))
    print(f"[notebooks.yml] wrote {len(notebooks)} entries "
          f"({curated} with summaries) -> {OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
