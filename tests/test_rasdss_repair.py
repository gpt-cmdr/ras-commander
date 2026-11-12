"""``RasDss.repair``: the DSS7 copy-out recovery from ras-commander-fast-dss (0.1.1 and later).

The wrapper always runs on the native engine, whatever ``RasDss.backend`` is, and
returns the engine's result unchanged. These tests write a small DSS7 file with the
native writer, repair a clean copy and a deliberately damaged copy, and check the
gating. No JVM is started. Skips without ras_commander_fast_dss or its ``repair``.
"""

from __future__ import annotations

import hashlib
import logging

import numpy as np
import pandas as pd
import pytest

dc = pytest.importorskip("ras_commander_fast_dss")

from ras_commander import RasDss  # noqa: E402
from ras_commander.dss import _backend, _errors  # noqa: E402

if not _backend.native_repair_available():  # pragma: no cover - depends on the wheel
    pytest.skip("installed ras-commander-fast-dss has no repair", allow_module_level=True)

TIMES = pd.date_range("2020-01-01", periods=24, freq="h")
PATHNAMES = [f"/A/B{i}/FLOW//1HOUR/F/" for i in range(5)]


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def dss7(tmp_path, monkeypatch):
    monkeypatch.setattr(RasDss, "backend", "native")
    monkeypatch.delenv(_backend.ENV_VAR, raising=False)
    src = tmp_path / "source.dss"
    for i, pathname in enumerate(PATHNAMES):
        RasDss.write_timeseries(src, pathname, TIMES, np.arange(24.0) * (i + 1))
    assert RasDss.get_file_version(src) == 7
    return src


@pytest.mark.parametrize("backend", ["java", "native", "shadow"])
def test_repair_copies_a_clean_file_on_every_backend(dss7, tmp_path, monkeypatch, backend):
    monkeypatch.setattr(RasDss, "backend", backend)
    before = _digest(dss7)
    dest = tmp_path / f"recovered_{backend}.dss"
    result = RasDss.repair(dss7, dest)
    assert result["complete"] is True
    assert result["not_copied"] == []
    assert result["src_interrupted_write"] is False
    assert result["records_copied"] == result["src_listed_records"] > 0
    assert _digest(dss7) == before  # src is opened read-only
    monkeypatch.setattr(RasDss, "backend", "native")
    for i, pathname in enumerate(PATHNAMES):
        dated = pathname.replace("//1HOUR", "/01JAN2020/1HOUR")
        df = RasDss.read_timeseries(dest, dated)
        np.testing.assert_array_equal(df["value"].to_numpy(), np.arange(24.0) * (i + 1))


def test_repair_publishes_a_partial_recovery_and_warns(dss7, tmp_path, caplog):
    raw = bytearray(dss7.read_bytes())
    for j in range(int(len(raw) * 0.55), int(len(raw) * 0.65)):
        raw[j] ^= 0xFF
    damaged = tmp_path / "damaged.dss"
    damaged.write_bytes(raw)
    before = _digest(damaged)
    dest = tmp_path / "partial.dss"
    with caplog.at_level(logging.WARNING, logger="ras_commander.dss.RasDss"):
        result = RasDss.repair(damaged, dest)
    assert result["complete"] is False
    assert result["not_copied"]
    assert dest.exists()
    assert _digest(damaged) == before
    assert any(o[3] == "not_copied" for o in result["ledger"])
    assert "incomplete" in caplog.text


def test_repair_never_replaces_dest(dss7, tmp_path):
    dest = tmp_path / "exists.dss"
    dest.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        RasDss.repair(dss7, dest)
    assert dest.read_bytes() == b"keep"


def test_repair_requires_an_existing_source(tmp_path):
    with pytest.raises(FileNotFoundError):
        RasDss.repair(tmp_path / "missing.dss", tmp_path / "out.dss")
    assert not (tmp_path / "out.dss").exists()


def test_repair_is_gated_on_the_engine_feature(dss7, tmp_path, monkeypatch):
    monkeypatch.setattr(dc, "FEATURES", frozenset(dc.FEATURES) - {"repair_copy_out"})
    assert _backend.native_repair_available() is False
    assert RasDss.get_capabilities().attrs["native_repair_available"] is False
    with pytest.raises(_errors.get("DssCapabilityError"), match="repair_copy_out"):
        RasDss.repair(dss7, tmp_path / "gated.dss")
    assert not (tmp_path / "gated.dss").exists()
    monkeypatch.undo()
    assert RasDss.get_capabilities().attrs["native_repair_available"] is True
