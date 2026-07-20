"""
RasTcu - HEC-RAS Terms & Conditions for Use (TCU) acceptance state.

HEC-RAS (``Ras.exe``, a VB6 application) shows a modal *"Terms and Conditions
for Use (TCU)"* dialog the first time it runs for a given **Windows user +
version**. The dialog is a VB6 form (window class ``ThunderRT6FormDC``), not a
standard Windows dialog (``#32770``), so ``DialogWatchdog`` cannot see or dismiss
it -- and it blocks headless / COM launches until a human clicks *I Agree*.

Acceptance is recorded implicitly, per user, in the VB6 settings hive. HEC-RAS
keys its settings by the **install path**, so once a user has run a version
successfully its settings live under::

    HKCU\\Software\\VB and VBA Program Settings\\<install-dir>\\<node>\\...

where ``<install-dir>`` is the folder containing ``Ras.exe`` and ``<node>`` is
``ras.exe`` (HEC-RAS 5.0+) or ``ras`` (4.x). The presence of that initialized
per-version subtree is what suppresses the TCU on later launches -- there is no
explicit ``Accepted=1`` value.

This module lets ras-commander:

* **Detect** that state (``RasTcu.status`` / ``RasTcu.is_accepted``) -- read-only,
  safe on any OS. ``init_ras_project`` calls this and emits a one-line warning
  when the TCU has not been accepted, so headless users are told *before* a run
  hangs.
* **Accept** it on demand (``RasTcu.accept``, or ``init_ras_project(accept_tcu=True)``)
  -- an explicit, opt-in write that seeds the current user's registry by
  replicating an already-accepted subtree found on the machine. **Never called
  automatically.**

For fleet / template provisioning (seeding the Default User profile and
``HKU\\.DEFAULT`` so every *new* user or cloned VM inherits acceptance), use the
companion PowerShell script ``Set-HecRasTcuAccepted.ps1`` -- that requires
elevation and hive loading, which is out of scope for this in-process API.

HEC-RAS is public-domain software of the U.S. Army Corps of Engineers,
Hydrologic Engineering Center. Full terms: https://www.hec.usace.army.mil/software/hec-ras/

All methods are static and designed to be used without instantiation.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .LoggingConfig import get_logger
from .Decorators import log_call

logger = get_logger(__name__)

# Root of the VB6 SaveSetting/GetSetting registry tree (under HKCU / HKU\<sid>).
_VB_ROOT = r"Software\VB and VBA Program Settings"

# Direct child sections of the per-version node that hold user-specific data.
# Cleared when copying a donor unless keep_personal=True.
_PERSONAL_SECTIONS = ("Projects", "Form Position")

HEC_TERMS_URL = "https://www.hec.usace.army.mil/software/hec-ras/"


@dataclass(frozen=True)
class TcuStatus:
    """Result of a TCU acceptance check.

    Attributes:
        accepted: True (accepted), False (not accepted), or None (unknown --
            e.g. not on Windows, or the HEC-RAS version could not be resolved).
        version: Resolved HEC-RAS version label, if known.
        install_dir: Folder containing Ras.exe, if resolved.
        registry_key: The per-version HKCU subkey that gates the TCU.
        reason: Short machine-readable reason
            ("accepted" | "no-vb6-subtree" | "not-windows" | "version-unresolved").
    """

    accepted: Optional[bool]
    version: Optional[str]
    install_dir: Optional[str]
    registry_key: Optional[str]
    reason: str

    def __bool__(self) -> bool:  # `if RasTcu.status(...):` -> True only when accepted
        return self.accepted is True


class RasTcu:
    """HEC-RAS Terms & Conditions for Use (TCU) acceptance detection and seeding.

    All methods are static. Detection is read-only and safe on any platform;
    :meth:`accept` is the only method that writes, and it is never called
    automatically by the library.
    """

    # ------------------------------------------------------------------ #
    # Internal resolution helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _resolve_exe(ras_object=None, ras_version=None) -> Optional[str]:
        """Resolve the full path to Ras.exe from a RasPrj object, a version, or the global ras."""
        from .RasPrj import get_ras_exe, ras

        if ras_object is not None and getattr(ras_object, "ras_exe_path", None):
            return str(ras_object.ras_exe_path)
        if ras_version is not None:
            exe = get_ras_exe(ras_version)
            return None if str(exe) == "Ras.exe" else str(exe)
        if getattr(ras, "ras_exe_path", None):
            return str(ras.ras_exe_path)
        return None

    @staticmethod
    def _version_label(ras_object=None, ras_version=None, install_dir=None) -> Optional[str]:
        if ras_version is not None:
            return str(ras_version)
        if ras_object is not None and getattr(ras_object, "ras_version", None):
            return str(ras_object.ras_version)
        if install_dir:
            return Path(install_dir).name
        return None

    @staticmethod
    def _node_name_for(version_label: Optional[str], install_dir: Optional[str] = None) -> str:
        """VB6 app-node name: 'ras' for HEC-RAS 4.x, 'ras.exe' for 5.0+."""
        label = version_label or (Path(install_dir).name if install_dir else "")
        return "ras" if str(label).strip().startswith("4") else "ras.exe"

    @staticmethod
    def _node_has_subkeys(hive, subkey: str) -> bool:
        import winreg

        try:
            with winreg.OpenKey(hive, subkey) as key:
                return winreg.QueryInfoKey(key)[0] > 0
        except OSError:
            return False

    # ------------------------------------------------------------------ #
    # Public: detection (read-only)
    # ------------------------------------------------------------------ #
    @staticmethod
    @log_call
    def status(ras_object=None, ras_version=None) -> TcuStatus:
        """Report whether the HEC-RAS TCU has been accepted for the current user.

        Read-only: never writes to the registry and never raises. Returns
        ``accepted=None`` when the answer is unknowable (non-Windows, or the
        version/exe could not be resolved).

        Args:
            ras_object (RasPrj, optional): Project object; uses its ras_exe_path.
            ras_version (str, optional): Version (e.g. "6.6") or full path to Ras.exe.
                If both are None, the global ``ras`` object is used.

        Returns:
            TcuStatus
        """
        version = RasTcu._version_label(ras_object, ras_version)

        if os.name != "nt":
            return TcuStatus(None, version, None, None, "not-windows")

        exe = RasTcu._resolve_exe(ras_object, ras_version)
        if not exe or Path(exe).name.lower() != "ras.exe":
            return TcuStatus(None, version, None, None, "version-unresolved")

        install_dir = str(Path(exe).parent)
        version = version or Path(install_dir).name

        try:
            import winreg
        except ImportError:  # pragma: no cover - Windows only
            return TcuStatus(None, version, install_dir, None, "not-windows")

        for node in ("ras.exe", "ras"):
            subkey = f"{_VB_ROOT}\\{install_dir}\\{node}"
            if RasTcu._node_has_subkeys(winreg.HKEY_CURRENT_USER, subkey):
                return TcuStatus(True, version, install_dir, subkey, "accepted")

        target = f"{_VB_ROOT}\\{install_dir}\\{RasTcu._node_name_for(version, install_dir)}"
        return TcuStatus(False, version, install_dir, target, "no-vb6-subtree")

    @staticmethod
    def is_accepted(ras_object=None, ras_version=None) -> bool:
        """Convenience boolean wrapper around :meth:`status`."""
        return RasTcu.status(ras_object, ras_version).accepted is True

    # ------------------------------------------------------------------ #
    # Donor discovery (for accept)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _iter_accepted_nodes(hive, vb_parent: str):
        """Yield accepted per-version node subkeys under a HEC-RAS parent path."""
        import winreg

        try:
            with winreg.OpenKey(hive, vb_parent) as parent:
                idx = 0
                while True:
                    try:
                        ver = winreg.EnumKey(parent, idx)
                    except OSError:
                        break
                    idx += 1
                    for node in ("ras.exe", "ras"):
                        candidate = f"{vb_parent}\\{ver}\\{node}"
                        if RasTcu._node_has_subkeys(hive, candidate):
                            yield candidate
        except OSError:
            return

    @staticmethod
    def _find_donor(install_dir: str) -> Tuple[Optional[int], Optional[str]]:
        """Find an already-accepted subtree to replicate.

        Search order: (1) the current user's other installed versions, then
        (2) other users' hives (readable only with sufficient privilege).
        Returns ``(hive, subkey)`` or ``(None, None)``.
        """
        import winreg

        install_parent = str(Path(install_dir).parent)  # ...\HEC\HEC-RAS
        vb_parent = f"{_VB_ROOT}\\{install_parent}"

        for node in RasTcu._iter_accepted_nodes(winreg.HKEY_CURRENT_USER, vb_parent):
            return winreg.HKEY_CURRENT_USER, node

        try:
            idx = 0
            while True:
                try:
                    sid = winreg.EnumKey(winreg.HKEY_USERS, idx)
                except OSError:
                    break
                idx += 1
                if sid.endswith("_Classes") or not sid.startswith("S-1-5-21"):
                    continue
                for node in RasTcu._iter_accepted_nodes(winreg.HKEY_USERS, f"{sid}\\{vb_parent}"):
                    return winreg.HKEY_USERS, node
        except OSError:
            pass

        return None, None

    @staticmethod
    def _copy_key(src_hive, src_path: str, dst_hive, dst_path: str, writes: List[str], dry_run: bool) -> None:
        """Recursively copy a registry key (subkeys + values)."""
        import winreg

        with winreg.OpenKey(src_hive, src_path) as src:
            n_sub, n_val, _ = winreg.QueryInfoKey(src)

            if not dry_run:
                winreg.CreateKey(dst_hive, dst_path)
            writes.append(dst_path)

            for i in range(n_val):
                name, value, vtype = winreg.EnumValue(src, i)
                if not dry_run:
                    with winreg.OpenKey(dst_hive, dst_path, 0, winreg.KEY_SET_VALUE) as dst:
                        winreg.SetValueEx(dst, name, 0, vtype, value)

            for i in range(n_sub):
                child = winreg.EnumKey(src, i)
                RasTcu._copy_key(
                    src_hive, f"{src_path}\\{child}",
                    dst_hive, f"{dst_path}\\{child}",
                    writes, dry_run,
                )

    # ------------------------------------------------------------------ #
    # Public: acceptance (opt-in, writes the registry)
    # ------------------------------------------------------------------ #
    @staticmethod
    @log_call
    def accept(
        ras_object=None,
        ras_version=None,
        *,
        keep_personal: bool = False,
        write_ack: bool = True,
        dry_run: bool = False,
    ) -> TcuStatus:
        """Accept the HEC-RAS TCU for the **current Windows user** (opt-in write).

        Seeds the current user's HKCU by replicating an already-accepted HEC-RAS
        settings subtree found elsewhere on the machine (another installed
        version the user has run, or -- with sufficient privilege -- another
        user's profile). This is the validated, reliable mechanism: HEC-RAS then
        treats this version as already-run and never shows the TCU.

        If nothing on the machine has ever accepted any version, there is no
        subtree to replicate; this returns ``accepted=None`` and logs guidance to
        accept once in the GUI (see :meth:`open_gui_to_accept`) or run the
        provisioning script. The library never fabricates acceptance from nothing.

        Args:
            ras_object (RasPrj, optional): Project object; uses its ras_exe_path.
            ras_version (str, optional): Version or full path to Ras.exe.
            keep_personal (bool): Keep the donor's "Projects" (recent-file MRU)
                and "Form Position" values. Default False (they are dropped so a
                donor user's file paths / window layout do not propagate).
            write_ack (bool): Write an acceptance/audit record. Default True.
            dry_run (bool): Resolve and report what would be written without
                touching the registry. Default False.

        Returns:
            TcuStatus reflecting the state after the operation (``reason`` is
            "accepted", "already-accepted", "no-donor-available", "not-windows",
            or "version-unresolved").
        """
        pre = RasTcu.status(ras_object, ras_version)
        if pre.accepted is True:
            logger.debug("HEC-RAS %s TCU already accepted; nothing to do.", pre.version)
            return TcuStatus(True, pre.version, pre.install_dir, pre.registry_key, "already-accepted")
        if pre.accepted is None:
            return pre  # not-windows / version-unresolved -- nothing we can do

        import winreg

        install_dir = pre.install_dir
        target_node = RasTcu._node_name_for(pre.version, install_dir)
        target_key = f"{_VB_ROOT}\\{install_dir}\\{target_node}"

        donor_hive, donor_key = RasTcu._find_donor(install_dir)
        if donor_key is None:
            logger.warning(
                "Cannot auto-accept the HEC-RAS %s TCU: no already-accepted HEC-RAS "
                "settings exist on this machine to replicate. Open HEC-RAS %s once and "
                "click \"I Agree\" (see RasTcu.open_gui_to_accept), or run the provisioning "
                "script Set-HecRasTcuAccepted.ps1. Terms: %s",
                pre.version, pre.version, HEC_TERMS_URL,
            )
            return TcuStatus(None, pre.version, install_dir, target_key, "no-donor-available")

        writes: List[str] = []
        try:
            RasTcu._copy_key(donor_hive, donor_key, winreg.HKEY_CURRENT_USER, target_key, writes, dry_run)
            if not keep_personal and not dry_run:
                for section in _PERSONAL_SECTIONS:
                    RasTcu._clear_values(winreg.HKEY_CURRENT_USER, f"{target_key}\\{section}")
        except OSError as exc:
            logger.error("Failed to seed HEC-RAS %s TCU acceptance: %s", pre.version, exc)
            return TcuStatus(False, pre.version, install_dir, target_key, "no-vb6-subtree")

        if dry_run:
            logger.info(
                "[dry-run] Would accept HEC-RAS %s TCU by copying %s keys from an existing "
                "acceptance into HKCU\\%s", pre.version, len(writes), target_key,
            )
            return TcuStatus(False, pre.version, install_dir, target_key, "no-vb6-subtree")

        if write_ack:
            RasTcu._write_ack(pre.version, install_dir, target_key)

        logger.info(
            "Accepted the HEC-RAS %s Terms & Conditions for Use for the current user "
            "(seeded %d registry keys). Terms: %s", pre.version, len(writes), HEC_TERMS_URL,
        )
        return TcuStatus(True, pre.version, install_dir, target_key, "accepted")

    @staticmethod
    def _clear_values(hive, subkey: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_ALL_ACCESS) as key:
                names = []
                i = 0
                while True:
                    try:
                        names.append(winreg.EnumValue(key, i)[0])
                        i += 1
                    except OSError:
                        break
                for name in names:
                    try:
                        winreg.DeleteValue(key, name)
                    except OSError:
                        pass
        except OSError:
            pass

    @staticmethod
    def _write_ack(version: Optional[str], install_dir: Optional[str], registry_key: str) -> None:
        """Write a human-readable acceptance/audit record."""
        import getpass
        import socket
        from datetime import datetime

        base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or "."
        ack_dir = Path(base) / "ras_commander"
        try:
            ack_dir.mkdir(parents=True, exist_ok=True)
            ack_path = ack_dir / "TCU_AutoAcceptance.txt"
            record = (
                "HEC-RAS TERMS AND CONDITIONS FOR USE - ACCEPTANCE RECORD\n"
                "=======================================================\n"
                f"Host       : {socket.gethostname()}\n"
                f"User       : {getpass.getuser()}\n"
                f"Applied    : {datetime.now().isoformat(timespec='seconds')}\n"
                f"Version    : {version}\n"
                f"Registry   : HKCU\\{registry_key}\n"
                f"Applied by : ras-commander RasTcu.accept()\n\n"
                "The HEC-RAS Terms and Conditions for Use were accepted programmatically "
                "on behalf of the operator to allow unattended / headless use. HEC-RAS is "
                "public-domain software of the U.S. Army Corps of Engineers, Hydrologic "
                "Engineering Center (HEC).\n"
                f"Full terms: {HEC_TERMS_URL}\n\n"
                "By accepting, the operator affirms agreement to those Terms and Conditions "
                "for automated HEC-RAS use on this host.\n"
            )
            with open(ack_path, "a", encoding="utf-8") as handle:
                handle.write(record + "\n")
            logger.debug("TCU acceptance record written to %s", ack_path)
        except OSError as exc:
            logger.debug("Could not write TCU acceptance record: %s", exc)

    # ------------------------------------------------------------------ #
    # Public: manual acceptance path
    # ------------------------------------------------------------------ #
    @staticmethod
    @log_call
    def open_gui_to_accept(ras_object=None, ras_version=None) -> bool:
        """Launch HEC-RAS so the user can read and accept the TCU manually.

        Opens ``Ras.exe`` (no project). The user clicks *I Agree* once; HEC-RAS
        then records acceptance for this user+version. Returns True if the
        process was launched. This is the honest, zero-registry-write path that
        the ``init_ras_project`` warning suggests first.
        """
        if os.name != "nt":
            logger.warning("open_gui_to_accept is Windows-only.")
            return False
        exe = RasTcu._resolve_exe(ras_object, ras_version)
        if not exe or Path(exe).name.lower() != "ras.exe" or not Path(exe).is_file():
            logger.warning("Could not resolve an installed Ras.exe to open (got %r).", exe)
            return False
        import subprocess

        try:
            subprocess.Popen([exe], cwd=str(Path(exe).parent))
            logger.info(
                "Launched HEC-RAS. Click \"I Agree\" on the Terms and Conditions for Use "
                "dialog, then close HEC-RAS. Terms: %s", HEC_TERMS_URL,
            )
            return True
        except OSError as exc:
            logger.error("Failed to launch HEC-RAS: %s", exc)
            return False
