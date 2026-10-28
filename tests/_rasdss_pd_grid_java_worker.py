"""Run RasDss paired-data, grid and file-version requests on Java in an isolated process.

Used by ``test_rasdss_paired_grid_version.py``. The JVM starts only once per process
and HEC software can modify files it opens, so Java runs here, on working copies.

argv: requests.json out.pkl
Each request is a dict with ``op`` and arguments; results are returned in order.
Exceptions are returned as picklable summaries (the typed classes are created at
run time and do not pickle). Exit code 77 with ``P18_BRIDGE_UNAVAILABLE:`` on stdout
means pyjnius, Java or Monolith is unavailable.
"""

import json
import os
import pickle
import sys
from pathlib import Path

os.environ.pop("RAS_COMMANDER_DSS_BACKEND", None)

import numpy as np  # noqa: E402

from ras_commander import RasDss  # noqa: E402
from ras_commander.dss import _backend  # noqa: E402


def _error(exc):
    return {
        "error": type(exc).__name__,
        "message": str(exc)[:500],
        "is_value_error": isinstance(exc, ValueError),
        "is_type_error": isinstance(exc, TypeError),
        "is_runtime_error": isinstance(exc, RuntimeError),
        "is_not_implemented": isinstance(exc, NotImplementedError),
        "mro": [c.__name__ for c in type(exc).__mro__],
    }


def write_paired_data(dss_file, version, records):
    """Author paired-data records with HEC Monolith (test fixtures only)."""
    from jnius import autoclass, cast

    path = Path(dss_file)
    RasDss._create_empty_dss(path, int(version))
    HecDss = autoclass("hec.heclib.dss.HecDss")
    PairedDataContainer = autoclass("hec.io.PairedDataContainer")
    dss = HecDss.open(str(path))
    try:
        for rec in records:
            pdc = PairedDataContainer()
            pdc.setFullName(rec["pathname"])
            x = [float(v) for v in rec["x"]]
            y = [[float(v) for v in curve] for curve in rec["y"]]
            pdc.setValues(x, y)
            pdc.setXUnits(rec["x_units"])
            pdc.setYUnits(rec["y_units"])
            pdc.setXType(rec["x_type"])
            pdc.setYType(rec["y_type"])
            if rec.get("labels"):
                pdc.setLabels(list(rec["labels"]))
            pdc.setStoreAsDoubles(bool(rec.get("doubles", False)))
            # put() is overloaded (DataContainer, DataContainerTransformer).
            dss.put(cast("hec.io.DataContainer", pdc))
    finally:
        dss.done()
    return str(path)


def run(req):
    op = req["op"]
    if op == "write_pd":
        return write_paired_data(req["dss_file"], req["version"], req["records"])
    if op == "pd":
        return RasDss.read_paired_data(
            req["dss_file"], req["pathname"],
            ignore_d_part=req.get("ignore_d_part", True), dtype=req.get("dtype", "stored"),
        )
    if op == "grid":
        return RasDss.read_grid(req["dss_file"], req["pathname"])
    if op == "version":
        return RasDss.get_file_version(req["dss_file"])
    if op == "catalog_types":
        import dss_commander as dc

        with dc.open(req["dss_file"]) as handle:
            cat = handle.catalog()
        return list(zip(cat["pathname"].tolist(), [int(t) for t in cat["record_type"]]))
    if op in ("shadow_pd", "shadow_grid", "shadow_version"):
        RasDss.backend = "shadow"
        _backend.reset_shadow_stats()
        try:
            if op == "shadow_pd":
                value = RasDss.read_paired_data(req["dss_file"], req["pathname"])
            elif op == "shadow_grid":
                value = RasDss.read_grid(
                    req["dss_file"], req["pathname"],
                    allow_unqualified_native=req.get("allow_unqualified_native", False),
                )
            else:
                value = RasDss.get_file_version(req["dss_file"])
        except Exception as exc:  # noqa: BLE001
            value = _error(exc)
        finally:
            RasDss.backend = "java"
        return {"value": value, "records": list(_backend.SHADOW_RECORDS)}
    raise ValueError(f"unknown op {op}")


def main():
    requests = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        RasDss._configure_jvm()
        from jnius import autoclass

        autoclass("hec.heclib.dss.HecDss")
    except Exception as exc:  # noqa: BLE001
        print(f"P18_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
        sys.exit(77)
    results = []
    for req in requests:
        try:
            results.append(run(req))
        except Exception as exc:  # noqa: BLE001
            results.append(_error(exc))
    with open(sys.argv[2], "wb") as fh:
        pickle.dump(results, fh)
    np.seterr(all="ignore")


if __name__ == "__main__":
    main()
