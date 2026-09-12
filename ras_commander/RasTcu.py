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
``ras.exe`` (HEC-RAS 5.0+) or ``ras`` (4.x). Opening a release initializes this
subtree even before acceptance. The release-specific
``Projects\\System Statistic`` sentinel is the acceptance evidence; subtree
presence, recent projects, and window positions are not.

This module lets ras-commander:

* **Detect** that state (``RasTcu.status`` / ``RasTcu.is_accepted``) -- read-only,
  safe on any OS. ``init_ras_project`` calls this and emits a one-line warning
  when the TCU has not been accepted, so headless users are told *before* a run
  hangs.
* **Accept** it on demand (``RasTcu.accept``, or
  ``init_ras_project(accept_tcu=True)``) -- an explicit, opt-in registry copy
  from an already-accepted subtree plus the target release's exact sentinel.
  The result is revalidated and is never reported as accepted unless it matches.
  **Never called automatically.**

For fleet / template provisioning (seeding the Default User profile and
``HKU\\.DEFAULT`` so every *new* user or cloned VM inherits acceptance), use the
companion PowerShell script ``Set-HecRasTcuAccepted.ps1`` -- that requires
elevation and hive loading, which is out of scope for this in-process API.

HEC-RAS is public-domain software of the U.S. Army Corps of Engineers,
Hydrologic Engineering Center. Full terms: https://www.hec.usace.army.mil/software/hec-ras/

All methods are static and designed to be used without instantiation.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import List, Optional, Tuple

from .LoggingConfig import get_logger
from .Decorators import log_call

logger = get_logger(__name__)

# Root of the VB6 SaveSetting/GetSetting registry tree (under HKCU / HKU\<sid>).
_VB_ROOT = r"Software\VB and VBA Program Settings"

# Direct child sections of the per-version node that hold user-specific data.
# Cleared when copying a donor unless keep_personal=True.
_PERSONAL_SECTIONS = ("Projects", "Form Position")
_PERSONAL_SECTION_NAMES = {section.casefold() for section in _PERSONAL_SECTIONS}

