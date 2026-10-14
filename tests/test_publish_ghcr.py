"""Offline tests for the GHCR publishing helper (no docker, oras, or network)."""

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("publish_ghcr", ROOT / "containers/publish/publish_ghcr.py")
publish = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(publish)


def _artifact(folder: Path, name: str, data: bytes = b"image") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    (folder / (name + ".sha256")).write_text(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    return path


@pytest.mark.parametrize("name, expected", [
    ("hec-ras-wine-executor_5.0.7_fb32cbae0c92.tar.gz", ("wine-executor", "5.0.7")),
    ("hec-ras-wine-precompute_6.6_v5-f5c887e9474d.tar.gz", ("wine-precompute", "6.6")),
    ("hec-ras-wine-executor_6.0-397f2543.sif", ("wine-executor", "6.0")),
    ("hec-ras-linux-unsteady_7.0.1.sif", ("linux-unsteady", "7.0.1")),
])
def test_names_give_role_and_release(name, expected):
    assert publish.parse_name(name) == expected


@pytest.mark.parametrize("name", ["hec-ras-examples_6.6_abc.tar.gz", "hec-ras-wine-executor_4.1.0_x.tar.gz",
                                  "other.tar.gz"])
def test_other_files_are_refused(name):
    with pytest.raises(ValueError):
        publish.parse_name(name)


def test_plan_targets_one_repository_per_role_and_release(tmp_path):
    _artifact(tmp_path / "a", "hec-ras-wine-executor_5.0.7_fb32cbae0c92.tar.gz")
    _artifact(tmp_path / "s", "hec-ras-wine-executor_5.0.7-fb32cbae.sif")
    actions = publish.plan(tmp_path / "a", tmp_path / "s", "ghcr.io/gpt-cmdr/", "0.106.0")
    assert [(a["kind"], a["target"]) for a in actions] == [
        ("oci", "ghcr.io/gpt-cmdr/hec-ras-wine-executor_5.0.7:0.106.0"),
        ("sif", "ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_5.0.7:0.106.0"),
    ]
    _artifact(tmp_path / "a", "hec-ras-wine-executor_5.0.7_000000000000.tar.gz")
    with pytest.raises(ValueError, match="two archives"):
        publish.plan(tmp_path / "a", None, "ghcr.io/gpt-cmdr", "0.106.0")


def test_plan_requires_hash_sidecars_and_a_safe_tag(tmp_path):
    (tmp_path / "hec-ras-wine-executor_6.6_x.tar.gz").write_bytes(b"x")
    with pytest.raises(FileNotFoundError):
        publish.plan(tmp_path, None, "ghcr.io/gpt-cmdr", "0.106.0")
    with pytest.raises(ValueError, match="tag"):
        publish.plan(tmp_path, None, "ghcr.io/gpt-cmdr", "bad tag")


def test_execute_needs_the_terms_confirmation(tmp_path, capsys):
    _artifact(tmp_path, "hec-ras-wine-executor_6.6_x.tar.gz")
    assert publish.main(["--archives", str(tmp_path), "--tag", "t"]) == 0
    assert "dry run: 1 pushes" in capsys.readouterr().out
    assert publish.main(["--archives", str(tmp_path), "--tag", "t", "--execute"]) == 2
    assert "terms" in capsys.readouterr().err


def test_updated_catalog_loads_and_prefers_ghcr(tmp_path, monkeypatch):
    catalog = tmp_path / "container_images.json"
    shutil.copy(ROOT / "ras_commander/resources/container_images.json", catalog)
    digest = "sha256:" + "c" * 64
    pushed = [
        {"kind": "oci", "role": "wine-executor", "version": "5.0.7", "digest": digest,
         "target": "ghcr.io/gpt-cmdr/hec-ras-wine-executor_5.0.7:0.106.0", "sha256": "d" * 64},
        {"kind": "sif", "role": "wine-executor", "version": "5.0.7", "digest": "sha256:" + "e" * 64,
         "target": "ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_5.0.7:0.106.0", "sha256": "f" * 64},
        {"kind": "oci", "role": "linux-unsteady", "version": "6.6", "digest": digest,
         "target": "ghcr.io/gpt-cmdr/hec-ras-linux-unsteady_6.6:0.106.0", "sha256": "d" * 64},
    ]
    publish.update_catalog(catalog, pushed)

    from ras_commander import RasContainerImages
    module = __import__("ras_commander.RasContainerImages", fromlist=["x"])
    original = module.files
    monkeypatch.setattr(module, "files", lambda _: type("R", (), {
        "joinpath": lambda self, _p: catalog})())
    try:
        executor = RasContainerImages.get("wine-executor", "5.0.7")
        native = RasContainerImages.get("linux-unsteady", "6.6")
    finally:
        monkeypatch.setattr(module, "files", original)
    assert executor.reference == f"ghcr.io/gpt-cmdr/hec-ras-wine-executor_5.0.7@{digest}"
    assert executor.sif == "oras://ghcr.io/gpt-cmdr/hec-ras-wine-executor-sif_5.0.7@sha256:" + "e" * 64
    assert executor.sif_sha256 == "f" * 64
    assert native.reference.startswith("ghcr.io/") and "docker.io" in (native.mirror or "")
    assert json.loads(catalog.read_text())["images"][0]["role"] == "wine-executor"
