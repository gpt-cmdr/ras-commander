"""A failed native write removes only a DSS file that the write itself created.

``_native_write_target`` checks whether the target exists before the write; another
process can create the file before ``ras_commander_fast_dss.create`` runs. The
engine's exclusive create then refuses with ``FileExistsError``, and the rollback
must leave the other writer's file and record in place (review finding P1 on PR
#794). The race is injected at the engine's ``create`` boundary with real DSS I/O.
The time-series, paired-data and grid writers share the helper; each is checked.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

dc = pytest.importorskip("ras_commander_fast_dss")

from ras_commander import RasDss  # noqa: E402
from ras_commander.dss import _backend  # noqa: E402

if not _backend.native_writes_available():  # pragma: no cover - depends on the wheel
    pytest.skip("installed ras-commander-fast-dss has no writers", allow_module_level=True)

OTHER = "/OTHER/OWNER/FLOW//1HOUR/KEEP/"
OTHER_DATED = "/OTHER/OWNER/FLOW/01JAN2020/1HOUR/KEEP/"
HOURS = pd.date_range("2020-01-01", periods=2, freq="h")


def _write_timeseries(target):
    RasDss.write_timeseries(target, "/A/B/FLOW//1HOUR/F/", HOURS, [1.0, 2.0])


def _write_paired_data(target):
    RasDss.write_paired_data(target, "/B/L/STAGE-DAMAGE///R/", [1.0, 2.0, 3.0], [10.0, 20.0, 30.0],
                             x_units="FEET", y_units="$", x_type="LINEAR", y_type="LINEAR")


def _write_grid(target):
    RasDss.write_grid_timeseries(
        target, "/SHG/B/PRECIP///F/", np.ones((1, 3, 4), dtype=np.float32), HOURS,
        {"cellsize": 2000, "origin": (0, 0), "crs": "SHG", "data_type": "PER-CUM"},
    )


WRITERS = {"timeseries": _write_timeseries, "paired_data": _write_paired_data, "grid": _write_grid}


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setattr(RasDss, "backend", "native")
    monkeypatch.delenv(_backend.ENV_VAR, raising=False)


@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_refused_create_keeps_a_competing_writers_file(native, tmp_path, monkeypatch, writer):
    target = tmp_path / "race_target.dss"
    original = dc.create
    sizes = []

    def racing_create(path, version=7):
        # Another process creates and fills the file between the preflight check and
        # this call; then the requested exclusive create runs and must refuse.
        original(path, version)
        dc.write_timeseries(path, OTHER, [99.0, 100.0], times=HOURS.to_numpy(),
                            version=version, units="CFS", data_type="INST-VAL")
        sizes.append(target.stat().st_size)
        return original(path, version)

    monkeypatch.setattr(dc, "create", racing_create)
    with pytest.raises(FileExistsError):
        WRITERS[writer](target)
    monkeypatch.setattr(dc, "create", original)

    assert sizes and target.exists()
    assert target.stat().st_size == sizes[0]
    frame = RasDss.read_timeseries(target, OTHER_DATED)
    np.testing.assert_array_equal(frame["value"].to_numpy(), [99.0, 100.0])


@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_failed_write_removes_the_file_it_created(native, tmp_path, monkeypatch, writer):
    target = tmp_path / "sub" / "owned.dss"
    failing = {"timeseries": "write_timeseries", "paired_data": "write_paired_data",
               "grid": "write_grid"}[writer]

    def boom(*args, **kwargs):
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(dc, failing, boom)
    with pytest.raises(RuntimeError, match="simulated write failure"):
        WRITERS[writer](target)
    assert not target.exists()
    assert not target.parent.exists()  # the parent made for it is removed too
