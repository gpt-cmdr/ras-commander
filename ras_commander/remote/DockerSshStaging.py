"""
DockerSshStaging - SSH/SFTP file staging helpers for native-Linux Docker hosts.

When a DockerWorker targets a native-Linux Docker daemon over an ``ssh://`` URL
(e.g. CLB07), there is no Windows UNC share to copy project files into. Instead
the project is transferred to a Linux staging directory on the Docker host using
SSH (SFTP via paramiko, or scp/ssh via the system client) and results are copied
back the same way.

This module is intentionally self-contained so the Windows-Docker-Desktop code
path in :mod:`DockerWorker` is left completely untouched.

Two transports are supported, matching the existing ``use_ssh_client`` option:

    - paramiko (default): in-process SSH/SFTP, no external ssh binary required.
    - system ssh client (``use_ssh_client=True``): shells out to ``ssh``/``scp``
      so that SSH agent and ``~/.ssh/config`` settings are honored.

The host/user/port are parsed from the ``ssh://user@host:port`` Docker host URL.
"""

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import List, Optional
from urllib.parse import urlparse

from ..LoggingConfig import get_logger

logger = get_logger(__name__)


@dataclass
class SshTarget:
    """Parsed connection details for an ``ssh://user@host:port`` Docker host."""

    host: str
    user: Optional[str] = None
    port: int = 22

    @property
    def user_host(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host


def parse_ssh_host(docker_host: str) -> SshTarget:
    """
    Parse an ``ssh://user@host[:port]`` Docker host URL into an SshTarget.

    Args:
        docker_host: e.g. "ssh://root@192.168.3.81" or "ssh://root@host:2222"

    Returns:
        SshTarget with host, user, and port.

    Raises:
        ValueError: if the URL is not an ssh:// URL or has no host.
    """
    if not docker_host or not docker_host.startswith("ssh://"):
        raise ValueError(
            f"Linux Docker host requires an ssh:// URL, got: {docker_host!r}"
        )
    parsed = urlparse(docker_host)
    if not parsed.hostname:
        raise ValueError(f"Could not parse host from ssh URL: {docker_host!r}")
    return SshTarget(
        host=parsed.hostname,
        user=parsed.username,
        port=parsed.port or 22,
    )


def _is_windows_reserved(name: str) -> bool:
    """Local helper mirroring RasUtils.is_windows_reserved_name without import cost."""
    reserved = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    stem = name.split(".")[0].upper()
    return stem in reserved


def _iter_project_files(local_dir: Path):
    """
    Yield (absolute_local_path, posix_relative_path) for every file under
    local_dir, skipping Windows reserved names.
    """
    local_dir = Path(local_dir)
    for path in sorted(local_dir.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(local_dir)
        if any(_is_windows_reserved(part) for part in rel.parts):
            continue
        yield path, PurePosixPath(*rel.parts)


class LinuxDockerSshStager:
    """
    Stages files to and from a native-Linux Docker host over SSH.

    Usage:
        stager = LinuxDockerSshStager(worker)
        stager.mkdirs([input_remote, output_remote])
        stager.upload_dir(local_input, input_remote)
        ... run container ...
        stager.download_matching(output_remote, ["*.hdf"], local_dest)
        stager.rmtree(staging_root)
    """

    def __init__(
        self,
        docker_host: str,
        use_ssh_client: bool = False,
        ssh_key_path: Optional[str] = None,
    ):
        self.target = parse_ssh_host(docker_host)
        self.use_ssh_client = use_ssh_client
        self.ssh_key_path = (
            os.path.expanduser(ssh_key_path) if ssh_key_path else None
        )

    # ------------------------------------------------------------------ #
    # paramiko transport
    # ------------------------------------------------------------------ #
    def _paramiko_client(self):
        import paramiko

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kwargs = {
            "hostname": self.target.host,
            "port": self.target.port,
            "username": self.target.user,
        }
        # Allow an explicit key, the env var workaround, or agent/default keys.
        key_file = self.ssh_key_path or os.environ.get("DOCKER_SSH_KEY_FILE")
        if key_file and os.path.exists(key_file):
            connect_kwargs["key_filename"] = key_file
        connect_kwargs["look_for_keys"] = True
        connect_kwargs["allow_agent"] = True
        # Bound the connect handshake so an unreachable/slow Linux Docker host
        # can never block a worker thread forever (the original deadlock that
        # wedged the whole ensemble). paramiko's connect() is unbounded by
        # default.
        connect_kwargs["timeout"] = 30          # TCP connect
        connect_kwargs["banner_timeout"] = 30   # SSH banner
        connect_kwargs["auth_timeout"] = 30     # authentication
        client.connect(**connect_kwargs)
        return client

    # ------------------------------------------------------------------ #
    # system ssh/scp transport
    # ------------------------------------------------------------------ #
    def _ssh_base_args(self) -> List[str]:
        args = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
        if self.target.port != 22:
            args += ["-p", str(self.target.port)]
        if self.ssh_key_path:
            args += ["-i", self.ssh_key_path]
        return args

    def _scp_base_args(self) -> List[str]:
        args = ["scp", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-r"]
        if self.target.port != 22:
            args += ["-P", str(self.target.port)]
        if self.ssh_key_path:
            args += ["-i", self.ssh_key_path]
        return args

    def _run_ssh_command(self, remote_cmd: str) -> None:
        args = self._ssh_base_args() + [self.target.user_host, remote_cmd]
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Remote command failed ({result.returncode}): {remote_cmd}\n"
                f"stderr: {result.stderr.strip()}"
            )

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def mkdirs(self, remote_dirs: List[str]) -> None:
        """Create remote directories (recursively) on the Linux host."""
        quoted = " ".join(shlex.quote(str(d)) for d in remote_dirs)
        cmd = f"mkdir -p {quoted}"
        if self.use_ssh_client:
            self._run_ssh_command(cmd)
        else:
            client = self._paramiko_client()
            try:
                stdin, stdout, stderr = client.exec_command(cmd, timeout=120)
                chan = stdout.channel
                # Bound recv_exit_status: the bare call blocks forever if the
                # channel never signals exit. status_event.wait() is timeout-able.
                if not chan.status_event.wait(120):
                    raise RuntimeError(
                        f"remote 'mkdir -p' timed out after 120s on {self.target.host}"
                    )
                rc = chan.recv_exit_status()
                if rc != 0:
                    err = stderr.read().decode("utf-8", "replace")
                    raise RuntimeError(f"mkdir -p failed ({rc}): {err}")
            finally:
                client.close()

    def upload_dir(self, local_dir: Path, remote_dir: str) -> int:
        """
        Upload every file under local_dir into remote_dir, preserving the
        relative directory structure. Returns the number of files uploaded.
        """
        local_dir = Path(local_dir)
        remote_root = PurePosixPath(remote_dir)
        files = list(_iter_project_files(local_dir))

        if self.use_ssh_client:
            # scp -r the whole directory's contents.
            self.mkdirs([str(remote_root)])
            # Upload each subtree at top level for structure fidelity.
            for child in sorted(local_dir.iterdir()):
                if _is_windows_reserved(child.name):
                    continue
                args = self._scp_base_args() + [
                    str(child),
                    f"{self.target.user_host}:{shlex.quote(str(remote_root))}/",
                ]
                # shlex.quote already applied to remote path component; scp target
                # must not be shell-quoted by us, rebuild cleanly:
                args[-1] = f"{self.target.user_host}:{remote_root}/"
                result = subprocess.run(
                    args, capture_output=True, text=True, timeout=600
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"scp upload failed for {child}: {result.stderr.strip()}"
                    )
            return len(files)

        # paramiko SFTP transport
        client = self._paramiko_client()
        try:
            sftp = client.open_sftp()
            made = set()

            def _ensure_remote_dir(rdir: PurePosixPath):
                parts = rdir.parts
                cur = PurePosixPath(parts[0]) if parts else rdir
                # Build progressively from root.
                accum = PurePosixPath("/") if str(rdir).startswith("/") else PurePosixPath("")
                for part in parts:
                    if part == "/":
                        continue
                    accum = accum / part
                    key = str(accum)
                    if key in made:
                        continue
                    try:
                        sftp.stat(key)
                    except IOError:
                        try:
                            sftp.mkdir(key)
                        except IOError:
                            pass
                    made.add(key)

            _ensure_remote_dir(remote_root)
            for local_path, rel in files:
                remote_path = remote_root / rel
                _ensure_remote_dir(remote_path.parent)
                sftp.put(str(local_path), str(remote_path))
            sftp.close()
            return len(files)
        finally:
            client.close()

    def list_matching(self, remote_dir: str, patterns: List[str]) -> List[str]:
        """Return remote file paths in remote_dir matching any glob pattern."""
        remote_root = PurePosixPath(remote_dir)
        if self.use_ssh_client:
            # Use a remote shell glob.
            globs = " ".join(
                shlex.quote(str(remote_root / p)) for p in patterns
            )
            cmd = f"ls -1 {globs} 2>/dev/null || true"
            args = self._ssh_base_args() + [self.target.user_host, cmd]
            result = subprocess.run(args, capture_output=True, text=True, timeout=120)
            lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
            return lines

        import fnmatch

        client = self._paramiko_client()
        try:
            sftp = client.open_sftp()
            try:
                names = sftp.listdir(str(remote_root))
            except IOError:
                names = []
            matches = []
            for name in names:
                if any(fnmatch.fnmatch(name, p) for p in patterns):
                    matches.append(str(remote_root / name))
            sftp.close()
            return matches
        finally:
            client.close()

    def download_files(self, remote_files: List[str], local_dest: Path) -> List[Path]:
        """Download specific remote files into local_dest. Returns local paths."""
        local_dest = Path(local_dest)
        local_dest.mkdir(parents=True, exist_ok=True)
        downloaded: List[Path] = []

        if self.use_ssh_client:
            for rfile in remote_files:
                name = PurePosixPath(rfile).name
                args = self._scp_base_args() + [
                    f"{self.target.user_host}:{rfile}",
                    str(local_dest / name),
                ]
                result = subprocess.run(
                    args, capture_output=True, text=True, timeout=600
                )
                if result.returncode != 0:
                    logger.warning(
                        f"scp download failed for {rfile}: {result.stderr.strip()}"
                    )
                    continue
                downloaded.append(local_dest / name)
            return downloaded

        client = self._paramiko_client()
        try:
            sftp = client.open_sftp()
            for rfile in remote_files:
                name = PurePosixPath(rfile).name
                local_path = local_dest / name
                try:
                    sftp.get(rfile, str(local_path))
                    downloaded.append(local_path)
                except IOError as e:
                    logger.warning(f"SFTP download failed for {rfile}: {e}")
            sftp.close()
            return downloaded
        finally:
            client.close()

    def rmtree(self, remote_dir: str) -> None:
        """Remove a remote directory tree (best effort)."""
        cmd = f"rm -rf {shlex.quote(str(remote_dir))}"
        try:
            if self.use_ssh_client:
                self._run_ssh_command(cmd)
            else:
                client = self._paramiko_client()
                try:
                    stdin, stdout, stderr = client.exec_command(cmd, timeout=120)
                    chan = stdout.channel
                    if not chan.status_event.wait(120):
                        raise RuntimeError(
                            f"remote cleanup timed out after 120s on {self.target.host}"
                        )
                    chan.recv_exit_status()
                finally:
                    client.close()
        except Exception as e:
            logger.debug(f"Remote cleanup failed for {remote_dir}: {e}")
