"""Run RasDss write and read requests on the Java (or shadow) backend in a separate process.

Used by ``test_rasdss_native_writes.py``. The JVM can start only once per process, so
the Java side of the native-write tests runs here and the test compares in-process.

argv: requests.pkl out.pkl
Each request is ``{"op": name, "kwargs": {...}}``. ``op`` is a ``RasDss`` method name,
or one of ``set_backend`` (``value``), ``reset_shadow`` and ``shadow_records``.
Exit code 77 with ``R1_BRIDGE_UNAVAILABLE:`` on stdout means pyjnius, Java or Monolith
is unavailable.
"""

import os
import pickle
import sys

os.environ.pop("RAS_COMMANDER_DSS_BACKEND", None)

from ras_commander import RasDss  # noqa: E402
from ras_commander.dss import _backend  # noqa: E402


def run(req):
    op, kwargs = req["op"], req.get("kwargs", {})
    if op == "set_backend":
        RasDss.backend = kwargs["value"]
        return RasDss.get_backend()
    if op == "reset_shadow":
        _backend.reset_shadow_stats()
        return None
    if op == "shadow_records":
        return list(_backend.SHADOW_RECORDS)
    return getattr(RasDss, op)(**kwargs)


def main():
    req_path, out_path = sys.argv[1:3]
    try:
        RasDss._configure_jvm()
        import jnius  # noqa: F401  (starts the JVM)
    except Exception as exc:  # noqa: BLE001
        print(f"R1_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
        raise SystemExit(77)
    with open(req_path, "rb") as fh:
        requests = pickle.load(fh)
    results = []
    for req in requests:
        try:
            results.append({"result": run(req)})
        except Exception as exc:  # noqa: BLE001
            results.append({"error": (type(exc).__name__, str(exc)[:500])})
    with open(out_path, "wb") as fh:
        pickle.dump(results, fh)


if __name__ == "__main__":
    main()
