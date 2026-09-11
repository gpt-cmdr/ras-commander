#!/usr/bin/env python3
"""Export a native HEC-RAS engine into a clean external Docker build context.

Run on Linux to preserve executable permissions. Obtain the runtime and notices
from the official distribution; this script neither downloads nor modifies it.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile


def _hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_tree(source, destination):
    source = source.resolve(strict=True)
    for path in sorted(source.rglob("*")):
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(source):
            raise ValueError(f"Runtime link escapes the selected input: {path}")
        target = destination / path.relative_to(source)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            if path.suffix.lower() in {".zip", ".7z", ".tar", ".gz", ".hdf", ".prj", ".tif"}:
                raise ValueError(f"Runtime input contains an archive or model file: {path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resolved, target)
        else:
            raise ValueError(f"Runtime input is not an ordinary file or directory: {path}")


def bundle_runtime(*, engine_source, libraries_source, notices_source, hec_ras_version, output):
    if hec_ras_version not in {"6.5", "6.6", "7.0.1"}:
        raise ValueError("This image currently supports native HEC-RAS 6.5, 6.6 and 7.0.1")
    engine_source = Path(engine_source).resolve(strict=True)
    executable = engine_source / "RasUnsteady"
    if not executable.is_file() or executable.stat().st_size == 0:
        raise ValueError("engine-source must contain the native RasUnsteady executable")
    with executable.open("rb") as stream:
        header = stream.read(20)
    if header[:5] != b"\x7fELF\x02" or header[18:20] != b"\x3e\x00":
        raise ValueError("RasUnsteady must be a 64-bit Linux x86-64 ELF executable")
    notices_source = Path(notices_source).resolve(strict=True)
    if not notices_source.is_dir() or not any(p.is_file() for p in notices_source.rglob("*")):
        raise ValueError("notices-source must contain retained vendor terms/notices")
    libraries_source = Path(libraries_source).resolve(strict=True)
    if not libraries_source.is_dir() or not any(p.is_file() for p in libraries_source.rglob("*")):
        raise ValueError("libraries-source must contain the vendor shared libraries")
    output = Path(output).absolute()
    if output.exists():
        raise ValueError("Output must be a new external build-context directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="." + output.name, dir=output.parent))
    try:
        (temporary / "engine").mkdir()
        target = temporary / "engine" / "RasUnsteady"
        shutil.copy2(executable, target)
        target.chmod(0o755)
        _copy_tree(libraries_source, temporary / "engine" / "libs")
        _copy_tree(notices_source, temporary / "notices")
        artifacts = [{"path": p.relative_to(temporary).as_posix(),
                      "size_bytes": p.stat().st_size, "sha256": _hash(p)}
                     for p in sorted(temporary.rglob("*")) if p.is_file()]
        manifest = {"schema": "ras-commander-native-runtime/v1", "kind": "native",
                    "hec_ras_version": hec_ras_version,
                    "native": {"engine_directory": "engine"}, "artifacts": artifacts}
        (temporary / "runtime.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        temporary.rename(output)
    except Exception:
        shutil.rmtree(temporary)
        raise
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-source", type=Path, required=True)
    parser.add_argument("--libraries-source", type=Path, required=True)
    parser.add_argument("--notices-source", type=Path, required=True)
    parser.add_argument("--hec-ras-version", choices=("6.5", "6.6", "7.0.1"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    print(bundle_runtime(**vars(parser.parse_args())))


if __name__ == "__main__":
    main()
