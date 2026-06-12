"""
Unit tests for the native-Linux Docker host path of DockerWorker.

These tests mock all SSH and Docker interactions so they run without a live
host. A separate live smoke test against CLB07 is documented in the PR notes.

Covered:
    - remote_host_os inference (ssh:// => linux, tcp:// => windows)
    - explicit remote_host_os override and validation of bad values
    - Linux hosts do NOT require share_path; Windows hosts still do
    - ssh:// URL parsing (user/host/port)
    - LinuxDockerSshStager paramiko + system-ssh transports (mocked)
    - execute_docker_plan dispatches to the Linux path for Linux hosts
"""

import sys
from pathlib import Path
from unittest import mock

import pytest

# Ensure the package under test is importable when run directly.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ras_commander.remote.DockerWorker import DockerWorker, execute_docker_plan
from ras_commander.remote.DockerSshStaging import (
    LinuxDockerSshStager,
    parse_ssh_host,
    SshTarget,
)


def _make_worker(**overrides):
    """Build a DockerWorker without going through Docker daemon validation."""
    kwargs = dict(
        worker_type="docker",
        worker_id="docker_test",
        docker_image="hecras:6.6",
    )
    kwargs.update(overrides)
    return DockerWorker(**kwargs)


# --------------------------------------------------------------------------- #
# Host OS inference + validation
# --------------------------------------------------------------------------- #
def test_ssh_host_infers_linux():
    w = _make_worker(
        docker_host="ssh://root@192.168.3.81",
        remote_staging_path="/opt/RasRemote",
    )
    assert w.remote_host_os == "linux"
    assert w._is_remote is True
    assert w._is_linux_host is True


def test_tcp_host_infers_windows_and_requires_share():
    with pytest.raises(ValueError, match="share_path is required"):
        _make_worker(
            docker_host="tcp://192.168.3.8:2375",
            remote_staging_path="C:/RasRemote",
        )


def test_linux_host_does_not_require_share_path():
    # Should not raise even though share_path is None.
    w = _make_worker(
        docker_host="ssh://root@192.168.3.81",
        remote_staging_path="/opt/RasRemote",
    )
    assert w.share_path is None
    assert w._is_linux_host is True


def test_linux_host_requires_remote_staging_path():
    with pytest.raises(ValueError, match="remote_staging_path is required for Linux"):
        _make_worker(docker_host="ssh://root@192.168.3.81")


def test_explicit_windows_over_ssh_requires_share_path():
    with pytest.raises(ValueError, match="share_path is required"):
        _make_worker(
            docker_host="ssh://user@winhost",
            remote_host_os="windows",
            remote_staging_path="C:/RasRemote",
        )


def test_explicit_linux_requires_ssh_url():
    with pytest.raises(ValueError, match="requires an ssh:// docker_host"):
        _make_worker(
            docker_host="tcp://192.168.3.8:2375",
            remote_host_os="linux",
            remote_staging_path="/opt/RasRemote",
        )


def test_invalid_remote_host_os_rejected():
    with pytest.raises(ValueError, match="remote_host_os must be"):
        _make_worker(
            docker_host="ssh://root@host",
            remote_host_os="solaris",
            remote_staging_path="/opt/RasRemote",
        )


def test_local_worker_unaffected():
    w = _make_worker()  # no docker_host
    assert w._is_remote is False
    assert w._is_linux_host is False
    assert w.remote_host_os == "windows"  # default placeholder, unused when local


# --------------------------------------------------------------------------- #
# SSH URL parsing
# --------------------------------------------------------------------------- #
def test_parse_ssh_host_basic():
    t = parse_ssh_host("ssh://root@192.168.3.81")
    assert t == SshTarget(host="192.168.3.81", user="root", port=22)
    assert t.user_host == "root@192.168.3.81"


def test_parse_ssh_host_with_port():
    t = parse_ssh_host("ssh://deploy@host.example:2222")
    assert t.host == "host.example"
    assert t.user == "deploy"
    assert t.port == 2222


