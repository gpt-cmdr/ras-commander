#!/usr/bin/env python3
"""Assemble a skills-only portable plugin from canonical, allowlisted sources.

No environment installation, MCP registration, or publication is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, unquote

from sync_codex_skill_bridge import is_shared_skill, parse_frontmatter, validate_codex_skill_metadata

LINK = re.compile(r'(!?\[[^\]\n]*\]\(\s*)(<[^>\n]+>|[^\s)]+)([^)\n]*\))')
REFERENCE = re.compile(r'(^ {0,3}\[[^\]\n]+\]:\s*)(<[^>\n]+>|[^\s]+)([^\n]*)', re.MULTILINE)


def markdown_targets(text: str):
    # HTML targets are outside the accepted packaging source format. Fail rather
    # than ship a local reference whose containment was never evaluated.
    if re.search(r'(?:href|src)=[\"\'](?!https?://|data:|#)', text):
        raise ValueError('Local HTML references are unsupported; use Markdown links.')
    return [match for pattern in (LINK, REFERENCE) for match in pattern.finditer(text)]


def link_parts(target: str):
    return urlsplit(target[1:-1] if target.startswith('<') and target.endswith('>') else target)

BRIDGE_FIELDS = ('shared_corpus', 'harness_scope', 'source_owner', 'security_review')


def confined(path: Path, root: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f'Source escapes canonical root: {path}')
    if not resolved.is_file():
        raise ValueError(f'Expected a source file: {path}')
    return resolved


def build(repo: Path, output: Path) -> None:
    repo = repo.resolve()
    canonical = repo / '.claude'
    config = json.loads((canonical / 'plugin/package.json').read_text())
    if output.exists() or output.is_symlink():
        raise ValueError('Output already exists; choose a new distribution destination.')
    # Output is a disposable distribution. Prevent overwriting canonical instructions.
    if output.resolve().is_relative_to(canonical.resolve()):
        raise ValueError('Output must be outside the canonical .claude tree.')
    sources: dict[Path, Path] = {}
    selected: dict[str, Path] = {}
    for name in config['skills']:
        if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?', name) or '--' in name:
            raise ValueError(f'Invalid portable skill name: {name}')
        directory = canonical / 'skills' / name
        skill = confined(directory / 'SKILL.md', canonical)
        if not is_shared_skill(directory):
            raise ValueError(f'Skill is not approved for shared distribution: {name}')
        metadata_errors = validate_codex_skill_metadata(directory)
        if metadata_errors:
            raise ValueError('; '.join(metadata_errors))
        if parse_frontmatter(skill).get('name') != name:
            raise ValueError(f'Skill name differs from selected directory: {name}')
        selected[name] = directory.resolve()
        for candidate in directory.rglob('*'):
            if candidate.is_file():
                source = confined(candidate, canonical)
                sources[source] = Path('skills') / name / source.relative_to(directory.resolve())

    # Traverse every local Markdown target, including links in supporting resources.
    pending = list(sources)
    scanned = set()
    while pending:
        source = pending.pop()
        if source in scanned or source.suffix.lower() != '.md':
            continue
        scanned.add(source)
        for match in markdown_targets(source.read_text()):
            target = match.group(2)
            parts = link_parts(target)
            if parts.scheme or parts.netloc or not parts.path:
                continue
            resolved = confined(source.parent / unquote(parts.path), canonical)
            if resolved not in sources:
                destination = None
                for name, directory in selected.items():
                    if resolved.is_relative_to(directory):
                        destination = Path('skills') / name / resolved.relative_to(directory)
                        break
                sources[resolved] = destination or Path('resources') / resolved.relative_to(repo)
                pending.append(resolved)

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='commander-plugin-', dir=output.parent) as temporary:
        staging = Path(temporary) / 'bundle'
        staging.mkdir()
        provenance = []
        for source, destination in sorted(sources.items(), key=lambda item: str(item[1])):
            content = source.read_bytes()
            target = staging / destination
            if not target.resolve().is_relative_to(staging.resolve()):
                raise ValueError(f'Package destination escapes staging: {destination}')
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.suffix.lower() == '.md':
                text = content.decode('utf-8')
                def rebase(match: re.Match) -> str:
                    link = match.group(2)
                    parts = link_parts(link)
                    if parts.scheme or parts.netloc or not parts.path:
                        return match.group(0)
                    original = confined(source.parent / unquote(parts.path), canonical)
                    # POSIX relative package paths work across distribution hosts.
                    import posixpath
                    rewritten = posixpath.relpath(sources[original].as_posix(), destination.parent.as_posix())
                    if parts.query:
                        rewritten += '?' + parts.query
                    if parts.fragment:
                        rewritten += '#' + parts.fragment
                    if link.startswith('<') or ' ' in rewritten:
                        rewritten = '<' + rewritten + '>'
                    return match.group(1) + rewritten + match.group(3)
                markdown_targets(text)
                text = LINK.sub(rebase, text)
                text = REFERENCE.sub(rebase, text)
                if source.name == 'SKILL.md' and text.startswith('---\n'):
                    # Bridge fields are repository metadata, not portable skill fields.
                    lines = text.splitlines(keepends=True)
                    closing = next(i for i in range(1, len(lines)) if lines[i].strip() == '---')
                    custom = []
                    front = []
                    for line in lines[1:closing]:
                        if line.split(':', 1)[0] in BRIDGE_FIELDS:
                            key, value = line.split(':', 1)
                            # Agent Skills metadata is a string-to-string map.
                            custom.append(f'  {key}: {json.dumps(value.strip().strip(chr(34)).strip(chr(39)))}\n')
                        else:
                            front.append(line)
                    if custom:
                        if any(line.startswith('metadata:') for line in front):
                            raise ValueError('Merge existing skill metadata before packaging.')
                        front += ['metadata:\n'] + custom
                    text = '---\n' + ''.join(front) + ''.join(lines[closing:])
                target.write_text(text, encoding='utf-8')
            else:
                target.write_bytes(content)
            provenance.append({'source': source.relative_to(repo).as_posix(),
                               'source_sha256': hashlib.sha256(content).hexdigest(),
                               'packaged': destination.as_posix(),
                               'packaged_sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
        manifest = config['manifest']
        (staging / 'plugin.json').write_text(json.dumps(manifest, indent=2) + '\n')
        (staging / 'source-provenance.json').write_text(json.dumps({
            'source_repository': manifest['repository'],
            'package_configuration_sha256': hashlib.sha256((canonical / 'plugin/package.json').read_bytes()).hexdigest(),
            'files': provenance}, indent=2) + '\n')
        # Check packaged relative links before promoting the assembled bundle.
        for markdown in staging.rglob('*.md'):
            for match in markdown_targets(markdown.read_text()):
                parts = link_parts(match.group(2))
                if not parts.scheme and not parts.netloc and parts.path:
                    confined(markdown.parent / unquote(parts.path), staging)
        shutil.move(str(staging), str(output))
    print(f'Assembled {manifest["name"]} {manifest["version"]}: {output}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    build(arguments.repo_root, arguments.output)


if __name__ == '__main__':
    main()
