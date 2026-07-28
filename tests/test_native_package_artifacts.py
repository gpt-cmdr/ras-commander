"""Regression coverage for native helper files shipped in package artifacts."""

from pathlib import Path
import os
import subprocess
import sys


NATIVE_HELPERS = (
    "InvokeRas5GeometryLandCover.ps1",
    "InvokeRas5LandCover.ps1",
)


def test_ras5_powershell_helpers_are_in_build_artifact(tmp_path):
    """The installed package must contain both scripts used by the Python API."""
    repository_root = Path(__file__).resolve().parents[1]
    build_lib = tmp_path / "build-lib"
    environment = os.environ.copy()
    environment["CI"] = "1"

    subprocess.run(
        [
            sys.executable,
            "setup.py",
            "build_py",
            "--build-lib",
            str(build_lib),
        ],
        cwd=repository_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    native_artifact = build_lib / "ras_commander" / "native"
    for helper in NATIVE_HELPERS:
        packaged_helper = native_artifact / helper
        assert packaged_helper.is_file(), (
            f"{helper} is missing from the built ras_commander.native package"
        )
        assert packaged_helper.read_bytes() == (
            repository_root / "ras_commander" / "native" / helper
        ).read_bytes()
