#!/usr/bin/env python3
"""
Prepare Notebooks for Documentation Build

This script pre-converts Jupyter notebooks to Markdown for faster documentation builds.
The mkdocs-jupyter plugin is slow with many notebooks; pre-conversion with nbconvert
is ~30x faster.

Usage:
    python .claude/scripts/prepare_notebooks_for_docs.py

What it does:
1. Converts all examples/*.ipynb to docs/notebooks/*.md using nbconvert
2. Updates mkdocs.yml to reference .md files instead of .ipynb
3. Disables mkdocs-jupyter plugin (no longer needed)

This is run during ReadTheDocs pre_build step.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

# Shared title / numbering / section logic, also used by generate_examples_index.py
# so the left-nav and the overview table never drift. stdlib-only import.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _docs_notebook_common import (  # noqa: E402
    derive_title,
    load_notebook,
    numbered_title,
    section_for,
)


def convert_notebooks(examples_dir: Path, output_dir: Path) -> int:
    """Convert all notebooks to markdown using batch processing."""
    output_dir.mkdir(parents=True, exist_ok=True)

    notebooks = list(examples_dir.glob("*.ipynb"))
    print(f"Converting {len(notebooks)} notebooks to markdown...")

    # Use batch mode - much faster than one-by-one
    # nbconvert can process multiple files in one call
    result = subprocess.run(
        [
            sys.executable, "-m", "jupyter", "nbconvert",
            "--to", "markdown",
            "--output-dir", str(output_dir),
        ] + [str(nb) for nb in notebooks],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print(f"  Some errors during conversion:")
        print(f"  {result.stderr[:500]}")

    # Show conversion output
    for line in result.stderr.split('\n'):
        if 'Converting' in line or 'Writing' in line:
            print(f"  {line.strip()}")

    # Count results
    md_files = list(output_dir.glob("*.md"))
    print(f"Created {len(md_files)} markdown files")

    return len(md_files)


def _yaml_dq(text: str) -> str:
    """Double-quote a YAML scalar, escaping backslashes and double-quotes.

    Notebook H1 titles can contain ``:``, ``&``, ``'`` etc. (e.g.
    "Using eBFE Models: Spring Creek 2D Analysis"), which break a bare YAML key,
    so every generated nav label is double-quoted.
    """
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def build_notebook_nav(examples_dir: Path) -> str:
    """Build the ``Example Notebooks`` nav block from notebooks on disk.

    Sourced from ``examples/*.ipynb`` (NOT the hand-authored nav) so the sidebar
    always matches what ships. Entries are numbered, grouped by hundreds bucket,
    and sequential within each group -- the same source and ordering as the
    overview table in generate_examples_index.py. Returns the YAML block (2-space
    indented to sit under the top-level ``nav:`` list), Overview entry first.
    """
    notebooks = sorted(examples_dir.glob("*.ipynb"))

    grouped: dict = {}
    section_order = []
    for nb_path in notebooks:
        name = nb_path.stem
        nb = load_notebook(nb_path)
        label = numbered_title(name, derive_title(nb_path, nb))
        sort_key, section_label = section_for(name)
        key = (sort_key, section_label)
        if key not in grouped:
            grouped[key] = []
            section_order.append(key)
        grouped[key].append((name, label))

    section_order.sort(key=lambda k: k[0])

    lines = [
        "  - Example Notebooks:",
        "    - Overview: examples/index.md",
        "    - Example Projects: examples/example-projects.md",
        "    - Muncie Map Viewer: examples/example-project-viewer.md",
    ]
    for key in section_order:
        lines.append(f"    - {_yaml_dq(key[1])}:")
        for name, label in sorted(grouped[key], key=lambda r: r[0]):
            lines.append(f"      - {_yaml_dq(label)}: notebooks/{name}.md")
    return "\n".join(lines)


def inject_notebook_nav(content: str, examples_dir: Path) -> str:
    """Replace the ``- Example Notebooks:`` nav block with one generated from disk.

    On ``main`` the block is a lone ``Overview`` entry; this expands it to the full
    numbered/grouped tree. Robust to a populated block too (e.g. a feature branch):
    it consumes the header line and every more-indented line beneath it, stopping at
    the next top-level (2-space) sibling.
    """
    lines = content.split("\n")
    start = None
    for i, line in enumerate(lines):
        if line.rstrip() == "  - Example Notebooks:":
            start = i
            break
    if start is None:
        print("  WARNING: '  - Example Notebooks:' nav anchor not found — nav not injected")
        return content

    # Consume children: blank lines or lines indented deeper than the 2-space header.
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() == "" or line.startswith("   "):
            end += 1
        else:
            break

    new_block = build_notebook_nav(examples_dir).split("\n")
    rebuilt = lines[:start] + new_block + lines[end:]
    return "\n".join(rebuilt)


def update_mkdocs_config(mkdocs_path: Path, examples_dir: Path) -> None:
    """Update mkdocs.yml: inject notebook nav, use .md files, disable jupyter plugin."""
    print(f"Updating {mkdocs_path}...")

    content = mkdocs_path.read_text(encoding='utf-8')
    original = content

    # 0. Inject the numbered/grouped Example Notebooks nav generated from disk.
    content = inject_notebook_nav(content, examples_dir)

    # 1. Replace .ipynb with .md in nav entries
    # Pattern: notebooks/XXX.ipynb -> notebooks/XXX.md
    # Use non-greedy match to handle filenames with dots (e.g., 6.1_to_6.6)
    content = re.sub(
        r'notebooks/(.+?)\.ipynb',
        r'notebooks/\1.md',
        content
    )

    # 2. Comment out or remove mkdocs-jupyter plugin
    # This handles both simple and complex plugin configs
    lines = content.split('\n')
    new_lines = []
    in_jupyter_plugin = False
    disabled_jupyter_line = "  # DISABLED for pre-rendered notebooks: - mkdocs-jupyter:"

    for i, line in enumerate(lines):
        # Detect start of mkdocs-jupyter plugin config
        if 'mkdocs-jupyter' in line:
            if line.strip().startswith('#') and 'DISABLED for pre-rendered notebooks' in line:
                new_lines.append(disabled_jupyter_line)
                in_jupyter_plugin = False
                continue
            if ':' in line:  # Complex config like "  - mkdocs-jupyter:"
                in_jupyter_plugin = True
                new_lines.append(disabled_jupyter_line)
                continue
            else:  # Simple config like "  - mkdocs-jupyter"
                new_lines.append("  # DISABLED for pre-rendered notebooks: - mkdocs-jupyter")
                continue

        # Skip indented lines that are part of jupyter plugin config
        if in_jupyter_plugin:
            # Check if this line is still part of the plugin config (indented)
            if line.startswith('      ') or (line.strip().startswith('-') is False and line.startswith('    ') and ':' in line):
                new_lines.append(f"  # {line.strip()}")
                continue
            else:
                in_jupyter_plugin = False

        new_lines.append(line)

    content = '\n'.join(new_lines)

    if content != original:
        mkdocs_path.write_text(content, encoding='utf-8')
        print("  Updated mkdocs.yml:")
        print("    - Injected numbered/grouped Example Notebooks nav from disk")
        print("    - Changed .ipynb references to .md")
        print("    - Disabled mkdocs-jupyter plugin")
    else:
        print("  No changes needed to mkdocs.yml")


def main():
    """Main entry point."""
    # Determine paths
    script_dir = Path(__file__).parent  # .claude/scripts/
    repo_root = script_dir.parent.parent  # repo root

    examples_dir = repo_root / "examples"
    output_dir = repo_root / "docs" / "notebooks"
    mkdocs_path = repo_root / "mkdocs.yml"

    print("=" * 60)
    print("Preparing Notebooks for Documentation Build")
    print("=" * 60)
    print(f"Source: {examples_dir}")
    print(f"Output: {output_dir}")
    print()

    # Step 1: Convert notebooks
    count = convert_notebooks(examples_dir, output_dir)
    if count == 0:
        print("ERROR: No notebooks converted!")
        return 1

    print()

    # Step 2: Update mkdocs.yml
    update_mkdocs_config(mkdocs_path, examples_dir)

    print()
    print("=" * 60)
    print("Notebook preparation complete!")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
