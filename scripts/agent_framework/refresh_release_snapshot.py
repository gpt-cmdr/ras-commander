#!/usr/bin/env python3
"""Record current stable PyPI metadata for review; never install or publish.

A missing distribution is recorded. Transient network failures leave an existing
snapshot intact and fail the command, so they do not generate misleading updates.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import urllib.error
import urllib.request

from packaging.version import Version, InvalidVersion

MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def fetch(url: str) -> dict:
    request = urllib.request.Request(url, headers={'User-Agent': 'commander-release-maintenance/1'})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError('PyPI metadata exceeds the configured response limit')
    return json.loads(data)


def observe(name: str) -> dict:
    try:
        index = fetch(f'https://pypi.org/pypi/{name}/json')
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return {'status': 'not_published', 'source': f'https://pypi.org/pypi/{name}/json'}
        raise
    stable = []
    for version, files in index.get('releases', {}).items():
        try:
            parsed = Version(version)
        except InvalidVersion:
            continue
        if not parsed.is_prerelease and not parsed.is_devrelease and any(not f.get('yanked', False) for f in files):
            stable.append(parsed)
    if not stable:
        return {'status': 'no_stable_release', 'source': f'https://pypi.org/pypi/{name}/json'}
    version = str(max(stable))
    detail = fetch(f'https://pypi.org/pypi/{name}/{version}/json')
    info = detail['info']
    archives = [{'filename': item['filename'], 'package_type': item['packagetype'],
                 'sha256': item.get('digests', {}).get('sha256'),
                 'url': item['url'], 'size_bytes': item['size'],
                 'uploaded_utc': item.get('upload_time_iso_8601')}
                for item in detail.get('urls', []) if not item.get('yanked', False)]
    return {'status': 'released', 'version': version,
            'requires_python': info.get('requires_python'),
            'requires_dist': sorted(info.get('requires_dist') or []),
            'archives': sorted(archives, key=lambda item: item['filename']),
            'source': f'https://pypi.org/pypi/{name}/{version}/json',
            'qualification': 'not_established_by_metadata_check'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.repo_root.resolve()
    config = json.loads((root / '.claude/plugin/release-watch.json').read_text())
    destination = root / config['snapshot']
    if not destination.resolve().is_relative_to((root / '.claude/plugin').resolve()):
        raise ValueError('Snapshot destination must remain in .claude/plugin')
    previous = json.loads(destination.read_text()) if destination.exists() else {}
    # Gather all observations before changing retained evidence.
    observed = {name: observe(name) for name in config['packages']}
    if previous.get('packages') == observed:
        print('Release metadata unchanged; no update candidate.')
        return
    result = {'schema_version': 1,
              'purpose': 'Current stable package discovery; not a compatibility qualification record.',
              'observed_utc': datetime.now(timezone.utc).isoformat(), 'packages': observed}
    destination.write_text(json.dumps(result, indent=2) + '\n')
    print(f'Recorded update candidate: {destination}')


if __name__ == '__main__':
    main()
