"""Accepted ``ENGINE_COMMIT`` values for the native extension.

The extension (``ras-commander-fast-hdf``) is built from
https://github.com/gpt-cmdr/ras-commander-fast-hdf. A wheel reports the commit
it was built from as ``ras_commander_fast_hdf.ENGINE_COMMIT``.

* ``RAS_EXPECTED_ENGINE_COMMIT`` set: only that commit is accepted. Use it to
  gate one specific build (for example a release candidate).
* Otherwise any complete 40-digit commit is accepted, so a new extension
  release on PyPI does not need a change here. A build without Git metadata
  reports ``"unknown"`` and is rejected.
"""
import os
import re

# Recorded for reference: internal wheels built before the move, from the
# private engine repository; the first commit of gpt-cmdr/ras-commander-fast-hdf;
# and ras-commander-fast-hdf 0.1.0 (tag v0.1.0).
PRE_MOVE_ENGINE_COMMIT = "0b024adc7857e9fb2d364997ad002e01a939cec1"
FAST_HDF_FIRST_COMMIT = "7ca433ea4fbe68902a50902de815e56697eb21b2"
FAST_HDF_0_1_0_COMMIT = "b2ab8280617383519d38aad9bd47b88b654009b1"
KNOWN_ENGINE_COMMITS = (PRE_MOVE_ENGINE_COMMIT, FAST_HDF_FIRST_COMMIT, FAST_HDF_0_1_0_COMMIT)

_COMMIT = re.compile(r"[0-9a-f]{40}")


class _AnyCommit:
    """Container that accepts any complete lowercase hexadecimal commit."""

    def __contains__(self, value):
        return isinstance(value, str) and _COMMIT.fullmatch(value) is not None

    def __repr__(self):
        return "<any 40-digit commit>"


def accepted_engine_commits():
    """Return the engine commits a test should accept (supports ``in``)."""
    expected = os.environ.get("RAS_EXPECTED_ENGINE_COMMIT", "").strip().lower()
    return (expected,) if expected else _AnyCommit()
