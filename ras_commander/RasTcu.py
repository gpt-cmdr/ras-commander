"""
RasTcu - HEC-RAS Terms & Conditions for Use (TCU) acceptance state.

HEC-RAS (``Ras.exe``, a VB6 application) shows a modal *"Terms and Conditions
for Use (TCU)"* dialog the first time it runs for a given **Windows user +
version**. The dialog is a VB6 form (window class ``ThunderRT6FormDC``), not a
standard Windows dialog (``#32770``), so ``DialogWatchdog`` cannot see or dismiss
it -- and it blocks headless / COM launches until the operator accepts *I Agree*.
The explicit accept_gui_terms API can perform that action after the operator
has authorized assent; ordinary computation never clicks legal controls.

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

# Container images record a black-box acceptance probe at build time: the
# operator accepted the dialog for the exact Ras.exe, and a relaunch showed no
# dialog. Under Wine, releases up to 6.0 record acceptance in a form that is
# not interpretable from the registry, so this record is the only evidence.
TCU_PROBE_ENVIRONMENT = "RAS_COMMANDER_TCU_PROBE"
TCU_PROBE_SCHEMA = "ras-commander-tcu-probe/v1"


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
    registry seeding, acceptance import and affirmative GUI actions require
    explicit operator authorization. Ordinary compute never grants assent.
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
    def _running_under_wine() -> bool:
        """Return whether this Windows process runs under Wine."""
        try:
            import ctypes

            return hasattr(ctypes.windll.ntdll, "wine_get_version")
        except Exception:
            return False

    @staticmethod
    def _probe_verifies(exe: str) -> bool:
        """Return whether a build-time probe record verifies this exact Ras.exe."""
        import hashlib
        import json

        record_path = os.environ.get(TCU_PROBE_ENVIRONMENT, "").strip()
        if not record_path:
            return False
        try:
            record = json.loads(Path(record_path).read_text(encoding="utf-8"))
            entries = record.get("executables", []) if record.get("schema") == TCU_PROBE_SCHEMA else []
            for entry in entries:
                legacy = RasTcu._version_tuple(Path(exe).parent.name)
                # HEC-RAS 6.0 and earlier keep per-machine state: only an
                # acceptance given in this task's prefix counts.
                if legacy is not None and legacy[:2] <= (6, 0) and record.get("scope") != "task":
                    continue
                if (str(entry.get("ras_executable", "")).casefold() == str(exe).casefold()
                        and entry.get("verified") is True):
                    digest = hashlib.sha256(Path(exe).read_bytes()).hexdigest()
                    return digest == entry.get("ras_executable_sha256")
        except (OSError, ValueError, AttributeError):
            return False
        return False

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

    @staticmethod
    def _requires_gui_evidence(version_label: Optional[str]) -> bool:
        # Real 6.0 Wine tests show a valid copied sentinel with a live TCU wizard.
        if RasTcu._version_tuple(version_label) != (6, 0, 0):
            return False
        try:
            import ctypes
            return hasattr(ctypes.WinDLL("ntdll"), "wine_get_version")
        except (AttributeError, OSError):
            return False

    @staticmethod
    def _gui_verification_path(executable) -> Path:
        import hashlib
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise OSError("LOCALAPPDATA is required for GUI verification evidence")
        identity = str(PureWindowsPath(executable)).casefold()
        label = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        return Path(base) / "ras_commander" / f"tcu-gui-{label}.json"

    @staticmethod
    def _runtime_digest(executable) -> str:
        import hashlib
        digest = hashlib.sha256()
        with Path(executable).open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _has_gui_verification(executable) -> bool:
        import json
        try:
            record = json.loads(RasTcu._gui_verification_path(executable).read_text())
            return (
                isinstance(record, dict)
                and record.get("schema") == "ras-commander-tcu-gui-v1"
                and record.get("operator_acceptance") is True
                and record.get("gui_ready_verified") is True
                and record.get("graceful_exit") is True
                and (record.get("dialog_closed") is True or record.get("already_accepted_profile") is True)
                and record.get("executable") == str(PureWindowsPath(executable)).casefold()
                and record.get("runtime_sha256") == RasTcu._runtime_digest(executable)
            )
        except (OSError, ValueError, TypeError):
            return False

    @staticmethod
    def _save_gui_verification(executable, receipt) -> None:
        import json
        import tempfile
        path = RasTcu._gui_verification_path(executable)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = dict(receipt, schema="ras-commander-tcu-gui-v1",
                      executable=str(PureWindowsPath(executable)).casefold(),
                      runtime_sha256=RasTcu._runtime_digest(executable))
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix="tcu-gui-", suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                json.dump(record, output, indent=2)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

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
        if not exe or PureWindowsPath(exe).name.lower() != "ras.exe":
            return TcuStatus(None, version, None, None, "version-unresolved")

        install_dir = str(PureWindowsPath(exe).parent)
        version = version or PureWindowsPath(install_dir).name
        install_version = PureWindowsPath(install_dir).name

        if RasTcu._probe_verifies(exe):
            return TcuStatus(True, version, install_dir, None, "probe-verified")

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
                if RasTcu._requires_gui_evidence(install_version) and not RasTcu._has_gui_verification(exe):
                    return TcuStatus(None, version, install_dir, subkey,
                                     "legacy-wine-gui-verification-required")
                return TcuStatus(True, version, install_dir, subkey, "accepted")
            if (
                existing_key is None
                and RasTcu._node_exists(winreg.HKEY_CURRENT_USER, subkey)
            ):
                existing_key = subkey

        legacy = RasTcu._version_tuple(install_version)
        if legacy is not None and legacy[:2] <= (6, 0) and RasTcu._running_under_wine():
            # The legacy sentinel written under Wine is not interpretable;
            # report unknown rather than a false negative.
            return TcuStatus(None, version, install_dir, existing_key, "wine-legacy-unverifiable")

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

        # Portable/private runtimes may be outside the standard installation
        # tree. Use only verified acceptance-bearing nodes in known HEC roots,
        # retaining the target's own parent as the first preference.
        standard_parent = str(PureWindowsPath(
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        ) / "HEC" / "HEC-RAS")
        vb_parents = list(dict.fromkeys((vb_parent, f"{_VB_ROOT}\\{standard_parent}")))
        for parent in vb_parents:
            current_user_nodes = list(
                RasTcu._iter_accepted_nodes(winreg.HKEY_CURRENT_USER, parent)
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
                for parent in vb_parents:
                    for node in RasTcu._iter_accepted_nodes(winreg.HKEY_USERS, f"{sid}\\{parent}"):
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
    def inspect_acceptance(ras_object=None, ras_version=None) -> dict:
        """Read the selected release's TCU sentinel in both registry views.

        Reads only the current user's exact release key and ``System Statistic``
        value. It does not enumerate personal settings, copy preferences, write
        acceptance, launch HEC-RAS or infer GUI readiness from registry contents.

        Args:
            ras_object: Optional initialized project for executable resolution.
            ras_version: Explicit release or installed Ras.exe path.

        Returns:
            JSON-safe status, expected sentinel and observed 32/64-bit values,
            value types and release matches. Missing views retain their error.
        """
        import dataclasses
        state = RasTcu.status(ras_object=ras_object, ras_version=ras_version)
        record = {"status": dataclasses.asdict(state),
                  "expected_sentinel": RasTcu._accepted_sentinel_value(state.version),
                  "registry_views": []}
        if os.name != "nt" or not state.registry_key:
            return record
        import winreg
        parent = state.registry_key.rsplit("\\", 1)[0]
        for node in ("ras.exe", "ras"):
            registry_key = parent + "\\" + node
            for view, flag in (("32", winreg.KEY_WOW64_32KEY), ("64", winreg.KEY_WOW64_64KEY)):
                entry = {"view": view, "registry_key": registry_key, "present": False}
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                        registry_key + "\\" + _TCU_SENTINEL_SECTION,
                                        0, winreg.KEY_READ | flag) as key:
                        value, value_type = winreg.QueryValueEx(key, _TCU_SENTINEL_VALUE)
                    safe_value = {"bytes_hex": value.hex()} if isinstance(value, bytes) else value
                    entry.update(present=True, value=safe_value, value_type=value_type,
                                 matches_release=RasTcu._sentinel_accepts_version(value, state.version))
                except OSError as error:
                    entry["error"] = str(error)
                record["registry_views"].append(entry)
        return record

    @staticmethod
    @log_call
    def export_acceptance(ras_object=None, ras_version=None) -> dict:
        """Export verified acceptance for operator-authorized fleet provisioning.

        Call on a Windows profile that has already accepted the terms. The
        record contains only the release-specific acceptance value and runtime
        provenance; recent projects, preferences and credentials are excluded.
        Transfer the record as trusted operator configuration, then explicitly
        call import_acceptance() in a new Windows/Wine profile. A container task
        probe without a registry-backed value cannot be exported this way.

        Args:
            ras_object: Optional initialized project for executable resolution.
            ras_version: Explicit release or installed Ras.exe path.

        Returns:
            Acceptance value and source release, runtime hash and host provenance.

        Raises:
            ValueError: Acceptance is unverified, lacks a registry-backed value,
                or changes during export.
            OSError: The acceptance value or runtime cannot be read.

        """
        import hashlib
        import socket
        state = RasTcu.status(ras_object, ras_version)
        if state.accepted is not True or not state.registry_key:
            raise ValueError("Only verified, existing registry-backed TCU acceptance can be exported")
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            state.registry_key + "\\" + _TCU_SENTINEL_SECTION,
        ) as key:
            value, _ = winreg.QueryValueEx(key, _TCU_SENTINEL_VALUE)
        if not RasTcu._sentinel_accepts_version(value, state.version):
            raise ValueError("TCU acceptance changed while exporting")
        executable = Path(RasTcu._resolve_exe(ras_object, ras_version))
        digest = hashlib.sha256()
        with executable.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return {
            "schema": "ras-commander-tcu-acceptance-v1",
            "source_version": state.version,
            "source_runtime_sha256": digest.hexdigest(),
            "source_host": socket.gethostname(),
            "system_statistic": str(value),
        }

    @staticmethod
    @log_call
    def import_acceptance(
        acceptance: dict,
        ras_object=None,
        ras_version=None,
        *,
        write_ack: bool = True,
        dry_run: bool = False,
    ) -> TcuStatus:
        """Explicitly accept terms using a trusted export from an accepted profile.

        This is an operator provisioning action, never an automatic fallback.
        It validates the exported release/sentinel and runtime hash format,
        writes only the target release's acceptance value, and rechecks it.
        The export is operator-supplied configuration, not a signed attestation.
        Stable releases only; beta sentinel derivation is not supported.

        Args:
            acceptance: Trusted operator record from export_acceptance().
            ras_object: Optional initialized project for executable resolution.
            ras_version: Target release or installed Ras.exe path.
            write_ack: Append a local acceptance audit record after success.
            dry_run: Validate the record without writing acceptance.

        Returns:
            Rechecked TcuStatus. Unknown remains unknown; no GUI readiness is
            inferred for a profile that requires separate GUI verification.

        Raises:
            ValueError: Export validation fails or target release is unsupported.
            OSError: The registry cannot be updated.

        """
        if (
            not isinstance(acceptance, dict)
            or acceptance.get("schema") != "ras-commander-tcu-acceptance-v1"
            or not RasTcu._sentinel_accepts_version(
                acceptance.get("system_statistic"), acceptance.get("source_version")
            )
            or re.fullmatch(r"[0-9a-f]{64}", str(acceptance.get("source_runtime_sha256", ""))) is None
        ):
            raise ValueError("A valid RasTcu.export_acceptance() record is required")
        pre = RasTcu.status(ras_object, ras_version)
        if pre.accepted is None or pre.accepted is True:
            return pre
        if RasTcu._accepted_sentinel_value(pre.version) is None:
            raise ValueError("TCU export provisioning requires a stable target release")
        if dry_run:
            return TcuStatus(False, pre.version, pre.install_dir, pre.registry_key, "dry-run")
        import winreg

        RasTcu._write_target_sentinel(winreg.HKEY_CURRENT_USER, pre.registry_key, pre.version)
        after = RasTcu.status(ras_object, ras_version)
        if after.accepted is not True:
            return TcuStatus(None, pre.version, pre.install_dir, pre.registry_key, "seeded-unverified")
        if write_ack:
            RasTcu._write_ack(
                pre.version, pre.install_dir, pre.registry_key,
                method="RasTcu.import_acceptance",
            )
        logger.info(
            "Accepted HEC-RAS %s TCU using an operator-supplied export from %s "
            "release %s (runtime SHA-256 %s); personal settings were not imported",
            pre.version, acceptance.get("source_host", "unknown"),
            acceptance["source_version"], acceptance["source_runtime_sha256"],
        )
        return TcuStatus(True, pre.version, pre.install_dir, pre.registry_key, "accepted-from-export")

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
    def _write_ack(
        version: Optional[str], install_dir: Optional[str], registry_key: str,
        *, method: str = "RasTcu.accept",
    ) -> None:
        """Write a human-readable acceptance/audit record."""
        import getpass
        import socket
        from datetime import datetime

        base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or "."
        ack_dir = Path(base) / "ras_commander"
        try:
            ack_dir.mkdir(parents=True, exist_ok=True)
            ack_path = ack_dir / "TCU_AutoAcceptance.txt"
            registry_description = f"HKCU\\{registry_key}" if registry_key else "(not available)"
            record = (
                "HEC-RAS TERMS AND CONDITIONS FOR USE - ACCEPTANCE RECORD\n"
                "=======================================================\n"
                f"Host       : {socket.gethostname()}\n"
                f"User       : {getpass.getuser()}\n"
                f"Applied    : {datetime.now().isoformat(timespec='seconds')}\n"
                f"Version    : {version}\n"
                f"Registry   : {registry_description}\n"
                f"Applied by : ras-commander {method}()\n\n"
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
    def accept_running_terms(
        process_id: int,
        *,
        expected_create_time: float,
        ras_object=None,
        ras_version=None,
        operator_acceptance: bool = False,
        timeout: float = 30,
    ) -> dict:
        """Explicitly accept a TCU wizard in one already-owned compute launch.

        Never launches or terminates a process. Requires explicit operator assent,
        exact Ras.exe path and unchanged PID creation time. Selects only the known
        affirmative TCU control and its bounded Next/OK sequence, then returns
        when that owned wizard closes. The caller must still verify preprocessing
        or computation normally; wizard closure is not solver-readiness evidence.

        Args:
            process_id: Already-owned exact Ras.exe PID.
            expected_create_time: Witnessed PID creation time from psutil.
            ras_object: Optional initialized project for executable resolution.
            ras_version: Exact selected release or executable path.
            operator_acceptance: Must be True after explicit operator assent.
            timeout: Maximum acceptance wait in seconds.

        Returns:
            Owned-dialog action receipt. The process remains running.

        Raises:
            ValueError: Assent, identity parameters or timeout are invalid.
            FileNotFoundError: The selected executable is unavailable.
            RuntimeError: Windows Python or exact process ownership is absent.
            TimeoutError: The owned wizard does not close before the deadline.

        """
        import math
        import ntpath
        if operator_acceptance is not True:
            raise ValueError("Explicit operator_acceptance=True is required")
        if os.name != "nt":
            raise RuntimeError("Use Windows Python (native or Wine) for scoped TCU acceptance")
        if isinstance(process_id, bool) or not isinstance(process_id, int) or process_id <= 0:
            raise ValueError("process_id must be a positive integer")
        if not math.isfinite(expected_create_time) or expected_create_time <= 0:
            raise ValueError("A finite positive expected_create_time is required")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        exe = RasTcu._resolve_exe(ras_object, ras_version)
        if not exe or Path(exe).name.casefold() != "ras.exe" or not Path(exe).is_file():
            raise FileNotFoundError("An exact installed Ras.exe is required")
        import psutil
        process = psutil.Process(process_id)
        if process.create_time() != expected_create_time:
            raise RuntimeError("TCU process identity changed")
        if ntpath.normcase(ntpath.normpath(process.exe())) != ntpath.normcase(ntpath.normpath(str(exe))):
            raise RuntimeError("TCU process executable does not match the selected Ras.exe")
        from ._tcu_gui import accept_owned_terms
        receipt = accept_owned_terms(process, str(exe), float(timeout),
                                     keep_running=True, expected_create_time=expected_create_time)
        if receipt.get("dialog_closed") is not True and receipt.get("already_accepted_profile") is not True:
            raise RuntimeError("Owned TCU dialog did not close")
        logger.info("Explicit operator TCU assent recorded for owned PID %s; compute remains running", process_id)
        return receipt

    @staticmethod
    @log_call
    def accept_gui_terms(
        ras_object=None,
        ras_version=None,
        *,
        operator_acceptance: bool = False,
        timeout: float = 60,
        write_ack: bool = True,
    ) -> dict:
        """Record the operator's explicit assent through the owned native TCU UI.

        Requires operator_acceptance=True. Never called by compute, initialization,
        or a dialog watchdog. Launches only the selected Ras.exe, clicks one exact
        enabled I Agree control in its witnessed process tree, waits for closure,
        and cleans up only those processes. Windows Python also supports Wine.
        A registry-status assertion alone is not treated as proof of UI success.

        Args:
            ras_object: Optional initialized project for executable resolution.
            ras_version: Exact selected release or executable path.
            operator_acceptance: Must be True after explicit operator assent.
            timeout: Maximum acceptance and main-window readiness wait in seconds.
            write_ack: Append a local acceptance audit record after success.

        Returns:
            Owned-dialog receipt after stable enabled main-window verification
            and graceful exit. Saves verification for this exact runtime/profile.

        Raises:
            ValueError: Explicit assent or a finite positive timeout is absent.
            FileNotFoundError: The selected executable is unavailable.
            RuntimeError: Windows Python or exact window ownership is absent.
            TimeoutError: Acceptance, main-window readiness or graceful exit fails.

        """
        import math
        if operator_acceptance is not True:
            raise ValueError("Explicit operator_acceptance=True is required")
        if os.name != "nt":
            raise RuntimeError("Run accept_gui_terms using Windows Python (native or Wine)")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        exe = RasTcu._resolve_exe(ras_object, ras_version)
        if not exe or Path(exe).name.casefold() != "ras.exe" or not Path(exe).is_file():
            raise FileNotFoundError("An exact installed Ras.exe is required")
        import subprocess
        from ._tcu_gui import accept_owned_terms
        process = subprocess.Popen([str(exe)], cwd=str(Path(exe).parent))
        try:
            receipt = accept_owned_terms(process, str(exe), float(timeout))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
        RasTcu._save_gui_verification(exe, receipt)
        state = RasTcu.status(ras_object, ras_version)
        receipt["system_statistic"] = None
        if state.registry_key:
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, state.registry_key + "\\" + _TCU_SENTINEL_SECTION) as key:
                    receipt["system_statistic"], _ = winreg.QueryValueEx(key, _TCU_SENTINEL_VALUE)
            except OSError:
                pass
        receipt["registry_status_accepted"] = state.accepted if state.registry_key else None
        receipt["acceptance_status_reason"] = state.reason
        receipt["registry_key"] = state.registry_key
        if write_ack:
            RasTcu._write_ack(state.version, state.install_dir, state.registry_key,
                              method="RasTcu.accept_gui_terms (explicit operator assent)")
        return receipt

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
