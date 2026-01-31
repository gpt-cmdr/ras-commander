#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable


ERROR_TEXT_PATTERN = re.compile(
    r"(Traceback\s*\(most recent call last\)|\b[A-Za-z_][A-Za-z0-9_]*Error\b|\bException\b)",
    re.IGNORECASE,
)

ANOMALY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("empty_results", re.compile(r"\b(0\s+rows?|empty|no\s+data)\b", re.I)),
    ("missing_file", re.compile(r"\b(file\s+not\s+found|not\s+found)\b", re.I)),
    ("no_maps", re.compile(r"\b(no\s+maps?\s+generated|no\s+maps?)\b", re.I)),
]

PATH_LEAK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+", re.I),
    re.compile(r"/Users/[^/\s]+", re.I),
]

PRIVATE_IP_PATTERN = re.compile(
    r"\b(?:"
    r"10(?:\.\d{1,3}){3}"
    r"|192\.168(?:\.\d{1,3}){2}"
    r"|172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}"
    r")\b"
)


def _now_compact() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _is_glob_pattern(value: str) -> bool:
    return any(char in value for char in ["*", "?", "["])


def _expand_inputs(inputs: Iterable[str], recursive: bool) -> list[Path]:
    resolved: list[Path] = []

    for raw in inputs:
        value = os.path.expandvars(raw)

        if _is_glob_pattern(value):
            matches = glob.glob(value, recursive=recursive)
            resolved.extend(Path(match) for match in matches)
            continue

        path = Path(value)
        if path.is_dir():
            pattern = "**/*.ipynb" if recursive else "*.ipynb"
            resolved.extend(path.glob(pattern))
            continue

        resolved.append(path)

    unique = sorted({p.resolve() for p in resolved if p.suffix == ".ipynb"})
    return [p for p in unique if p.exists()]


def _cell_source(cell: dict[str, Any]) -> str:
    source = cell.get("source", "")
    if isinstance(source, list):
        return "".join(source)
    if isinstance(source, str):
        return source
    return str(source)


def _output_text(output: dict[str, Any]) -> str:
    output_type = output.get("output_type", "")

    if output_type == "error":
        traceback_lines = output.get("traceback") or []
        if isinstance(traceback_lines, list):
            return "\n".join(str(line) for line in traceback_lines)
        return str(traceback_lines)

    if output_type == "stream":
        text = output.get("text", "")
        if isinstance(text, list):
            return "".join(str(part) for part in text)
        return str(text)

    if output_type in {"execute_result", "display_data"}:
        data = output.get("data") or {}
        text_plain = data.get("text/plain", "")
        if isinstance(text_plain, list):
            return "".join(str(part) for part in text_plain)
        return str(text_plain)

    return ""


