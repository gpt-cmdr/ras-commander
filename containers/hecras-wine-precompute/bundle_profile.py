#!/usr/bin/env python3
"""Export a verified Wine runtime into a new external release build context."""
import argparse
import json
from pathlib import Path, PurePosixPath
import shutil

from prepare import JobError, load_runtime, write_json


def excluded_path(relative, version):
    parts = PurePosixPath(relative).parts
    lower = [part.lower() for part in parts]
    if any(part in {'package cache', 'installation cache'} for part in lower):
        return True
    if len(lower) >= 3 and lower[:2] == ['prefix', 'drive_c']:
        if lower[2] not in {'windows', 'python311', 'programdata', 'program files', 'program files (x86)', 'users', 'ras2fim-runtime'}:
            return True
    # User state is limited to application settings; no documents or downloads.
    if 'users' in lower:
        index = lower.index('users')
        rest = lower[index + 2:]
        if rest and rest[0] != 'appdata':
            return True
        if any(part in {'temp', 'cache', 'package cache', 'inetcache', 'inetcookies', 'recent'} for part in rest):
            return True
        if lower[-1].endswith('.lnk') or lower[-1] == 'tcu_autoacceptance.txt':
            return True
    if 'windows' in lower and 'temp' in lower:
        return True
    if 'hec-ras' in lower:
        index = lower.index('hec-ras')
        if len(parts) > index + 1 and parts[index + 1] != version:
            return True
    return False


def export_profile(source, destination, version):
    source = Path(source).resolve(strict=True)
    destination = Path(destination).resolve()
    repository = Path(__file__).resolve().parents[2]
    if destination == repository or repository in destination.parents:
        raise JobError('Release profiles must stay outside the source repository')
    if destination == source or source in destination.parents:
        raise JobError('Release destination must be separate from the source profile')
    if destination.exists():
        raise JobError('Release destination must be new: ' + str(destination))
    runtime = load_runtime(source / 'runtime.json', version)
    data = json.loads((source / 'runtime.json').read_text(encoding='utf-8'))
    if data['wine']['prefix_seed'] != 'prefix':
        raise JobError('The image build requires wine.prefix_seed=prefix')
    destination.mkdir(parents=True)
    retained = []
    skipped = []
    for item in data['artifacts']:
        relative = item['path']
        if not relative.startswith('prefix/'):
            raise JobError('Only prefix artifacts belong in a release profile: ' + relative)
        if excluded_path(relative, version):
            skipped.append(relative)
            continue
        src = source / relative
        if src.suffix.lower() in {'.prj', '.hdf', '.dss', '.rasmap'} and not relative.startswith('prefix/drive_c/Python311/'):
            raise JobError('Review unexpected model data before release: ' + relative)
        dest = destination / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        retained.append(item)
    # Recreate the standard Wine drive mappings; never follow the host-root link.
    links = [{'path': 'prefix/dosdevices/c:', 'target': '../drive_c'},
             {'path': 'prefix/dosdevices/z:', 'target': '/'}]
    for link in links:
        path = destination / link['path']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(link['target'], target_is_directory=True)
    for path in [destination / 'prefix/drive_c/users/rasworker/AppData/Local/Temp',
                 destination / 'prefix/drive_c/windows/temp']:
        path.mkdir(parents=True, exist_ok=True)
    data['artifacts'] = retained
    data['symlinks'] = links
    write_json(destination / 'runtime.json', data)
    verified = load_runtime(destination / 'runtime.json', version)
    evidence = {
        'hec_ras_version': version,
        'source_manifest_sha256': runtime['identity']['manifest_sha256'],
        'release_manifest_sha256': verified['identity']['manifest_sha256'],
        'retained_artifacts': len(retained),
        'excluded_paths': skipped,
        'source': str(source),
        'destination': str(destination),
    }
    # Keep the audit next to the context, not in the published image.
    write_json(destination.with_name(destination.name + '-export.json'), evidence)
    return {key: value for key, value in evidence.items() if key != 'excluded_paths'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--version', required=True, choices=['6.5', '6.6', '7.0.1'])
    args = parser.parse_args()
    print(json.dumps(export_profile(args.source, args.destination, args.version), sort_keys=True))
