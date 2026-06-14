#!/usr/bin/env python3
"""
generate_api_surface.py -- emit the agent-native API surface for ras-commander.

Runs during the docs build (invoked by the ras-commander-docs ``build.sh`` ``ras`` prebuild
profile, AFTER ``uv pip install -e .`` so the library is importable). It introspects the
**installed** ``ras_commander`` package and reads the declarative ``ras_commander/schemas.py``,
then writes machine + human artifacts into ``docs/`` so mkdocs publishes them under ``/ras``:

    docs/version.json             -> /ras/version.json            (build provenance)
    docs/llms/api/index.json      -> /ras/llms/api/index.json      (public signatures)
    docs/llms/api/dataframes.json -> /ras/llms/api/dataframes.json (DataFrame column contracts)
    docs/llms/api/index.md        -> /ras/llms/api/                (human index + provenance banner)

The point: a stable, always-in-sync surface an LLM or ras-commander-mcp can pull to resolve
"current signature of X" / "columns of plan_df" without scraping rendered HTML. mkdocstrings
still owns the rich *human* API reference; this complements it with machine-readable JSON.

Design notes
------------
* Stdlib + ``ras_commander`` only -- no extra build deps.
* The public surface is ``ras_commander.__all__`` (the authoritative export list). Lazy exports
  (GUI / remote / DSS) are resolved through the package's ``__getattr__``; on the Linux build box
  their optional deps (pywin32 / boto3 / jpype) are absent, so **each symbol is introspected in
  its own try/except** and a failure is recorded as ``available: false`` rather than aborting the
  build.
* ``inspect.signature`` is reliable here: the library's ``@log_call`` / ``@standardize_input``
  decorators use ``functools.wraps``.
* Output is sorted for stable diffs. A non-fatal generator: any top-level failure prints a clear
  warning and exits 0 so a surface hiccup never darks the flagship docs build.
"""

from __future__ import annotations

import datetime
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

GENERATOR = "generate_api_surface.py/1.0"
REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs"
API_DIR = DOCS_DIR / "llms" / "api"


def _now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def build_commit() -> str:
    """Commit the docs are built from. Provided by build.sh; fall back to local git."""
    env = os.environ.get("RASDOCS_BUILD_COMMIT")
    if env:
        return env.strip()
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _summary(obj) -> str:
    """First non-empty line of the object's docstring, trimmed."""
    try:
        doc = inspect.getdoc(obj)
    except Exception:
        return ""
    if not doc:
        return ""
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _signature(obj) -> str:
    try:
        return str(inspect.signature(obj))
    except (ValueError, TypeError):
        return "(...)"
    except Exception:
        return "(...)"


def _return_annotation(obj) -> str:
    try:
        ann = inspect.signature(obj).return_annotation
    except Exception:
        return ""
    if ann is inspect.Signature.empty:
        return ""
    try:
        return inspect.formatannotation(ann)
    except Exception:
        return str(ann)


def _member_kind(cls, name) -> str:
    """Classify a class member without binding it (staticmethod/classmethod/property/method)."""
    try:
        raw = inspect.getattr_static(cls, name)
    except Exception:
        return "method"
    if isinstance(raw, staticmethod):
        return "staticmethod"
    if isinstance(raw, classmethod):
        return "classmethod"
    if isinstance(raw, property):
        return "property"
    return "method"


def _is_ras_commander(obj) -> bool:
    mod = getattr(obj, "__module__", "") or ""
    return mod.startswith("ras_commander")


def describe_class(cls) -> dict:
    """Public methods/properties defined within ras_commander (skip inherited stdlib/pandas)."""
    methods = []
    for name, member in inspect.getmembers(cls):
        if name.startswith("_"):
            continue
        kind = _member_kind(cls, name)
        if kind == "property":
            methods.append({
                "name": name, "kind": "property",
                "summary": _summary(getattr(cls, name, member)),
            })
            continue
        # Resolve the underlying function for module-origin filtering + signature.
        target = member
        if not (inspect.isfunction(target) or inspect.ismethod(target) or inspect.isbuiltin(target)):
            continue
        if not _is_ras_commander(target):
            continue
        methods.append({
            "name": name,
            "kind": kind,
            "signature": _signature(target),
            "returns": _return_annotation(target),
            "summary": _summary(target),
        })
    methods.sort(key=lambda m: m["name"])
    return {
        "kind": "class",
        "summary": _summary(cls),
        "method_count": len(methods),
        "methods": methods,
    }


def describe_function(fn) -> dict:
    return {
        "kind": "function",
        "summary": _summary(fn),
        "signature": _signature(fn),
        "returns": _return_annotation(fn),
    }


def build_index(rc) -> dict:
    symbols = {}
    available = 0
    for name in sorted(set(getattr(rc, "__all__", []))):
        entry = {"name": name}
        try:
            obj = getattr(rc, name)
        except Exception as exc:  # optional dep missing on the build box, etc.
            entry.update({"available": False, "error": f"{type(exc).__name__}: {exc}"})
            symbols[name] = entry
            continue
        available += 1
        entry["available"] = True
        entry["module"] = getattr(obj, "__module__", None)
        try:
            if inspect.isclass(obj):
                entry.update(describe_class(obj))
            elif callable(obj):
                entry.update(describe_function(obj))
            else:
                entry["kind"] = "object"
                entry["summary"] = _summary(obj)
        except Exception as exc:
            entry["kind"] = "error"
            entry["error"] = f"{type(exc).__name__}: {exc}"
        symbols[name] = entry
    return {
        "schema": "rascmdr.api-index/1",
        "generated_at_utc": _now_utc(),
        "generator": GENERATOR,
        "ras_commander_version": getattr(rc, "__version__", "unknown"),
        "build_commit": build_commit(),
        "symbol_count": len(symbols),
        "available_count": available,
        "symbols": [symbols[k] for k in sorted(symbols)],
    }


