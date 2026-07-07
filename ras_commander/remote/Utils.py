"""
Utils - Shared utilities for remote execution operations.

This module contains helper functions used across multiple worker implementations.
"""

import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Union

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


def copy_plan_hdf_back(
    worker_project_path: Union[str, Path],
    plan_number: str,
    ras_obj,
) -> Optional[Path]:
    """
    Copy the plan result HDF for *plan_number* back from a worker.
    """
    from ..RasCurrency import RasCurrency

    worker_project_path = Path(worker_project_path)
    dest_hdf = RasCurrency.get_plan_hdf_path(plan_number, ras_obj)
    worker_hdf = worker_project_path / dest_hdf.name

    if not worker_hdf.exists():
        logger.error(f"Worker plan HDF not found: {worker_hdf}")
        return None

    shutil.copy2(worker_hdf, dest_hdf)
    logger.info(
        "Copied plan result HDF for plan %s: %s",
        str(plan_number).zfill(2),
        dest_hdf.name,
    )
    logger.debug(
        "Copied plan result HDF for plan %s: %s -> %s",
        str(plan_number).zfill(2),
        worker_hdf,
        dest_hdf,
    )
    return dest_hdf


def clear_worker_plan_hdf_artifacts(
    worker_project_path: Union[str, Path],
    plan_number: str,
    ras_obj,
) -> List[Path]:
    """
    Remove copied/stale plan HDF artifacts from a staged worker project.

    Worker projects are copied from the source project before execution. If the
    source project already has a plan HDF, the staged copy can otherwise look
    like a successful worker output even when the remote execution failed.
    """
    from ..RasCurrency import RasCurrency

    worker_project_path = Path(worker_project_path)
    plan_hdf = RasCurrency.get_plan_hdf_path(plan_number, ras_obj)
    candidate_names = {plan_hdf.name, f"{plan_hdf.stem}.tmp.hdf"}
    removed: List[Path] = []

    for file_name in candidate_names:
        worker_hdf = worker_project_path / file_name
        if worker_hdf.exists():
            worker_hdf.unlink()
            removed.append(worker_hdf)
            logger.debug(f"Removed stale worker result artifact: {worker_hdf}")

    return removed


def _resolve_geompre_path(
    project_folder: Path,
    project_name: str,
    plan_number: str,
    ras_obj,
    geom_hdf_path: Path,
) -> Optional[Path]:
    """
    Resolve the source-project .c## path for a plan's geometry.

    Prefer ras-commander metadata via RasCurrency. The filename fallback is
    retained for thin test doubles and legacy RasPrj objects without geom paths.
    """
    from ..RasCurrency import RasCurrency

    input_files = RasCurrency.get_plan_input_files(plan_number, ras_obj)
    geom_path = input_files.get("geom")
    if geom_path:
        geom_path = Path(geom_path)
        suffix = geom_path.suffix
        if suffix.lower().startswith(".g") and len(suffix) > 2:
            return geom_path.with_suffix(f".c{suffix[2:]}")

    geom_token = geom_hdf_path.stem.rsplit(".g", 1)[-1]
    if geom_token and geom_token != geom_hdf_path.stem:
        return project_folder / f"{project_name}.c{geom_token}"

    return None


def copy_geometry_outputs_back(
    worker_project_path: Union[str, Path],
    project_folder: Union[str, Path],
    project_name: str,
    plan_number: str,
    ras_obj,
    require_geom_hdf: bool = True,
) -> List[Path]:
    """
    Copy geometry-preprocessor outputs for *plan_number* back from a worker.

    HEC-RAS writes important preprocessing products, including 2D per-cell
    Manning's n, into the geometry HDF. Remote workers execute against a staged
    project copy, so plan-result copyback alone leaves the source project with
    stale geometry preprocessing state.
    """
    from ..RasCurrency import RasCurrency

    worker_project_path = Path(worker_project_path)
    project_folder = Path(project_folder)
    copied: List[Path] = []

    source_geom_hdf = RasCurrency.get_geom_hdf_path(plan_number, ras_obj)
    if source_geom_hdf is None:
        message = f"Could not resolve geometry HDF for plan {plan_number}"
        if require_geom_hdf:
            raise FileNotFoundError(message)
        logger.debug(message)
        return copied

    source_geom_hdf = Path(source_geom_hdf)
    worker_geom_hdf = worker_project_path / source_geom_hdf.name
    if worker_geom_hdf.exists():
        shutil.copy2(worker_geom_hdf, source_geom_hdf)
        copied.append(source_geom_hdf)
        logger.info(
            "Copied geometry HDF for plan %s: %s",
            str(plan_number).zfill(2),
            source_geom_hdf.name,
        )
        logger.debug(
            "Copied geometry HDF for plan %s: %s -> %s",
            str(plan_number).zfill(2),
            worker_geom_hdf,
            source_geom_hdf,
        )
    else:
        message = f"Worker geometry HDF not found: {worker_geom_hdf}"
        if require_geom_hdf:
            raise FileNotFoundError(message)
        logger.warning(message)

    source_geompre = _resolve_geompre_path(
        project_folder=project_folder,
        project_name=project_name,
        plan_number=plan_number,
        ras_obj=ras_obj,
        geom_hdf_path=source_geom_hdf,
    )
    if source_geompre:
        worker_geompre = worker_project_path / source_geompre.name
        if worker_geompre.exists():
            shutil.copy2(worker_geompre, source_geompre)
            copied.append(source_geompre)
            logger.info(
                "Copied geometry preprocessor file for plan %s: %s",
                str(plan_number).zfill(2),
                source_geompre.name,
            )
            logger.debug(
                "Copied geometry preprocessor file for plan %s: %s -> %s",
                str(plan_number).zfill(2),
                worker_geompre,
                source_geompre,
            )

    return copied


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
