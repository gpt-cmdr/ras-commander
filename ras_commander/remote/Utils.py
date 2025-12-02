"""
Utils - Shared utilities for remote execution operations.

This module contains helper functions used across multiple worker implementations.
"""

import subprocess
from pathlib import Path

from ..LoggingConfig import get_logger

logger = get_logger(__name__)


def convert_unc_to_local_path(unc_path: str, share_path: str, local_path: str) -> str:
    """
    Convert UNC path to local path on remote machine.

    PsExec executes commands on the remote machine's local filesystem, so UNC paths
    must be converted to the corresponding local paths.

    Args:
        unc_path: Full UNC path (e.g., \\\\192.168.3.8\\RasRemote\\folder\\file.bat)
        share_path: Base share path (e.g., \\\\192.168.3.8\\RasRemote)
        local_path: Local path on remote machine that share_path maps to (e.g., C:\\RasRemote)

    Returns:
        str: Local path on remote machine (e.g., C:\\RasRemote\\folder\\file.bat)

    Example:
        >>> convert_unc_to_local_path(
        ...     r"\\\\192.168.3.8\\RasRemote\\temp\\file.bat",
        ...     r"\\\\192.168.3.8\\RasRemote",
        ...     r"C:\\RasRemote"
        ... )
        'C:\\\\RasRemote\\\\temp\\\\file.bat'
    """
    # Normalize paths (handle both \\ and \ separators)
    unc_normalized = unc_path.replace('/', '\\')
    share_normalized = share_path.replace('/', '\\').rstrip('\\')
    local_normalized = local_path.replace('/', '\\').rstrip('\\')

    # Replace the share path prefix with local path
    if unc_normalized.lower().startswith(share_normalized.lower()):
        relative_part = unc_normalized[len(share_normalized):]
        return local_normalized + relative_part
    else:
        # If UNC path doesn't start with share_path, return as-is
        logger.warning(
            f"UNC path '{unc_path}' doesn't start with share_path '{share_path}'. "
            f"Returning path as-is."
        )
        return unc_path


def authenticate_network_share(share_path: str, username: str, password: str) -> bool:
    """
    Authenticate to a network share using net use command.

    This establishes a connection to the remote share using the provided credentials,
    allowing subsequent file operations (copy, mkdir) to succeed.

    Args:
        share_path: UNC path to share (e.g., \\\\hostname\\ShareName)
        username: Username for authentication (e.g., .\\user or DOMAIN\\user)
        password: Password for authentication

    Returns:
        bool: True if authentication succeeded or share already accessible
    """
    # Extract base share path (\\hostname\ShareName) from full path
    share_parts = share_path.strip('\\').split('\\')
    if len(share_parts) >= 2:
        base_share = f"\\\\{share_parts[0]}\\{share_parts[1]}"
    else:
        base_share = share_path

    # First, try to disconnect any existing connection (ignore errors)
    try:
        subprocess.run(
            ["net", "use", base_share, "/delete", "/y"],
            capture_output=True,
            timeout=30
        )
    except Exception:
        pass

    # Establish new connection with credentials
    try:
        result = subprocess.run(
            ["net", "use", base_share, f"/user:{username}", password],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            logger.debug(f"Successfully authenticated to {base_share}")
            return True
        else:
            # Check if already connected (error 1219 = multiple connections not allowed)
            if "1219" in result.stderr or "already" in result.stderr.lower():
                logger.debug(f"Share {base_share} already connected")
                return True
            logger.error(f"Failed to authenticate to {base_share}: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        logger.error(f"Timeout authenticating to {base_share}")
        return False
    except Exception as e:
        logger.error(f"Error authenticating to {base_share}: {e}")
        return False
