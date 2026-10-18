"""Installed-wheel / native consumer acceptance gate.

Blocked by supervisor instruction until an accepted combined source pin and a
reviewed portable-build receipt are supplied. Point
RAS_CONSUMER_ACCEPTANCE_RECEIPT at that JSON receipt to activate; the gate then
asserts the receipt's identity before any native acceptance test may run. The
acceptance tests themselves are deliberately not written against an unreviewed
build.
"""
import hashlib
import json
import os
from pathlib import Path

import pytest

REQUIRED = ("accepted_source_commit", "accepted_source_tree", "portable_build_receipt",
            "wheel_sha256", "native_binary_sha256", "hdf5_reader_rev", "reviewed_by")


def _receipt():
    path = os.environ.get("RAS_CONSUMER_ACCEPTANCE_RECEIPT")
    if not path:
        pytest.skip("BLOCKED: no accepted combined source pin / reviewed portable-build "
                    "receipt (supervisor gate). Native acceptance not attempted.")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED if not data.get(k)]
    assert not missing, f"receipt missing {missing}"
    return data


def test_receipt_identifies_installed_native_module():
    receipt = _receipt()
    import ras_commander
    import ras_commander_fast_hdf as native
    binary = Path(native.__file__)
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == receipt["native_binary_sha256"]
    assert "site-packages" in Path(ras_commander.__file__).as_posix() or \
        receipt.get("editable_install_allowed"), "expected installed-wheel import"
