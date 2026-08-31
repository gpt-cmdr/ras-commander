"""Process-isolated execution-evidence qualification foundations.

This package deliberately contains no HEC-RAS execution implementation.  The
pre-engine foundation validates manifests and immutable receipts, captures
stable filesystem snapshots, and materializes deterministic Arrow tables.
"""

from .aggregate import aggregate_run, verify_run
from .invariants import InvariantResult, evaluate_invariants
from .manifest import ManifestError, normalize_manifest
from .receipts import ReceiptError, verify_attempt_receipt
from .schemas import QUALIFICATION_SCHEMA_VERSION, table_from_rows
from .snapshots import SnapshotError, TreeSnapshot, snapshot_tree

__all__ = [
    "InvariantResult",
    "ManifestError",
    "QUALIFICATION_SCHEMA_VERSION",
    "ReceiptError",
    "SnapshotError",
    "TreeSnapshot",
    "aggregate_run",
    "evaluate_invariants",
    "normalize_manifest",
    "snapshot_tree",
    "table_from_rows",
    "verify_attempt_receipt",
    "verify_run",
]
