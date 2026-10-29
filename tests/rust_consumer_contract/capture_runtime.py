"""Capture the full-feature installed runtime; never synthesize missing bindings."""
import argparse
import hashlib
import importlib
import inspect
import json
from pathlib import Path

from expected import EXPECTED


def _member_signature(member):
    if not callable(member):
        return '<attribute>'
    try:
        return str(inspect.signature(member))
    except (TypeError, ValueError):
        return '<unavailable>'


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
        # Private names are skipped except listed test hooks (_panic_for_test).
        if (name.startswith('_') and name not in EXPECTED) or isinstance(obj, type(pkg)) or not callable(obj):
            continue
        if isinstance(obj, type) and issubclass(obj, BaseException):
            continue
        entry = {'signature': str(inspect.signature(obj)),
                 'kind': 'class' if isinstance(obj, type) else 'function'}
        if isinstance(obj, type):
            # Every member the source registers: methods (including private test
            # hooks and __enter__/__exit__) and getters, as the source inventory
            # lists them. Only the constructor and type metadata are excluded.
            entry['methods'] = {m: _member_signature(getattr(obj, m))
                                for m in vars(obj) if m not in {'__new__', '__doc__', '__module__'}}
        entries[name] = entry
    # Test hooks (feature test-hooks) are absent from release-feature wheels.
    expected = {n for n, (_, gate, _) in EXPECTED.items() if gate != 'test-hooks' or n in entries}
    if set(entries) != expected:
        raise SystemExit(f'Full-feature ABI mismatch: missing={sorted(expected-set(entries))}, extra={sorted(set(entries)-expected)}')
    binary = Path(inner.__file__)
    result = dict(source_commit=args.source_commit,
                  native_binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                  api_version=pkg.API_VERSION, text_api_version=pkg.TEXT_API_VERSION,
                  engine_commit=pkg.ENGINE_COMMIT, entrypoints=entries)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()

