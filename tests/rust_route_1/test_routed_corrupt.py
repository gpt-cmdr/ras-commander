"""PY-ROUTE-1 error, missing and corrupt behaviour on damaged *copies* of real fixtures.

The source fixture is copied to pytest's tmp directory and only the copy is
modified. Auto mode must reproduce the h5py result or exception exactly (the
engine refusal falls back to h5py, recorded in the trace); required-native mode
must raise ``FastHdfError`` instead of returning a result.
"""
import json
import os
import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest

from ._exact import assert_identical

MANIFEST = os.environ.get("RAS_ROUTE1_FIXTURES")
FIXTURES = {f["name"]: f["path"] for f in json.loads(Path(MANIFEST).read_text())["fixtures"]} if MANIFEST else {}
pytestmark = pytest.mark.skipif(
    not MANIFEST, reason="Set RAS_ROUTE1_FIXTURES to the PY-ROUTE-1 real-fixture JSON manifest")


def _info_count_overflow(dataset_path):
    def damage(f):
        info = f[dataset_path][()]
        info[0, 1] = np.iinfo(info.dtype).max // 2
        f[dataset_path][...] = info
    return damage


def _delete(dataset_path):
    def damage(f):
        del f[dataset_path]
    return damage


def _cases():
    from ras_commander import hdf
    return [
        ("BaldEagle.g01", "xs_cut_line_count", _info_count_overflow("Geometry/Cross Sections/Polyline Info"),
         lambda p: hdf.HdfXsec.get_cross_sections(p)),
        ("BaldEagle.g01", "station_elevation_count", _info_count_overflow("Geometry/Cross Sections/Station Elevation Info"),
         lambda p: hdf.HdfXsec.get_xs_coords(p)),
        ("BaldEagle.g01", "centerline_parts_missing", _delete("Geometry/River Centerlines/Polyline Parts"),
         lambda p: hdf.HdfXsec.get_river_centerlines(p)),
        ("BaldEagle.p01", "htab_info_count", _info_count_overflow("Geometry/Cross Sections/Property Tables/XSEC Info"),
         lambda p: hdf.HdfHydraulicTables.get_all_xs_htabs(p)),
        ("AustinOyster.p01", "bc_line_count", _info_count_overflow("Geometry/Boundary Condition Lines/Polyline Info"),
         lambda p: hdf.HdfBndry.get_bc_lines(p)),
        ("Baxter.g02", "storage_polygon_count", _info_count_overflow("Geometry/Storage Areas/Polygon Info"),
         lambda p: hdf.HdfStruc.get_storage_area_polygons(p)),
    ]


def _outcome(monkeypatch, mode, call, path):
    from ras_commander import fast_hdf
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    fast_hdf.close_sessions()
    with fast_hdf.trace_reads() as trace:
        try:
            return ("ok", call(path)), list(trace)
        except Exception as exc:
            return ("raise", type(exc), str(exc)), list(trace)


@pytest.mark.parametrize("index", range(6), ids=lambda i: f"case{i}")
def test_damaged_copy(index, tmp_path, monkeypatch):
    pytest.importorskip("ras_commander_fast_hdf")
    from ras_commander import fast_hdf
    name, label, damage, call = _cases()[index]
    if name not in FIXTURES:
        pytest.skip(f"fixture {name} not in manifest")
    source = Path(FIXTURES[name])
    copy = tmp_path / source.name
    shutil.copyfile(source, copy)
    with h5py.File(copy, "r+") as f:
        damage(f)
    py, _ = _outcome(monkeypatch, "0", call, copy)
    auto, auto_trace = _outcome(monkeypatch, "auto", call, copy)
    req, _ = _outcome(monkeypatch, "required", call, copy)
    assert py[0] == auto[0], label
    if py[0] == "ok":
        assert_identical(py[1], auto[1], label)
    else:
        assert py[1] is auto[1] and py[2] == auto[2], label
    assert any(r["backend"] == "h5py-fallback" for r in auto_trace), f"{label}: engine accepted damaged data"
    assert req[0] == "raise" and req[1] is fast_hdf.FastHdfError, f"{label}: required native returned {req[:2]}"
