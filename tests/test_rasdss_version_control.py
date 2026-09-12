"""Coverage for explicit HEC-DSS 6/7 time-series file control."""

from __future__ import annotations

import hashlib
import inspect
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ras_commander import RasDss


def test_dss_version_parameters_are_keyword_only() -> None:
    for method in (
        RasDss.write_timeseries,
        RasDss.write_timeseries_from_dataframe,
        RasDss.write_grid_timeseries,
    ):
        parameter = inspect.signature(method).parameters["dss_version"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is None


@pytest.mark.parametrize("version", [True, False, 6.0, "6", np.int64(6), 5, 8])
def test_write_timeseries_rejects_non_contract_versions_before_jvm(
    monkeypatch,
    tmp_path,
    version,
) -> None:
    monkeypatch.setattr(
        RasDss,
        "_configure_jvm",
        staticmethod(
            lambda: pytest.fail("invalid versions must fail before JVM setup")
        ),
    )

    with pytest.raises(ValueError, match="dss_version"):
        RasDss.write_timeseries(
            tmp_path / "invalid.dss",
            "/BASIN/UPSTREAM/FLOW//5MIN/C03/",
            pd.date_range("2020-01-01", periods=2, freq="5min"),
            [1.0, 2.0],
            dss_version=version,
        )


@pytest.mark.parametrize("version", [True, False, 6.0, "6", np.int64(6), 5, 8])
def test_write_grid_rejects_non_contract_versions_before_jvm(
    monkeypatch,
    tmp_path,
    version,
) -> None:
    monkeypatch.setattr(
        RasDss,
        "_configure_jvm",
        staticmethod(
            lambda: pytest.fail("invalid versions must fail before JVM setup")
        ),
    )

    with pytest.raises(ValueError, match="dss_version"):
        RasDss.write_grid_timeseries(
            tmp_path / "invalid-grid.dss",
            "/SHG/TEST/PRECIP/01JAN2020:0000/01JAN2020:0100/C03/",
            np.ones((1, 1, 1), dtype=np.float32),
            [pd.Timestamp("2020-01-01 01:00")],
            {"cellsize": 2000, "crs": "SHG"},
            dss_version=version,
        )


def test_create_if_missing_false_fails_before_jvm(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        RasDss,
        "_configure_jvm",
        staticmethod(
            lambda: pytest.fail(
                "missing-file validation must precede JVM setup"
            )
        ),
    )
    output = tmp_path / "missing.dss"

    with pytest.raises(FileNotFoundError, match="DSS file not found"):
        RasDss.write_timeseries(
            output,
            "/BASIN/UPSTREAM/FLOW//5MIN/C03/",
            pd.date_range("2020-01-01", periods=2, freq="5min"),
            [1.0, 2.0],
            create_if_missing=False,
        )

    assert not output.exists()


def test_dataframe_writer_forwards_explicit_version(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_write_timeseries(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

    monkeypatch.setattr(
        RasDss,
        "write_timeseries",
        staticmethod(fake_write_timeseries),
    )
    frame = pd.DataFrame(
        {"value": [1.0, 2.0]},
        index=pd.date_range("2020-01-01", periods=2, freq="5min"),
    )

    RasDss.write_timeseries_from_dataframe(
        tmp_path / "frame.dss",
        "/BASIN/UPSTREAM/FLOW//5MIN/C03/",
        frame,
        dss_version=6,
    )

    assert captured["kwargs"]["dss_version"] == 6


def test_get_file_version_validates_missing_path_before_jvm(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        RasDss,
        "_configure_jvm",
        staticmethod(lambda: pytest.fail("path validation must precede JVM setup")),
    )

    with pytest.raises(FileNotFoundError, match="DSS file not found"):
        RasDss.get_file_version(tmp_path / "missing.dss")


@pytest.mark.parametrize(("reported", "expected"), [(6, 6), (7, 7), (0, None)])
def test_get_file_version_uses_authoritative_java_result(
    monkeypatch,
    tmp_path,
    reported: int,
    expected: int | None,
) -> None:
    from ras_commander.RasUtils import RasUtils

    dss_file = tmp_path / "existing.dss"
    dss_file.write_bytes(b"fixture")

    class FakeHecDataManager:
        @staticmethod
        def getDssFileVersion(_path):
            return reported

    monkeypatch.setattr(RasDss, "_configure_jvm", staticmethod(lambda: None))
    monkeypatch.setattr(RasUtils, "safe_resolve", staticmethod(lambda path: Path(path)))
    monkeypatch.setitem(
        sys.modules,
        "jnius",
        types.SimpleNamespace(
            autoclass=lambda name: (
                FakeHecDataManager
                if name == "hec.heclib.dss.HecDataManager"
                else pytest.fail(f"Unexpected Java class: {name}")
            )
        ),
    )

    if expected is None:
        with pytest.raises(ValueError, match="not a supported HEC-DSS"):
            RasDss.get_file_version(dss_file)
    else:
        assert RasDss.get_file_version(dss_file) == expected


def test_create_empty_dss_fails_closed_when_java_open_returns_none(
    monkeypatch,
    tmp_path,
) -> None:
    from ras_commander.RasUtils import RasUtils

    class FakeHecDss:
        @staticmethod
        def open(_path, _version):
            return None

    output = tmp_path / "not-created.dss"
    monkeypatch.setattr(RasDss, "_configure_jvm", staticmethod(lambda: None))
    monkeypatch.setattr(RasUtils, "safe_resolve", staticmethod(lambda path: Path(path)))
    monkeypatch.setitem(
        sys.modules,
        "jnius",
        types.SimpleNamespace(
            autoclass=lambda name: (
                FakeHecDss
                if name == "hec.heclib.dss.HecDss"
                else pytest.fail(f"Unexpected Java class: {name}")
            )
        ),
    )

    with pytest.raises(RuntimeError, match="did not create version 6"):
        RasDss._create_empty_dss(output, 6)

    assert not output.exists()


def test_existing_version_mismatch_fails_before_writer_open(
    monkeypatch,
    tmp_path,
) -> None:
    dss_file = tmp_path / "existing-v6.dss"
    original = b"existing DSS content"
    dss_file.write_bytes(original)
    monkeypatch.setattr(
        RasDss,
        "get_file_version",
        staticmethod(lambda _path: 6),
    )
    monkeypatch.setattr(
        RasDss,
        "_configure_jvm",
        staticmethod(lambda: pytest.fail("mismatch must fail before writer setup")),
    )

    with pytest.raises(ValueError, match="version 6, not requested version 7"):
        RasDss.write_timeseries(
            dss_file,
            "/BASIN/UPSTREAM/FLOW//5MIN/C03/",
            pd.date_range("2020-01-01", periods=2, freq="5min"),
            [1.0, 2.0],
            dss_version=7,
        )

    assert dss_file.read_bytes() == original


def test_existing_grid_version_mismatch_fails_before_writer_open(
    monkeypatch,
    tmp_path,
) -> None:
    dss_file = tmp_path / "existing-grid-v6.dss"
    original = b"existing DSS content"
    dss_file.write_bytes(original)
    monkeypatch.setattr(
        RasDss,
        "get_file_version",
        staticmethod(lambda _path: 6),
    )
    monkeypatch.setattr(
        RasDss,
        "_configure_jvm",
        staticmethod(lambda: pytest.fail("mismatch must fail before writer setup")),
    )

    with pytest.raises(ValueError, match="version 6, not requested version 7"):
        RasDss.write_grid_timeseries(
            dss_file,
            "/SHG/TEST/PRECIP/01JAN2020:0000/01JAN2020:0100/C03/",
            np.ones((1, 1, 1), dtype=np.float32),
            [pd.Timestamp("2020-01-01 01:00")],
            {"cellsize": 2000, "crs": "SHG"},
            dss_version=7,
        )

    assert dss_file.read_bytes() == original


def _run_bridge_script(script: str, *args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script), *(str(arg) for arg in args)],
        check=False,
        capture_output=True,
        text=True,
    )


def _skip_if_bridge_unavailable(completed: subprocess.CompletedProcess[str]) -> None:
    if completed.returncode == 77 and "C03_BRIDGE_UNAVAILABLE:" in completed.stdout:
        pytest.skip(completed.stdout.strip())


def _assert_clean_native_output(
    completed: subprocess.CompletedProcess[str],
) -> None:
    diagnostic = (completed.stdout + completed.stderr).casefold()
    assert "access violation" not in diagnostic
    assert "fatal exception" not in diagnostic


@pytest.mark.parametrize(
    ("requested", "expected_version"),
    [("default", 7), ("6", 6), ("7", 7)],
)
@pytest.mark.integration
def test_separate_process_creates_requested_dss_version_and_round_trips(
    tmp_path,
    requested: str,
    expected_version: int,
) -> None:
    output = tmp_path / f"created-{requested}.dss"
    script = """
        import sys
        from pathlib import Path

        import numpy as np
        import pandas as pd

        from ras_commander import RasDss

        try:
            RasDss._configure_jvm()
        except Exception as exc:
            print(f"C03_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
            raise SystemExit(77)

        output = Path(sys.argv[1])
        requested = sys.argv[2]
        expected_version = int(sys.argv[3])
        pathname = "/BASIN/UPSTREAM/FLOW//5MIN/C03-VERSION/"
        times = pd.date_range("2019-09-18 13:00", periods=3, freq="5min")
        values = np.array([10.25, 20.5, 30.75], dtype=np.float64)
        updated = values + 1.0
        kwargs = {} if requested == "default" else {"dss_version": int(requested)}
        RasDss.write_timeseries(output, pathname, times, values, **kwargs)
        assert RasDss.get_file_version(output) == expected_version
        RasDss.write_timeseries(output, pathname, times, updated)
        assert RasDss.get_file_version(output) == expected_version
        reread = RasDss.read_timeseries(output, pathname)
        np.testing.assert_array_equal(
            reread.index.to_numpy(dtype="datetime64[m]"),
            times.to_numpy(dtype="datetime64[m]"),
        )
        np.testing.assert_array_equal(reread["value"].to_numpy(), updated)
    """

    completed = _run_bridge_script(
        script,
        output,
        requested,
        expected_version,
    )
    _skip_if_bridge_unavailable(completed)
    _assert_clean_native_output(completed)
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.integration
def test_separate_process_matching_update_then_mismatch_is_fail_closed(
    tmp_path,
) -> None:
    output = tmp_path / "existing-v6.dss"
    prepare_script = """
        import sys
        from pathlib import Path

        import numpy as np
        import pandas as pd

        from ras_commander import RasDss

        try:
            RasDss._configure_jvm()
        except Exception as exc:
            print(f"C03_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
            raise SystemExit(77)

        output = Path(sys.argv[1])
        pathname = "/BASIN/UPSTREAM/FLOW//5MIN/C03-MISMATCH/"
        times = pd.date_range("2019-09-18 13:00", periods=3, freq="5min")
        initial = np.array([1.0, 2.0, 3.0], dtype=np.float64)
        updated = np.array([4.0, 5.0, 6.0], dtype=np.float64)
        RasDss.write_timeseries(
            output, pathname, times, initial, dss_version=6
        )
        RasDss.write_timeseries(
            output, pathname, times, updated, dss_version=6
        )
        reread = RasDss.read_timeseries(output, pathname)
        np.testing.assert_array_equal(reread["value"].to_numpy(), updated)
    """

    prepared = _run_bridge_script(prepare_script, output)
    _skip_if_bridge_unavailable(prepared)
    _assert_clean_native_output(prepared)
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    before = hashlib.sha256(output.read_bytes()).hexdigest()

    mismatch_script = """
        import sys
        from pathlib import Path

        import numpy as np
        import pandas as pd

        from ras_commander import RasDss

        try:
            RasDss._configure_jvm()
        except Exception as exc:
            print(f"C03_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
            raise SystemExit(77)

        output = Path(sys.argv[1])
        pathname = "/BASIN/UPSTREAM/FLOW//5MIN/C03-MISMATCH/"
        times = pd.date_range("2019-09-18 13:00", periods=3, freq="5min")
        updated = np.array([4.0, 5.0, 6.0], dtype=np.float64)
        try:
            RasDss.write_timeseries(
                output, pathname, times, [7.0, 8.0, 9.0], dss_version=7
            )
        except ValueError as exc:
            assert "version 6, not requested version 7" in str(exc)
        else:
            raise AssertionError("version mismatch did not fail")
        assert RasDss.get_file_version(output) == 6
        reread = RasDss.read_timeseries(output, pathname)
        np.testing.assert_array_equal(reread["value"].to_numpy(), updated)
    """

    mismatched = _run_bridge_script(mismatch_script, output)
    _skip_if_bridge_unavailable(mismatched)
    _assert_clean_native_output(mismatched)
    assert mismatched.returncode == 0, mismatched.stdout + mismatched.stderr
    assert hashlib.sha256(output.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("dss_version", [6, 7])
@pytest.mark.integration
def test_separate_process_creates_requested_grid_dss_version(
    tmp_path,
    dss_version: int,
) -> None:
    output = tmp_path / f"created-grid-v{dss_version}.dss"
    script = """
        import sys
        from pathlib import Path

        import numpy as np
        import pandas as pd

        from ras_commander import RasDss

        try:
            RasDss._configure_jvm()
        except Exception as exc:
            print(f"C03_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
            raise SystemExit(77)

        output = Path(sys.argv[1])
        version = int(sys.argv[2])
        pathname = (
            "/SHG/TEST/PRECIP/01JAN2020:0000/01JAN2020:0100/"
            f"C03-V{version}/"
        )
        expected = np.array(
            [[0.0, 0.25, np.nan], [1.0, 5.0, 120.0]],
            dtype=np.float32,
        )
        written = RasDss.write_grid_timeseries(
            output,
            pathname,
            expected[np.newaxis, ...],
            [pd.Timestamp("2020-01-01 01:00")],
            {
                "cellsize": 2000,
                "origin": (0, 0),
                "crs": "SHG",
                "data_type": "PER-CUM",
            },
            dss_version=version,
        )
        assert written == [pathname]
        assert RasDss.get_file_version(output) == version
        reread = RasDss.read_grid(output, pathname)
        np.testing.assert_allclose(
            reread["data"],
            expected,
            atol=0.01,
            equal_nan=True,
        )
        compression = reread["metadata"]["compression"]
        assert compression["method"] == {6: 101001, 7: 26}[version]
        assert compression["base"] == 0.0
        assert compression["scale_factor"] == {6: 100.0, 7: 0.0}[version]
        assert compression["element_size"] > 0
        assert reread["metadata"]["number_missing"] == 1
    """

    completed = _run_bridge_script(script, output, dss_version)
    _skip_if_bridge_unavailable(completed)
    _assert_clean_native_output(completed)
    assert completed.returncode == 0, completed.stdout + completed.stderr
