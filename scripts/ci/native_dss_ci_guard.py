"""CI guards for the native DSS engine job (.github/workflows/native-dss.yml).

``python scripts/ci/native_dss_ci_guard.py engine [--expect-backend NAME]``
    Fails unless ras-commander-fast-dss is installed at 0.1.2 or later (below 0.2),
    imports, advertises the features the wrappers use, and RasDss reports it. With
    --expect-backend, RasDss.get_backend() must also return NAME. ``auto`` (the default
    leg) expects what the automatic default must select: ``native`` when the engine's
    own ``__version__`` is a release of at least 0.1.3, otherwise ``java`` (0.1.2 is
    installable but does not qualify).

``python scripts/ci/native_dss_ci_guard.py junit REPORT.xml [--min-passed N] [--java]``
    Fails unless the pytest JUnit report shows at least N passed tests in total, no
    failures or errors, and every native-engine module in REQUIRED_MODULES ran: it
    has passed tests and none of its tests were skipped. Expected failures
    (``pytest.xfail``, for documented engine gaps) are counted apart, not as skips. A job whose engine is
    missing, or whose native tests all skip, cannot pass this check. With --java,
    the Java-bridge modules in JAVA_MODULES must also have run (shadow leg).
"""

from __future__ import annotations

import argparse
import importlib.metadata
import sys
import xml.etree.ElementTree as ET
from collections import Counter

#: Test modules that exercise only the native engine (they importorskip it). Each must
#: run in the job: some passed, none skipped.
REQUIRED_MODULES = (
    "tests.test_rasdss_wrappers",
    "tests.test_rasdss_fast_dss_012",
    "tests.test_rasdss_repair",
    "tests.test_rasdss_native_write_ownership",
)

#: Modules that compare the native engine with the Java (HEC Monolith) path. Their Java
#: tests skip without a JVM; the shadow leg requires them to run with none skipped.
JAVA_MODULES = (
    "tests.test_rasdss_native_parity",
    "tests.test_rasdss_native_writes",
    "tests.test_rasdss_native_default",
    "tests.test_rasdss_write_times",
)

#: Skip reasons that are intended on some platforms and do not make a required module
#: count as skipped (matched as substrings of the JUnit skip message).
ALLOWED_SKIP_REASONS = (
    "the held handle blocks os.replace on Windows",
)

FEATURES = ("write_sync_modes", "dssfile_held_handle", "repair_copy_out", "gridded_import",
            "grid_tools", "grid_to_point", "write_profile", "write_location")


def _version_tuple(text: str):
    return tuple(int(part) for part in text.split(".")[:3])


#: Installed distributions the job accepts: 0.1.2 until 0.1.3 is on PyPI (the job cannot
#: install 0.1.3 yet). Accepting 0.1.2 for installation does not make it qualify for the
#: automatic default: that needs the engine's own __version__ >= 0.1.3 (see --expect-backend).
INSTALLABLE = ((0, 1, 2), (0, 2, 0))


def check_engine(expect_backend=None) -> int:
    version = importlib.metadata.version("ras-commander-fast-dss")
    low, high = INSTALLABLE
    if not low <= _version_tuple(version) < high:
        print(f"ras-commander-fast-dss {version} is outside >=0.1.2,<0.2")
        return 1
    import ras_commander_fast_dss as engine
    from ras_commander import RasDss
    from ras_commander.dss import _backend

    missing = [name for name in FEATURES if name not in engine.FEATURES]
    if missing:
        print(f"engine FEATURES lack {missing}")
        return 1
    attrs = RasDss.get_capabilities().attrs
    if not (attrs["native_installed"] and attrs["native_writes_available"]):
        print(f"RasDss does not see the engine: {attrs}")
        return 1
    backend = RasDss.get_backend()
    release, release_text = _backend.engine_release(engine)
    qualifies = release is not None and release >= _backend.MIN_DEFAULT_ENGINE_VERSION
    print(f"ras-commander-fast-dss {version}; {len(engine.FEATURES)} features; "
          f"{release_text}; qualifies for the automatic default: {qualifies}; "
          f"RasDss backend {backend} ({attrs['backend_source']}: "
          f"{attrs['default_backend_reason']})")
    if expect_backend == "auto":
        # The automatic default: native only with an engine release >= 0.1.3.
        expect_backend = "native" if qualifies else "java"
        if attrs["backend_source"] != "auto":
            print(f"--expect-backend auto needs no backend override; got {attrs}")
            return 1
    if expect_backend and backend != expect_backend:
        print(f"RasDss backend is {backend!r}, expected {expect_backend!r}")
        return 1
    return 0


def check_junit(path: str, min_passed: int, java: bool) -> int:
    root = ET.parse(path).getroot()
    outcome = Counter()
    per_module: dict = {}
    for case in root.iter("testcase"):
        classname = case.get("classname") or ""
        # pytest classnames are "tests.test_x" or "tests.test_x.TestClass".
        parts = classname.split(".")
        module = ".".join(parts[:2]) if len(parts) >= 2 else classname
        skipped = case.find("skipped")
        if case.find("failure") is not None or case.find("error") is not None:
            state = "failed"
        elif skipped is not None and skipped.get("type") == "pytest.xfail":
            # A declared expected failure (a documented engine gap), not a skipped test.
            state = "xfailed"
        elif skipped is not None:
            reason = (skipped.get("message") or "") + (skipped.text or "")
            state = "platform_skip" if any(r in reason for r in ALLOWED_SKIP_REASONS) else "skipped"
        else:
            state = "passed"
        outcome[state] += 1
        per_module.setdefault(module, Counter())[state] += 1
    print(f"JUnit totals: {dict(outcome)}")
    problems = []
    if outcome["failed"]:
        problems.append(f"{outcome['failed']} failed or errored")
    if outcome["passed"] < min_passed:
        problems.append(f"only {outcome['passed']} passed (minimum {min_passed})")
    required = REQUIRED_MODULES + (JAVA_MODULES if java else ())
    for module in required:
        counts = per_module.get(module, Counter())
        print(f"  {module}: {dict(counts)}")
        if counts["passed"] == 0:
            problems.append(f"{module} ran no passing test")
        if counts["skipped"]:
            problems.append(f"{module} skipped {counts['skipped']} test(s)")
    if problems:
        print("Native DSS job check FAILED: " + "; ".join(problems))
        return 1
    print("Native DSS job check passed")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    engine = sub.add_parser("engine")
    engine.add_argument("--expect-backend", choices=("auto", "java", "native", "shadow"))
    junit = sub.add_parser("junit")
    junit.add_argument("report")
    junit.add_argument("--min-passed", type=int, default=600)
    junit.add_argument("--java", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "engine":
        return check_engine(args.expect_backend)
    return check_junit(args.report, args.min_passed, args.java)


if __name__ == "__main__":
    sys.exit(main())
