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


def update_mkdocs_config(mkdocs_path: Path) -> None:
    """Update mkdocs.yml to use .md files and disable jupyter plugin."""
    print(f"Updating {mkdocs_path}...")

    content = mkdocs_path.read_text(encoding='utf-8')
    original = content

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
    skip_until_next_plugin = False
    in_jupyter_plugin = False

    for i, line in enumerate(lines):
        # Detect start of mkdocs-jupyter plugin config
        if 'mkdocs-jupyter' in line:
            if ':' in line:  # Complex config like "  - mkdocs-jupyter:"
                in_jupyter_plugin = True
                new_lines.append(f"  # DISABLED for pre-rendered notebooks: {line.strip()}")
                continue
            else:  # Simple config like "  - mkdocs-jupyter"
                new_lines.append(f"  # DISABLED for pre-rendered notebooks: {line.strip()}")
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
    update_mkdocs_config(mkdocs_path)

    print()
    print("=" * 60)
    print("Notebook preparation complete!")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
