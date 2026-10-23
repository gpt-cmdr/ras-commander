"""Native typed read of ``Geometry/Cross Sections/Attributes`` without packed cut lines.

Several HEC-RAS 6.x plan HDFs keep the cross-section Attributes table (the steady
identity Python falls back to) but no ``Polyline Info/Parts/Points``. The engine's
line family is then unavailable ("packed line datasets absent"), so the table is
served from the engine's XS geometry inventory (the same exact stored compound).
"""

import h5py
import numpy as np
import pytest

from ras_commander import _fast_hdf_typed as typed
from ras_commander import fast_hdf

ATTRS = "Geometry/Cross Sections/Attributes"
DTYPE = np.dtype([("River", "S16"), ("Reach", "S16"), ("RS", "S8"), ("Len Channel", "<f4")])
ROWS = [(b"River A", b"Reach A", b"1000", 125.0), (b"River A", b"Reach A", b"900", 1.0e30)]


def _write(path, *, cut_lines):
    with h5py.File(path, "w") as hdf:
        hdf.create_dataset(ATTRS, data=np.array(ROWS, dtype=DTYPE))
        if cut_lines:
            hdf["Geometry/Cross Sections/Polyline Info"] = np.array([[0, 2, 0, 1], [2, 2, 1, 1]], dtype="i4")
            hdf["Geometry/Cross Sections/Polyline Parts"] = np.array([[0, 2], [0, 2]], dtype="i4")
            hdf["Geometry/Cross Sections/Polyline Points"] = np.array(
                [[0.0, 0.0], [10.0, 0.0], [0.0, 5.0], [10.0, 5.0]])


def test_cut_lines_absent_requires_the_exact_unavailable_reason():
    absent = {"value": None, "capability": {"status": "unavailable", "reason": "packed line datasets absent"}}
    assert typed._cut_lines_absent(absent, "cross_section_cut_lines")
    assert not typed._cut_lines_absent(absent, "river_centerlines")
    for capability in (
        {"status": "unavailable", "reason": "canonical 1D line family absent"},
        {"status": "unsupported", "reason": "packed line datasets absent"},
        {"status": "corrupt", "reason": "invalid packed line Info/Parts/Points shape"},
    ):
        assert not typed._cut_lines_absent({"value": None, "capability": capability},
                                           "cross_section_cut_lines")
    assert not typed._cut_lines_absent(
        {"value": {"attributes": None}, "capability": {"status": "supported", "reason": None}},
        "cross_section_cut_lines")


@pytest.mark.parametrize("cut_lines", [False, True], ids=["without-cut-lines", "with-cut-lines"])
def test_required_native_reads_attributes_exactly(tmp_path, monkeypatch, cut_lines):
    pytest.importorskip("ras_commander_fast_hdf")
    path = tmp_path / "plan.hdf"
    _write(path, cut_lines=cut_lines)
    with h5py.File(path, "r") as hdf:
        expected = hdf[ATTRS][()]
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    fast_hdf.close_sessions()
    typed.clear_cache()
    with h5py.File(path, "r") as hdf, fast_hdf.trace_reads() as trace:
        values = fast_hdf.read_typed(hdf[ATTRS])
    assert values.dtype == expected.dtype
    assert values.tobytes() == expected.tobytes()
    backends = [(r["backend"], r["route"]) for r in trace if r["path"] == "/" + ATTRS]
    assert ("native-typed", "line_family") in backends
    diagnostic = [r for r in trace if r["backend"] == "diagnostic"]
    assert bool(diagnostic) is not cut_lines
