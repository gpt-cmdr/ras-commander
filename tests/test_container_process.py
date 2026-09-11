"""Real subprocess coverage for Docker CLI streaming; no Docker or HEC-RAS."""

import os
import subprocess
import sys
import threading
import time

import pytest

from ras_commander import _container_process
from ras_commander._container_process import run_streaming


def _python(code, *arguments):
    return [sys.executable, "-u", "-c", code, *map(str, arguments)]


@pytest.fixture
def children(monkeypatch):
    original = subprocess.Popen
    processes = []

    def tracked(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(_container_process.subprocess, "Popen", tracked)
    yield processes
    for process in processes:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def _assert_clean(process):
    assert process.poll() is not None
    assert process.stdout.closed
    assert process.stderr.closed
    prefix = f"ras-container-{process.pid}-"
    assert not [t for t in threading.enumerate() if t.name.startswith(prefix)]


def test_both_streams_arrive_on_caller_thread_before_exit(tmp_path, children):
    gate = tmp_path / "callback-observed-both-streams"
    owner = threading.get_ident()
    seen = []

    def callback(stream, line):
        assert threading.get_ident() == owner
        assert children[0].poll() is None
        seen.append((stream, line))
        if {name for name, _ in seen} == {"stdout", "stderr"}:
            gate.write_text("ready", encoding="utf-8")

    result = run_streaming(_python(
        "import os, pathlib, sys, time\n"
        "os.write(1, b'live-out\\n')\nos.write(2, b'live-error\\n')\n"
        "while not pathlib.Path(sys.argv[1]).exists(): time.sleep(0.01)\n",
        gate,
    ), timeout=5, on_line=callback)
    assert result.returncode == 0
    assert set(seen) == {("stdout", "live-out"), ("stderr", "live-error")}
    assert result.stdout == "live-out\n"
    assert result.stderr == "live-error\n"
    _assert_clean(children[0])


def test_newlines_utf8_and_incomplete_final_line_across_chunks(tmp_path, children):
    gate = tmp_path / "lone-cr-observed"
    seen = []

    def callback(stream, line):
        seen.append((stream, line))
        if line == "progress":
            gate.write_text("ready", encoding="utf-8")

    result = run_streaming(_python(
        "import os, pathlib, sys, time\n"
        "os.write(1, b'first\\n\\nprogress\\r')\n"
        "while not pathlib.Path(sys.argv[1]).exists(): time.sleep(0.01)\n"
        "for chunk in [b'\\nnext\\r', b'last\\r\\n', b'\\xe2', b'\\x98\\x83\\n', b'bad\\xff-tail']:\n"
        " os.write(1, chunk); time.sleep(0.03)\n",
        gate,
    ), timeout=5, on_line=callback)
    assert seen == [("stdout", line) for line in (
        "first", "", "progress", "next", "last", "\u2603", "bad\ufffd-tail",
    )]
    assert result.stdout == "first\n\nprogress\r\nnext\rlast\r\n\u2603\nbad\ufffd-tail"
    assert result.stderr == ""
    _assert_clean(children[0])


def test_captures_both_full_streams_without_callback_and_nonzero_exit(children):
    result = run_streaming(_python(
        "import os\n"
        "for i in range(48):\n"
        " os.write(1, b'O' * 8192); os.write(2, b'E' * 8192)\n"
        "os._exit(7)\n"
    ), timeout=10)
    assert result.returncode == 7
    assert result.stdout == "O" * (48 * 8192)
    assert result.stderr == "E" * (48 * 8192)
    _assert_clean(children[0])


def test_timeout_preserves_both_streams_and_reaps_cli(children):
    seen = []
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        run_streaming(_python(
            "import os, time\n"
            "os.write(1, b'out\\r\\n'); os.write(2, b'err\\n')\n"
            "time.sleep(30)\n"
        ), timeout=1, on_line=lambda stream, line: seen.append((stream, line)))
    assert caught.value.stdout == "out\r\n"
    assert caught.value.stderr == "err\n"
    assert set(seen) == {("stdout", "out"), ("stderr", "err")}
    _assert_clean(children[0])


@pytest.mark.parametrize("exception", [KeyboardInterrupt, RuntimeError])
def test_callback_exception_propagates_after_cleanup(exception, children):
    def callback(stream, line):
        raise exception("callback stopped this run")

    with pytest.raises(exception, match="callback stopped this run"):
        run_streaming(_python(
            "import os, time\nos.write(1, b'ready\\n')\ntime.sleep(30)\n"
        ), timeout=5, on_line=callback)
    _assert_clean(children[0])


def test_closed_streams_do_not_disable_process_timeout(children):
    with pytest.raises(subprocess.TimeoutExpired):
        run_streaming(_python(
            "import os, time\nos.close(1); os.close(2); time.sleep(30)\n"
        ), timeout=1)
    _assert_clean(children[0])


def test_inherited_pipe_handles_do_not_block_reader_shutdown(children):
    # The helper owns/reaps only the CLI. Explicitly clean up its separate
    # descendant here, just as RasDocker separately cleans up its container.
    import psutil

    descendant = None
    try:
        started = time.monotonic()
        result = run_streaming(_python(
            "import os, subprocess, sys\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
            "print(child.pid, flush=True)\nos._exit(9)\n"
        ), timeout=5)
        descendant = psutil.Process(int(result.stdout.strip()))
        assert time.monotonic() - started < 4
        assert result.returncode == 9
        assert descendant.is_running()
        _assert_clean(children[0])
    finally:
        if descendant is not None and descendant.is_running():
            descendant.kill()
            try:
                descendant.wait(timeout=5)
            except psutil.TimeoutExpired:
                # An orphan can remain a zombie until the system reaps it.
                assert descendant.status() == psutil.STATUS_ZOMBIE


def test_command_arguments_are_not_interpreted_as_shell(tmp_path, children):
    argument = "literal ; & $(echo injected) > untouched"
    result = run_streaming(_python("import sys; print(sys.argv[1])", argument), timeout=5)
    assert result.stdout == argument + os.linesep
    assert not (tmp_path / "untouched").exists()
    _assert_clean(children[0])
