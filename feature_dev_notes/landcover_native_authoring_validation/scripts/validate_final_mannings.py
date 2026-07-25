"""Read-only final Manning gate for a completed geometry or plan HDF."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ras_commander.hdf import HdfLandCover


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("hdf_path")
    parser.add_argument("--mesh")
    parser.add_argument("--tolerance", type=float, default=1.0e-4)
    parser.add_argument("--expected", type=float, nargs="*", default=[])
    args = parser.parse_args()

    report = HdfLandCover.audit_final_mannings_n(
        args.hdf_path,
        mesh_name=args.mesh,
        tolerance=args.tolerance,
        expected_values=args.expected,
    )
    print(json.dumps(report.to_dict(orient="records"), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
