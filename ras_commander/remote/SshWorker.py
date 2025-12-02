"""
SshWorker - SSH-based remote execution for Linux/Mac systems.

This module implements the SshWorker class for executing HEC-RAS on remote
machines via SSH connections.

IMPLEMENTATION STATUS: STUB - Future Development

Requirements:
    pip install ras-commander[remote-ssh]
    # or: pip install paramiko
"""

from dataclasses import dataclass
from typing import Optional

from .RasWorker import RasWorker
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


def check_ssh_dependencies():
    """
    Check if paramiko is available, raise clear error if not.

    This function is called lazily only when SSH functionality is actually used.
    """
    try:
        import paramiko
        return paramiko
    except ImportError:
        raise ImportError(
            "SSH worker requires paramiko.\n"
            "Install with: pip install ras-commander[remote-ssh]\n"
            "Or: pip install paramiko"
        )


@dataclass
class SshWorker(RasWorker):
    """
    SSH-based remote execution worker for Linux/Mac systems.

    IMPLEMENTATION STATUS: STUB - Future Development

    IMPLEMENTATION NOTES:
    When implemented, this worker will:
    1. Use paramiko library for SSH connections
    2. Deploy projects via scp or rsync
    3. Execute HEC-RAS using SSH remote command execution
    4. Support SSH key-based or password authentication
    5. Work with Linux/Mac HEC-RAS installations (if available) or Wine

    Required Parameters:
        - hostname: SSH server hostname/IP
        - port: SSH port (default 22)
        - username: SSH username
        - auth_method: "password" or "key"
        - password or key_path: Authentication credentials
        - remote_path: Remote directory for project deployment

    Usage Pattern:
        ssh_worker = init_ras_worker(
            "ssh",
            hostname="linux-server.example.com",
            port=22,
            username="user",
            auth_method="key",
            key_path="/home/user/.ssh/id_rsa",
            remote_path="/tmp/ras_runs",
            ras_exe_path="/opt/hecras/bin/ras"
        )

    Dependencies:
        - paramiko: SSH client library
        - scp or subprocess for rsync: File transfer
    """
    port: int = 22
    username: str = None
    auth_method: str = "password"
    password: str = None
    key_path: str = None
    remote_path: str = None

    def __post_init__(self):
        super().__post_init__()
        self.worker_type = "ssh"
        raise NotImplementedError(
            "SshWorker is not yet implemented. "
            "Planned for future release. "
            "Will use paramiko for SSH connections and scp/rsync for file transfer.\n"
            "Requires: pip install ras-commander[remote-ssh]"
        )


def init_ssh_worker(**kwargs) -> SshWorker:
    """Initialize SSH worker (stub - raises NotImplementedError)."""
    check_ssh_dependencies()
    kwargs['worker_type'] = 'ssh'
    return SshWorker(**kwargs)
