"""
PsexecWorker - Windows remote execution via Microsoft Sysinternals PsExec.

This module implements the PsexecWorker class for executing HEC-RAS on remote
Windows machines using PsExec over network shares.

IMPLEMENTATION STATUS: ✓ FULLY IMPLEMENTED
"""

import subprocess
import shutil
import time
import uuid
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from .RasWorker import RasWorker
from .Utils import convert_unc_to_local_path, authenticate_network_share
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


@dataclass
class PsexecWorker(RasWorker):
    """
    PsExec-based Windows remote execution worker.

    Uses Microsoft Sysinternals PsExec to execute HEC-RAS on remote Windows machines
    via network share deployment.

    IMPLEMENTATION STATUS: ✓ FULLY IMPLEMENTED

    Attributes:
        share_path: UNC path to accessible network share (e.g., \\\\hostname\\RasRemote)
        worker_folder: Local path on remote machine that corresponds to share_path.
                      This is the actual folder path on the remote machine's filesystem.
                      Example: If share_path is \\\\hostname\\RasRemote and the share points
                      to C:\\RasRemote on the remote machine, set worker_folder="C:\\RasRemote".
                      If not specified, defaults to "C:\\{share_name}" (e.g., C:\\RasRemote).
        credentials: Dict with 'username' and 'password' for remote authentication.
                    OPTIONAL for trusted networks. When omitted (empty dict or None),
                    PsExec uses the current user's Windows authentication, which:
                    - Works on domain-joined machines with proper trust
                    - Avoids the "secondary logon" issue that prevents GUI access
                    - Is RECOMMENDED for most internal network setups
                    When credentials ARE provided, the specified user must be the same
                    user logged into the remote desktop session, or have
                    "Replace a process level token" (SeAssignPrimaryTokenPrivilege) right.
        session_id: Session ID to run in (default 2 - typical for single-user workstations)
        process_priority: OS process priority for HEC-RAS execution on remote machine.
                         Valid values: "low" (default), "below normal", "normal".
                         Recommended: "low" to minimize impact on remote user operations.
                         Note: Higher priorities (above normal, high, realtime) are NOT
                         supported to avoid impacting remote user operations.
        queue_priority: Execution queue priority level (0-9). Lower values execute first.
                       Workers at queue level 0 are fully utilized before queue level 1.
                       Default: 0. Use for tiered bursting (local=0, remote=1, cloud=2).
        system_account: Run as SYSTEM account (default False)
        psexec_path: Path to PsExec.exe (auto-detected from PATH if not specified)
        remote_temp_folder: Temporary folder name on remote machine
        cores_total: Total CPU cores available on remote machine (optional)
        cores_per_plan: Cores to allocate per HEC-RAS plan (default 4)
        max_parallel_plans: Max plans to run in parallel (calculated: cores_total/cores_per_plan)

    CRITICAL: HEC-RAS is a GUI application and REQUIRES session-based execution.
    - system_account=False (default) - Runs in user session with desktop (REQUIRED for HEC-RAS)
    - system_account=True - Runs as SYSTEM (no desktop, HEC-RAS will hang)

    Multi-Core Parallelism:
    - Set cores_total (e.g., 16) and cores_per_plan (e.g., 4) for parallel execution
    - Worker will run cores_total/cores_per_plan plans simultaneously (e.g., 4 plans)
    - Each plan gets cores_per_plan cores allocated
    - If not specified, executes plans sequentially (legacy behavior)

    Session-based execution requires additional Group Policy configuration on the remote machine.
    See REMOTE_WORKER_SETUP_GUIDE.md for complete setup instructions.

    Example:
        # RECOMMENDED: No credentials (uses Windows authentication, avoids GUI issues)
        worker = init_ras_worker(
            "psexec",
            hostname="WORKSTATION-01",
            share_path=r"\\\\WORKSTATION-01\\RasRemote",
            worker_folder=r"C:\\RasRemote",
            ras_exe_path=r"C:\\Program Files\\HEC\\HEC-RAS\\6.3\\RAS.exe",
            session_id=2
        )

        # With explicit credentials (only if required by network policy)
        worker = init_ras_worker(
            "psexec",
            hostname="WORKSTATION-01",
            share_path=r"\\\\WORKSTATION-01\\RasRemote",
            worker_folder=r"C:\\RasRemote",
            credentials={"username": "DOMAIN\\\\user", "password": "SecurePass123"},
            ras_exe_path=r"C:\\Program Files\\HEC\\HEC-RAS\\6.3\\RAS.exe",
            session_id=2,
            process_priority="low",
            queue_priority=0
        )
    """
    share_path: str = None
    worker_folder: str = None
    credentials: Dict[str, str] = field(default_factory=dict)
    session_id: int = 2
    process_priority: str = "low"
    queue_priority: int = 0
    system_account: bool = False
    psexec_path: str = None
    remote_temp_folder: str = None
    cores_total: int = None
    cores_per_plan: int = 4
    max_parallel_plans: int = None

    def __post_init__(self):
        """Validate PsExec worker configuration."""
        super().__post_init__()

        if not self.share_path:
            raise ValueError("share_path is required for PsExec workers")
        if not self.hostname:
            raise ValueError("hostname is required for PsExec workers")
        # Credentials are optional - if provided, must have both username and password
        if self.credentials:
            if "username" not in self.credentials or "password" not in self.credentials:
                raise ValueError("credentials must contain both 'username' and 'password' keys")
        if self.process_priority not in ["low", "below normal", "normal"]:
            raise ValueError(
                f"process_priority must be 'low', 'below normal', or 'normal' "
                f"(got '{self.process_priority}'). 'low' is recommended to minimize "
                f"impact on remote user operations."
            )
        if not isinstance(self.queue_priority, int) or self.queue_priority < 0 or self.queue_priority > 9:
            raise ValueError(
                f"queue_priority must be an integer from 0 to 9 (got {self.queue_priority}). "
                f"Lower values execute first. Default is 0."
            )

        # Auto-derive worker_folder from share_path if not specified
        if not self.worker_folder:
            share_parts = self.share_path.strip('\\').split('\\')
            if len(share_parts) >= 2:
                share_name = share_parts[1]
                self.worker_folder = f"C:\\{share_name}"
            else:
                raise ValueError(
                    f"Cannot auto-derive worker_folder from share_path '{self.share_path}'. "
                    f"Please specify worker_folder explicitly."
                )

        # Calculate max parallel plans if cores_total specified
        if self.cores_total is not None:
            self.max_parallel_plans = self.cores_total // self.cores_per_plan
            if self.max_parallel_plans < 1:
                self.max_parallel_plans = 1
        else:
            self.max_parallel_plans = 1


