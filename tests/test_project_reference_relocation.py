"""Exact-record relocation on new clones without requiring initialized RAS state."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

import pytest

owner = importlib.import_module("ras_commander.RasUtils")
OLD = r".\delivered_plans\SampleModel.p01"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model(tmp_path, project=None):
    project_file = tmp_path / "SampleModel.prj"
    plan = tmp_path / "SampleModel.p01"
    project_file.write_bytes(
        project
        if project is not None
        else (
            "Proj Title=SampleModel\r\nPlan File=" + OLD + "\r\nCurrent Plan=p01\r\n"
        ).encode()
    )
    plan.write_bytes(b"Plan Title=delivered\r\nComputation Interval=30SEC\r\n")
    return project_file, plan


def relocate(project, plan, **kwargs):
    expected = (
        kwargs.pop("expected_target_sha256")
        if "expected_target_sha256" in kwargs
        else sha(plan)
    )
    return owner.RasUtils.relocate_project_reference(
        project,
        kwargs.pop("entry_type", "Plan"),
        kwargs.pop("old_reference", OLD),
        kwargs.pop("new_reference", "p01"),
        expected_target_sha256=expected,
        **kwargs,
    )


@pytest.mark.parametrize("newline", [b"\r\n", b"\n", b"\r"])
@pytest.mark.parametrize("terminal", [True, False])
def test_preserves_other_records_encoding_and_plan_bytes(tmp_path, newline, terminal):
    original = newline.join(
        [
            b"Proj Title=Rivi\xe8re",
            b"Plan File=" + OLD.encode(),
            b"Current Plan=p01",
            b"Unknown=preserve \x80 \xff bytes",
        ]
    ) + (newline if terminal else b"")
    project, plan = model(tmp_path, original)
    plan_bytes = plan.read_bytes()
    receipt = relocate(project, plan)
    assert project.read_bytes() == original.replace(OLD.encode(), b"p01")
    assert plan.read_bytes() == plan_bytes
    assert receipt["other_project_bytes_preserved"] and receipt["plan_bytes_unchanged"]
    assert receipt["project_before_sha256"] == hashlib.sha256(original).hexdigest()
    assert receipt["project_after_sha256"] == sha(project)
    assert receipt["target_sha256"] == sha(plan)
    assert not list(tmp_path.glob("*.tmp"))


def test_mixed_newlines_and_utf8_bom_are_preserved(tmp_path):
    original = (
        b"\xef\xbb\xbfProj Title=\xe6\xb2\xb3\r\nPlan File="
        + OLD.encode()
        + b"\nCurrent Plan=p01\rTail=unchanged"
    )
    project, plan = model(tmp_path, original)
    relocate(project, plan)
    assert project.read_bytes() == original.replace(OLD.encode(), b"p01")


def test_no_initialized_ras_project_required(tmp_path, monkeypatch):
    project, plan = model(tmp_path)
    monkeypatch.setattr(
        owner.ras, "check_initialized", lambda: pytest.fail("RAS initialization used")
    )
    assert relocate(project, plan)["atomic_replace"]


@pytest.mark.parametrize(
    "other", [b"Plan File=p01", b"Plan File= P01 ", b"Plan File=" + OLD.encode()]
)
def test_duplicate_old_or_new_references_refused_without_mutation(tmp_path, other):
    project, plan = model(tmp_path)
    original = project.read_bytes() + other + b"\r\n"
    project.write_bytes(original)
    with pytest.raises(ValueError):
        relocate(project, plan)
    assert project.read_bytes() == original


@pytest.mark.parametrize(
    "kwargs",
    [
        {"entry_type": "Geom"},
        {"new_reference": "p1"},
        {"new_reference": "../p01"},
        {"new_reference": "P01"},
        {"expected_target_sha256": "bad"},
        {"expected_target_sha256": "0" * 64},
        {"old_reference": "p02"},
        {"old_reference": ""},
        {"old_reference": OLD + "\nInjected=x"},
        {"old_reference": "p01"},
        {"old_reference": "../SampleModel.p01"},
        {"old_reference": r"C:\outside\SampleModel.p01"},
        {"old_reference": r"\outside\SampleModel.p01"},
        {"old_reference": r"\\server\share\SampleModel.p01"},
    ],
)
def test_invalid_or_escaping_contract_rejected(tmp_path, kwargs):
    project, plan = model(tmp_path)
    original, plan_bytes = project.read_bytes(), plan.read_bytes()
    with pytest.raises((ValueError, FileNotFoundError)):
        relocate(project, plan, **kwargs)
    assert project.read_bytes() == original and plan.read_bytes() == plan_bytes


def test_missing_or_nonregular_target_is_refused(tmp_path):
    project, plan = model(tmp_path)
    expected = sha(plan)
    plan.unlink()
    original = project.read_bytes()
    with pytest.raises(FileNotFoundError):
        relocate(project, plan, expected_target_sha256=expected)
    plan.mkdir()
    with pytest.raises(ValueError):
        relocate(project, plan, expected_target_sha256=expected)
    assert project.read_bytes() == original


def test_plan_symlink_refused(tmp_path):
    project, plan = model(tmp_path)
    outside = tmp_path / "outside-plan"
    outside.write_bytes(plan.read_bytes())
    plan.unlink()
    try:
        plan.symlink_to(outside)
    except OSError:
        pytest.skip("Host cannot create symbolic links")
    original = project.read_bytes()
    with pytest.raises(ValueError):
        relocate(project, plan)
    assert project.read_bytes() == original


def test_atomic_publish_and_hash_readback(tmp_path, monkeypatch):
    project, plan = model(tmp_path)
    original = project.read_bytes()
    real_replace = owner.os.replace
    observed = []

    def replace(source, destination):
        assert project.read_bytes() == original
        assert Path(source).read_bytes() == original.replace(OLD.encode(), b"p01")
        observed.append(destination)
        return real_replace(source, destination)

    monkeypatch.setattr(owner.os, "replace", replace)
    assert relocate(project, plan)["atomic_replace"]
    assert observed == [project.resolve()]


def test_owner_writer_failure_keeps_original_and_cleans_temp(tmp_path, monkeypatch):
    project, plan = model(tmp_path)
    original = project.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("injected serialization failure")

    monkeypatch.setattr(owner, "_write_ras_text", fail)
    with pytest.raises(OSError):
        relocate(project, plan)
    assert project.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_source_project_drift_refused_before_publish(tmp_path, monkeypatch):
    project, plan = model(tmp_path)
    other_edit = project.read_bytes() + b"OtherOwner=change\r\n"
    real_write = owner._write_ras_text

    def changed(*args, **kwargs):
        real_write(*args, **kwargs)
        project.write_bytes(other_edit)

    monkeypatch.setattr(owner, "_write_ras_text", changed)
    with pytest.raises(RuntimeError, match="changed before"):
        relocate(project, plan)
    assert project.read_bytes() == other_edit


@pytest.mark.parametrize(
    "alias",
    [r".\SampleModel.p01", r".\other\SampleModel.p01", "p01", "SAMPLEMODEL.P01"],
)
def test_destination_aliases_are_rejected(tmp_path, alias):
    project, plan = model(tmp_path)
    project.write_bytes(project.read_bytes() + ("Plan File=" + alias + "\r\n").encode())
    before = project.read_bytes()
    with pytest.raises(ValueError, match="already registered or ambiguous"):
        relocate(project, plan)
    assert project.read_bytes() == before
