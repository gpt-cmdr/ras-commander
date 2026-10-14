"""Offline tests for the container image catalog and the local SIF cache."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from ras_commander import RasContainerImages
from ras_commander.RasContainerImages import ContainerImage, applicable_roles, normalize_version

BASH = shutil.which("bash")
FAKE_APPTAINER = """#!/bin/bash
# fake 'apptainer pull <dest> <source>': writes deterministic bytes per source
[ "$1" = pull ] || exit 9
[ -e "$2" ] && { echo "refusing to overwrite" >&2; exit 3; }
[ -n "${FAKE_PULL_FAIL:-}" ] && { echo "registry unreachable" >&2; exit 1; }
printf 'sif for %s\\n' "$3" > "$2"
echo "$3" >> "${FAKE_PULL_LOG:-/dev/null}"
"""


@pytest.fixture()
def apptainer(tmp_path, monkeypatch):
    fake = tmp_path / "bin" / "apptainer"
    fake.parent.mkdir()
    fake.write_text(FAKE_APPTAINER)
    fake.chmod(0o755)
    log = tmp_path / "pulls.log"
    monkeypatch.setenv("FAKE_PULL_LOG", str(log))
    monkeypatch.delenv("RAS_COMMANDER_IMAGE_CACHE", raising=False)
    return str(fake), log


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("given, folder", [
    ("4.1", "4.1.0"), ("41", "4.1.0"), ("4.10", "4.1.0"), ("5.07", "5.0.7"), ("507", "5.0.7"),
    ("6.6", "6.6"), ("66", "6.6"), (6.6, "6.6"), ("6.4", "6.4.1"), ("7.0.1", "7.0.1"), ("7.1.0", "7.1"),
])
def test_versions_normalize_to_install_folders(given, folder):
    assert normalize_version(given) == folder


@pytest.mark.parametrize("bad", ["3.1", "8.0", "6.7 Beta 5", "latest", ""])
def test_unsupported_versions_are_rejected(bad):
    with pytest.raises(ValueError):
        normalize_version(bad)


@pytest.mark.parametrize("version, roles", [
    ("4.1", ("wine-executor",)),
    ("5.0.6", ("wine-executor",)),
    ("6.0", ("wine-executor",)),
    ("5.0.7", ("wine-executor", "wine-precompute", "linux-unsteady")),
    ("6.1", ("wine-executor", "wine-precompute", "linux-unsteady")),
    ("7.0.1", ("wine-executor", "wine-precompute", "linux-unsteady")),
])
def test_roles_apply_by_release(version, roles):
    assert applicable_roles(version) == roles


def test_catalog_entries_are_digest_pinned_and_applicable():
    catalog = RasContainerImages.catalog()
    assert {(i.role, i.hec_ras_version) for i in catalog} >= {
        ("linux-unsteady", "6.6"), ("wine-precompute", "6.6"), ("linux-unsteady", "7.0.1")}
    for image in catalog:
        assert "@sha256:" in image.reference
        assert image.role in applicable_roles(image.hec_ras_version)


def test_native_role_is_refused_for_releases_without_a_linux_engine():
    with pytest.raises(ValueError, match="no HEC Linux engine"):
        RasContainerImages.get("linux-unsteady", "4.1")


def test_unpublished_image_explains_how_to_supply_one():
    with pytest.raises(LookupError, match="sif_path"):
        RasContainerImages.get("wine-executor", "4.1")


def test_explicit_local_sif_is_used_without_pulling(tmp_path, apptainer):
    fake, log = apptainer
    local = tmp_path / "site-built.sif"
    local.write_bytes(b"site image")
    resolved = RasContainerImages.resolve_sif(
        "wine-executor", "4.1", sif_path=local, apptainer_executable=fake)
    assert resolved.source == "explicit" and resolved.path == local.resolve()
    assert resolved.container_identity == f"sif:sha256:{_sha(b'site image')}"
    assert not log.exists()
    with pytest.raises(ValueError, match="does not match"):
        RasContainerImages.resolve_sif("wine-executor", "4.1", sif_path=local,
                                       expected_sha256="0" * 64, apptainer_executable=fake)
    with pytest.raises(FileNotFoundError):
        RasContainerImages.resolve_sif("wine-executor", "4.1", sif_path=tmp_path / "absent.sif")


def test_cache_is_filled_once_then_reused_offline(tmp_path, apptainer):
    fake, log = apptainer
    cache = tmp_path / "cache"
    first = RasContainerImages.resolve_sif("linux-unsteady", "6.6", cache_dir=cache,
                                           apptainer_executable=fake)
    assert first.source == "pulled" and first.path.parent == cache
    assert (cache / (first.path.name + ".sha256")).read_text().split()[0] == first.sha256
    assert not list(cache.glob("*.partial*"))
    again = RasContainerImages.resolve_sif("linux-unsteady", "6.6", cache_dir=cache,
                                           pull="never", apptainer_executable=fake)
    assert again.source == "cache" and again.sha256 == first.sha256
    assert log.read_text().count("docker://") == 1
    image = RasContainerImages.get("linux-unsteady", "6.6")
    assert log.read_text().strip() == f"docker://{image.reference}"


def test_cache_directory_comes_from_environment(tmp_path, apptainer, monkeypatch):
    fake, _ = apptainer
    monkeypatch.setenv("RAS_COMMANDER_IMAGE_CACHE", str(tmp_path / "shared"))
    resolved = RasContainerImages.resolve_sif("linux-unsteady", "66", apptainer_executable=fake)
    assert resolved.path.parent == tmp_path / "shared"


def test_tampered_cache_entry_is_replaced(tmp_path, apptainer):
    fake, log = apptainer
    cache = tmp_path / "cache"
    first = RasContainerImages.resolve_sif("linux-unsteady", "6.6", cache_dir=cache,
                                           apptainer_executable=fake)
    first.path.write_bytes(b"corrupted")
    with pytest.raises(FileNotFoundError, match="No verified cached SIF"):
        RasContainerImages.resolve_sif("linux-unsteady", "6.6", cache_dir=cache, pull="never",
                                       apptainer_executable=fake)
    repaired = RasContainerImages.resolve_sif("linux-unsteady", "6.6", cache_dir=cache,
                                              apptainer_executable=fake)
    assert repaired.source == "pulled" and repaired.sha256 == first.sha256


def test_pull_always_refreshes_and_failures_leave_no_partial_files(tmp_path, apptainer, monkeypatch):
    fake, log = apptainer
    cache = tmp_path / "cache"
    RasContainerImages.resolve_sif("linux-unsteady", "6.6", cache_dir=cache, apptainer_executable=fake)
    RasContainerImages.resolve_sif("linux-unsteady", "6.6", cache_dir=cache, pull="always",
                                   apptainer_executable=fake)
    assert log.read_text().count("docker://") == 2
    monkeypatch.setenv("FAKE_PULL_FAIL", "1")
    with pytest.raises(RuntimeError, match="registry unreachable"):
        RasContainerImages.resolve_sif("linux-unsteady", "7.0.1", cache_dir=cache,
                                       apptainer_executable=fake)
    assert not list(cache.glob("*7.0.1*"))


def test_published_sif_hash_is_enforced(tmp_path, apptainer, monkeypatch):
    fake, _ = apptainer
    oras = "oras://ghcr.io/gpt-cmdr/hec-ras-linux-unsteady-sif@sha256:" + "a" * 64
    image = ContainerImage("linux-unsteady", "6.6", None,
                           "docker.io/x/y@sha256:" + "b" * 64, oras, "c" * 64)
    module = __import__("ras_commander.RasContainerImages", fromlist=["x"])
    monkeypatch.setattr(module, "_load_catalog", lambda: [image])
    with pytest.raises(ValueError, match="does not match"):
        RasContainerImages.resolve_sif("linux-unsteady", "6.6", cache_dir=tmp_path,
                                       apptainer_executable=fake)
    good = _sha(f"sif for {oras}\n".encode())
    monkeypatch.setattr(module, "_load_catalog", lambda: [
        ContainerImage("linux-unsteady", "6.6", None, image.mirror, oras, good)])
    resolved = RasContainerImages.resolve_sif("linux-unsteady", "6.6", cache_dir=tmp_path,
                                              apptainer_executable=fake)
    assert resolved.sha256 == good


@pytest.mark.skipif(BASH is None or os.name == "nt", reason="needs bash")
def test_ensure_sif_command_is_idempotent(tmp_path, apptainer):
    fake, log = apptainer
    cache = tmp_path / "shared-cache"
    script = RasContainerImages.ensure_sif_command(
        "linux-unsteady", "6.6", str(cache), apptainer_executable=fake)
    first = subprocess.run([BASH, "-c", script], capture_output=True, text=True)
    second = subprocess.run([BASH, "-c", script], capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert first.stdout == second.stdout
    digest, path = first.stdout.split()
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
    assert log.read_text().count("docker://") == 1
    offline = RasContainerImages.ensure_sif_command(
        "linux-unsteady", "7.0.1", str(cache), apptainer_executable=fake, pull=False)
    assert subprocess.run([BASH, "-c", offline], capture_output=True, text=True).returncode == 4


@pytest.mark.skipif(BASH is None or os.name == "nt", reason="needs bash")
def test_ensure_sif_command_fails_loudly_when_the_pull_fails(tmp_path, apptainer, monkeypatch):
    fake, _ = apptainer
    monkeypatch.setenv("FAKE_PULL_FAIL", "1")
    script = RasContainerImages.ensure_sif_command(
        "linux-unsteady", "7.0.1", str(tmp_path / "cache"), apptainer_executable=fake)
    completed = subprocess.run([BASH, "-c", script], capture_output=True, text=True)
    assert completed.returncode == 3 and completed.stdout == ""
    assert not list((tmp_path / "cache").glob("*.sif*"))


def test_ensure_sif_command_work_dir_is_configurable():
    script = RasContainerImages.ensure_sif_command(
        "linux-unsteady", "6.6", "/shared/cache", work_dir="/scratch/$SLURM_JOB_ID/aw")
    assert "/scratch/$SLURM_JOB_ID/aw" in script and "/shared/cache/.apptainer-work" not in script
    with pytest.raises(ValueError, match="absolute"):
        RasContainerImages.ensure_sif_command("linux-unsteady", "6.6", "/c", work_dir="rel")
