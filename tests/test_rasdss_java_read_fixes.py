"""Regression tests for RasDss Java-path read fixes.

- Reads never create a missing DSS file (HecDss.open creates one).
- A pathname with no data raises ValueError, not an accidental TypeError.
- Non-time-series records (paired data) raise TypeError before field access.
- Times honour TimeSeriesContainer.julianBaseDate and the time granularity,
  so sub-minute and base-dated records get correct stamps and interval.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import types

import pytest

from ras_commander import RasDss


def _tsc(interval, granularity=None):
    fake = types.SimpleNamespace(interval=interval)
    if granularity is not None:
        fake.getTimeGranularitySeconds = lambda: granularity
    return fake


def test_interval_minutes_for_minute_granularity() -> None:
    tsc = _tsc(60, 60)
    assert RasDss._tsc_interval_minutes(tsc, RasDss._tsc_granularity_seconds(tsc)) == 60


def test_interval_minutes_for_second_granularity() -> None:
    tsc = _tsc(15, 1)
    assert RasDss._tsc_interval_minutes(tsc, RasDss._tsc_granularity_seconds(tsc)) == 0.25
    tsc = _tsc(3, 1)
    assert RasDss._tsc_interval_minutes(tsc, RasDss._tsc_granularity_seconds(tsc)) == 0.05


def test_interval_minutes_irregular_and_whole_minutes_from_seconds() -> None:
    assert RasDss._tsc_interval_minutes(_tsc(0, 1), 1) == 0
    assert RasDss._tsc_interval_minutes(_tsc(3600, 1), 1) == 60


def test_granularity_defaults_to_minutes() -> None:
    assert RasDss._tsc_granularity_seconds(types.SimpleNamespace()) == 60
    assert RasDss._tsc_granularity_seconds(_tsc(1, 0)) == 60


def test_require_existing_dss_file_does_not_create(tmp_path) -> None:
    missing = tmp_path / "missing.dss"
    with pytest.raises(FileNotFoundError):
        RasDss._require_existing_dss_file(missing)
    assert not missing.exists()
    with pytest.raises(IsADirectoryError):
        RasDss._require_existing_dss_file(tmp_path)


@pytest.mark.integration
def test_java_read_fixes_on_rasexamples(tmp_path) -> None:
    script = textwrap.dedent(
        """
        import os
        import shutil
        import sys
        from pathlib import Path

        # These checks cover the Java read path whatever backend the caller selected.
        os.environ.pop("RAS_COMMANDER_DSS_BACKEND", None)

        import numpy as np
        import pandas as pd

        from ras_commander import RasDss, RasExamples

        if hasattr(RasDss, "backend"):
            RasDss.backend = "java"

        try:
            RasDss._configure_jvm()
        except Exception as exc:
            print(f"JAVA_READ_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
            raise SystemExit(77)

        work = Path(sys.argv[1])
        try:
            muncie_dir = RasExamples.extract_project("Muncie", output_path=work / "ex")
            davis_dir = RasExamples.extract_project("Davis", output_path=work / "ex")
        except Exception as exc:
            print(f"JAVA_READ_BRIDGE_UNAVAILABLE:examples:{type(exc).__name__}:{exc}")
            raise SystemExit(77)
        muncie = next(Path(muncie_dir).glob("*.dss"))
        davis = next(Path(davis_dir).glob("*.dss"))

        # 1. A read never creates a missing file.
        missing = work / "missing.dss"
        for call in (lambda: RasDss.get_catalog(missing),
                     lambda: RasDss.read_timeseries(missing, "/A/B/FLOW//1HOUR/F/")):
            try:
                call()
                raise AssertionError("expected FileNotFoundError")
            except FileNotFoundError:
                pass
        assert not missing.exists()

        # 2. A pathname with no data raises ValueError.
        try:
            RasDss.read_timeseries(muncie, "/NO/SUCH/FLOW//1HOUR/NONE/")
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert "No data found" in str(exc)

        # 3. Paired data raises TypeError instead of a misread container.
        catalog = RasDss.get_catalog(muncie)
        pd_paths = [p for p in catalog["pathname"] if "/LOCATION-ELEV/" in p.upper()
                    or p.split("/")[5] == ""]
        if pd_paths:
            try:
                RasDss.read_timeseries(muncie, pd_paths[0])
                raise AssertionError("expected TypeError")
            except TypeError:
                pass

        # 4. 3-second data: stamps from julianBaseDate and second granularity.
        cat = RasDss.get_catalog(davis)
        sub = [p for p in cat["pathname"] if p.split("/")[5].upper() == "3SECOND"]
        assert sub, "Davis should contain 3Second records"
        df = RasDss.read_timeseries(davis, sub[0])
        block_day = pd.Timestamp(sub[0].split("/")[4])
        assert df.index[0].normalize() == block_day, (df.index[0], block_day)
        stamps = df.index.to_numpy(dtype="datetime64[s]").astype(np.int64)
        steps = np.diff(stamps)
        assert set(steps.tolist()) == {3}, set(steps.tolist())
        assert df.attrs["interval"] == 0.05
        print("JAVA_READ_FIXES_OK")
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 77 and "JAVA_READ_BRIDGE_UNAVAILABLE:" in completed.stdout:
        pytest.skip(completed.stdout.strip().splitlines()[-1])

    diagnostic = (completed.stdout + completed.stderr).casefold()
    assert "access violation" not in diagnostic
    assert completed.returncode == 0, completed.stdout[-3000:] + completed.stderr[-3000:]
    assert "JAVA_READ_FIXES_OK" in completed.stdout
