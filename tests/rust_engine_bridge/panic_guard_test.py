"""Rust panics are contained at the Python boundary and never poison a session.

A panic is an engine bug, so these tests inject one through test hooks:
``ras_commander_fast_hdf._panic_for_test`` and ``HdfSession._panic_for_test``
(the latter panics inside an engine call while the session lock is held).
The hooks exist only in extension builds with the ``test-hooks`` Cargo feature
(ras-commander-fast-hdf after 0.2.4); release wheels leave them out, so these
tests skip there.
"""
import importlib
import sys

import h5py
import numpy as np
import pytest


@pytest.fixture
def native():
    module = pytest.importorskip("ras_commander_fast_hdf")
    if not hasattr(module, "_panic_for_test"):
        pytest.skip("extension built without the test-hooks feature (release wheel)")
    return module


@pytest.fixture
def small_h5(tmp_path):
    path = tmp_path / "values.h5"
    with h5py.File(path, "w") as f:
        f.create_dataset("values", data=np.arange(12, dtype="f8").reshape(3, 4))
    return path


def test_standalone_panic_is_a_runtime_error_not_panic_exception(native, monkeypatch):
    # Without ras_commander.fast_hdf imported, the extension's own class is used.
    monkeypatch.delitem(sys.modules, "ras_commander.fast_hdf", raising=False)
    with pytest.raises(native.NativePanicError, match="native extension panicked: boom") as info:
        native._panic_for_test("boom")
    assert isinstance(info.value, RuntimeError)
    assert isinstance(info.value, Exception)


def test_contained_panic_prints_nothing(native, monkeypatch, capfd):
    # The extension's quiet panic hook: the message is in the exception only.
    monkeypatch.delenv("RUST_BACKTRACE", raising=False)
    with pytest.raises(Exception, match="native extension panicked: silent") as info:
        native._panic_for_test("silent")
    captured = capfd.readouterr()
    if "panicked at" in captured.err:
        pytest.skip("extension predates the quiet panic hook")
    assert "silent" not in captured.err
    assert "silent" in str(info.value)


def test_panic_maps_to_fast_hdf_error_subclass(native):
    fast_hdf = importlib.import_module("ras_commander.fast_hdf")
    with pytest.raises(fast_hdf.FastHdfPanicError) as info:
        native._panic_for_test("engine bug")
    assert isinstance(info.value, fast_hdf.FastHdfError)
    assert "engine bug" in str(info.value)
    # The existing broad handlers in auto mode catch it.
    try:
        native._panic_for_test("engine bug")
    except Exception as exc:  # noqa: BLE001 - this is the contract under test
        caught = exc
    assert isinstance(caught, fast_hdf.FastHdfPanicError)


def test_panic_does_not_poison_the_session(native, small_h5):
    fast_hdf = importlib.import_module("ras_commander.fast_hdf")
    session = native.HdfSession(small_h5)
    for _ in range(2):
        with pytest.raises(fast_hdf.FastHdfPanicError, match="session lock is held"):
            session._panic_for_test()
        values = session.read_numeric("/values")
        np.testing.assert_array_equal(values, np.arange(12, dtype="f8").reshape(3, 4))
        assert session.closed is False
    with session:
        np.testing.assert_array_equal(session.read_numeric("/values", [(0, 1, 1), (0, 4, 1)]),
                                      np.arange(4, dtype="f8").reshape(1, 4))
    assert session.closed is True
    session.close()


def test_cached_session_survives_a_panic_and_auto_mode_falls_back(native, small_h5, monkeypatch):
    fast_hdf = importlib.import_module("ras_commander.fast_hdf")
    fast_hdf.close_sessions()
    with h5py.File(small_h5) as f:
        expected = f["values"][()]
        np.testing.assert_array_equal(fast_hdf.read_dataset(f["values"], backend="rust"), expected)
        # Panic inside the process-cached session, then keep using it.
        with fast_hdf._session(native, small_h5) as cached:
            with pytest.raises(fast_hdf.FastHdfPanicError):
                cached._panic_for_test()
        np.testing.assert_array_equal(fast_hdf.read_dataset(f["values"], backend="rust"), expected)

        # A panicking native read: auto mode serves h5py, rust mode reports FastHdfError.
        class PanickingSession:
            def read_numeric(self, *args, **kwargs):
                native._panic_for_test("read panicked")

        from contextlib import contextmanager

        @contextmanager
        def panicking(*args, **kwargs):
            yield PanickingSession()

        monkeypatch.setattr(fast_hdf, "_session", panicking)
        monkeypatch.setattr(fast_hdf, "_read_fim_result", lambda *a, **k: None, raising=False)
        np.testing.assert_array_equal(fast_hdf.read_dataset(f["values"], backend="auto"), expected)
        with pytest.raises(fast_hdf.FastHdfError, match="read panicked"):
            fast_hdf.read_dataset(f["values"], backend="rust")
    monkeypatch.undo()
    fast_hdf.close_sessions()
