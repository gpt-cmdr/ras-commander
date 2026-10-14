#!/usr/bin/env python3
"""Export a native HEC-RAS engine into a clean external Docker build context.

Run on Linux to preserve executable permissions. Obtain the runtime and notices
from the official distribution; this script neither downloads nor modifies it.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

# Releases with a HEC native Linux engine: 5.0.7 (bin_ras layout) and 6.1-7.x.
_NATIVE_VERSION = re.compile(r"(?:5\.0\.7|6\.(?:[1-9])(?:\.[0-9]+)?|7\.[0-9]+(?:\.[0-9]+)?)\Z")
_LAYOUT_EXECUTABLE = {"canonical": "RasUnsteady", "bin_ras": "rasUnsteady64"}


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


def bundle_runtime(*, engine_source, libraries_source, notices_source, hec_ras_version, output,
                   layout=None):
    """Bundle one native engine. ``layout`` is ``canonical`` (6.1-7.x: RasUnsteady
    plus a ``libs`` tree) or ``bin_ras`` (5.0.7: ``rasUnsteady64`` with its
    libraries beside it, staged as ``engine/bin_ras``); default from the version."""
    if not _NATIVE_VERSION.fullmatch(str(hec_ras_version)):
        raise ValueError("Native HEC-RAS engines exist for 5.0.7 and 6.1 through 7.x")
    layout = layout or ("bin_ras" if hec_ras_version == "5.0.7" else "canonical")
    if layout not in _LAYOUT_EXECUTABLE or (layout == "bin_ras") != (hec_ras_version == "5.0.7"):
        raise ValueError("layout must be bin_ras for 5.0.7 and canonical otherwise")
    engine_source = Path(engine_source).resolve(strict=True)
    executable = engine_source / _LAYOUT_EXECUTABLE[layout]
    if not executable.is_file() or executable.stat().st_size == 0:
        raise ValueError(f"engine-source must contain the native {executable.name} executable")
    with executable.open("rb") as stream:
        header = stream.read(20)
    if header[:5] != b"\x7fELF\x02" or header[18:20] != b"\x3e\x00":
        raise ValueError(f"{executable.name} must be a 64-bit Linux x86-64 ELF executable")
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
        if layout == "bin_ras":
            # 5.0.7 keeps its libraries beside the binary (HEC's bin_ras folder).
            _copy_tree(libraries_source, temporary / "engine" / "bin_ras")
            target = temporary / "engine" / "bin_ras" / executable.name
            shutil.copy2(executable, target)
            target.chmod(0o755)
            gfortran = temporary / "engine" / "bin_ras" / "libgfortran.so"
            alias = gfortran.with_name("libgfortran.so.3")
            # The binary links libgfortran.so.3; HEC ships the same library unversioned.
            if gfortran.is_file() and not alias.exists() and b"libgfortran.so.3" in gfortran.read_bytes():
                os.symlink(gfortran.name, alias)
        else:
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
                    "native": {"engine_directory": "engine", "layout": layout,
                               "executable": target.relative_to(temporary / "engine").as_posix()},
                    "artifacts": artifacts}
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
    parser.add_argument("--hec-ras-version", required=True,
                        help="5.0.7 or 6.1 through 7.x (the HEC Linux engine release)")
    parser.add_argument("--layout", choices=sorted(_LAYOUT_EXECUTABLE),
                        help="default: bin_ras for 5.0.7, canonical otherwise")
    parser.add_argument("--output", type=Path, required=True)
    print(bundle_runtime(**vars(parser.parse_args())))


if __name__ == "__main__":
    main()
