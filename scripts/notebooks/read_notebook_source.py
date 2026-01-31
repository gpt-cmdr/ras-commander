#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _cell_source(cell: dict[str, Any]) -> str:
    source = cell.get("source", "")
    if isinstance(source, list):
        return "".join(source)
    if isinstance(source, str):
        return source
    return str(source)


def extract_source(path: Path) -> str:
    with path.open("r", encoding="utf-8") as handle:
        nb = json.load(handle)

    cells: list[dict[str, Any]] = nb.get("cells") or []
    out: list[str] = []
    out.append(f"# Notebook Source: {path}")
    out.append("")

    for idx, cell in enumerate(cells):
        cell_type = cell.get("cell_type")
        if cell_type not in {"markdown", "code"}:
            continue

        src = _cell_source(cell).rstrip()
        if not src:
            continue

        out.append(f"## Cell {idx} ({cell_type})")
        out.append("")

        if cell_type == "code":
            out.append("```python")
            out.append(src)
            out.append("```")
        else:
            out.append(src)

        out.append("")

    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract code+markdown cells from a .ipynb (skips outputs)."
    )
    parser.add_argument("notebook", type=Path, help="Path to .ipynb")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional output markdown file path. Default: stdout.",
    )

    args = parser.parse_args()
    if not args.notebook.exists():
        raise SystemExit(f"Notebook not found: {args.notebook}")
    if args.notebook.suffix.lower() != ".ipynb":
        raise SystemExit(f"Not a notebook: {args.notebook}")

    text = extract_source(args.notebook)
    if args.out is None:
        print(text, end="")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"Wrote: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
