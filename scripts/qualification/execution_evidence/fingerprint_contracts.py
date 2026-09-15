"""Versioned fingerprint namespaces used by qualification evidence."""

from __future__ import annotations


# ``snapshot_tree`` hashes canonical JSON rows for existing regular files.
# This namespace is intentionally distinct from ``stage_project``'s framed
# tree digest, which also represents directory population.
QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM = (
    "ras_commander.qualification_snapshot.canonical_json.v1"
)
