"""Patched hdf5-reader preparation: pins, patch hashes, refusal paths.

Runs with only the standard library and git. Set ``RAS_DIST_DEP_SOURCE`` to a
Git URL or local netcdf-rust repository to also prepare the real dependency
and verify the recorded patched tree.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts" / "build_rust_backend"
sys.path.insert(0, str(SCRIPTS))
import prepare_dependency as prep  # noqa: E402

MANIFEST = prep.load_manifest()


def test_manifest_matches_cargo_pin():
    cargo = tomllib.loads((ROOT / "rust" / "fast-hdf" / "Cargo.toml").read_text(encoding="utf-8"))
    pin = cargo["dependencies"]["hdf5-reader"]
    assert pin["git"] == MANIFEST["cargo_patch_source"]
    assert pin["rev"] == MANIFEST["commit"]
    assert MANIFEST["patched_tree"] and re.fullmatch(r"[0-9a-f]{40}", MANIFEST["patched_tree"])


def test_lock_requires_the_path_override():
    """The committed lock has no git source for hdf5-reader, so --locked needs the override."""
    lock = tomllib.loads((ROOT / "rust" / "fast-hdf" / "Cargo.lock").read_text(encoding="utf-8"))
    entries = {p["name"]: p for p in lock["package"] if p["name"] in {"hdf5-reader", "hdf5-core"}}
    assert set(entries) == {"hdf5-reader", "hdf5-core"}
    assert all("source" not in entry for entry in entries.values())


def test_checked_patch_hashes():
    paths = prep.verify_patches(MANIFEST)
    assert [p.name for p in paths] == ["01-dependency-shared-message.patch",
                                       "02-dependency-fixed-array-width.patch"]
    for path in paths:
        text = path.read_bytes()
        assert b"\r\n" not in text, "patch line endings must stay LF to keep the recorded hash"
        assert all(line.startswith(b"+++ b/hdf5-reader/") for line in text.splitlines()
                   if line.startswith(b"+++ "))


def test_tampered_patch_rejected(tmp_path):
    shutil.copytree(SCRIPTS / "patches", tmp_path / "patches")
    (tmp_path / "dependency.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    target = tmp_path / "patches" / "02-dependency-fixed-array-width.patch"
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(prep.PrepareError, match="SHA256 mismatch"):
        prep.prepare(tmp_path / "dep", "unused", tmp_path / "dependency.json")
    assert not (tmp_path / "dep").exists()


def test_existing_non_repository_destination_preserved(tmp_path):
    dest = tmp_path / "dep"
    dest.mkdir()
    (dest / "keep.txt").write_text("user work", encoding="utf-8")
    with pytest.raises(prep.PrepareError, match="refusing to overwrite"):
        prep.prepare(dest, "unused")
    assert (dest / "keep.txt").read_text(encoding="utf-8") == "user work"


def test_cargo_override_forms_agree(tmp_path):
    dest = tmp_path / "dep"
    args = prep.cargo_config_args(dest, MANIFEST)
    toml = tomllib.loads(prep.cargo_patch_toml(dest, MANIFEST))
    table = toml["patch"][MANIFEST["cargo_patch_source"]]
    assert set(table) == set(MANIFEST["override_crates"]) == {"hdf5-reader"}
    expected = (dest / "hdf5-reader").resolve().as_posix()
    assert table["hdf5-reader"]["path"] == expected
    assert args == ["--config", f'patch."{MANIFEST["cargo_patch_source"]}".hdf5-reader.path="{expected}"']
    assert "\\" not in expected and not expected.startswith("//")


@pytest.mark.skipif(not os.environ.get("RAS_DIST_DEP_SOURCE"),
                    reason="RAS_DIST_DEP_SOURCE (netcdf-rust Git URL or local repo) not provided")
def test_real_preparation_reproduces_tree(tmp_path):
    dest = tmp_path / "netcdf-rust"
    receipt = prep.prepare(dest, os.environ["RAS_DIST_DEP_SOURCE"])
    assert receipt["state"] == "created"
    assert receipt["patched_tree"] == MANIFEST["patched_tree"]
    assert set(receipt["license_files"]) == {"LICENSE-MIT", "LICENSE-APACHE"}
    head = subprocess.check_output(["git", "-C", str(dest), "rev-parse", "HEAD"], text=True).strip()
    assert head == MANIFEST["commit"]
    again = prep.prepare(dest, os.environ["RAS_DIST_DEP_SOURCE"])
    assert again["state"] == "existing-verified"
    (dest / "hdf5-reader" / "src" / "lib.rs").write_text("// local edit\n", encoding="utf-8")
    with pytest.raises(prep.PrepareError, match="preserved, not reset"):
        prep.prepare(dest, os.environ["RAS_DIST_DEP_SOURCE"])
    assert (dest / "hdf5-reader" / "src" / "lib.rs").read_text(encoding="utf-8") == "// local edit\n"
