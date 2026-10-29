"""Owned transport for serialized sloping requests to a persistent Rust process."""

import json
import subprocess
import tempfile

from .errors import FimEngineError


class NativeSlopingSession:
    def __init__(self, engine):
        self.errors = tempfile.TemporaryFile(mode="w+b")
        try:
            self.process = subprocess.Popen(
                [str(engine), "sloping-server"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.errors,
            )
        except BaseException:
            self.errors.close()
            raise

    def submit(self, request, output):
        if self.process.poll() is not None:
            raise FimEngineError("Prepared native session exited unexpectedly")
        command = (
            json.dumps(
                {"request": str(request.resolve()), "output": str(output.resolve())}
            ).encode()
            + b"\n"
        )
        if len(command) > 65536:
            raise FimEngineError("Native session command exceeds protocol limit")
        try:
            self.process.stdin.write(command)
            self.process.stdin.flush()
        except OSError as exc:
            raise FimEngineError("Prepared native session command failed") from exc
        return self.process

    def close(self):
        if self.process.poll() is None:
            # Killing avoids an unbounded wait if a worker became stuck.
            self.process.kill()
        self.process.wait()
        try:
            try:
                self.process.stdin.close()
            except OSError:
                pass  # A terminated worker may have unflushed pipe bytes.
            self.process.stdout.close()
        finally:
            self.errors.close()
