"""Capture a Docker CLI process while delivering its output on the caller thread.

This module owns only the launched CLI process. The caller remains responsible
for stopping any Docker container that the CLI started.
"""

from __future__ import annotations

import codecs
import os
from queue import Empty, Queue
import subprocess
import threading
import time
from typing import Callable, Optional


_POLL_SECONDS = 0.02
_READ_SIZE = 65536


def _windows_available(file_descriptor):
    """Return a Windows pipe poller; anonymous pipes cannot use select()."""
    import ctypes
    from ctypes import wintypes
    import msvcrt

    handle = msvcrt.get_osfhandle(file_descriptor)
    peek = ctypes.WinDLL("kernel32", use_last_error=True).PeekNamedPipe
    peek.argtypes = (
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
        wintypes.LPDWORD, wintypes.LPDWORD, wintypes.LPDWORD,
    )
    peek.restype = wintypes.BOOL

    def available():
        count = wintypes.DWORD()
        if peek(handle, None, 0, None, ctypes.byref(count), None):
            return count.value
        error = ctypes.get_last_error()
        if error in {109, 232, 233}:  # Broken/disconnected pipe: no writers remain.
            return None
        raise ctypes.WinError(error)

    return available


def _read_pipe(process, pipe, stream, events, stop):
    """Read without an uncancellable blocking read, including on Windows."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    try:
        descriptor = pipe.fileno()
        if os.name == "nt":
            available = _windows_available(descriptor)
        else:
            os.set_blocking(descriptor, False)
            available = None

        while not stop.is_set():
            count = _READ_SIZE
            if available is not None:
                count = available()
                if count is None:
                    break
                if count == 0:
                    # A descendant may retain the pipe after the CLI exits.
                    if process.poll() is not None:
                        break
                    stop.wait(_POLL_SECONDS)
                    continue
            try:
                chunk = os.read(descriptor, min(count, _READ_SIZE))
            except BlockingIOError:
                if process.poll() is not None:
                    break
                stop.wait(_POLL_SECONDS)
                continue
            if not chunk:
                break
            text = decoder.decode(chunk)
            if text:
                events.put(("text", stream, text))
    except Exception as error:
        events.put(("error", stream, error))
    finally:
        tail = decoder.decode(b"", final=True)
        if tail:
            events.put(("text", stream, tail))
        pipe.close()
        events.put(("eof", stream, None))


class _Lines:
    """Incrementally split LF, CRLF and progress updates ending in lone CR."""

    def __init__(self):
        self.pending = ""
        self.after_cr = False

    def feed(self, text):
        # CR is emitted immediately; suppress a following LF across chunks.
        start = 0
        for index, character in enumerate(text):
            if self.after_cr:
                self.after_cr = False
                if character == "\n":
                    start = index + 1
                    continue
            if character in "\r\n":
                line = self.pending + text[start:index]
                self.pending = ""
                self.after_cr = character == "\r"
                start = index + 1
                yield line
        self.pending += text[start:]

    def finish(self):
        if self.pending:
            line, self.pending = self.pending, ""
            return line
        return None


def _finish_process(process, readers, stop):
    """Reap the CLI, drain available bytes, and join both cancellable readers."""
    try:
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        process.wait()
    finally:
        # Usually the readers immediately drain to EOF after the CLI exits.
        # Bound draining in case a descendant keeps writing inherited handles.
        deadline = time.monotonic() + 1.0
        for reader in readers:
            reader.join(timeout=max(0.0, deadline - time.monotonic()))
        stop.set()
        for reader in readers:
            reader.join()


def run_streaming(
    command: list,
    timeout: int,
    on_line: Optional[Callable[[str, str], None]] = None,
) -> subprocess.CompletedProcess:
    """Run one CLI process and deliver decoded output lines as they arrive.

    ``on_line(stream, line)`` executes on the calling thread; ``stream`` is
    ``"stdout"`` or ``"stderr"``. Terminators are omitted, empty lines are
    retained, and an unterminated final line is delivered at EOF. A lone CR
    emits a progress line immediately; CRLF emits only one line, including
    when the two characters arrive in separate reads. Callbacks should return
    promptly. Their exceptions, including KeyboardInterrupt, propagate after
    the CLI is killed/reaped and its reader threads are joined.

    Both CompletedProcess streams contain the full UTF-8-decoded output with
    original line endings retained and invalid bytes replaced. Ordering is
    preserved within each stream; ordering between streams is unspecified.
    Nonzero exits return normally. TimeoutExpired carries captured ``stdout``
    and ``stderr`` as strings. No shell is involved and stdin is closed.

    Reader shutdown does not wait for unrelated descendants to close inherited
    pipe handles. This helper does not terminate Docker containers; callers
    must perform their own container cleanup.
    """
    started = time.monotonic()
    process = subprocess.Popen(
        command, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        bufsize=0, shell=False,
    )
    events = Queue()
    stop = threading.Event()
    readers = []
    captured = {"stdout": [], "stderr": []}
    lines = {"stdout": _Lines(), "stderr": _Lines()}
    finished = set()
    failure = None

    def retain_queued_output():
        while True:
            try:
                kind, stream, value = events.get_nowait()
            except Empty:
                break
            if kind == "text":
                captured[stream].append(value)

    try:
        for stream in ("stdout", "stderr"):
            reader = threading.Thread(
                target=_read_pipe,
                args=(process, getattr(process, stream), stream, events, stop),
                name=f"ras-container-{process.pid}-{stream}",
            )
            reader.start()
            readers.append(reader)

        while len(finished) < 2 or process.poll() is None:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                kind, stream, value = events.get(timeout=min(_POLL_SECONDS, remaining))
            except Empty:
                continue
            if kind == "text":
                captured[stream].append(value)
                if on_line is not None:
                    for line in lines[stream].feed(value):
                        on_line(stream, line)
            elif kind == "eof":
                finished.add(stream)
                tail = lines[stream].finish()
                if tail is not None and on_line is not None:
                    on_line(stream, tail)
            else:
                raise value

        return subprocess.CompletedProcess(
            command, process.wait(),
            stdout="".join(captured["stdout"]),
            stderr="".join(captured["stderr"]),
        )
    except BaseException as error:
        # The caller must distinguish a failed Popen from later transport I/O
        # failure: killing the CLI does not stop a container it already started.
        error._ras_container_cli_started = True
        failure = error
        raise
    finally:
        _finish_process(process, readers, stop)
        retain_queued_output()
        if isinstance(failure, subprocess.TimeoutExpired):
            failure.output = "".join(captured["stdout"])
            failure.stderr = "".join(captured["stderr"])
        # Covers a failure starting either reader before it can own its pipe.
        for pipe in (process.stdout, process.stderr):
            if pipe is not None and not pipe.closed:
                pipe.close()
