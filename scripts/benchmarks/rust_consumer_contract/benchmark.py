"""On-demand slice versus whole-plan archival route: consumer benchmark plan.

GATED. Refuses to measure until an accepted combined source pin and reviewed
portable-build receipt are supplied (supervisor instruction for the
consumer-contract packet). Running it without a receipt prints the planned
matrix and exits 2, so no unreviewed binary is ever reported as accepted.

    python scripts/benchmarks/rust_consumer_contract/benchmark.py --plan
    python scripts/benchmarks/rust_consumer_contract/benchmark.py --receipt R.json --fixtures F.json --out DIR

Planned measurements (release build, same immutable copied fixture, >=3
interleaved reference/candidate repetitions, semantically equal full output):
  * open+capability+slice read via fast_hdf.read_dataset(selection=...) versus
    h5py full-dataset read then slice (no-full-read assertion uses
    numeric_capability chunk layout and bytes_read where exposed);
  * repeated open/select/read loop versus one whole-plan archival export;
  * mesh WKB/Arrow assembly (packed_meshes) versus Python polygonizer;
  * first-tier export per advertised format with independent reopen/decode.
Each row reports extraction, setup, kernel, encoding, output, total wall,
peak process RSS (not isolated native memory), temporary disk, thread count,
hardware, fixture and binary SHA256, cold/warm scope and copy/IPC notes.
"""
import argparse
import json
import sys
from pathlib import Path

FIXTURES = [
    # Stored-version coverage is decided from the HDF, not archive labels.
    {"id": "D601_p04", "expect": {"valid_polygons": 340246, "ghosts": 11893}},
    {"id": "BaldEagle66_p07", "expect": {"cells": 87039}},
    {"id": "BaldEagle66_p03", "expect": {"cells": 18066}},
    {"id": "Stored70_p18", "expect": {"cells": 4425, "final_regions": 72}},
]
ROUTES = ["slice_native", "slice_python_reference", "repeated_open_select_read",
          "whole_plan_archival", "mesh_wkb_arrow", "first_tier_export_reopen"]
REQUIRED = ("accepted_source_commit", "accepted_source_tree", "portable_build_receipt",
            "wheel_sha256", "native_binary_sha256", "hdf5_reader_rev", "reviewed_by")


def plan():
    return {"schema": "ras-commander/consumer-benchmark-plan/v1", "fixtures": FIXTURES,
            "routes": ROUTES, "min_interleaved_repetitions": 3,
            "status": "blocked: awaiting accepted pins + reviewed portable-build receipt"}


def main():
    parser = argparse.ArgumentParser(description="Gated consumer benchmark")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.plan or not args.receipt:
        print(json.dumps(plan(), indent=2))
        return 0 if args.plan else 2
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED if not receipt.get(k)]
    if missing:
        print(f"receipt incomplete: {missing}", file=sys.stderr)
        return 2
    print("Receipt accepted; measurement routines intentionally not implemented in "
          "phase 1 (source/API inventory only).", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
