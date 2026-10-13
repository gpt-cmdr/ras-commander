"""Offline checks of the SIF builder and the Wine executor build script.

``build_sif_from_archive.sbatch`` runs end to end with a stand-in
``apptainer`` on PATH, exercising hash checks, no-clobber publication, the
record sidecar, and cleanup. ``build_executor_image.sh`` is checked for syntax,
its executor contract, and argument validation before any Docker call. No
Docker, Apptainer, Slurm, or Wine is required.
"""

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SBATCH = REPO_ROOT / "containers" / "apptainer" / "build_sif_from_archive.sbatch"
EXECUTOR_BUILD = REPO_ROOT / "containers" / "hecras-wine-executor" / "build_executor_image.sh"
BASH = shutil.which("bash")
CONFIG_DIGEST = "ab" * 32

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or BASH is None, reason="Linux bash scripts"
)

FAKE_APPTAINER = r"""#!/bin/bash
set -e
case "$1" in
  --version) echo "apptainer version 0.0.0-test" ;;
  build)
    if [ -n "${FAKE_DOCKER_ARCHIVE_FAILS:-}" ] && [[ "$3" == docker-archive://* ]]; then exit 1; fi
    printf 'sif built from %s\n' "${3%%://*}" > "$2" ;;
  inspect) echo "inspect $*" ;;
  exec)
    shift
    while [[ "$1" == --* ]]; do
      case "$1" in --workdir|--bind|--env) shift 2 ;; *) shift ;; esac
    done
    [ -f "$1" ] || exit 9
    shift
    printf '%s\n' "$*" >> "$FAKE_EXEC_LOG"
    if [ -n "${FAKE_SMOKE_FAILS:-}" ]; then exit 3; fi
    echo "smoke ok" ;;
  *) exit 64 ;;
esac
"""


