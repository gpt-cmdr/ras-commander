"""Serial sampling must fail closed and restore public runtime state."""

import pytest

from ras_commander import _terrain_sampling_execution as sampling
from ras_commander.terrain import RasTerrainMod


@pytest.fixture
def runtime(monkeypatch):
    state = {"affinity": 12, "min": (2, 2), "max": (32, 16), "invocations": 0}

    def set_value(name):
        def setter(*values):
            state[name] = values[0] if name == "affinity" else values
            return True

        return setter

    def invoke(operation):
        assert state["affinity"] == 4
        assert state["max"] == state["min"] == (1, 1)
        state["invocations"] += 1
        return operation()

    controls = {
        "get_affinity": lambda: state["affinity"],
        "get_min": lambda: state["min"],
        "get_max": lambda: state["max"],
        "set_affinity": set_value("affinity"),
        "set_min": set_value("min"),
        "set_max": set_value("max"),
        "invoke": invoke,
        "processor_count": 8,
    }
    monkeypatch.setattr(sampling, "_load_controls", lambda: controls)
    return state, controls


def assert_restored(state):
    assert state["affinity"] == 12
    assert state["min"] == (2, 2)
    assert state["max"] == (32, 16)


def test_public_callback_preserves_result_and_restores_runtime(runtime):
    state, _ = runtime
    expected = object()
    result, evidence = RasTerrainMod.run_serial_native_sampling(lambda: expected)
    assert result is expected
    assert evidence["mode"] == "single-clr-pool-worker-v1"
    assert evidence["called_on_pool_worker"] is True
    assert evidence["runtime_restored"] is True
    assert state["invocations"] == 1
    assert_restored(state)


@pytest.mark.parametrize("name", ["set_min", "set_max"])
def test_rejected_limit_never_invokes_callback_and_restores(runtime, name):
    state, controls = runtime
    original = controls[name]
    controls[name] = lambda *v: False if v == (1, 1) else original(*v)
    with pytest.raises(RuntimeError, match="rejected"):
        sampling.run_serial_sampling(lambda: pytest.fail("must not invoke"))
    assert state["invocations"] == 0
    assert_restored(state)


@pytest.mark.parametrize("name", ["set_min", "set_max"])
def test_ignored_limits_never_invoke_callback(runtime, name):
    state, controls = runtime
    original = controls[name]
    controls[name] = lambda *v: True if v == (1, 1) else original(*v)
    with pytest.raises(RuntimeError, match="did not apply"):
        sampling.run_serial_sampling(lambda: pytest.fail("must not invoke"))
    assert state["invocations"] == 0
    assert_restored(state)


def test_callback_exception_is_preserved_and_runtime_restored(runtime):
    state, _ = runtime
    error = ValueError("sampling failure")

    def fail():
        raise error

    with pytest.raises(ValueError) as caught:
        sampling.run_serial_sampling(fail)
    assert caught.value is error
    assert_restored(state)
    assert sampling.run_serial_sampling(lambda: 7)[0] == 7


def test_restoration_failure_cannot_return_a_success(runtime):
    _, controls = runtime
    original = controls["set_affinity"]
    controls["set_affinity"] = lambda v: False if v == 12 else original(v)
    with pytest.raises(RuntimeError, match="restoration failed"):
        sampling.run_serial_sampling(lambda: 7)


def test_cleanup_failure_does_not_replace_callback_exception(runtime):
    _, controls = runtime
    original = controls["set_max"]
    controls["set_max"] = lambda *v: False if v == (32, 16) else original(*v)
    error = ValueError("original sampling failure")

    def fail():
        raise error

    with pytest.raises(ValueError) as caught:
        sampling.run_serial_sampling(fail)
    assert caught.value is error
    assert "restoration failed" in error.__notes__[0]


def test_nested_call_is_rejected_without_losing_outer_runtime(runtime):
    state, _ = runtime

    def nested():
        with pytest.raises(RuntimeError, match="already active"):
            sampling.run_serial_sampling(lambda: None)
        return "outer"

    assert sampling.run_serial_sampling(nested)[0] == "outer"
    assert state["invocations"] == 1
    assert_restored(state)


def test_initialization_failure_releases_lock(monkeypatch):
    def missing():
        raise RuntimeError("runtime unavailable")

    monkeypatch.setattr(sampling, "_load_controls", missing)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="unavailable"):
            sampling.run_serial_sampling(lambda: None)


def test_noncallable_does_not_load_native_runtime(monkeypatch):
    monkeypatch.setattr(
        sampling, "_load_controls", lambda: pytest.fail("must not load")
    )
    with pytest.raises(TypeError, match="callable"):
        sampling.run_serial_sampling(None)


@pytest.mark.parametrize(
    "queue_ok,on_pool", [(True, True), (False, True), (True, False)]
)
def test_native_dispatch_queues_pool_work_without_inlining(
    monkeypatch, queue_ok, on_pool
):
    import sys
    from types import SimpleNamespace

    calls = []

    class Event:
        def __init__(self, initial):
            self.signaled = initial

        def Set(self):
            self.signaled = True
            calls.append("signal")

        def WaitOne(self):
            assert self.signaled, "the waiting thread must not execute the callback"
            calls.append("wait")

        def Dispose(self):
            calls.append("dispose")

    def queue(callback):
        calls.append("queue")
        if queue_ok:
            callback(None)
        return queue_ok

    monkeypatch.setattr(RasTerrainMod, "_ensure_initialized", lambda: None)
    monkeypatch.setitem(
        sys.modules,
        "System",
        SimpleNamespace(Environment=SimpleNamespace(ProcessorCount=8), IntPtr=int),
    )
    monkeypatch.setitem(
        sys.modules,
        "System.Diagnostics",
        SimpleNamespace(Process=SimpleNamespace(GetCurrentProcess=lambda: None)),
    )
    pool = SimpleNamespace(
        QueueUserWorkItem=queue,
        GetMinThreads=lambda: (1, 1),
        GetMaxThreads=lambda: (1, 1),
        SetMinThreads=lambda *v: True,
        SetMaxThreads=lambda *v: True,
    )
    monkeypatch.setitem(
        sys.modules,
        "System.Threading",
        SimpleNamespace(
            ManualResetEvent=Event,
            ThreadPool=pool,
            WaitCallback=lambda callback: callback,
            Thread=SimpleNamespace(
                CurrentThread=SimpleNamespace(IsThreadPoolThread=on_pool)
            ),
        ),
    )
    invoked = []
    invoke = sampling._load_controls()["invoke"]
    if queue_ok and on_pool:
        assert invoke(lambda: invoked.append("sample") or 7) == 7
        assert invoked == ["sample"]
        assert calls == ["queue", "signal", "wait", "dispose"]
    else:
        with pytest.raises(RuntimeError, match="pool"):
            invoke(lambda: invoked.append("must not sample"))
        assert invoked == []
        assert calls[-1] == "dispose"
        if not queue_ok:
            assert "wait" not in calls
