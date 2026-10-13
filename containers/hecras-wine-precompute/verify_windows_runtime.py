#!/usr/bin/env python3
"""Inspect installed HEC-RAS and saved TCU state without accepting terms.

Run with the prepared Windows Python inside a fresh writable Wine prefix.
The Linux launcher verifies the seed manifest before making that copy.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

EXPECTED = {
    "6.5": ("6.5.0.0", "650"),
    "6.6": ("6.6.0.0", "660"),
    # The vendor's 7.0.1 Ras.exe uses this Windows file-version resource.
    "7.0.1": ("7.0.0.1", "701"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", choices=EXPECTED)
    parser.add_argument("--expected-exe-sha256", required=True)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Run this checker with Windows Python under Wine")

    import win32api
    import winreg
    from ras_commander.RasTcu import RasTcu

    exe = Path(r"C:\Program Files (x86)\HEC\HEC-RAS") / args.version / "Ras.exe"
    info = win32api.GetFileVersionInfo(str(exe), "\\")
    parts = [info["FileVersionMS"] >> 16, info["FileVersionMS"] & 65535,
             info["FileVersionLS"] >> 16, info["FileVersionLS"] & 65535]
    file_version = ".".join(map(str, parts))
    exe_sha = hashlib.sha256(exe.read_bytes()).hexdigest()
    status = RasTcu.status(ras_version=str(exe))
    sentinel = None
    if status.registry_key:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                status.registry_key + r"\Projects") as key:
                value, registry_type = winreg.QueryValueEx(key, "System Statistic")
                sentinel = {"value": value, "registry_type": registry_type}
        except OSError:
            pass

    expected_version, expected_sentinel = EXPECTED[args.version]
    checks = {
        "executable_version": file_version == expected_version,
        "executable_hash": exe_sha == args.expected_exe_sha256.lower(),
        "accepted_tcu": status.accepted is True and status.reason == "accepted",
        "version_specific_registry": sentinel == {
            "value": expected_sentinel, "registry_type": winreg.REG_SZ},
    }
    print(json.dumps({
        "requested_version": args.version, "exe": str(exe),
        "file_version": file_version, "exe_sha256": exe_sha,
        "windows_python": sys.version.split()[0],
        "tcu_status": asdict(status), "system_statistic": sentinel,
        "acceptance_called": False, "checks": checks,
        "status": "succeeded" if all(checks.values()) else "failed",
    }, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
