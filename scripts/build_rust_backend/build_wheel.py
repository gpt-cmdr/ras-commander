"""Build the optional ras-commander-fast-hdf wheel from a clean local checkout.

Steps: verify the source checkout, prepare the pinned patched dependency
(``prepare_dependency.py``), run ``maturin build --release --locked`` from the
work directory, where a generated ``.cargo/config.toml`` supplies the
dependency ``[patch]`` override. maturin does not forward ``--config`` to
``cargo metadata``, and Cargo discovers config from the current directory, so
nothing is written to the source checkout and standalone writer manifests run
elsewhere are unaffected. A build receipt records the wheel and inner
extension SHA256, sizes and timings.

The build uses a fresh, caller-chosen ``CARGO_TARGET_DIR``. It never copies a
previously built extension. Nothing is uploaded or published.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from prepare_dependency import PrepareError, prepare, sha256_file  # noqa: E402

DEFAULT_FEATURES = "exports-all,exports-pmtiles"  # extension-module comes from pyproject
MATURIN = "maturin==1.15.0"
NATIVE_SUFFIXES = (".pyd", ".so", ".dylib")


def run(command, *, cwd=None, env=None, log=None) -> float:
    started = time.perf_counter()
    with (open(log, "w", encoding="utf-8") if log else open(os.devnull, "w")) as handle:
        handle.write("$ " + subprocess.list2cmdline(map(str, command)) + "\n")
        handle.flush()
        result = subprocess.run(list(map(str, command)), cwd=cwd, env=env,
                                stdout=handle, stderr=subprocess.STDOUT)
    if result.returncode:
        raise SystemExit(f"Command failed ({result.returncode}); see {log}")
    return time.perf_counter() - started


def git(source: Path, *args) -> str:
    return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()


def source_state(source: Path) -> dict:
    status = git(source, "status", "--porcelain", "--untracked-files=all")
    diff = subprocess.run(["git", "-C", str(source), "diff", "HEAD", "--binary"],
                          capture_output=True, check=True).stdout
    return {
        "root": source.as_posix(),
        "commit": git(source, "rev-parse", "HEAD"),
        "tree": git(source, "rev-parse", "HEAD^{tree}"),
        "dirty_paths": [line[3:] for line in status.splitlines()],
        "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
    }


def inherited_natives(source: Path) -> list[str]:
    """Prebuilt extension binaries in the checkout outside build targets."""
    found = []
    for root in (source / "ras_commander", source / "rust"):
        for path in root.rglob("ras_commander_fast_hdf*"):
            if path.suffix in NATIVE_SUFFIXES and "target" not in path.parts:
                found.append(path.as_posix())
    return found


def inspect_wheel(wheel: Path) -> dict:
    with zipfile.ZipFile(wheel) as archive:
        infos = archive.infolist()
        natives = [i for i in infos if i.filename.endswith(NATIVE_SUFFIXES)]
        if len(natives) != 1:
            raise SystemExit(f"Expected one native module in {wheel.name}, found {len(natives)}")
        native_sha = hashlib.sha256(archive.read(natives[0])).hexdigest()
        return {
            "file": wheel.name,
            "sha256": sha256_file(wheel),
            "bytes": wheel.stat().st_size,
            "unpacked_bytes": sum(i.file_size for i in infos),
            "members": sorted(i.filename for i in infos),
            "native_member": natives[0].filename,
            "native_sha256": native_sha,
            "native_bytes": natives[0].file_size,
        }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work-dir", type=Path, required=True,
                        help="Local directory for dependency, target, wheels and logs")
    parser.add_argument("--source-root", type=Path, default=HERE.parents[1])
    parser.add_argument("--dep-source", help="Git URL or local repo for netcdf-rust")
    parser.add_argument("--python", default=sys.executable, help="Interpreter for maturin -i")
    parser.add_argument("--features", default=DEFAULT_FEATURES)
    parser.add_argument("--maturin", default=MATURIN, help="Exact maturin requirement")
    parser.add_argument("--allow-existing-target", action="store_true",
                        help="Reuse a non-empty CARGO_TARGET_DIR (warm build)")
    args = parser.parse_args(argv)

    source = args.source_root.resolve()
    work = args.work_dir.expanduser().resolve()
    if str(work).startswith(("\\\\", "//")):
        raise SystemExit("Choose a local --work-dir, not a network share")
    work.mkdir(parents=True, exist_ok=True)
    logs, wheels, target = work / "logs", work / "wheels", work / "target"
    logs.mkdir(exist_ok=True)
    if target.exists() and any(target.iterdir()) and not args.allow_existing_target:
        raise SystemExit(f"{target} is not empty; remove it or pass --allow-existing-target")
    if wheels.exists():
        shutil.rmtree(wheels)

    state = source_state(source)
    inherited = inherited_natives(source)
    if inherited:
        raise SystemExit(f"Inherited native binaries present in source: {inherited}")
    try:
        dependency = prepare(work / "deps" / "netcdf-rust-patched", args.dep_source)
    except PrepareError as exc:
        raise SystemExit(f"Dependency preparation failed: {exc}")

    config = work / ".cargo" / "config.toml"
    config.parent.mkdir(exist_ok=True)
    config.write_text(dependency["cargo_patch_toml"], encoding="utf-8")
    env = dict(os.environ, CARGO_TARGET_DIR=str(target))
    manifest = source / "rust" / "fast-hdf" / "Cargo.toml"
    command = ["uv", "tool", "run", "--from", args.maturin, "maturin", "build",
               "--release", "--locked", "--manifest-path", manifest,
               "--features", args.features, "--interpreter", args.python,
               "--out", wheels]
    seconds = run(command, cwd=work, env=env, log=logs / "maturin-build.log")
    built = sorted(wheels.glob("*.whl"))
    if len(built) != 1:
        raise SystemExit(f"Expected one wheel, found {[w.name for w in built]}")

    versions = {}
    for tool in ("rustc", "cargo"):
        versions[tool] = subprocess.check_output([tool, "-V"], text=True).strip()
    versions["maturin"] = args.maturin
    versions["python"] = subprocess.check_output(
        [args.python, "-c", "import sys;print(sys.version.split()[0])"], text=True).strip()
    receipt = {
        "schema": 1,
        "source": state,
        "inherited_native_binaries": inherited,
        "dependency": dependency,
        "features": "extension-module (pyproject)," + args.features,
        "profile": "release",
        "cargo_config_file": config.as_posix(),
        "cargo_config_sha256": sha256_file(config),
        "cargo_target_dir": target.as_posix(),
        "target_reused": bool(args.allow_existing_target),
        "build_seconds": round(seconds, 2),
        "toolchain": versions,
        "host": {"system": platform.system(), "machine": platform.machine(),
                 "release": platform.release(), "cpu_count": os.cpu_count()},
        "wheel": inspect_wheel(built[0]),
        "command": subprocess.list2cmdline(map(str, command)),
    }
    path = work / "build-receipt.json"
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps({k: receipt[k] for k in ("build_seconds", "features")} |
                     {"wheel": receipt["wheel"]["file"], "receipt": path.as_posix()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
