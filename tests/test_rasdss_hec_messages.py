"""HEC Monolith messages must never land in DSS files, and refused writes must raise.

HEC Monolith's DSS library writes messages through a stdout handle that its Fortran runtime
caches at its first message. Redirecting file descriptor 1 (as pytest's capture does around
every test) closes that handle; Windows can reuse its value for the next DSS file the
library opens, and later messages are written into that file. With no message handling, the
loop below read console text back as values from DSS6 files (5 of 30 reads wrong and 11
files holding messages in one run).

Turning the messages off stops that but hides failures: at level 0 a DSS6 time-series write
to a read-only file returned normally with nothing written. ``_route_hec_messages`` sends
them to a private file, and the Java writers raise on the failure lines.

The JVM can start only once, so the bridge runs in a subprocess. It skips without Java.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import stat
import textwrap
import types

import numpy as np
import pandas as pd
import pytest

from ras_commander import RasDss

WORKER = textwrap.dedent(
    """
    import json, os, sys, tempfile
    from pathlib import Path

    import numpy as np
    import pandas as pd

    os.environ.pop("RAS_COMMANDER_DSS_BACKEND", None)
    from ras_commander import RasDss

    folder, version, result = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
    try:
        RasDss._configure_jvm()
    except Exception as exc:
        print(f"R3_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
        raise SystemExit(77)

    times = pd.date_range("2020-01-01 01:00", periods=48, freq="h")
    values = np.arange(48.0)
    pathname = "//G/FLOW//1HOUR/R/"
    wrong = []
    sink = tempfile.TemporaryFile()
    saved = os.dup(1)
    try:
        for i in range(30):
            os.dup2(sink.fileno(), 1)  # capture on: closes the previous fd-1 handle
            target = folder / f"c{i}.dss"
            RasDss.write_timeseries(target, pathname, times, values, dss_version=version)
            RasDss.write_paired_data(target, "/G/H/STAGE-FLOW///R/", values, values,
                                     x_units="FEET", y_units="CFS")
            back = RasDss.read_timeseries(target, pathname)
            if not np.array_equal(back["value"].to_numpy(), values):
                wrong.append(f"{target.name}:timeseries")
            curve = RasDss.read_paired_data(target, "/G/H/STAGE-FLOW///R/")
            if not np.array_equal(curve.iloc[:, 0].to_numpy(), values):
                wrong.append(f"{target.name}:paired")
            os.dup2(saved, 1)  # capture off
            RasDss.write_timeseries(folder / f"b{i}.dss", "//B/FLOW//1HOUR/R/", times, values,
                                    dss_version=version)
    finally:
        os.dup2(saved, 1)
        os.close(saved)
    # Read while nothing is open: every RasDss call released its file.
    files_with_text = sorted(
        path.name for path in folder.glob("*.dss")
        if b"-----DSS" in path.read_bytes() or b"ZOPEN" in path.read_bytes()
    )
    sink.seek(0)
    result.write_text(json.dumps({
        "routed": RasDss._message_file is not None,
        "wrong": wrong,
        "files_with_text": files_with_text,
        "captured": sink.read().decode("latin-1"),
    }))
    """
)


@pytest.mark.parametrize("version", [6, 7])
def test_messages_never_land_in_dss_files_when_stdout_is_redirected(tmp_path, version):
    folder = tmp_path / "files"
    folder.mkdir()
    result = tmp_path / "result.json"
    env = {k: v for k, v in os.environ.items() if k != "RAS_COMMANDER_DSS_BACKEND"}
    proc = subprocess.run(
        [sys.executable, "-c", WORKER, str(folder), str(version), str(result)],
        capture_output=True, text=True, errors="replace", timeout=600, env=env,
    )
    if proc.returncode == 77:
        pytest.skip(proc.stdout.strip())
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    report = json.loads(result.read_text())
    assert report["routed"] is True
    assert report["wrong"] == []
    assert report["files_with_text"] == []
    assert "-----DSS" not in report["captured"]


FAILURE_WORKER = textwrap.dedent(
    """
    import hashlib, json, logging, os, stat, sys
    from pathlib import Path

    import numpy as np
    import pandas as pd

    os.environ.pop("RAS_COMMANDER_DSS_BACKEND", None)
    from ras_commander import RasDss

    folder, version, result = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
    try:
        RasDss._configure_jvm()
    except Exception as exc:
        print(f"R4_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
        raise SystemExit(77)

    logged = []

    class Capture(logging.Handler):
        def emit(self, record):
            logged.append(record.getMessage())

    logging.getLogger("ras_commander.dss.RasDss").addHandler(Capture())

    T = pd.date_range("2020-01-01 01:00", periods=4, freq="h")
    V = np.arange(4.0)
    TS, PD, GR = "//G/FLOW//1HOUR/R/", "/G/H/STAGE-FLOW///R/", "/SHG/B/PRECIP///R/"
    GT = pd.date_range("2020-01-01 00:00", periods=3, freq="h")
    GD = np.ones((2, 3, 4), dtype=np.float32)
    GI = dict(cellsize=2000.0, lower_left_cell_x=10, lower_left_cell_y=10, crs="SHG",
              units="MM", data_type="PER-CUM", compression="ZLIB")
    preflight = RasDss._require_writable_dss_file
    no_preflight = staticmethod(lambda path: None)
    count = [0]

    def seeded():
        count[0] += 1
        path = folder / f"s{count[0]}.dss"
        RasDss.write_timeseries(path, TS, T, V, dss_version=version)
        RasDss.write_paired_data(path, PD, V, V, x_units="FEET", y_units="CFS")
        RasDss.write_grid_timeseries(path, GR, GD, GT, GI)
        return path

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def outcome(action, path=None):
        before = digest(path) if path is not None and path.exists() else None
        try:
            value = action()
            entry = {"outcome": "returned", "value": str(value)[:200]}
        except BaseException as exc:
            entry = {"outcome": "raised", "type": type(exc).__name__,
                     "mro": [c.__name__ for c in type(exc).__mro__],
                     "message": str(exc)[:600]}
        if before is not None:
            entry["unchanged"] = digest(path) == before
        return entry

    def read_only_case(write, *, messages_only=False, shadow=False):
        path = seeded()
        path.chmod(stat.S_IREAD)
        if messages_only:
            RasDss._require_writable_dss_file = no_preflight
        if shadow:
            RasDss.backend = "shadow"
        try:
            return outcome(lambda: write(path), path)
        finally:
            RasDss.backend = "java"
            RasDss._require_writable_dss_file = staticmethod(preflight)
            path.chmod(stat.S_IWRITE)

    writers = {
        "ts_new": lambda p: RasDss.write_timeseries(p, "//NEW/FLOW//1HOUR/R/", T, V),
        "ts_existing": lambda p: RasDss.write_timeseries(p, TS, T, V + 1),
        "ts_irregular": lambda p: RasDss.write_timeseries(p, "//I/FLOW//IR-DAY/R/", T, V),
        "ts_dataframe": lambda p: RasDss.write_timeseries_from_dataframe(
            p, TS, pd.DataFrame({"value": V + 2}, index=T)),
        "pd_new": lambda p: RasDss.write_paired_data(p, "/G/N/STAGE-FLOW///R/", V, V),
        "pd_existing": lambda p: RasDss.write_paired_data(
            p, PD, V, V + 1, x_units="FEET", y_units="CFS"),
        "grid_new": lambda p: RasDss.write_grid_timeseries(p, "/SHG/N/PRECIP///R/", GD, GT, GI),
        "grid_existing": lambda p: RasDss.write_grid_timeseries(p, GR, GD * 2, GT, GI),
    }
    report = {"routed": RasDss._message_file is not None, "cases": {}}
    cases = report["cases"]
    for name, write in writers.items():
        cases[f"read_only:{name}"] = read_only_case(write)
        cases[f"messages:{name}"] = read_only_case(write, messages_only=True)
    cases["shadow:ts_existing"] = read_only_case(writers["ts_existing"], shadow=True)
    cases["shadow_messages:ts_existing"] = read_only_case(
        writers["ts_existing"], messages_only=True, shadow=True)

    # The grid derivative's temporary file is refused while it is being built.
    source = seeded()
    output = folder / "derivative.dss"
    create = RasDss._create_empty_dss

    def create_read_only(path, dss_version):
        create(path, dss_version)
        path.chmod(stat.S_IREAD)

    RasDss._create_empty_dss = staticmethod(create_read_only)
    cases["copy_grid:temporary_refused"] = outcome(
        lambda: RasDss.copy_grid_with_zero_tail(source, output, GR, 1))
    RasDss._create_empty_dss = staticmethod(create)
    report["copy_output_exists"] = output.exists()
    for leftover in folder.glob(".derivative.*"):
        leftover.chmod(stat.S_IWRITE)

    # A read-only source is not a write target.
    source.chmod(stat.S_IREAD)
    cases["copy_grid:read_only_source"] = outcome(
        lambda: RasDss.copy_grid_with_zero_tail(source, output, GR, 1))
    source.chmod(stat.S_IWRITE)

    # Healthy work must not trip on routine messages or on words in names.
    named = folder / "Error Cannot Unable to"
    named.mkdir()
    logged.clear()
    healthy = named / "ok.dss"
    tricky = "//ERROR; Cannot /FLOW//1HOUR/Unable to/"

    def healthy_io():
        RasDss.write_timeseries(healthy, TS, T, V, dss_version=version)
        RasDss.write_timeseries(healthy, TS, T, V + 1)
        RasDss.write_timeseries(healthy, tricky, T, V)
        RasDss.write_timeseries(healthy, "//I/FLOW//IR-DAY/R/", T, V)
        RasDss.write_timeseries(healthy, "//M/FLOW//1HOUR/R/",
                                pd.date_range("2020-01-01 01:00", periods=2000, freq="h"),
                                np.arange(2000.0))
        RasDss.write_paired_data(healthy, PD, V, V)
        RasDss.write_paired_data(healthy, PD, V, V + 1)
        RasDss.write_grid_timeseries(healthy, GR, GD, GT, GI)
        RasDss.write_grid_timeseries(healthy, GR, GD * 2, GT, GI)
        RasDss.get_catalog(healthy)
        RasDss.read_timeseries(healthy, TS)
        RasDss.read_paired_data(healthy, PD)
        return RasDss.read_timeseries(healthy, TS)["value"].tolist()

    cases["healthy"] = outcome(healthy_io)
    report["healthy_values"] = RasDss.read_timeseries(healthy, TS)["value"].tolist()
    report["healthy_logged"] = [m for m in logged if "HEC-DSS library" in m]

    # A failure reported for an earlier call must not fail a later healthy write.
    damaged = seeded()
    data = damaged.read_bytes()
    damaged.write_bytes(data[: len(data) // 2])
    logged.clear()
    cases["damaged_read"] = outcome(lambda: RasDss.read_timeseries(damaged, TS))
    report["damaged_read_logged"] = [m for m in logged if "HEC-DSS library reported" in m]
    after = seeded()
    cases["healthy_after_failure"] = outcome(lambda: RasDss.write_timeseries(after, TS, T, V + 5))
    report["after_values"] = RasDss.read_timeseries(after, TS)["value"].tolist()

    # A new record on a damaged file: Monolith can return normally with nothing readable.
    for name, write, read in (
        ("ts", lambda p: RasDss.write_timeseries(p, "//NEW/FLOW//1HOUR/R/", T, V + 9),
         lambda p: RasDss.read_timeseries(p, "//NEW/FLOW//1HOUR/R/")["value"].tolist()),
        ("pd", lambda p: RasDss.write_paired_data(p, "/G/N/STAGE-FLOW///R/", V, V + 9),
         lambda p: RasDss.read_paired_data(p, "/G/N/STAGE-FLOW///R/").iloc[:, 0].tolist()),
    ):
        cut = seeded()
        data = cut.read_bytes()
        cut.write_bytes(data[: len(data) // 2])
        entry = outcome(lambda: write(cut))
        if entry["outcome"] == "returned":
            entry["read_back"] = outcome(lambda: read(cut))
        cases[f"damaged_new:{name}"] = entry

    # Names that Monolith alters must not fail the stored-record check.
    alter = folder / "alter.dss"
    long_part = "L" * 70
    cases["altered:long_part"] = outcome(lambda: RasDss.write_timeseries(
        alter, f"//{long_part}/FLOW//1HOUR/R/", T, V, dss_version=version))
    cases["altered:non_ascii"] = outcome(lambda: RasDss.write_paired_data(
        alter, "/G/CAFÉ/STAGE-FLOW///R/", V, V))
    cases["altered:lower_case"] = outcome(lambda: RasDss.write_timeseries(
        alter, "//lower/flow//1Hour/r/", T, V))
    cases["altered:interval_spelling"] = outcome(lambda: RasDss.write_timeseries(
        alter, "//SP/FLOW//1Hour/R/", T, V))
    report["sidecars"] = sorted(
        p.name for p in folder.rglob("*") if p.is_file() and p.suffix.lower() != ".dss")

    # Wrong-kind reads refuse; plain Java must not crash the JVM on them.
    wrong = seeded()
    grid_path = next(p for p in RasDss.get_catalog(wrong)["pathname"] if "PRECIP" in p)
    cases["wrong_kind:ts_on_paired"] = outcome(lambda: RasDss.read_timeseries(wrong, PD))
    cases["wrong_kind:ts_on_grid"] = outcome(lambda: RasDss.read_timeseries(wrong, grid_path))
    cases["wrong_kind:ts_window_on_paired"] = outcome(lambda: RasDss._read_timeseries_java(
        wrong, PD, start_date="01JAN2020 0000", end_date="02JAN2020 0000"))
    cases["wrong_kind:paired_on_ts"] = outcome(lambda: RasDss.read_paired_data(wrong, TS))

    result.write_text(json.dumps(report))
    """
)

LEVEL_ZERO_WORKER = textwrap.dedent(
    """
    import os, stat, sys
    from pathlib import Path

    import numpy as np
    import pandas as pd

    os.environ.pop("RAS_COMMANDER_DSS_BACKEND", None)
    from ras_commander import RasDss

    RasDss.hec_message_level = 0
    path = Path(sys.argv[1])
    try:
        RasDss._configure_jvm()
    except Exception as exc:
        print(f"R4_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
        raise SystemExit(77)
    T = pd.date_range("2020-01-01 01:00", periods=4, freq="h")
    RasDss.write_timeseries(path, "//G/FLOW//1HOUR/R/", T, np.arange(4.0), dss_version=6)
    path.chmod(stat.S_IREAD)
    RasDss._require_writable_dss_file = staticmethod(lambda p: None)
    try:
        RasDss.write_timeseries(path, "//G/FLOW//1HOUR/R/", T, np.arange(4.0) + 1)
    except RuntimeError as exc:
        print("REFUSED" if "Read Access Only" in str(exc) else f"OTHER:{exc}")
    else:
        print("RETURNED")
    finally:
        path.chmod(stat.S_IWRITE)
    """
)


def _clean_env():
    return {k: v for k, v in os.environ.items() if k != "RAS_COMMANDER_DSS_BACKEND"}


@pytest.fixture(scope="module", params=[6, 7], ids=["dss6", "dss7"])
def failures(request, tmp_path_factory):
    root = tmp_path_factory.mktemp(f"failures{request.param}")
    folder = root / "files"
    folder.mkdir()
    result = root / "result.json"
    proc = subprocess.run(
        [sys.executable, "-c", FAILURE_WORKER, str(folder), str(request.param), str(result)],
        capture_output=True, text=True, errors="replace", timeout=600, env=_clean_env(),
    )
    if proc.returncode == 77:
        pytest.skip(proc.stdout.strip())
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    return json.loads(result.read_text())


WRITERS = ["ts_new", "ts_existing", "ts_irregular", "ts_dataframe",
           "pd_new", "pd_existing", "grid_new", "grid_existing"]


@pytest.mark.parametrize("writer", WRITERS)
def test_write_to_read_only_file_raises_and_changes_nothing(failures, writer):
    """Before the fix, the DSS6 time-series cases returned normally with nothing written."""
    case = failures["cases"][f"read_only:{writer}"]
    assert case["outcome"] == "raised", case
    assert "RuntimeError" in case["mro"]
    assert "read-only" in case["message"]
    assert case["unchanged"] is True


@pytest.mark.parametrize("writer", WRITERS)
def test_refused_write_raises_without_the_read_only_check(failures, writer):
    """The library's refusal itself raises, for failures the early check cannot see."""
    case = failures["cases"][f"messages:{writer}"]
    assert case["outcome"] == "raised", case
    assert "RuntimeError" in case["mro"]
    assert case["unchanged"] is True


def test_refused_dss6_time_series_write_names_the_library_message(failures, request):
    if "dss7" in request.node.name:
        pytest.skip("DSS7 raises from HecDss.put with a status")
    message = failures["cases"]["messages:ts_existing"]["message"]
    assert "HEC-DSS library refused the write" in message
    assert "Read Access Only" in message


@pytest.mark.parametrize("case_name", ["shadow:ts_existing", "shadow_messages:ts_existing"])
def test_shadow_reports_the_java_write_failure(failures, case_name):
    """Shadow returns Java's result and errors: a refused write is not reported as success.
    Only its comparison never raises (see test_rasdss_shadow_regressions)."""
    case = failures["cases"][case_name]
    assert case["outcome"] == "raised", case
    assert "RuntimeError" in case["mro"]
    assert case["unchanged"] is True


def test_copy_grid_refused_temporary_raises_and_publishes_nothing(failures):
    case = failures["cases"]["copy_grid:temporary_refused"]
    assert case["outcome"] == "raised", case
    assert failures["copy_output_exists"] is False


def test_copy_grid_accepts_a_read_only_source(failures):
    assert failures["cases"]["copy_grid:read_only_source"]["outcome"] == "returned"


def test_healthy_java_io_reports_no_library_failure(failures):
    """Failure-line matching must not trip on routine messages or on words in names."""
    assert failures["cases"]["healthy"]["outcome"] == "returned", failures["cases"]["healthy"]
    assert failures["healthy_logged"] == []
    assert failures["healthy_values"] == [1.0, 2.0, 3.0, 4.0]


def test_read_of_damaged_file_logs_the_library_failure(failures):
    assert failures["cases"]["damaged_read"]["outcome"] == "raised"
    assert failures["damaged_read_logged"]


def test_earlier_failure_does_not_fail_a_later_healthy_write(failures):
    assert failures["cases"]["healthy_after_failure"]["outcome"] == "returned"
    assert failures["after_values"] == [5.0, 6.0, 7.0, 8.0]


@pytest.mark.parametrize("name", ["ts", "pd"])
def test_new_record_on_damaged_file_is_stored_or_raises(failures, name):
    """Monolith returned normally from these DSS7 writes, leaving an unreadable record."""
    case = failures["cases"][f"damaged_new:{name}"]
    if case["outcome"] == "returned":
        assert case["read_back"]["outcome"] == "returned", case
        assert case["read_back"]["value"] == "[9.0, 10.0, 11.0, 12.0]"
    else:
        assert "RuntimeError" in case["mro"], case


@pytest.mark.parametrize("case_name", [
    "altered:long_part", "altered:non_ascii", "altered:lower_case", "altered:interval_spelling",
])
def test_names_monolith_alters_do_not_fail_the_stored_record_check(failures, case_name):
    assert failures["cases"][case_name]["outcome"] == "returned", failures["cases"][case_name]


def test_verification_leaves_no_sidecar_files(failures):
    assert failures["sidecars"] == []


@pytest.mark.parametrize("case_name", [
    "wrong_kind:ts_on_paired", "wrong_kind:ts_on_grid", "wrong_kind:ts_window_on_paired",
    "wrong_kind:paired_on_ts",
])
def test_wrong_kind_java_reads_refuse_and_the_jvm_survives(failures, case_name):
    """RasDss checks the container class before casting. The worker must also exit cleanly."""
    case = failures["cases"][case_name]
    assert case["outcome"] == "raised", case
    assert "TypeError" in case["mro"]


def test_level_zero_cannot_hide_a_refused_write(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-c", LEVEL_ZERO_WORKER, str(tmp_path / "zero.dss")],
        capture_output=True, text=True, errors="replace", timeout=300, env=_clean_env(),
    )
    if proc.returncode == 77:
        pytest.skip(proc.stdout.strip())
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    assert "REFUSED" in proc.stdout


def test_read_only_precip_grid_overwrite_raises(tmp_path):
    """``write_precip_grid_arrays`` never uses Java. pydsstools writes a sibling file and
    publishing over a read-only target already fails; this guards that."""
    pytest.importorskip("pydsstools")
    affine = pytest.importorskip("affine")
    target = tmp_path / "ro.dss"
    target.write_bytes(b"existing")
    target.chmod(stat.S_IREAD)
    backend = RasDss.backend
    RasDss.backend = "java"
    env = os.environ.pop("RAS_COMMANDER_DSS_BACKEND", None)
    try:
        with pytest.raises(OSError):
            RasDss.write_precip_grid_arrays(
                target, "/UTM15/B/PRECIP///A/", np.ones((2, 3, 4), dtype=np.float32),
                pd.date_range("2020-01-01", periods=3, freq="h"),
                transform=affine.Affine(2000, 0, 0, 0, -2000, 6000), crs="EPSG:26915",
                units="mm", overwrite=True,
            )
    finally:
        RasDss.backend = backend
        if env is not None:
            os.environ["RAS_COMMANDER_DSS_BACKEND"] = env
        target.chmod(stat.S_IWRITE)
    assert target.read_bytes() == b"existing"


class _FakeManager:
    def __init__(self, status=0, fail=False):
        self.status, self.fail = status, fail
        self.files = []

    def setMessageFile(self, path):
        if self.fail:
            raise RuntimeError("no library")
        self.files.append(path)
        return self.status

    def flushMessageFile(self):
        pass

    def windMessageFile(self):
        pass

    def closeMessageFile(self):
        pass


def _fake_jnius(monkeypatch, calls, manager=None, fail_level=False):
    manager = manager or _FakeManager()

    class Heclib:
        @staticmethod
        def Hec_zset(name, text, value):
            if fail_level:
                raise RuntimeError("no library")
            calls.append((name, text, value))

    classes = {"hec.heclib.util.Heclib": Heclib, "hec.heclib.dss.HecDataManager": manager}
    module = types.SimpleNamespace(autoclass=lambda name: classes[name])
    monkeypatch.setitem(sys.modules, "jnius", module)
    monkeypatch.setattr(RasDss, "_messages_routed", False)
    monkeypatch.setattr(RasDss, "_message_file", None)
    monkeypatch.setattr(RasDss, "_message_offset", 0)
    monkeypatch.setattr("atexit.register", lambda *a, **k: None)
    return manager


def _discard_message_dir():
    import shutil

    if RasDss._message_file is not None:
        shutil.rmtree(RasDss._message_file.parent, ignore_errors=True)


def test_routing_is_set_once_from_the_class_attribute(monkeypatch):
    calls = []
    manager = _fake_jnius(monkeypatch, calls)
    monkeypatch.setattr(RasDss, "hec_message_level", 4)
    try:
        RasDss._route_hec_messages()
        RasDss._route_hec_messages()
        assert calls == [("MLEVEL", "", 4)]
        assert len(manager.files) == 1
        assert RasDss._message_file is not None
    finally:
        _discard_message_dir()


def test_message_level_defaults_to_one_and_cannot_go_below_it(monkeypatch):
    assert RasDss.hec_message_level == 1
    calls = []
    _fake_jnius(monkeypatch, calls)
    monkeypatch.setattr(RasDss, "hec_message_level", 0)
    try:
        RasDss._route_hec_messages()
        assert calls == [("MLEVEL", "", 1)]
    finally:
        _discard_message_dir()


@pytest.mark.parametrize("manager_args", [{"fail": True}, {"status": -1}])
def test_routing_failure_warns_silences_and_never_blocks(monkeypatch, caplog, manager_args):
    calls = []
    _fake_jnius(monkeypatch, calls, _FakeManager(**manager_args))
    with caplog.at_level("WARNING", logger="ras_commander.dss.RasDss"):
        RasDss._route_hec_messages()
    assert RasDss._message_file is None
    assert calls == [("MLEVEL", "", 0)]
    assert "Could not route HEC-DSS library messages" in caplog.text
    assert RasDss._drain_hec_messages() == []


def test_routing_failure_with_no_library_never_raises(monkeypatch):
    _fake_jnius(monkeypatch, [], _FakeManager(fail=True), fail_level=True)
    RasDss._route_hec_messages()
    assert RasDss._message_file is None


def test_an_already_running_jvm_is_still_routed(monkeypatch):
    calls = []
    _fake_jnius(monkeypatch, calls)
    config = types.SimpleNamespace(vm_running=True)
    monkeypatch.setitem(sys.modules, "jnius_config", config)
    monkeypatch.setattr(RasDss, "_jvm_configured", False)
    monkeypatch.setattr(RasDss, "_ensure_monolith", staticmethod(lambda: object()))
    try:
        RasDss._configure_jvm()
        assert calls == [("MLEVEL", "", 1)]
    finally:
        _discard_message_dir()


def test_drain_reports_failure_lines_only_once_and_skips_routine_lines(monkeypatch, tmp_path, caplog):
    _fake_jnius(monkeypatch, [])
    message_file = tmp_path / "messages.txt"
    message_file.write_bytes(
        b" -----DSS---ZOPEN:  Existing File Opened,  File: C:\\Error Cannot\\a.dss\r\n"
        b" -----DSS---ZOPEN:  (Read Access Only) File: b.dss\r\n"
        b" -----DSS---zsrtsi6:  ERROR;  File has Read Access Only\r\n"
    )
    monkeypatch.setattr(RasDss, "_message_file", message_file)
    with caplog.at_level("WARNING", logger="ras_commander.dss.RasDss"):
        first = RasDss._drain_hec_messages()
    assert first == ["-----DSS---zsrtsi6:  ERROR;  File has Read Access Only"]
    assert "HEC-DSS library reported" in caplog.text
    assert RasDss._drain_hec_messages() == []


def test_message_file_restarts_past_the_limit(monkeypatch, tmp_path):
    manager = _fake_jnius(monkeypatch, [])
    winds = []
    manager.windMessageFile = lambda: winds.append(True)
    message_file = tmp_path / "messages.txt"
    message_file.write_bytes(b"x" * 64)
    monkeypatch.setattr(RasDss, "_message_file", message_file)
    monkeypatch.setattr(
        sys.modules[RasDss.__module__], "_HEC_MESSAGE_FILE_LIMIT", 10
    )
    RasDss._drain_hec_messages()
    assert winds == [True]
    assert RasDss._message_offset == 0


def test_drain_failure_never_raises(monkeypatch, tmp_path):
    _fake_jnius(monkeypatch, [])
    monkeypatch.setattr(RasDss, "_message_file", tmp_path / "missing.txt")
    assert RasDss._drain_hec_messages() == []


def test_read_only_check_needs_no_jvm(tmp_path):
    target = tmp_path / "ro.dss"
    target.write_bytes(b"x")
    RasDss._require_writable_dss_file(target)
    target.chmod(stat.S_IREAD)
    try:
        with pytest.raises(RuntimeError, match="read-only"):
            RasDss._require_writable_dss_file(target)
    finally:
        target.chmod(stat.S_IWRITE)


def test_create_empty_failure_is_a_runtime_error(monkeypatch, tmp_path):
    """Grid writes to a location HEC cannot create raised a bare JavaException."""
    class JavaLikeError(Exception):
        pass

    class HecDss:
        @staticmethod
        def open(path, version):
            raise JavaLikeError("Unable to access HEC-DSS file")

    module = types.SimpleNamespace(autoclass=lambda name: HecDss)
    monkeypatch.setitem(sys.modules, "jnius", module)
    monkeypatch.setattr(RasDss, "_configure_jvm", staticmethod(lambda: None))
    with pytest.raises(RuntimeError, match="could not create version 6"):
        RasDss._create_empty_dss(tmp_path / "new.dss", 6)


def test_shadow_snapshot_of_a_read_only_target_can_be_cleaned_up(tmp_path):
    target = tmp_path / "ro.dss"
    target.write_bytes(b"x")
    target.chmod(stat.S_IREAD)
    try:
        ctx = RasDss._shadow_write_snapshot(target)
        assert os.access(ctx["copy"], os.W_OK)
        RasDss._shadow_write_cleanup(ctx)
        assert not ctx["tmpdir"].exists()
    finally:
        target.chmod(stat.S_IWRITE)
