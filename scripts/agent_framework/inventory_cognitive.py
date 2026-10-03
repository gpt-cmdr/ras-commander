#!/usr/bin/env python3
"""Report registry targets and active cognitive roles for maintainer review.

Inventory is read-only. It does not rewrite historical records or infer that a
Markdown role is active in a host solely because its file exists.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


def inventory(root: Path) -> dict:
    manifest = root / '.claude/MANIFEST.md'
    targets = sorted(set(re.findall(r'`(\.claude/[^`]+)`', manifest.read_text())))
    references = [{'path': target, 'exists': (root / target).exists()} for target in targets]
    agents = []
    for file in sorted((root / '.claude/agents').rglob('*.md')):
        text = file.read_text(encoding='utf-8')
        if file.name in ('README.md', 'AGENTS.md'):
            continue
        if file.name not in ('SUBAGENT.md', 'AGENT.md') and file.parent.name != 'agents':
            continue
        if text.startswith('---\n'):
            name = re.search(r'^name:\s*([^\n]+)', text, re.MULTILINE)
            agents.append({'path': str(file.relative_to(root)),
                           'name': name.group(1).strip() if name else file.stem,
                           'kind': 'thin_adapter' if re.search(r'Load \[.*(?:skill|Discovery|Integration|Commander)', text) else 'specialist_or_reference',
                           'declared_model': (re.search(r'^model:\s*([^\n]+)', text, re.MULTILINE).group(1).strip()
                                              if re.search(r'^model:\s*([^\n]+)', text, re.MULTILINE) else None)})
    return {'registry_targets': references, 'missing_targets': [item['path'] for item in references if not item['exists']],
            'roles': agents, 'scope': 'Registry paths and role metadata only; not host activation or semantic qualification.'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path)
    arguments = parser.parse_args()
    text = json.dumps(inventory(arguments.repo_root.resolve()), indent=2) + '\n'
    if arguments.output:
        arguments.output.write_text(text)
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