def test_parse_ssh_host_rejects_non_ssh():
    with pytest.raises(ValueError):
        parse_ssh_host("tcp://1.2.3.4:2375")


# --------------------------------------------------------------------------- #
# Stager transports (mocked)
# --------------------------------------------------------------------------- #
def test_stager_system_ssh_mkdirs_invokes_ssh():
    stager = LinuxDockerSshStager(
        docker_host="ssh://root@10.0.0.5", use_ssh_client=True
    )
    with mock.patch("subprocess.run") as run:
        run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        stager.mkdirs(["/opt/RasRemote/run1/input", "/opt/RasRemote/run1/output"])
        assert run.called
        args = run.call_args[0][0]
        assert args[0] == "ssh"
        assert "root@10.0.0.5" in args
        assert "mkdir -p" in args[-1]


def test_stager_system_ssh_list_matching_parses_output():
    stager = LinuxDockerSshStager(
        docker_host="ssh://root@10.0.0.5", use_ssh_client=True
    )
    fake_out = "/opt/RasRemote/run1/output/Muncie.p04.hdf\n"
    with mock.patch("subprocess.run") as run:
        run.return_value = mock.Mock(returncode=0, stdout=fake_out, stderr="")
        matches = stager.list_matching(
            "/opt/RasRemote/run1/output", ["*.hdf"]
        )
        assert matches == ["/opt/RasRemote/run1/output/Muncie.p04.hdf"]


def test_stager_paramiko_download(tmp_path):
    stager = LinuxDockerSshStager(
        docker_host="ssh://root@10.0.0.5", use_ssh_client=False
    )
    fake_sftp = mock.Mock()
    fake_client = mock.Mock()
    fake_client.open_sftp.return_value = fake_sftp

    def fake_get(remote, local):
        Path(local).write_text("hdf-bytes")

    fake_sftp.get.side_effect = fake_get

    with mock.patch.object(stager, "_paramiko_client", return_value=fake_client):
        out = stager.download_files(
            ["/opt/RasRemote/run1/output/Muncie.p04.hdf"], tmp_path
        )
    assert len(out) == 1
    assert out[0].name == "Muncie.p04.hdf"
    assert out[0].read_text() == "hdf-bytes"
    fake_client.close.assert_called()


def test_stager_paramiko_upload(tmp_path):
    # Build a small local project tree.
    proj = tmp_path / "proj"
    (proj / "sub").mkdir(parents=True)
    (proj / "Muncie.prj").write_text("prj")
    (proj / "Muncie.p04").write_text("Geom File=g04\n")
    (proj / "sub" / "extra.txt").write_text("x")

    stager = LinuxDockerSshStager(
        docker_host="ssh://root@10.0.0.5", use_ssh_client=False
    )
    fake_sftp = mock.Mock()
    # stat raises IOError so mkdir is attempted for each dir.
    fake_sftp.stat.side_effect = IOError("missing")
    fake_client = mock.Mock()
    fake_client.open_sftp.return_value = fake_sftp

    with mock.patch.object(stager, "_paramiko_client", return_value=fake_client):
        count = stager.upload_dir(proj, "/opt/RasRemote/run1/input")

    assert count == 3
    # Three files put to remote.
    assert fake_sftp.put.call_count == 3


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def test_execute_dispatches_to_linux_path(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "Muncie.prj").write_text("prj")

    ras_obj = mock.Mock()
    ras_obj.project_folder = str(proj)
    ras_obj.project_name = "Muncie"
    ras_obj.ras_version = "6.6"

    w = _make_worker(
        docker_host="ssh://root@192.168.3.81",
        remote_staging_path="/opt/RasRemote",
    )

    with mock.patch(
        "ras_commander.remote.DockerWorker.execute_docker_plan_linux",
        return_value=True,
    ) as linux_fn:
        ok = execute_docker_plan(
            worker=w,
            plan_number="04",
            ras_obj=ras_obj,
            num_cores=2,
            clear_geompre=False,
        )
    assert ok is True
    linux_fn.assert_called_once()