# =============================================================================
# PSEXEC HELPER FUNCTIONS
# =============================================================================

def find_psexec() -> str:
    """
    Find PsExec.exe on the system.

    Search order:
    1. System PATH
    2. User profile directory
    3. Common installation locations
    4. Auto-download from Microsoft Sysinternals

    Returns:
        str: Path to PsExec.exe

    Raises:
        FileNotFoundError: PsExec.exe not found and download failed
    """
    logger.debug("Searching for PsExec.exe")

    # Check PATH
    psexec_in_path = shutil.which("PsExec.exe") or shutil.which("psexec.exe")
    if psexec_in_path:
        logger.debug(f"Found PsExec in PATH: {psexec_in_path}")
        return psexec_in_path

    # Check common locations
    common_locations = [
        Path.home() / "PSTools" / "PsExec.exe",
        Path.home() / "Downloads" / "PSTools" / "PsExec.exe",
        Path("C:/PSTools/PsExec.exe"),
        Path("C:/Tools/PSTools/PsExec.exe"),
        Path("C:/Program Files/PSTools/PsExec.exe"),
        Path("C:/Program Files (x86)/PSTools/PsExec.exe"),
    ]

    for loc in common_locations:
        if loc.exists():
            logger.debug(f"Found PsExec at: {loc}")
            return str(loc)

    # Try to download
    logger.info("PsExec.exe not found. Attempting to download from Microsoft Sysinternals...")
    target_dir = Path.home() / "PSTools"
    try:
        psexec_path = download_psexec(target_dir)
        logger.info(f"Downloaded PsExec to: {psexec_path}")
        return str(psexec_path)
    except Exception as e:
        logger.error(f"Failed to download PsExec: {e}")
        raise FileNotFoundError(
            "PsExec.exe not found. Please download from "
            "https://docs.microsoft.com/en-us/sysinternals/downloads/psexec "
            "and add to PATH or specify psexec_path parameter."
        )


