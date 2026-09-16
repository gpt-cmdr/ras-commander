"""
RasTcu - HEC-RAS Terms & Conditions for Use (TCU) acceptance state.

HEC-RAS (``Ras.exe``, a VB6 application) shows a modal *"Terms and Conditions
for Use (TCU)"* dialog the first time it runs for a given **Windows user +
version**. The dialog is a VB6 form (window class ``ThunderRT6FormDC``), not a
standard Windows dialog (``#32770``), so ``DialogWatchdog`` cannot see or dismiss
it -- and it blocks headless / COM launches until a human clicks *I Agree*.

Acceptance is recorded per user in the VB6 settings hive. HEC-RAS keys its
settings by the **install path**, so once a user has accepted a version its
settings live under::

    HKCU\\Software\\VB and VBA Program Settings\\<install-dir>\\<node>\\...

where ``<install-dir>`` is the folder containing ``Ras.exe`` and ``<node>`` is
``ras.exe`` (HEC-RAS 5.0+) or ``ras`` (4.x).  The acceptance sentinel is the
opaque ``Projects\\System Statistic`` string.  Unrelated initialized settings
(for example window positions) are not evidence that the TCU was accepted.

This module lets ras-commander:

* **Detect** that state (``RasTcu.status`` / ``RasTcu.is_accepted``) -- read-only,
  safe on any OS. ``init_ras_project`` calls this and emits a one-line warning
  when the TCU has not been accepted, so headless users are told *before* a run
  hangs.
* **Accept** it on demand (``RasTcu.accept``, or
  ``init_ras_project(accept_tcu=True)``) -- an explicit, opt-in write that
  transfers only the opaque sentinel from an already-accepted donor of the
  exact same version. **Never called automatically.** Cross-version transfer
  requires the restoring diagnostic and black-box restart probes implemented by
  :class:`ras_commander.RasAcceptanceState`.

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

_PROJECTS_SECTION = "Projects"
_SENTINEL_VALUE = "System Statistic"

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
            ("accepted" | "acceptance-sentinel-missing" | "not-windows" |
            "version-unresolved").
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

    @staticmethod
    def _read_acceptance_sentinel(hive, application_key: str):
        """Return the exact opaque acceptance value/type, or ``None``.

        A generic VB6 subtree is insufficient: normal application startup can
        create unrelated settings while the legal dialog still blocks the
        process.  Keep the value opaque and require the observed string type.
        """
        import winreg

        projects_key = f"{application_key}\\{_PROJECTS_SECTION}"
        try:
            with winreg.OpenKey(hive, projects_key) as key:
                value, value_type = winreg.QueryValueEx(key, _SENTINEL_VALUE)
        except OSError:
            return None
        if value_type != winreg.REG_SZ or not isinstance(value, str) or not value:
            return None
        return value, value_type

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
            if RasTcu._read_acceptance_sentinel(
                winreg.HKEY_CURRENT_USER, subkey
            ) is not None:
                return TcuStatus(True, version, install_dir, subkey, "accepted")

        target = f"{_VB_ROOT}\\{install_dir}\\{RasTcu._node_name_for(version, install_dir)}"
        return TcuStatus(
            False,
            version,
            install_dir,
            target,
            "acceptance-sentinel-missing",
        )

    @staticmethod
    def is_accepted(ras_object=None, ras_version=None) -> bool:
        """Convenience boolean wrapper around :meth:`status`."""
        return RasTcu.status(ras_object, ras_version).accepted is True

    # ------------------------------------------------------------------ #
    # Donor discovery (for accept)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _iter_accepted_nodes(hive, vb_parent: str, version_label: str):
        """Yield exact-version nodes containing the acceptance sentinel."""
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
                    if str(ver).casefold() != str(version_label).casefold():
                        continue
                    for node in ("ras.exe", "ras"):
                        candidate = f"{vb_parent}\\{ver}\\{node}"
                        if RasTcu._read_acceptance_sentinel(hive, candidate):
                            yield candidate
        except OSError:
            return

    @staticmethod
    def _find_donor(
        install_dir: str,
        version_label: str,
    ) -> Tuple[Optional[int], Optional[str]]:
        """Find an exact-version accepted sentinel to transfer.

        Search order: (1) the current user's matching installed version, then
        (2) matching-version nodes in other users' hives (readable only with
        sufficient privilege). Cross-version donors are deliberately excluded.
        Returns ``(hive, subkey)`` or ``(None, None)``.
        """
        import winreg

        install_parent = str(Path(install_dir).parent)  # ...\HEC\HEC-RAS
        vb_parent = f"{_VB_ROOT}\\{install_parent}"

        for node in RasTcu._iter_accepted_nodes(
            winreg.HKEY_CURRENT_USER,
            vb_parent,
            version_label,
        ):
            return winreg.HKEY_CURRENT_USER, node

        try:
            idx = 0
            while True:
                try:
                    sid = winreg.EnumKey(winreg.HKEY_USERS, idx)
                except OSError:
                    break
                idx += 1
                sid_upper = str(sid).upper()
                if sid_upper.endswith("_CLASSES") or not sid_upper.startswith(
                    "S-1-5-21"
                ):
                    continue
                for node in RasTcu._iter_accepted_nodes(
                    winreg.HKEY_USERS,
                    f"{sid}\\{vb_parent}",
                    version_label,
                ):
                    return winreg.HKEY_USERS, node
        except OSError:
            pass

        return None, None

    @staticmethod
    def _copy_acceptance_sentinel(
        src_hive,
        src_path: str,
        dst_hive,
        dst_path: str,
        writes: List[str],
        dry_run: bool,
    ) -> None:
        """Copy only the opaque acceptance sentinel, never personal settings."""
        import winreg

        sentinel = RasTcu._read_acceptance_sentinel(src_hive, src_path)
        if sentinel is None:
            raise OSError("Donor acceptance sentinel disappeared before transfer")
        value, value_type = sentinel
        projects_key = f"{dst_path}\\{_PROJECTS_SECTION}"
        writes.append(projects_key)
        if dry_run:
            return
        winreg.CreateKey(dst_hive, projects_key)
        with winreg.OpenKey(
            dst_hive,
            projects_key,
            0,
            winreg.KEY_SET_VALUE,
        ) as dst:
            winreg.SetValueEx(dst, _SENTINEL_VALUE, 0, value_type, value)

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

        Seeds the current user's HKCU by transferring only the opaque acceptance
        sentinel from an already-accepted donor of the exact same HEC-RAS
        version.  A donor may be the current profile or, with sufficient
        privilege, another loaded user profile.  Cross-version transfer is not
        performed by this convenience API.

        If nothing on the machine has ever accepted any version, there is no
        subtree to replicate; this returns ``accepted=None`` and logs guidance to
        accept once in the GUI (see :meth:`open_gui_to_accept`) or run the
        provisioning script. The library never fabricates acceptance from nothing.

        Args:
            ras_object (RasPrj, optional): Project object; uses its ras_exe_path.
            ras_version (str, optional): Version or full path to Ras.exe.
            keep_personal (bool): Retained for backward compatibility. Personal
                settings are never copied; only the acceptance sentinel is
                transferred.
            write_ack (bool): Write an acceptance/audit record. Default True.
            dry_run (bool): Resolve and report what would be written without
                touching the registry. Default False.

        Returns:
            TcuStatus reflecting the state after the operation (``reason`` is
            "accepted", "already-accepted", "no-exact-version-donor",
            "not-windows", or "version-unresolved").
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

        donor_hive, donor_key = RasTcu._find_donor(
            install_dir,
            str(pre.version),
        )
        if donor_key is None:
            logger.warning(
                "Cannot transfer the HEC-RAS %s TCU state: no accepted donor for "
                "that exact version is available in a loaded profile. Open HEC-RAS "
                "%s once and click \"I Agree\" (see RasTcu.open_gui_to_accept), or "
                "use the controlled RasAcceptanceState diagnostic/provisioning "
                "workflow for an explicitly authorized cross-version case. Terms: %s",
                pre.version, pre.version, HEC_TERMS_URL,
            )
            return TcuStatus(
                None,
                pre.version,
                install_dir,
                target_key,
                "no-exact-version-donor",
            )

        writes: List[str] = []
        try:
            RasTcu._copy_acceptance_sentinel(
                donor_hive,
                donor_key,
                winreg.HKEY_CURRENT_USER,
                target_key,
                writes,
                dry_run,
            )
        except OSError as exc:
            logger.error("Failed to seed HEC-RAS %s TCU acceptance: %s", pre.version, exc)
            return TcuStatus(
                False,
                pre.version,
                install_dir,
                target_key,
                "acceptance-sentinel-missing",
            )

        if dry_run:
            logger.info(
                "[dry-run] Would transfer the HEC-RAS %s TCU sentinel from an "
                "exact-version donor into HKCU\\%s",
                pre.version,
                target_key,
            )
            return TcuStatus(
                False,
                pre.version,
                install_dir,
                target_key,
                "acceptance-sentinel-missing",
            )

        verified = RasTcu.status(ras_object, ras_version)
        if verified.accepted is not True:
            logger.error(
                "HEC-RAS %s TCU sentinel transfer failed exact readback",
                pre.version,
            )
            return verified

        if write_ack:
            RasTcu._write_ack(pre.version, install_dir, target_key)

        logger.info(
            "Accepted the HEC-RAS %s Terms & Conditions for Use for the current user "
            "(transferred the exact-version sentinel). Terms: %s",
            pre.version,
            HEC_TERMS_URL,
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