def _syntax_check(path):
    completed = subprocess.run([BASH, "-n", str(path)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_scripts_parse_with_bash():
    _syntax_check(SBATCH)
    _syntax_check(EXECUTOR_BUILD)


@pytest.mark.parametrize("path", [SBATCH, EXECUTOR_BUILD])
def test_scripts_contain_no_site_specific_settings(path):
    text = path.read_text(encoding="utf-8")
    for fragment in ("fim", "/mnt/", "--account=", "--partition=", "HUC"):
        lines = [line for line in text.splitlines()
                 if fragment in line and not line.lstrip().startswith("#")]
        assert lines == [], (fragment, lines)
    assert "#SBATCH --account" not in text
    assert "#SBATCH --partition" not in text


def _archive(directory, name="image.tar.gz", sidecar=True, compressed=True):
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as archive:
        manifest = json.dumps([{
            "Config": "blobs/sha256/" + CONFIG_DIGEST,
            "RepoTags": ["local/test:review"],
            "Layers": [],
        }]).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest)
        archive.addfile(info, io.BytesIO(manifest))
    data = gzip.compress(payload.getvalue()) if compressed else payload.getvalue()
    path = directory / name
    path.write_bytes(data)
    if sidecar:
        digest = hashlib.sha256(data).hexdigest()
        Path(str(path) + ".sha256").write_text(digest + "  " + name + "\n")
    return path


@pytest.fixture
def sif_site(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "apptainer"
    fake.write_text(FAKE_APPTAINER)
    fake.chmod(0o755)
    dest = tmp_path / "images"
    dest.mkdir()
    scratch = tmp_path / "scratch"
    environment = {
        "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "SLURM_JOB_ID": "4242",
        "RAS_COMMANDER_SIF_NAME": "executor_6.6-test",
        "RAS_COMMANDER_SIF_SRC": str(_archive(tmp_path)),
        "RAS_COMMANDER_SIF_DEST": str(dest),
        "RAS_COMMANDER_SIF_SCRATCH": str(scratch),
        "FAKE_EXEC_LOG": str(tmp_path / "exec.log"),
    }
    return SimpleSite(tmp_path, dest, scratch, environment)


class SimpleSite:
    def __init__(self, root, dest, scratch, environment):
        self.root = root
        self.dest = dest
        self.scratch = scratch
        self.environment = environment

    def run(self, **overrides):
        environment = dict(self.environment)
        for key, value in overrides.items():
            if value is None:
                environment.pop(key, None)
            else:
                environment[key] = value
        return subprocess.run([BASH, str(SBATCH)], env=environment, capture_output=True,
                              text=True, timeout=60)


def _published(dest):
    return sorted(path.name for path in dest.iterdir())


def test_sif_builder_publishes_sif_hash_and_record(sif_site):
    completed = sif_site.run()
    assert completed.returncode == 0, completed.stdout + completed.stderr
    name = "executor_6.6-test.sif"
    assert _published(sif_site.dest) == [name, name + ".json", name + ".sha256"]
    sif = sif_site.dest / name
    digest = hashlib.sha256(sif.read_bytes()).hexdigest()
    assert (sif_site.dest / (name + ".sha256")).read_text() == digest + "  " + name + "\n"
    record = json.loads((sif_site.dest / (name + ".json")).read_text())
    source = Path(sif_site.environment["RAS_COMMANDER_SIF_SRC"])
    assert record["schema"] == "ras-commander-sif-record/v1"
    assert record["sif"] == name
    assert record["sif_sha256"] == digest
    assert record["image_id"] == "sha256:" + CONFIG_DIGEST
    assert record["source_archive"] == str(source.resolve())
    assert record["source_archive_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert record["smoke_command"] == "python -m ras_commander.remote.execute_request --help"
    assert record["slurm_job_id"] == "4242"
    assert sif.read_text() == "sif built from docker-archive\n"
    # The smoke command runs through /bin/sh -c inside the SIF.
    log = Path(sif_site.environment["FAKE_EXEC_LOG"]).read_text()
    assert log == "/bin/sh -c python -m ras_commander.remote.execute_request --help\n"
    # The private scratch work directory is removed.
    assert list(sif_site.scratch.iterdir()) == []


def test_sif_builder_refuses_to_overwrite(sif_site):
    assert sif_site.run().returncode == 0
    before = {path.name: path.read_bytes() for path in sif_site.dest.iterdir()}
    completed = sif_site.run()
    assert completed.returncode == 2
    assert "REFUSE" in completed.stdout
    assert {path.name: path.read_bytes() for path in sif_site.dest.iterdir()} == before


def test_sif_builder_rejects_archive_hash_mismatch(sif_site):
    source = Path(sif_site.environment["RAS_COMMANDER_SIF_SRC"])
    Path(str(source) + ".sha256").write_text("0" * 64 + "  image.tar.gz\n")
    completed = sif_site.run()
    assert completed.returncode == 5
    assert "SOURCE HASH MISMATCH" in completed.stdout
    assert _published(sif_site.dest) == []


def test_sif_builder_failed_smoke_publishes_nothing(sif_site):
    completed = sif_site.run(FAKE_SMOKE_FAILS="1",
                             RAS_COMMANDER_SIF_SMOKE="test -x /opt/hecras-runtime/engine/RasUnsteady")
    assert completed.returncode == 7
    assert "SMOKE FAILED" in completed.stdout
    assert _published(sif_site.dest) == []
    assert list(sif_site.scratch.iterdir()) == []


def test_sif_builder_falls_back_to_oci_archive_and_accepts_plain_tar(sif_site):
    source = _archive(sif_site.root, name="plain.tar", sidecar=False, compressed=False)
    completed = sif_site.run(FAKE_DOCKER_ARCHIVE_FAILS="1", RAS_COMMANDER_SIF_SRC=str(source))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert (sif_site.dest / "executor_6.6-test.sif").read_text() == "sif built from oci-archive\n"


@pytest.mark.parametrize("name", ["../escape", "a/b", ".hidden", "bad name", "x..y", ""])
def test_sif_builder_rejects_unsafe_names(sif_site, name):
    completed = sif_site.run(RAS_COMMANDER_SIF_NAME=name)
    assert completed.returncode != 0
    assert _published(sif_site.dest) == []
    assert not (sif_site.root / "escape.sif").exists()


def test_sif_builder_requires_existing_destination(sif_site):
    completed = sif_site.run(RAS_COMMANDER_SIF_DEST=str(sif_site.root / "missing"))
    assert completed.returncode == 2
    assert "does not exist" in completed.stdout


# --- Wine executor build script -------------------------------------------

def test_executor_build_sets_the_portable_executor_contract():
    from ras_commander.remote import execute_request

    script = EXECUTOR_BUILD.read_text(encoding="utf-8")
    for variable in (execute_request._WINE_PREFIX_SEED, execute_request._WINE_PYTHON,
                     execute_request._WINE_ARCH, execute_request._WINE_CPU_SHIM):
        assert "--change \"ENV " + variable + "=" in script or "--change 'ENV " + variable + "=" in script
    assert "ENV RAS_COMMANDER_WINE_PYTHON=C:\\\\Python311\\\\python.exe" in script
    assert "ENV RAS_COMMANDER_WINE_ARCH=win64" in script
    assert "SEED=/runtime/wine-seed/prefix" in script
    assert 'ENTRYPOINT ["/usr/bin/tini", "--"]' in script
    assert '"ras_commander.remote.execute_request"' in script
    assert "../Program Files (x86)/HEC/HEC-RAS/$VERSION/GDAL" in script
    for label in ("io.ras-commander.wheel-sha256", "io.ras-commander.commit",
                  "io.ras-commander.parent-image", "org.opencontainers.image.revision"):
        assert "LABEL " + label + "=" in script


@pytest.fixture
def executor_inputs(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "docker-called"
    docker = bin_dir / "docker"
    docker.write_text("#!/bin/bash\necho \"$*\" >> " + str(marker) + "\nexit 1\n")
    docker.chmod(0o755)
    wheel = tmp_path / "ras_commander-0.105.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "DOCKER": str(docker),
        "RAS_COMMANDER_COMMIT": "c" * 40,
    }
    base = "rascommander/hec-ras-wine-precompute_6.6@sha256:" + "5" * 64
    return environment, marker, wheel, base


def _run_executor_build(environment, *args):
    return subprocess.run([BASH, str(EXECUTOR_BUILD), *map(str, args)], env=environment,
                          capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("change", ["version", "tagged-base", "wheel-name", "commit", "tag"])
def test_executor_build_validates_inputs_before_docker(executor_inputs, tmp_path, change):
    environment, marker, wheel, base = executor_inputs
    version, tag = "6.6", "local/hec-ras-wine-executor_6.6:review"
    if change == "version":
        version = "6.4"
    elif change == "tagged-base":
        base = "rascommander/hec-ras-wine-precompute_6.6:v4"
    elif change == "wheel-name":
        wheel = tmp_path / "ras_commander-0.105.0-cp313-cp313-linux_x86_64.whl"
        wheel.write_bytes(b"wheel")
    elif change == "commit":
        environment = dict(environment, RAS_COMMANDER_COMMIT="main")
    elif change == "tag":
        tag = "no-tag"
    completed = _run_executor_build(environment, version, base, wheel, tag)
    assert completed.returncode == 2, completed.stderr
    assert completed.stderr.startswith("error:")
    assert not marker.exists()


def test_executor_build_requires_a_commit(executor_inputs):
    environment, marker, wheel, base = executor_inputs
    environment = dict(environment)
    environment.pop("RAS_COMMANDER_COMMIT")
    completed = _run_executor_build(environment, "6.6", base, wheel, "local/x:review")
    assert completed.returncode != 0
    assert "RAS_COMMANDER_COMMIT" in completed.stderr
    assert not marker.exists()


def test_executor_build_reaches_docker_with_valid_inputs(executor_inputs):
    environment, marker, wheel, base = executor_inputs
    completed = _run_executor_build(environment, "6.6", base, wheel, "local/x:review")
    # The stand-in Docker fails, so the build stops at the first image lookup.
    assert completed.returncode != 0
    calls = marker.read_text().splitlines()
    assert calls[0] == "image inspect " + base
