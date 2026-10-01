"""Check that curated RASMapper API members actually rendered in MkDocs HTML.

A strict MkDocs build can succeed when Griffe resolves an exported class name
as a module and silently omits its explicitly listed methods. Check the output,
not just the directive syntax. This intentionally covers only RASMapper pages.
"""
from __future__ import annotations

import argparse
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re
import sys


class AnchorInventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: Counter[str] = Counter()
        self.review_ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        anchor = dict(attrs).get("id")
        if not anchor or anchor.startswith(("__span", "__codelineno")):
            return
        self.ids[anchor] += 1
        if re.fullmatch(r"h[1-6]", tag) or anchor.startswith("ras_commander."):
            self.review_ids.add(anchor)

    handle_startendtag = handle_starttag


def listed_anchors(markdown: str) -> set[str]:
    """Read explicit class/member directives without depending on YAML plugins."""
    anchors: set[str] = set()
    current: str | None = None
    member_indent: int | None = None
    fence: str | None = None
    for line in markdown.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is not None:
            continue
        directive = re.fullmatch(r"::: +([A-Za-z_][\w.]*)\s*", line)
        if directive:
            current = directive.group(1)
            member_indent = None
            continue
        if current is None or not stripped:
            continue
        indent = len(line) - len(stripped)
        if indent == 0:
            current = None
            member_indent = None
            continue
        if stripped == "members:":
            member_indent = indent
            continue
        if member_indent is not None:
            if indent <= member_indent:
                member_indent = None
            else:
                member = re.fullmatch(r"- +([A-Za-z_]\w*)\s*", stripped)
                if member:
                    anchors.add(f"{current}.{member.group(1)}")
    return anchors


def validate(docs_dir: Path, site_dir: Path) -> list[str]:
    errors: list[str] = []
    total = 0
    pages = sorted((docs_dir / "api" / "rasmapper").glob("*.md"))
    if not pages:
        return [f"No RASMapper Markdown pages found under {docs_dir}"]
    for page in pages:
        expected = listed_anchors(page.read_text(encoding="utf-8"))
        total += len(expected)
        relative = Path("api") / "rasmapper"
        if page.stem != "index":
            relative /= page.stem
        html_path = site_dir / relative / "index.html"
        if not html_path.is_file():
            errors.append(f"{page.name}: missing built page {html_path}")
            continue
        inventory = AnchorInventory()
        inventory.feed(html_path.read_text(encoding="utf-8"))
        for anchor in sorted(expected - inventory.ids.keys()):
            errors.append(f"{page.name}: missing method anchor {anchor}")
        for anchor in sorted(inventory.review_ids):
            if inventory.ids[anchor] > 1:
                errors.append(f"{page.name}: duplicate API/heading ID {anchor}")
    if total == 0:
        errors.append("No explicitly listed RASMapper API members found; refusing a vacuous pass")
    if not errors:
        print(f"Validated {total} listed methods across {len(pages)} RASMapper pages.")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir", type=Path, default=Path("site"))
    parser.add_argument("--docs-dir", type=Path, default=Path("docs"))
    args = parser.parse_args()
    errors = validate(args.docs_dir, args.site_dir)
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
