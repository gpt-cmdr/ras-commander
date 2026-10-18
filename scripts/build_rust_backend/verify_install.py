"""Install a built wheel into clean environments and run distribution tests.

Creates two uv environments under ``--work-dir`` (outside the source tree):

* ``env-native``: ras-commander (non-editable, from the source checkout) plus
  the wheel named in the build receipt;
* ``env-python``: ras-commander only, proving the extension is optional.

Each runs ``tests/rust_distribution`` from an empty working directory with
JUnit XML output, and the receipt gains install timings and footprints.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEST_DEPS = ["pytest==8.4.2", "geopandas", "pyarrow>=14", "pyproj>=3.6", "shapely>=2.1", "h5py"]


def run(command, *, cwd=None, env=None, log=None, check=True):
    started = time.perf_counter()
    with open(log, "w", encoding="utf-8") as handle:
        handle.write("$ " + subprocess.list2cmdline(map(str, command)) + "\n")
        handle.flush()
        code = subprocess.run(list(map(str, command)), cwd=cwd, env=env,
                              stdout=handle, stderr=subprocess.STDOUT).returncode
    if check and code:
        raise SystemExit(f"Command failed ({code}); see {log}")
    return code, round(time.perf_counter() - started, 2)


def tree_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def python_of(env: Path) -> Path:
    return env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work-dir", type=Path, required=True, help="build_wheel.py work dir")
    parser.add_argument("--python", default="3.12", help="uv Python request for the clean envs")
    parser.add_argument("--fixtures", type=Path, help="Local copies of computed HDF fixtures")
    args = parser.parse_args(argv)
    work = args.work_dir.resolve()
    receipt_path = work / "build-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    source = Path(receipt["source"]["root"])
    wheel = work / "wheels" / receipt["wheel"]["file"]
    tests = source / "tests" / "rust_distribution"
    logs, evidence = work / "logs", work / "evidence"
    evidence.mkdir(exist_ok=True)
    results = {}
    for name, packages in (("env-python", [str(source)]),
                           ("env-native", [str(source), str(wheel)])):
        env_dir = work / name
        if env_dir.exists():
            raise SystemExit(f"{env_dir} exists; choose a fresh work dir for clean installs")
        run(["uv", "venv", "--python", args.python, env_dir], log=logs / f"{name}-venv.log")
        py = python_of(env_dir)
        _, base_seconds = run(["uv", "pip", "install", "--python", py, *packages],
                              cwd=work, log=logs / f"{name}-install.log")
        site = Path(subprocess.check_output(
            [py, "-c", "import sysconfig;print(sysconfig.get_paths()['purelib'])"], text=True).strip())
        footprint = tree_bytes(site)
        run(["uv", "pip", "install", "--python", py, *TEST_DEPS], cwd=work,
            log=logs / f"{name}-test-deps.log")
        cwd = work / f"{name}-cwd"
        cwd.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("RAS_DIST_", "PYTHONPATH"))}
        env["RAS_DIST_RECEIPT" if name == "env-native" else "RAS_DIST_EXPECT_NO_EXTENSION"] = (
            str(receipt_path) if name == "env-native" else "1")
        if args.fixtures:
            env["RAS_DIST_FIXTURES"] = str(args.fixtures.resolve())
        xml = evidence / f"{name}-tests.xml"
        files = ["test_installed_wheel.py"] if name == "env-native" else ["test_without_extension.py"]
        code, seconds = run([py, "-I", "-m", "pytest", *[tests / f for f in files], "-q", "-rs",
                             "-p", "no:cacheprovider", f"--rootdir={tests}", f"--confcutdir={tests}",
                             f"--junitxml={xml}"], cwd=cwd, env=env,
                            log=logs / f"{name}-pytest.log", check=False)
        versions = json.loads(subprocess.check_output([py, "-I", "-c", (
            "import json,sys,numpy,importlib.metadata as m;"
            "print(json.dumps({'python':sys.version.split()[0],'numpy':numpy.__version__,"
            "'ras_commander':m.version('ras-commander')}))")], text=True))
        results[name] = {"install_seconds": base_seconds, "site_packages_bytes_before_test_deps": footprint,
                         "pytest_exit_code": code, "pytest_seconds": seconds,
                         "junit_xml": xml.as_posix(), "versions": versions}
    receipt["install"] = results
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    return max(r["pytest_exit_code"] for r in results.values())


if __name__ == "__main__":
    raise SystemExit(main())