def download_psexec(target_dir: Path) -> Path:
    """
    Download PsExec from Microsoft Sysinternals.

    Args:
        target_dir: Directory to extract PSTools to

    Returns:
        Path: Path to PsExec.exe

    Raises:
        Exception: Download or extraction failed
    """
    url = "https://download.sysinternals.com/files/PSTools.zip"
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    zip_path = target_dir / "PSTools.zip"

    try:
        logger.debug(f"Downloading {url}")
        urllib.request.urlretrieve(url, zip_path)

        logger.debug(f"Extracting to {target_dir}")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(target_dir)

        zip_path.unlink()

        psexec_exe = target_dir / "PsExec.exe"
        if not psexec_exe.exists():
            psexec_exe = target_dir / "psexec.exe"

        if not psexec_exe.exists():
            raise FileNotFoundError("PsExec.exe not found after extraction")

        return psexec_exe

    except Exception as e:
        if zip_path.exists():
            zip_path.unlink()
        raise e


def init_psexec_worker(**kwargs) -> PsexecWorker:
    """
    Initialize PsExec worker.

    NOTE: Full validation (share access, remote connectivity) is deferred until
    execution time. This prevents false failures during initialization due to
    authentication and UAC complexities.

    Validation performed:
    1. Check PsExec.exe is available locally

    Validation deferred to execution:
    2. Network share accessibility (requires authenticated session)
    3. Remote execution permissions (depends on UAC, firewall, services)
    4. HEC-RAS.exe existence on remote machine

    Returns:
        PsexecWorker: Configured worker ready for execution

    Raises:
        FileNotFoundError: PsExec.exe not found locally
    """
    logger.info(f"Initializing PsExec worker for {kwargs.get('hostname', 'unknown')}")

    kwargs['worker_type'] = 'psexec'
    worker = PsexecWorker(**kwargs)

    # Find or validate PsExec.exe locally
    if not worker.psexec_path:
        worker.psexec_path = find_psexec()
    else:
        if not Path(worker.psexec_path).exists():
            raise FileNotFoundError(f"PsExec.exe not found at {worker.psexec_path}")

    logger.debug(f"Using PsExec at: {worker.psexec_path}")

    # Log configuration (obfuscate credentials)
    logger.info(f"PsExec worker configured:")
    logger.info(f"  Hostname: {worker.hostname}")
    logger.info(f"  Share path: {worker.share_path}")
    logger.info(f"  Worker folder: {worker.worker_folder}")
    if worker.credentials:
        logger.info(f"  User: {worker.credentials.get('username', '<unknown>')}")
    else:
        logger.info(f"  User: <Windows authentication>")
    logger.info(f"  System account: {worker.system_account}")
    logger.info(f"  Session ID: {worker.session_id if not worker.system_account else 'N/A'}")
    logger.info(f"  Process Priority: {worker.process_priority}")
    logger.info(f"  Queue Priority: {worker.queue_priority}")
    logger.warning(
        f"Validation deferred - share access and remote execution will be "
        f"tested during actual plan execution"
    )

    return worker


