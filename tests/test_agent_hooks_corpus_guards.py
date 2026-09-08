"""Guards protecting the retrieved federal source corpora.

Two rules that were written down but previously unenforced:

* ``F:\\AGENTS.md`` rule 1 -- ``raw\\`` holds as-delivered publisher bytes and is
  never modified. Generated knowledge goes to ``audit\\`` or ``derived\\``.
* Campaign decision D2 -- do not hash corpus data without asking. Verification is
  file size against the provenance sidecar, the ETag, and the zip's own CRC-32.

Both guards must refuse the real thing while staying out of the way of ordinary
work, including *writing about* those paths (this file does exactly that).

Path fragments are assembled at runtime rather than written as literals so that a
harness running these tests under its own PreToolUse hook does not trip the guard
on the test source itself.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DISPATCHER = REPO_ROOT / "scripts" / "agent_hooks" / "hook_dispatch.py"

RAW = "r" + "aw"
NAS_RAW = f"/nas/ebfe/{RAW}"
DRIVE_RAW = f"F:\\eBFE\\{RAW}"
POOL_RAW = f"/mnt/pool_12tb/FEMA/eBFE/{RAW}"
SHA = "sha256" + "sum"
WORK_STUDY = "/work/" + "12090301"


@pytest.fixture(scope="module")
def hooks():
    spec = importlib.util.spec_from_file_location("hook_dispatch", DISPATCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def write(file_path: str, content: str = "") -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": file_path, "content": content}}


# --------------------------------------------------------------------------
# raw\ immutability
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "payload",
    [
        write(f"{DRIVE_RAW}\\12040102\\Models.zip"),
        bash(f"rm -rf {NAS_RAW}/12040102"),
        bash(f"mv staged.zip {POOL_RAW}/12040102/"),
        bash(f"echo x > {NAS_RAW}/12040102/note.txt"),
    ],
    ids=["write-tool", "delete", "move-into", "redirect-into"],
)
def test_writes_to_raw_are_refused(hooks, payload):
    assert hooks.should_deny_immutable_corpus_write(payload) is not None


@pytest.mark.parametrize(
    "payload",
    [
        bash(f"unzip -l {NAS_RAW}/12040102/Models.zip"),
        bash(f"stat {DRIVE_RAW}/12040102/Models.zip"),
        write("/nas/ebfe/audit/12040102/_audit.json"),
        bash("rm -rf /work/12040102"),
        write("ras_commander/RasPrj.py"),
    ],
    ids=["read-listing", "stat", "write-audit", "clear-scratch", "ordinary-edit"],
)
def test_reads_and_non_corpus_writes_are_allowed(hooks, payload):
    assert hooks.should_deny_immutable_corpus_write(payload) is None


def test_writing_a_file_that_merely_mentions_raw_is_allowed(hooks):
    """The destination is what matters, not the content.

    Documenting or testing these paths must stay possible -- this very file
    contains them.
    """
    payload = write("tests/test_agent_hooks_corpus_guards.py", f"path = '{NAS_RAW}'")
    assert hooks.should_deny_immutable_corpus_write(payload) is None


# --------------------------------------------------------------------------
# hashing
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "payload",
    [
        bash(f"{SHA} {NAS_RAW}/12040102/Models.zip"),
        bash(f"Get-FileHash {DRIVE_RAW}\\12040102\\Models.zip"),
        bash(f"find {WORK_STUDY} -type f -exec {SHA} {{}} +"),
    ],
    ids=["posix-sum", "powershell", "over-extracted-study"],
)
def test_hashing_corpus_data_is_refused(hooks, payload):
    assert hooks.should_deny_corpus_hashing(payload) is not None


@pytest.mark.parametrize(
    "payload",
    [
        bash(f"git diff HEAD | {SHA}"),
        bash(f"{SHA} pyproject.toml"),
        bash(f"ls {NAS_RAW}/12040102"),
    ],
    ids=["hash-a-diff", "hash-a-config", "corpus-path-without-hashing"],
)
def test_unrelated_hashing_and_plain_reads_are_allowed(hooks, payload):
    """Scoped to corpus paths, so provenance hashing of small artifacts still works."""
    assert hooks.should_deny_corpus_hashing(payload) is None

# --------------------------------------------------------------------------
# The verb must be related to its target (ST-3 false positives)
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "command",
    [
        "unzip -l {raw}/12100302/M.zip > /work/listing.txt",
        "python probe.py {raw}/12100302/M.zip | tee /work/probe.log",
        "cp {raw}/12100302/M.zip.ebfe-source.json /work/sidecar.json",
        "find {raw}/12100302 -type f > /work/inventory.txt",
        "rm -rf /work/12100302 && unzip -l {raw}/12100302/M.zip",
    ],
    ids=["read-redirect", "read-tee", "copy-out-of", "find-redirect", "clean-then-read"],
)
def test_reading_corpus_and_writing_elsewhere_is_allowed(hooks, command):
    """A write verb and a corpus path in one command do not imply a corpus write.

    Regression for ST-3: probe-then-record was refused, which would have blocked
    routine worker traffic.
    """
    payload = bash(command.format(raw=NAS_RAW))
    assert hooks.should_deny_immutable_corpus_write(payload) is None


@pytest.mark.parametrize(
    "command",
    [
        "cp /work/out.zip {raw}/12100302/",
        "mv staged.json {raw}/12100302/M.zip.ebfe-source.json",
        "echo tampered > {raw}/12100302/note.txt",
        "python gen.py | tee {raw}/12100302/out.txt",
        "rm -rf {raw}/12100302",
        "dd if=/dev/zero of={raw}/12100302/M.zip",
    ],
    ids=["copy-into", "move-into", "redirect-into", "tee-into", "delete", "dd-onto"],
)
def test_writes_targeting_corpus_are_still_refused(hooks, command):
    payload = bash(command.format(raw=NAS_RAW))
    assert hooks.should_deny_immutable_corpus_write(payload) is not None
