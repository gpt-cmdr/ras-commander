"""Mapped-drive paths keep their drive letter on the way to HEC-RAS.

``Path.resolve()`` turns a mapped network drive into its UNC target. HEC-RAS
7.0.1 cannot open a project from a UNC path (Ras.exe shows a hidden
"Error loading project data" dialog and stalls), so project and run paths are
made absolute and normalized without resolving the drive.
"""

import os
import string
import subprocess
from pathlib import Path, PureWindowsPath

import pytest

from ras_commander import RasUtils

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows drive semantics")


def _fake_resolve(mapping):
    """Return a Path.resolve replacement that maps drive prefixes like Windows."""
    original = Path.resolve

    def resolve(self, strict=False):
        text = os.path.normpath(str(self.absolute()))
        for drive, target in mapping.items():
            if text.upper().startswith(drive.upper()):
                return Path(target + text[len(drive):])
        return original(self, strict=strict)

    return resolve


@windows_only
@pytest.mark.parametrize(
    "target",
    [r"\\fileserver\share", r"C:\backing\folder"],
    ids=["mapped_network_drive", "subst_drive"],
)
def test_drive_changing_resolution_keeps_drive_letter(monkeypatch, target):
    monkeypatch.setattr(Path, "resolve", _fake_resolve({"Q:": target}))
    result = RasUtils.safe_resolve(Path(r"Q:\Models\Muncie\..\Muncie\Muncie.prj"))
    assert str(result) == r"Q:\Models\Muncie\Muncie.prj"
    assert result.is_absolute()


@windows_only
def test_relative_path_on_mapped_working_directory_keeps_drive_letter(monkeypatch):
    # A relative input has no drive letter of its own; the working directory
    # supplies it and must survive.
    monkeypatch.setattr(Path, "resolve", _fake_resolve({"Q:": r"\\fileserver\share"}))
    monkeypatch.setattr(Path, "absolute", lambda self: Path(r"Q:\Models") / self)
    result = RasUtils.safe_resolve("Muncie")
    assert str(result) == r"Q:\Models\Muncie"


def test_local_path_is_resolved_and_normalized(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    result = RasUtils.safe_resolve(folder / ".." / "project" / "Model.prj")
    assert result == (folder / "Model.prj").resolve()
    assert ".." not in result.parts


def test_accepts_str(tmp_path):
    assert RasUtils.safe_resolve(str(tmp_path)) == tmp_path.resolve()


def _mapped_network_drive():
    if os.name != "nt":
        return None
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:\\")
        try:
            if root.exists() and str(root.resolve()).startswith("\\\\"):
                return root
        except OSError:
            continue
    return None


@windows_only
def test_real_mapped_network_drive_keeps_drive_letter():
    root = _mapped_network_drive()
    if root is None:
        pytest.skip("no mapped network drive on this host")
    probe = root / "ras-commander-path-probe" / ".." / "Model.prj"
    assert str(probe.resolve()).startswith("\\\\")
    result = RasUtils.safe_resolve(probe)
    assert PureWindowsPath(result).drive.upper() == root.drive.upper()
    assert str(result).upper() == f"{root.drive}\\MODEL.PRJ".upper()


@windows_only
def test_real_subst_drive_keeps_drive_letter(tmp_path):
    used = {p[0] for p in os.listdrives()} if hasattr(os, "listdrives") else set()
    free = next(
        (c for c in reversed(string.ascii_uppercase) if c not in used and not Path(f"{c}:\\").exists()),
        None,
    )
    if free is None:
        pytest.skip("no free drive letter for subst")
    created = subprocess.run(["subst", f"{free}:", str(tmp_path)], capture_output=True, check=False)
    if created.returncode != 0:
        pytest.skip("subst is unavailable")
    try:
        (tmp_path / "Model.prj").write_text("Proj Title=probe\n")
        drive_path = Path(f"{free}:\\Model.prj")
        result = RasUtils.safe_resolve(drive_path)
        assert PureWindowsPath(result).drive.upper() == f"{free}:"
        assert result.is_file()
    finally:
        subprocess.run(["subst", f"{free}:", "/D"], capture_output=True, check=False)


@windows_only
def test_project_candidate_paths_keep_mapped_drive(monkeypatch):
    from ras_commander import RasPrj

    monkeypatch.setattr(Path, "resolve", _fake_resolve({"Q:": r"\\fileserver\share"}))
    prj = RasPrj()
    prj.project_folder = Path(r"Q:\Models\Muncie")
    assert str(prj._resolve_candidate_path(Path("Terrain/Terrain.hdf"))) == (
        r"Q:\Models\Muncie\Terrain\Terrain.hdf"
    )
    assert str(prj._resolve_candidate_path(Path(r"Q:\Models\Other\x.hdf"))) == (
        r"Q:\Models\Other\x.hdf"
    )


@windows_only
def test_execution_artifact_paths_keep_mapped_drive(monkeypatch):
    from ras_commander.ExecutionArtifacts import get_plan_result_artifact_paths

    monkeypatch.setattr(Path, "resolve", _fake_resolve({"Q:": r"\\fileserver\share"}))
    paths = get_plan_result_artifact_paths(
        "01", project_folder=r"Q:\Models\Muncie", project_name="Muncie"
    )
    assert str(paths.plan_file) == r"Q:\Models\Muncie\Muncie.p01"
    assert str(paths.hdf) == r"Q:\Models\Muncie\Muncie.p01.hdf"