# HEC-RAS 6.x records the user-approved TCU state inside the otherwise-personal
# ``Projects`` section.  ``System Statistic`` is not an MRU entry: a value such
# as ``660`` is the release-family sentinel written after the user accepts the
# 6.6 terms.  It must be detected and preserved while the other Projects values
# remain excluded from acceptance inference and donor copying.
_TCU_SENTINEL_SECTION = "Projects"
_TCU_SENTINEL_VALUE = "System Statistic"
_LEGACY_SENTINEL_PREFIX = 0x3F800000
_VERSION_PATTERN = re.compile(r"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?")

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
            ("accepted" | "no-vb6-subtree" | "unaccepted-vb6-subtree" |
            "seeded-unverified" | "not-windows" | "version-unresolved").
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
            label = str(ras_version)
            if PureWindowsPath(label).name.casefold() == "ras.exe":
                return PureWindowsPath(label).parent.name
            return label
        if ras_object is not None and getattr(ras_object, "ras_version", None):
            label = str(ras_object.ras_version)
            if PureWindowsPath(label).name.casefold() == "ras.exe":
                return PureWindowsPath(label).parent.name
            return label
        if install_dir:
            return Path(install_dir).name
        return None

    @staticmethod
    def _node_name_for(version_label: Optional[str], install_dir: Optional[str] = None) -> str:
        """VB6 app-node name: 'ras' for HEC-RAS 4.x, 'ras.exe' for 5.0+."""
        label = version_label or (Path(install_dir).name if install_dir else "")
        return "ras" if str(label).strip().startswith("4") else "ras.exe"

    @staticmethod
    def _node_exists(hive, subkey: str) -> bool:
        import winreg

        try:
            with winreg.OpenKey(hive, subkey):
                return True
        except OSError:
            return False

    @staticmethod
    def _node_has_acceptance_state(
        hive,
        subkey: str,
        version_label: Optional[str] = None,
    ) -> bool:
        """Return whether a node has the exact TCU sentinel for its release.

        Merely opening HEC-RAS initializes many VB6 settings sections before the
        user accepts the TCU, so root values and non-personal child sections are
        not acceptance evidence. The version-specific ``System Statistic`` value
        is the authoritative signal.
        """
        if version_label is None:
            parts = str(subkey).replace("/", "\\").rstrip("\\").split("\\")
            if len(parts) >= 2:
                version_label = parts[-2]
        return RasTcu._has_tcu_sentinel(hive, subkey, version_label)

    @staticmethod
    def _version_tuple(version_label: Optional[str]) -> Optional[Tuple[int, int, int]]:
        match = _VERSION_PATTERN.search(str(version_label or ""))
        if match is None:
            return None
        major, minor, patch = match.groups()
        return int(major), int(minor), int(patch or 0)

    @staticmethod
    def _sentinel_accepts_version(value, version_label: Optional[str]) -> bool:
        """Validate one ``System Statistic`` value for an exact HEC-RAS release."""
        version = RasTcu._version_tuple(version_label)
        if version is None or isinstance(value, bool):
            return False

        major, minor, patch = version
        text = str(value).strip()
        if not text:
            return False

        if (major, minor) <= (6, 0):
            try:
                numeric = int(text, 10)
            except ValueError:
                return False
            release_code = major * 100 + minor * 10 + patch
            return numeric == _LEGACY_SENTINEL_PREFIX + release_code - 3

        release_code = str(major * 100 + minor * 10 + patch)
        return text == release_code or text.startswith(f"{release_code} ")

    @staticmethod
    def _accepted_sentinel_value(version_label: Optional[str]) -> Optional[str]:
        """Return the exact stable-release sentinel written after acceptance."""
        if "beta" in str(version_label or "").casefold():
            return None
        version = RasTcu._version_tuple(version_label)
        if version is None:
            return None

        major, minor, patch = version
        release_code = major * 100 + minor * 10 + patch
        if (major, minor) <= (6, 0):
            return str(_LEGACY_SENTINEL_PREFIX + release_code - 3)
        return str(release_code)

    @staticmethod
    def _write_target_sentinel(hive, target_key: str, version_label: str) -> bool:
        """Record explicit acceptance using the target release's sentinel."""
        import winreg

        sentinel = RasTcu._accepted_sentinel_value(version_label)
        if sentinel is None:
            return False
        projects_key = f"{target_key}\\{_TCU_SENTINEL_SECTION}"
        with winreg.CreateKey(hive, projects_key) as key:
            winreg.SetValueEx(
                key,
                _TCU_SENTINEL_VALUE,
                0,
                winreg.REG_SZ,
                sentinel,
            )
        return True

    @staticmethod
    def _has_tcu_sentinel(
        hive,
        subkey: str,
        version_label: Optional[str] = None,
    ) -> bool:
        """Return whether ``Projects`` contains the valid release-specific sentinel."""
        import winreg

        projects_key = f"{subkey}\\{_TCU_SENTINEL_SECTION}"
        try:
            with winreg.OpenKey(hive, projects_key) as key:
                _, n_val, _ = winreg.QueryInfoKey(key)
                for idx in range(n_val):
                    name, value, _ = winreg.EnumValue(key, idx)
                    if name.casefold() != _TCU_SENTINEL_VALUE.casefold():
                        continue
                    return RasTcu._sentinel_accepts_version(value, version_label)
        except OSError:
            pass
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
        install_version = Path(install_dir).name

        try:
            import winreg
        except ImportError:  # pragma: no cover - Windows only
            return TcuStatus(None, version, install_dir, None, "not-windows")

        existing_key = None
        for node in ("ras.exe", "ras"):
            subkey = f"{_VB_ROOT}\\{install_dir}\\{node}"
            if RasTcu._node_has_acceptance_state(
                winreg.HKEY_CURRENT_USER,
                subkey,
                install_version,
            ):
                return TcuStatus(True, version, install_dir, subkey, "accepted")
            if (
                existing_key is None
                and RasTcu._node_exists(winreg.HKEY_CURRENT_USER, subkey)
            ):
                existing_key = subkey

        if existing_key is not None:
            return TcuStatus(
                False,
                version,
                install_dir,
                existing_key,
                "unaccepted-vb6-subtree",
            )

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
                        if RasTcu._node_has_acceptance_state(hive, candidate, ver):
                            yield candidate
        except OSError:
            return

    @staticmethod
    def _find_donor(install_dir: str) -> Tuple[Optional[int], Optional[str]]:
        """Find an already-accepted subtree to replicate.

        Search order: (1) the nearest accepted release for the current user,
        then (2) the nearest accepted release in other users' readable hives.
        Returns ``(hive, subkey)`` or ``(None, None)``.
        """
        import winreg

        install_parent = str(Path(install_dir).parent)  # ...\HEC\HEC-RAS
        vb_parent = f"{_VB_ROOT}\\{install_parent}"
        target_version = RasTcu._version_tuple(Path(install_dir).name)

        def donor_key(subkey: str):
            parts = subkey.replace("/", "\\").rstrip("\\").split("\\")
            version_label = parts[-2] if len(parts) >= 2 else ""
            version = RasTcu._version_tuple(version_label)
            if target_version is None or version is None:
                return 2, float("inf"), version_label.casefold()
            target_code = (
                target_version[0] * 100
                + target_version[1] * 10
                + target_version[2]
            )
            version_code = version[0] * 100 + version[1] * 10 + version[2]
            return (
                0 if version[0] == target_version[0] else 1,
                abs(version_code - target_code),
                version_label.casefold(),
            )

        current_user_nodes = list(
            RasTcu._iter_accepted_nodes(winreg.HKEY_CURRENT_USER, vb_parent)
        )
        if current_user_nodes:
            return winreg.HKEY_CURRENT_USER, min(current_user_nodes, key=donor_key)

        other_user_nodes = []
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
                    other_user_nodes.append(node)
        except OSError:
            pass

        if other_user_nodes:
            return winreg.HKEY_USERS, min(other_user_nodes, key=donor_key)

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
        user's profile), then records the target release's exact sentinel. This
        method is itself the user's explicit acceptance action. The target is
        validated after writing; any mismatch returns ``accepted=None`` with
        ``reason="seeded-unverified"``.

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
            "version-unresolved", "unaccepted-vb6-subtree", or
            "seeded-unverified").
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
                "settings exist on this machine to replicate. MRU-only settings such as "
                "Projects/Form Position are intentionally ignored because they do not "
                "prove TCU acceptance. Open HEC-RAS %s once and "
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
                    preserve_names = (
                        (_TCU_SENTINEL_VALUE,)
                        if section.casefold() == _TCU_SENTINEL_SECTION.casefold()
                        else ()
                    )
                    RasTcu._clear_values(
                        winreg.HKEY_CURRENT_USER,
                        f"{target_key}\\{section}",
                        preserve_names=preserve_names,
                    )
            if not dry_run and not RasTcu._write_target_sentinel(
                winreg.HKEY_CURRENT_USER,
                target_key,
                Path(install_dir).name,
            ):
                logger.warning(
                    "Could not derive the TCU sentinel for HEC-RAS %s.",
                    pre.version,
                )
        except OSError as exc:
            logger.error("Failed to seed HEC-RAS %s TCU acceptance: %s", pre.version, exc)
            return TcuStatus(False, pre.version, install_dir, target_key, "no-vb6-subtree")

        if dry_run:
            logger.info(
                "[dry-run] Would accept HEC-RAS %s TCU by copying %s keys from an existing "
                "acceptance into HKCU\\%s", pre.version, len(writes), target_key,
            )
            return TcuStatus(False, pre.version, install_dir, target_key, "no-vb6-subtree")

        if not RasTcu._node_has_acceptance_state(
            winreg.HKEY_CURRENT_USER,
            target_key,
            Path(install_dir).name,
        ):
            logger.warning(
                "Seeded HEC-RAS %s TCU registry data, but the target key still does not "
                "contain acceptance-bearing state. Refusing to report accepted for "
                "HKCU\\%s.",
                pre.version,
                target_key,
            )
            return TcuStatus(None, pre.version, install_dir, target_key, "seeded-unverified")

        if write_ack:
            RasTcu._write_ack(pre.version, install_dir, target_key)

        logger.info(
            "Accepted the HEC-RAS %s Terms & Conditions for Use for the current user "
            "(seeded %d registry keys). Terms: %s", pre.version, len(writes), HEC_TERMS_URL,
        )
        return TcuStatus(True, pre.version, install_dir, target_key, "accepted")

    @staticmethod
    def _clear_values(hive, subkey: str, *, preserve_names=()) -> None:
        import winreg

        preserved = {name.casefold() for name in preserve_names}
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
                    if name.casefold() in preserved:
                        continue
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
