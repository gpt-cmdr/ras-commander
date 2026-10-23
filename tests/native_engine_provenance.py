"""Accepted ``ENGINE_COMMIT`` values for the optional native extension.

The extension (``ras-commander-fast-hdf``) is built from
https://github.com/gpt-cmdr/ras-commander-fast-hdf. A wheel reports the commit
it was built from as ``ras_commander_fast_hdf.ENGINE_COMMIT``.

* ``RAS_EXPECTED_ENGINE_COMMIT`` set: only that commit is accepted. Use it to
  gate one specific build (for example a release candidate).
* Otherwise the known released commits below are accepted.

Add a commit here when a new extension release is qualified.
"""
import os

# Internal wheels built before the move, from the private engine repository.
PRE_MOVE_ENGINE_COMMIT = "0b024adc7857e9fb2d364997ad002e01a939cec1"
# First commit of gpt-cmdr/ras-commander-fast-hdf (qualified before the release
# commit; same engine and extension code).
FAST_HDF_FIRST_COMMIT = "7ca433ea4fbe68902a50902de815e56697eb21b2"
# ras-commander-fast-hdf 0.1.0 (tag v0.1.0), the published wheels.
FAST_HDF_0_1_0_COMMIT = "89a62e5079debffd98d152303b32bd1df13b3ec2"
KNOWN_ENGINE_COMMITS = (PRE_MOVE_ENGINE_COMMIT, FAST_HDF_FIRST_COMMIT, FAST_HDF_0_1_0_COMMIT)


def accepted_engine_commits():
    """Return the tuple of engine commits a test should accept."""
    expected = os.environ.get("RAS_EXPECTED_ENGINE_COMMIT", "").strip().lower()
    return (expected,) if expected else KNOWN_ENGINE_COMMITS
