"""Installed-wheel provenance gate for the accepted combined build.

Runs only with RAS_CONSUMER_ACCEPTANCE_RECEIPT. Validates the actual wheel
archives (not receipt field presence), the actual inner extension binary, the
Python wheel against the accepted source commit, the installed (non-editable)
import origins, and the runtime ABI against the accepted inventory.
"""
import hashlib
import importlib.metadata as metadata
import inspect
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from .contract import env_path, native_binary, native_package, sha256

pytestmark = pytest.mark.usefixtures("receipt")


def _wheel_member(path, suffixes):
    with zipfile.ZipFile(path) as wheel:
        names = [n for n in wheel.namelist() if n.lower().endswith(suffixes)]
        return {n: hashlib.sha256(wheel.read(n)).hexdigest() for n in names}


def _record_ok(path):
    """Every RECORD hash in the wheel matches its member bytes."""
    import base64
    with zipfile.ZipFile(path) as wheel:
        record = next(n for n in wheel.namelist() if n.endswith(".dist-info/RECORD"))
        bad = []
        for line in wheel.read(record).decode().splitlines():
            name, digest, _size = line.rsplit(",", 2)
            if not digest:
                continue
            algo, value = digest.split("=", 1)
            actual = base64.urlsafe_b64encode(hashlib.new(algo, wheel.read(name)).digest()).rstrip(b"=")
            if actual.decode() != value:
                bad.append(name)
        return bad


def test_receipt_pins_are_the_activated_build(receipt):
    assert receipt["accepted"] is True
    assert receipt["accepted_source_commit"] == "3be708ad3fb1efa482ca9cf2b401e7f31b587d1a"
    assert receipt["accepted_source_tree"] == "bb3254f4d45c3c67acf52f5156c6b9b4841c5117"
    assert receipt["editable_install_allowed"] is False


def test_wheel_archives_hash_and_record(receipt):
    for key, sha_key in (("wheel_path", "wheel_sha256"), ("python_wheel_path", "python_wheel_sha256")):
        path = Path(receipt[key])
        assert sha256(path) == receipt[sha_key], key
        assert _record_ok(path) == [], f"RECORD mismatch in {path.name}"
    members = _wheel_member(receipt["wheel_path"], (".pyd", ".so"))
    assert len(members) == 1, members
    assert next(iter(members.values())) == receipt["native_binary_sha256"]


def test_installed_inner_binary_is_the_accepted_binary(receipt):
    binary, siblings, init = native_binary()
    assert binary != init and init.name == "__init__.py"
    assert siblings == [binary.name], f"ambiguous native binaries: {siblings}"
    assert sha256(binary) == receipt["native_binary_sha256"]
    # Python resolves the extension from exactly this file.
    loaded = sys.modules["ras_commander_fast_hdf.ras_commander_fast_hdf"]
    assert Path(loaded.__file__).resolve() == binary


def test_imports_are_installed_noneditable_and_outside_source(receipt):
    import ras_commander
    source = env_path("RAS_CONSUMER_SOURCE_CHECKOUT")
    cwd = Path.cwd().resolve()
    for dist, module in (("ras-commander", ras_commander), ("ras-commander-fast-hdf", native_package())):
        origin = Path(module.__file__).resolve()
        assert "site-packages" in origin.parts, origin
        if source is not None:
            assert source.resolve() not in origin.parents, f"{dist} imported from source checkout"
        assert cwd not in origin.parents, f"cwd {cwd} is an ancestor of installed {dist}"
        direct = metadata.distribution(dist).read_text("direct_url.json")
        if direct:
            assert not json.loads(direct).get("dir_info", {}).get("editable"), f"{dist} is editable"
    assert metadata.version("ras-commander") == "0.106.1"
    assert metadata.version("ras-commander-fast-hdf") == "0.1.0"


def test_python_wheel_matches_accepted_source(receipt):
    source = env_path("RAS_CONSUMER_SOURCE_CHECKOUT")
    if source is None:
        pytest.skip("RAS_CONSUMER_SOURCE_CHECKOUT not set")
    commit = receipt["accepted_source_commit"]
    assert subprocess.check_output(["git", "-C", str(source), "rev-parse", f"{commit}^{{tree}}"],
                                   text=True).strip() == receipt["accepted_source_tree"]
    exact = crlf_only = 0
    differing, missing = [], []
    with zipfile.ZipFile(receipt["python_wheel_path"]) as wheel:
        for name in wheel.namelist():
            if not name.startswith("ras_commander/"):
                continue
            blob = subprocess.run(["git", "-C", str(source), "show", f"{commit}:{name}"],
                                  capture_output=True)
            if blob.returncode:
                missing.append(name)
                continue
            data = wheel.read(name)
            if data == blob.stdout:
                exact += 1
            elif data.replace(b"\r\n", b"\n") == blob.stdout.replace(b"\r\n", b"\n"):
                crlf_only += 1  # producer checkout used autocrlf; content identical
            else:
                differing.append(name)
    print(json.dumps(dict(exact=exact, crlf_only=crlf_only, differing=differing, missing=missing)))
    assert differing == [] and missing == [] and exact + crlf_only > 200


def test_runtime_abi_matches_accepted_inventory(receipt):
    inventory = json.loads(Path(receipt["runtime_inventory"]).read_text(encoding="utf-8"))
    assert inventory["source_commit"] == receipt["accepted_source_commit"]
    assert inventory["native_binary_sha256"] == receipt["native_binary_sha256"]
    pkg = native_package()
    assert pkg.API_VERSION == inventory["api_version"] == 1
    assert pkg.TEXT_API_VERSION == inventory["text_api_version"] == 1
    runtime = {}
    for name in dir(pkg):
        obj = getattr(pkg, name)
        if name.startswith("_") or isinstance(obj, type(pkg)) or not callable(obj):
            continue
        if isinstance(obj, type) and issubclass(obj, BaseException):
            continue
        entry = {"signature": str(inspect.signature(obj)),
                 "kind": "class" if isinstance(obj, type) else "function"}
        if isinstance(obj, type):
            entry["methods"] = {m: str(inspect.signature(getattr(obj, m)))
                                for m in inventory["entrypoints"].get(name, {}).get("methods", {})}
        runtime[name] = entry
    assert sorted(runtime) == sorted(inventory["entrypoints"])
    assert len(runtime) == 17
    for name, entry in inventory["entrypoints"].items():
        assert runtime[name]["signature"] == entry["signature"], name
        assert runtime[name]["kind"] == entry["kind"], name
        if "methods" in entry:
            assert runtime[name]["methods"] == entry["methods"], name


def test_cwd_is_isolated_from_source_and_venv():
    cwd = Path.cwd().resolve()
    source = env_path("RAS_CONSUMER_SOURCE_CHECKOUT")
    prefix = Path(sys.prefix).resolve()
    assert cwd not in prefix.parents and cwd != prefix
    if source is not None:
        assert cwd != source.resolve() and source.resolve() not in cwd.parents
        assert cwd not in source.resolve().parents
    assert "PYTHONPATH" not in os.environ or not os.environ["PYTHONPATH"]