def build_dataframes(rc) -> dict:
    try:
        from ras_commander import schemas  # type: ignore
        frames = json.loads(json.dumps(schemas.DATAFRAME_SCHEMAS))  # deep copy of plain data
        schema_version = getattr(schemas, "SCHEMA_VERSION", "unknown")
    except Exception as exc:
        return {
            "schema": "rascmdr.dataframes/1",
            "generated_at_utc": _now_utc(),
            "error": f"could not import ras_commander.schemas: {type(exc).__name__}: {exc}",
            "frames": {},
        }

    # Cross-check the statically-shaped rasmap_df against live construction; flag drift.
    rasmap_check = None
    try:
        from ras_commander import _land_classification_helper as lch  # type: ignore
        live_cols = list(lch.empty_rasmap_dataframe().columns)
        declared = [c["name"] for c in frames.get("rasmap_df", {}).get("columns", [])]
        rasmap_check = {
            "matches": live_cols == declared,
            "live_columns": live_cols,
            "missing_from_schema": [c for c in live_cols if c not in declared],
            "extra_in_schema": [c for c in declared if c not in live_cols],
        }
    except Exception as exc:
        rasmap_check = {"matches": None, "error": f"{type(exc).__name__}: {exc}"}

    return {
        "schema": "rascmdr.dataframes/1",
        "schema_version": schema_version,
        "generated_at_utc": _now_utc(),
        "generator": GENERATOR,
        "ras_commander_version": getattr(rc, "__version__", "unknown"),
        "build_commit": build_commit(),
        "rasmap_df_live_check": rasmap_check,
        "frames": frames,
    }


def build_version(rc) -> dict:
    return {
        "schema": "rascmdr.version/1",
        "ras_commander_version": getattr(rc, "__version__", "unknown"),
        "build_commit": build_commit(),
        "built_at_utc": _now_utc(),
        "generator": GENERATOR,
    }


def render_api_md(version: dict, index: dict, dataframes: dict) -> str:
    df_rows = []
    for fname, fdef in dataframes.get("frames", {}).items():
        ncols = "dynamic" if fdef.get("dynamic") else str(len(fdef.get("columns", [])))
        df_rows.append(f"| `{fname}` | {ncols} | {fdef.get('description','')} |")
    df_table = "\n".join(df_rows)
    return f"""# Agent-native API surface

!!! info "Build provenance"
    **ras-commander `{version['ras_commander_version']}`** · docs build `{version['build_commit']}`
    · generated `{version['built_at_utc']}`

This page is a small, **machine-readable** surface of the public API, generated at build time by
introspecting the installed library. It is meant for LLMs and
[ras-commander-mcp](https://github.com/gpt-cmdr/ras-commander-mcp) to resolve current signatures
and DataFrame columns without scraping HTML. For the full human reference, see the
[API documentation](../../api/core.md) (rendered from docstrings by mkdocstrings).

## Pullable artifacts

| Artifact | What it is |
|---|---|
| [`version.json`](../../version.json) | Built library version + docs commit + build time. |
| [`index.json`](index.json) | Every public symbol in `__all__`: signatures, return types, one-line summaries ({index['available_count']}/{index['symbol_count']} importable on the build host). |
| [`dataframes.json`](dataframes.json) | Canonical column contracts for the project DataFrames. |

## DataFrame column contracts

| Frame | Columns | Description |
|---|---|---|
{df_table}

Column contracts are the stable core; some frames carry additional project-parsed columns at
runtime (and the HDF result frames are fully runtime-derived). The contracts live in
`ras_commander/schemas.py` (the single source of truth) and are emitted to `dataframes.json`.

*Generated by `{GENERATOR}` — do not edit by hand.*
"""


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    try:
        import ras_commander as rc  # noqa: E402
    except Exception as exc:
        print(f"[generate_api_surface] WARNING: cannot import ras_commander: {exc} — skipping", file=sys.stderr)
        return 0

    try:
        version = build_version(rc)
        index = build_index(rc)
        dataframes = build_dataframes(rc)

        write_json(DOCS_DIR / "version.json", version)
        write_json(API_DIR / "index.json", index)
        write_json(API_DIR / "dataframes.json", dataframes)
        API_DIR.mkdir(parents=True, exist_ok=True)
        (API_DIR / "index.md").write_text(
            render_api_md(version, index, dataframes), encoding="utf-8"
        )
    except Exception as exc:  # never dark the docs build over the surface
        print(f"[generate_api_surface] WARNING: surface generation failed: {exc} — skipping", file=sys.stderr)
        return 0

    print(
        f"[generate_api_surface] ras-commander {version['ras_commander_version']} "
        f"@ {version['build_commit']}: {index['available_count']}/{index['symbol_count']} symbols, "
        f"{len(dataframes.get('frames', {}))} dataframe contracts"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
