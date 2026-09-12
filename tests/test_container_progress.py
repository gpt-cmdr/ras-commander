"""Native log transport tests; the child processes write text, never run HEC-RAS."""

import io
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

import pytest

from ras_commander import _container_compute as worker
from test_container_compute import packet as _packet_fixture, _fake_success, _run

packet = _packet_fixture


class FlushedText(io.StringIO):
    def __init__(self):
        super().__init__()
        self.flushes = 0

    def flush(self):
        self.flushes += 1
        super().flush()


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 65536])
def test_line_delimiters_and_utf8_across_chunks(chunk_size):
    output = FlushedText()
    progress = worker._ProgressText(output)
    original = "first\r\nsecond\rthird\n\nrepeat\rrepeat\nlast π".encode()
    for offset in range(0, len(original), chunk_size):
        progress.feed(original[offset:offset + chunk_size])
    progress.feed(b"", final=True)
    assert output.getvalue() == "first\nsecond\nthird\n\nrepeat\nrepeat\nlast π"
    assert output.flushes == 7


def test_unterminated_long_line_is_bounded_and_not_discarded():
    output = FlushedText()
    progress = worker._ProgressText(output)
    block = b"x" * 65536
    for _ in range(8):
        progress.feed(block)
        assert len(progress.pending) < progress.fragment_size
    # A long line must reach the transport before any newline or completion.
    assert len(output.getvalue()) == 8 * len(block)
    progress.feed(b"end\xff", final=True)
    assert output.getvalue() == "x" * (8 * len(block)) + "end\ufffd"


def test_no_log_created_stops_promptly_and_joins(tmp_path):
    output = FlushedText()
    started = time.monotonic()
    with worker._forward_native_progress(tmp_path / "missing.log", stream=output,
                                         poll_interval=10) as thread:
        assert thread.is_alive()
    assert not thread.is_alive()
    assert time.monotonic() - started < 2
    assert output.getvalue() == ""


def test_final_fragment_drained_when_compute_raises(tmp_path):
    log = tmp_path / "compute_linux_01.log"
    output = FlushedText()
    with pytest.raises(RuntimeError, match="compute failed"):
        with worker._forward_native_progress(log, stream=output, poll_interval=10) as thread:
            log.write_bytes(b"error detail without newline")
            raise RuntimeError("compute failed")
    assert not thread.is_alive()
    assert output.getvalue() == "error detail without newline"
    assert log.read_bytes() == b"error detail without newline"


def test_broken_progress_sink_does_not_replace_compute_outcome(tmp_path, caplog):
    class BrokenSink:
        def write(self, text):
            raise BrokenPipeError("disconnected progress listener")

    log = tmp_path / "compute_linux_01.log"
    log.write_bytes(b"solver message\n")
    with worker._forward_native_progress(log, stream=BrokenSink()) as thread:
        result = "original compute result"
    assert result == "original compute result"
    assert not thread.is_alive()
    assert "Native progress forwarding stopped" in caplog.text


# Handshake keeps the writer alive until its first log line has crossed the
# real stderr pipe. These are transport fixtures, not hydraulic-model mocks.
WRITER = r'''
from pathlib import Path
import sys
import time
log, release = map(Path, sys.argv[1:3])
with log.open("wb", buffering=0) as stream:
    stream.write(b"step 1\r")
    deadline = time.monotonic() + 20
    while not release.exists():
        if time.monotonic() > deadline:
            raise RuntimeError("test did not acknowledge live progress")
        time.sleep(0.01)
    stream.write(b"\nstep 2\nfinal fragment \xcf")
    stream.write(b"\x80")
sys.exit(int(sys.argv[3]))
'''

FORWARDER = r'''
import json
from pathlib import Path
import subprocess
import sys
sys.stderr.reconfigure(encoding="utf-8")
from ras_commander._container_compute import _forward_native_progress
log, release = map(Path, sys.argv[1:3])
try:
    with _forward_native_progress(log, poll_interval=0.01):
        subprocess.run([sys.executable, "-u", "-c", sys.argv[4], str(log),
                        str(release), sys.argv[3]], check=True)
    success = True
except subprocess.CalledProcessError:
    success = False
print(json.dumps({"success": success}), flush=True)
sys.exit(0 if success else 1)
'''


@pytest.mark.parametrize("writer_exit", [0, 4])
def test_stderr_progress_arrives_before_process_exit_and_final_json(tmp_path, writer_exit):
    log, release = tmp_path / "compute_linux_01.log", tmp_path / "acknowledged"
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", FORWARDER, str(log), str(release),
         str(writer_exit), WRITER],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace")
    messages = queue.Queue()

    def read_stderr():
        for line in process.stderr:
            messages.put(line)
        messages.put(None)

    reader = threading.Thread(target=read_stderr, daemon=True)
    reader.start()
    try:
        assert messages.get(timeout=20) == "step 1\n"
        assert process.poll() is None
        assert not release.exists()
        # Repeated EOF polls may not replay the first line.
        with pytest.raises(queue.Empty):
            messages.get(timeout=0.15)
        release.touch()
        assert process.wait(timeout=20) == (0 if writer_exit == 0 else 1)
        reader.join(timeout=5)
        assert not reader.is_alive()
        assert messages.get_nowait() == "step 2\n"
        assert messages.get_nowait() == "final fragment π"
        assert messages.get_nowait() is None
        assert messages.empty()
        assert json.loads(process.stdout.read()) == {"success": writer_exit == 0}
        assert log.read_bytes() == b"step 1\r\nstep 2\nfinal fragment \xcf\x80"
    finally:
        # Release the owned text writer before terminating its parent if an
        # assertion failed; this avoids leaving an orphan waiting for our gate.
        release.touch(exist_ok=True)
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        reader.join(timeout=5)
        process.stdout.close()
        process.stderr.close()


def test_compute_worker_forwards_staged_log_and_preserves_json_contract(packet, monkeypatch, capsys):
    monkeypatch.setattr(worker, "_call_compute", _fake_success)
    success, receipt = _run(packet, prepare_receipt=packet["prep"])
    assert success
    captured = capsys.readouterr()
    assert captured.err == "Finished Unsteady Flow Simulation\n"
    assert captured.out == ""
    assert json.loads(receipt.read_text())["status"] == "succeeded"
    assert not list(packet["scratch"].iterdir())


@pytest.mark.parametrize("num_cores", [1, 8])
def test_worker_accepts_core_policy_boundaries(packet, monkeypatch, num_cores):
    seen = []

    def compute(project, engine, plan, timeout, cores):
        seen.append(cores)
        return _fake_success(project, engine, plan, timeout, cores)

    monkeypatch.setattr(worker, "_call_compute", compute)
    success, receipt = _run(packet, prepare_receipt=packet["prep"], num_cores=num_cores)
    assert success
    assert seen == [num_cores]
    assert json.loads(receipt.read_text())["arguments"]["num_cores"] == num_cores


def test_worker_rejects_more_than_eight_cores_before_starting(packet, monkeypatch):
    def forbidden(*args):
        pytest.fail("Invalid CPU allocation must not reach the solver")

    monkeypatch.setattr(worker, "_call_compute", forbidden)
    with pytest.raises(ValueError, match="between 1 and 8"):
        _run(packet, num_cores=9)
    assert not (packet["root"] / ".ras-commander" / "runs" / "compute").exists()