def execute_psexec_plan(
    worker: PsexecWorker,
    plan_number: str,
    ras_obj,
    num_cores: int,
    clear_geompre: bool,
    sub_worker_id: int = 1,
    autoclean: bool = True
) -> bool:
    """
    Execute a plan on a PsExec worker.

    Execution flow:
    1. Authenticate to network share (if credentials provided)
    2. Create temporary worker folder in network share
    3. Copy project to worker folder
    4. Generate batch file for HEC-RAS execution
    5. Execute batch file via PsExec
    6. Monitor execution (poll for .hdf file)
    7. Copy results back
    8. Cleanup temporary folder (if autoclean=True)

    Args:
        worker: PsexecWorker instance
        plan_number: Plan number to execute
        ras_obj: RAS project object
        num_cores: Number of cores
        clear_geompre: Clear geompre files
        sub_worker_id: Sub-worker ID for parallel execution (default 1)
        autoclean: Delete temporary worker folder after execution (default True).
                   Set to False for debugging to preserve worker folders.

    Returns:
        bool: True if successful
    """
    logger.info(f"Starting PsExec execution of plan {plan_number} (sub-worker #{sub_worker_id})")

    project_folder = Path(ras_obj.project_folder)
    project_name = ras_obj.project_name

    # Step 0: Authenticate to network share
    if worker.credentials:
        auth_success = authenticate_network_share(
            worker.share_path,
            worker.credentials["username"],
            worker.credentials["password"]
        )
        if not auth_success:
            logger.error(f"Failed to authenticate to share {worker.share_path}")
            return False

    # Step 1: Create temporary worker folder
    worker_temp_folder = Path(worker.share_path) / f"{project_name}_{plan_number}_SW{sub_worker_id}_{uuid.uuid4().hex[:8]}"
    worker_temp_folder.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Created worker folder: {worker_temp_folder}")

    try:
        # Step 2: Copy project to worker folder
        logger.info(f"Copying project to {worker_temp_folder}")
        shutil.copytree(project_folder, worker_temp_folder / project_name, dirs_exist_ok=True)

        worker_project_path = worker_temp_folder / project_name
        prj_file = list(worker_project_path.glob("*.prj"))[0]
        plan_file = worker_project_path / f"{project_name}.p{plan_number}"

        # Step 3: Generate batch file
        prj_file_local = convert_unc_to_local_path(str(prj_file), worker.share_path, worker.worker_folder)
        plan_file_local = convert_unc_to_local_path(str(plan_file), worker.share_path, worker.worker_folder)

        batch_file = worker_temp_folder / f"run_plan_{plan_number}.bat"
        batch_content = f'"{worker.ras_exe_path}" -c "{prj_file_local}" "{plan_file_local}"'
        batch_file.write_text(batch_content)
        logger.debug(f"Created batch file: {batch_file}")
        logger.debug(f"Batch file content: {batch_content}")

        # Step 4: Build PsExec command
        psexec_cmd = [
            worker.psexec_path,
            f"\\\\{worker.hostname}",
        ]

        # Add credentials only if provided (otherwise uses Windows authentication)
        if worker.credentials:
            psexec_cmd.extend(["-u", worker.credentials["username"]])
            psexec_cmd.extend(["-p", worker.credentials["password"]])

        psexec_cmd.extend(["-accepteula", "-h"])

        if worker.system_account:
            psexec_cmd.append("-s")
        else:
            psexec_cmd.extend(["-i", str(worker.session_id)])

        priority_flags = {
            "low": "-low",
            "below normal": "-belownormal",
            "normal": ""
        }
        priority_flag = priority_flags.get(worker.process_priority, "")
        if priority_flag:
            psexec_cmd.append(priority_flag)

        batch_file_local = convert_unc_to_local_path(str(batch_file), worker.share_path, worker.worker_folder)
        psexec_cmd.append(batch_file_local)

        if worker.credentials:
            cmd_display = ' '.join(psexec_cmd[:2]) + " -u <user> -p <password> -accepteula -h ..."
        else:
            cmd_display = ' '.join(psexec_cmd[:2]) + " -accepteula -h ..."
        logger.info(f"Executing: {cmd_display}")

        # Step 5: Execute PsExec command
        result = subprocess.run(
            psexec_cmd,
            capture_output=True,
            text=True,
            timeout=7200
        )

        # Step 6: Check for HDF file
        hdf_file = worker_project_path / f"{project_name}.p{plan_number}.hdf"

        max_wait = 60
        wait_interval = 5
        elapsed = 0

        while not hdf_file.exists() and elapsed < max_wait:
            time.sleep(wait_interval)
            elapsed += wait_interval
            logger.debug(f"Waiting for HDF file... ({elapsed}s)")

        if not hdf_file.exists():
            logger.error(f"HDF file not created: {hdf_file}")
            logger.error(f"PsExec stdout: {result.stdout}")
            logger.error(f"PsExec stderr: {result.stderr}")
            return False

        logger.info(f"HDF file created successfully: {hdf_file}")

        # Step 7: Copy results back
        dest_hdf = project_folder / hdf_file.name
        shutil.copy2(hdf_file, dest_hdf)
        logger.info(f"Copied results to {dest_hdf}")

        # Step 8: Cleanup (if autoclean enabled)
        if autoclean:
            shutil.rmtree(worker_temp_folder, ignore_errors=True)
            logger.debug(f"Cleaned up worker folder: {worker_temp_folder}")
        else:
            logger.info(f"Preserving worker folder for debugging: {worker_temp_folder}")

        return True

    except Exception as e:
        logger.error(f"Error in PsExec execution: {e}")
        if autoclean:
            try:
                if worker_temp_folder.exists():
                    shutil.rmtree(worker_temp_folder, ignore_errors=True)
            except:
                pass
        else:
            logger.info(f"Preserving worker folder for debugging: {worker_temp_folder}")
        return False
