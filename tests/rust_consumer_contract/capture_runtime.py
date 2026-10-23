"""Capture the full-feature installed runtime; never synthesize missing bindings."""
import argparse
import hashlib
import importlib
import inspect
import json
from pathlib import Path

from expected import EXPECTED


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    pkg = importlib.import_module('ras_commander_fast_hdf')
    inner = importlib.import_module('ras_commander_fast_hdf.ras_commander_fast_hdf')
    entries = {}
    for name in dir(pkg):
        obj = getattr(pkg, name)
        if name.startswith('_') or isinstance(obj, type(pkg)) or not callable(obj):
            continue
        if isinstance(obj, type) and issubclass(obj, BaseException):
            continue
        entry = {'signature': str(inspect.signature(obj)),
                 'kind': 'class' if isinstance(obj, type) else 'function'}
        if isinstance(obj, type):
            entry['methods'] = {m: str(inspect.signature(getattr(obj, m)))
                                for m in vars(obj) if not m.startswith('_') and callable(getattr(obj, m))}
        entries[name] = entry
    if set(entries) != set(EXPECTED):
        raise SystemExit(f'Full-feature ABI mismatch: missing={sorted(set(EXPECTED)-set(entries))}, extra={sorted(set(entries)-set(EXPECTED))}')
    binary = Path(inner.__file__)
    result = dict(source_commit=args.source_commit,
                  native_binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                  api_version=pkg.API_VERSION, text_api_version=pkg.TEXT_API_VERSION,
                  engine_commit=pkg.ENGINE_COMMIT, entrypoints=entries)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()

