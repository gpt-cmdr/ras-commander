"""Run RasDss read requests on the Java backend in an isolated process.

Used by ``test_rasdss_native_parity.py``. The JVM can start only once per process and
can crash on some records, so the parity tests run Java here and compare in-process.

argv: requests.json out.pkl
Each request is a dict with ``op`` and arguments. Exit code 77 with
``P09B_BRIDGE_UNAVAILABLE:`` on stdout means pyjnius, Java or Monolith is unavailable.
"""

import json
import os
import pickle
import sys

os.environ.pop("RAS_COMMANDER_DSS_BACKEND", None)

from ras_commander import RasDss  # noqa: E402


def _validation(result):
    """Picklable summary of a ValidationResult/ValidationReport."""
    if hasattr(result, "results"):
        return {
            "is_valid": result.is_valid,
            "results": [_validation(r) for r in result.results],
        }
    return {
        "check_name": getattr(result, "check_name", None),
        "severity": str(getattr(result, "severity", None)),
        "passed": getattr(result, "passed", None),
        "message": getattr(result, "message", None),
        "details": getattr(result, "details", None),
    }


def run(req):
    op = req["op"]
    if op == "catalog":
        return RasDss.get_catalog(req["dss_file"])
    if op == "ts":
        return RasDss.read_timeseries(req["dss_file"], req["pathname"])
    if op == "multiple":
        return RasDss.read_multiple_timeseries(req["dss_file"], req["pathnames"])
    if op == "info":
        return RasDss.get_info(req["dss_file"])
    if op == "check_pathname_exists":
        return _validation(RasDss.check_pathname_exists(req["dss_file"], req["pathname"]))
    if op == "check_data_availability":
        return _validation(RasDss.check_data_availability(req["dss_file"], req["pathname"]))
    if op == "check_pathname":
        return _validation(RasDss.check_pathname(req["dss_file"], req["pathname"]))
    if op == "is_pathname_available":
        return RasDss.is_pathname_available(req["dss_file"], req["pathname"])
    if op == "boundaries":
        import pandas as pd

        boundaries = pd.read_pickle(req["boundaries_pickle"])
        return RasDss.extract_boundary_timeseries(boundaries, project_dir=req["project_dir"])
    raise ValueError(f"unknown op {op}")


def main():
    req_path, out_path = sys.argv[1:3]
    try:
        RasDss._configure_jvm()
        import jnius  # noqa: F401  (starts the JVM)
    except Exception as exc:  # noqa: BLE001
        print(f"P09B_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
        raise SystemExit(77)
    requests = json.load(open(req_path, encoding="utf-8"))
    results = []
    for req in requests:
        try:
            results.append({"result": run(req)})
        except Exception as exc:  # noqa: BLE001
            results.append({"error": (type(exc).__name__, str(exc)[:300])})
    with open(out_path, "wb") as fh:
        pickle.dump(results, fh)


if __name__ == "__main__":
    main()
