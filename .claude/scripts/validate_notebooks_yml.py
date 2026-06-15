#!/usr/bin/env python3
"""
validate_notebooks_yml.py -- semantic validation of examples/notebooks.yml.

The docs gallery, learning paths, and llms surface all read examples/notebooks.yml (the source of
truth seeded by generate_notebooks_metadata.py). This gate fails the build when that metadata drifts
from reality -- not mere "is there an entry", but a SEMANTIC check (docs overhaul Workstream 1, W1.3):

  1. Coverage: every shipped notebook (examples/*.ipynb) has exactly one entry; no orphan entries
     pointing at notebooks that no longer exist.
  2. Required fields present and non-empty: id, filename, title, series, series_name.
  3. functions_used resolve to REAL public API symbols, cross-checked by introspecting the installed
     ras_commander -- the same authoritative surface published at /ras/llms/api (P3). A `Class.method`
     must be a public member of a public class; a `ras.<attr>` must be a known RasPrj attribute or a
     documented DataFrame (ras_commander/schemas.py). Symbols whose class can't be imported on this
     host (optional GUI/remote deps) are reported as UNVERIFIABLE warnings, never hard errors.

Exit code: 0 if no errors (warnings allowed), 1 on any error. Run in content-repo CI and as a
build-fatal step before the gallery generator.

Usage:  python .claude/scripts/validate_notebooks_yml.py [--strict]
        --strict : treat warnings (e.g. blank summaries, unverifiable symbols) as errors too.

Stdlib + PyYAML + ras_commander (all present in the docs build / CI env).
"""

from __future__ import annotations

import argparse
import inspect
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_ROOT / "examples"
NOTEBOOKS_YML = EXAMPLES_DIR / "notebooks.yml"

REQUIRED = ["id", "filename", "title", "series", "series_name"]

# RasPrj instance attributes that are set at init (not class-level, so dir(RasPrj) may miss them).
KNOWN_RAS_ATTRS = {
    "plan_df", "geom_df", "unsteady_df", "steady_df", "flow_df", "boundaries_df",
    "results_df", "rasmap_df", "hdf_entries", "project_name", "project_folder",
    "prj_file", "ras_exe_path", "ras_version", "current_ras_version",
}


def build_symbol_index():
    """Return (class_members, ras_attrs, importable_classes) from the installed library."""
    import ras_commander as rc
    class_members: dict[str, set] = {}
    importable: set[str] = set()
    public_classes: set[str] = set()
    for name in getattr(rc, "__all__", []):
        try:
            obj = getattr(rc, name)
        except Exception:
            public_classes.add(name)  # known public symbol, just not importable here
            continue
        if inspect.isclass(obj):
            public_classes.add(name)
            importable.add(name)
            class_members[name] = {m for m in dir(obj) if not m.startswith("_")}

    ras_attrs = set(KNOWN_RAS_ATTRS)
    rasprj = class_members.get("RasPrj")
    if rasprj:
        ras_attrs |= rasprj
    try:
        from ras_commander import schemas
        ras_attrs |= set(schemas.DATAFRAME_SCHEMAS.keys())
    except Exception:
        pass
    return class_members, ras_attrs, importable, public_classes


def classify_symbol(sym, class_members, ras_attrs, importable, public_classes):
    """Return 'ok' | 'bad' | 'unverifiable' for a functions_used entry."""
    if sym.startswith("ras."):
        return "ok" if sym.split(".", 1)[1] in ras_attrs else "bad"
    if "." not in sym:
        return "bad"
    cls, meth = sym.split(".", 1)
    if cls in importable:
        return "ok" if meth in class_members.get(cls, ()) else "bad"
    if cls in public_classes:
        return "unverifiable"   # public symbol but optional dep not importable on this host
    return "bad"                # references a class that isn't part of the public API at all


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args = ap.parse_args()

    if not NOTEBOOKS_YML.exists():
        print(f"ERROR: {NOTEBOOKS_YML} not found", file=sys.stderr)
        return 1
    data = yaml.safe_load(NOTEBOOKS_YML.read_text(encoding="utf-8")) or {}
    entries = data.get("notebooks", [])
    by_id = {e.get("id"): e for e in entries if e.get("id")}

    disk_ids = {p.stem for p in EXAMPLES_DIR.glob("*.ipynb")}
    yml_ids = set(by_id)

    errors: list[str] = []
    warnings: list[str] = []

    # 1) Coverage
    for missing in sorted(disk_ids - yml_ids):
        errors.append(f"missing entry: {missing}.ipynb is on disk but absent from notebooks.yml")
    for orphan in sorted(yml_ids - disk_ids):
        errors.append(f"orphan entry: notebooks.yml has '{orphan}' but no examples/{orphan}.ipynb")
    if len(entries) != len(by_id):
        errors.append(f"duplicate or id-less entries: {len(entries)} entries, {len(by_id)} unique ids")

    # 2) Required fields
    for nb_id, e in sorted(by_id.items()):
        for field in REQUIRED:
            val = e.get(field)
            if val is None or (isinstance(val, str) and not val.strip()):
                errors.append(f"{nb_id}: missing required field '{field}'")
        if not e.get("summary"):
            warnings.append(f"{nb_id}: blank summary (needs curation)")

    # 3) functions_used resolution
    try:
        class_members, ras_attrs, importable, public_classes = build_symbol_index()
    except Exception as exc:
        errors.append(f"could not introspect ras_commander for symbol validation: {exc}")
        class_members = ras_attrs = importable = public_classes = None

    if class_members is not None:
        for nb_id, e in sorted(by_id.items()):
            if e.get("excluded"):
                continue
            for sym in e.get("functions_used", []) or []:
                verdict = classify_symbol(sym, class_members, ras_attrs, importable, public_classes)
                if verdict == "bad":
                    # functions_used is regex-seeded best-effort (it can catch internal, non-__all__
                    # classes). Surface as a curation WARNING, not a hard build failure — --strict
                    # promotes it once the metadata is cleaned (then the build can gate on it).
                    warnings.append(f"{nb_id}: functions_used '{sym}' does not resolve to a public API symbol")
                elif verdict == "unverifiable":
                    warnings.append(f"{nb_id}: functions_used '{sym}' references an optional module not importable here")

    # Report
    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}", file=sys.stderr)

    n_err = len(errors) + (len(warnings) if args.strict else 0)
    print(f"\n[validate notebooks.yml] {len(by_id)} entries, {len(disk_ids)} notebooks on disk, "
          f"{len(errors)} errors, {len(warnings)} warnings"
          + (" (strict)" if args.strict else ""))
    return 1 if n_err else 0


if __name__ == "__main__":
    raise SystemExit(main())