def _truncate(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def audit_notebook(path: Path, max_text_chars: int) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        nb = json.load(handle)

    cells: list[dict[str, Any]] = nb.get("cells") or []

    first_cell_ok = False
    if cells:
        first = cells[0]
        if first.get("cell_type") == "markdown":
            first_source = _cell_source(first).lstrip()
            first_cell_ok = first_source.startswith("#")

    issues: list[dict[str, Any]] = []
    if not first_cell_ok:
        issues.append(
            {
                "kind": "missing_h1_title",
                "cell_index": 0 if cells else None,
                "message": "First cell should be markdown with H1 title",
            }
        )

    code_cells = 0
    output_items = 0

    for cell_index, cell in enumerate(cells):
        if cell.get("cell_type") != "code":
            continue

        code_cells += 1
        execution_count = cell.get("execution_count")
        outputs: list[dict[str, Any]] = cell.get("outputs") or []
        output_items += len(outputs)

        for output_index, output in enumerate(outputs):
            output_type = output.get("output_type", "")

            if output_type == "error":
                issues.append(
                    {
                        "kind": "error_output",
                        "cell_index": cell_index,
                        "execution_count": execution_count,
                        "output_index": output_index,
                        "ename": output.get("ename"),
                        "evalue": output.get("evalue"),
                        "excerpt": _truncate(_output_text(output), max_text_chars),
                    }
                )
                continue

            text = _output_text(output)
            if not text:
                continue

            if output_type == "stream" and output.get("name") == "stderr":
                if ERROR_TEXT_PATTERN.search(text) or "warning" in text.lower():
                    issues.append(
                        {
                            "kind": "stderr_stream",
                            "cell_index": cell_index,
                            "execution_count": execution_count,
                            "output_index": output_index,
                            "excerpt": _truncate(text, max_text_chars),
                        }
                    )

            if ERROR_TEXT_PATTERN.search(text):
                issues.append(
                    {
                        "kind": "error_text",
                        "cell_index": cell_index,
                        "execution_count": execution_count,
                        "output_index": output_index,
                        "excerpt": _truncate(text, max_text_chars),
                    }
                )

            for anomaly_name, pattern in ANOMALY_PATTERNS:
                if pattern.search(text):
                    issues.append(
                        {
                            "kind": "anomaly_text",
                            "anomaly": anomaly_name,
                            "cell_index": cell_index,
                            "execution_count": execution_count,
                            "output_index": output_index,
                            "excerpt": _truncate(text, max_text_chars),
                        }
                    )
                    break

            for pattern in PATH_LEAK_PATTERNS:
                match = pattern.search(text)
                if match:
                    issues.append(
                        {
                            "kind": "path_leak",
                            "cell_index": cell_index,
                            "execution_count": execution_count,
                            "output_index": output_index,
                            "excerpt": _truncate(match.group(0), max_text_chars),
                        }
                    )
                    break

            ip_match = PRIVATE_IP_PATTERN.search(text)
            if ip_match:
                issues.append(
                    {
                        "kind": "private_ip_leak",
                        "cell_index": cell_index,
                        "execution_count": execution_count,
                        "output_index": output_index,
                        "excerpt": _truncate(ip_match.group(0), max_text_chars),
                    }
                )

    error_kinds = {"error_output"}
    has_error_outputs = any(item.get("kind") in error_kinds for item in issues)

    return {
        "path": str(path),
        "cells_total": len(cells),
        "cells_code": code_cells,
        "output_items": output_items,
        "first_cell_h1_ok": first_cell_ok,
        "has_error_outputs": has_error_outputs,
        "issues": issues,
    }


def _render_markdown(results: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("# Notebook Audit")
    lines.append("")
    lines.append(f"- Notebooks scanned: {len(results)}")
    lines.append(
        f"- Notebooks with error outputs: "
        f"{sum(1 for r in results if r.get('has_error_outputs'))}"
    )
    lines.append("")

    for result in results:
        path = result.get("path", "<unknown>")
        lines.append(f"## {path}")
        lines.append("")
        lines.append(f"- Cells: {result.get('cells_total')} total")
        lines.append(f"- Code cells: {result.get('cells_code')}")
        lines.append(f"- Output items: {result.get('output_items')}")
        lines.append(f"- First cell H1 OK: {result.get('first_cell_h1_ok')}")
        lines.append(f"- Has error outputs: {result.get('has_error_outputs')}")
        lines.append("")

        issues = result.get("issues") or []
        if not issues:
            lines.append("- Issues: none detected")
            lines.append("")
            continue

        lines.append("- Issues:")
        for issue in issues:
            kind = issue.get("kind", "unknown")
            cell_index = issue.get("cell_index")
            execution_count = issue.get("execution_count")
            excerpt = issue.get("excerpt") or issue.get("message") or ""

            meta = []
            if cell_index is not None:
                meta.append(f"cell={cell_index}")
            if execution_count is not None:
                meta.append(f"exec={execution_count}")

            meta_text = f" ({', '.join(meta)})" if meta else ""
            excerpt = excerpt.replace("\n", " ").strip()
            lines.append(f"  - {kind}{meta_text}: {excerpt}")

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan .ipynb files for stored errors and suspicious outputs."
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Notebook paths, directories, or glob patterns "
        "(default: examples/*.ipynb).",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="When inputs include directories or globs, recurse into subdirs.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Directory to write audit.json and audit.md.",
    )
    parser.add_argument(
        "--max-text-chars",
        type=int,
        default=800,
        help="Max characters to include per output excerpt.",
    )
    parser.add_argument(
        "--fail-on-error-outputs",
        action="store_true",
        help="Exit non-zero if any notebooks contain stored error outputs.",
    )

    args = parser.parse_args()
    inputs = args.inputs or ["examples/*.ipynb"]

    paths = _expand_inputs(inputs, recursive=args.recursive)
    if not paths:
        print("No notebooks found.", file=sys.stderr)
        return 2

    results = [audit_notebook(path, max_text_chars=args.max_text_chars) for path in paths]

    if args.out_dir is not None:
        out_dir = args.out_dir
    else:
        out_dir = Path("working") / "notebook_runs" / _now_compact()

    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "audit.json"
    md_path = out_dir / "audit.md"

    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(results), encoding="utf-8")

    has_error_outputs = any(result.get("has_error_outputs") for result in results)

    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")

    if args.fail_on_error_outputs and has_error_outputs:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
