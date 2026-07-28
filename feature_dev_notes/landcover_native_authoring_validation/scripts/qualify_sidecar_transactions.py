"""Qualify native land-cover and infiltration sidecar transactions.

Run one HEC-RAS version per fresh Python process because pythonnet cannot
unload and replace an already-loaded RasMapperLib generation safely.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import h5py
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ras_commander.hdf.HdfInfiltration import HdfInfiltration  # noqa: E402
from ras_commander.hdf.HdfLandCover import HdfLandCover  # noqa: E402


def _copy_file(source: Path, destination: Path) -> Path:
    if not source.exists():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def _hdf_rows(path: Path) -> list[dict[str, Any]]:
    with h5py.File(path, "r") as hdf_file:
        data = hdf_file["Variables"][()]
    rows: list[dict[str, Any]] = []
    for raw_row in data:
        row: dict[str, Any] = {}
        for name in data.dtype.names or ():
            value = raw_row[name]
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace").strip()
            elif hasattr(value, "item"):
                value = value.item()
            row[name] = value
        rows.append(row)
    return rows


def run_qualification(
    *,
    version: str,
    source_project_root: Path,
    output_dir: Path,
    landcover_value: float,
    curve_number: float,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=False)

    landcover_path = _copy_file(
        source_project_root / "Land Classification" / "LandCover.hdf",
        output_dir / "Land Classification" / "LandCover.hdf",
    )
    _copy_file(
        source_project_root / "Land Classification" / "LandCover.tif",
        output_dir / "Land Classification" / "LandCover.tif",
    )
    _copy_file(
        source_project_root / "Soils Data" / "Hydrologic Soil Groups.hdf",
        output_dir / "Soils Data" / "Hydrologic Soil Groups.hdf",
    )
    _copy_file(
        source_project_root / "Soils Data" / "Hydrologic Soil Groups.tif",
        output_dir / "Soils Data" / "Hydrologic Soil Groups.tif",
    )
    infiltration_path = _copy_file(
        source_project_root / "Soils Data" / "Infiltration.hdf",
        output_dir / "Soils Data" / "Infiltration.hdf",
    )

    landcover_report = HdfLandCover.set_landcover_mannings_n(
        landcover_path,
        {"Mixed Forest": landcover_value},
        hecras_version=version,
    )
    infiltration_result = (
        HdfInfiltration.set_infiltration_sidecar_parameters(
            infiltration_hdf_path=infiltration_path,
            infiltration_df=pd.DataFrame(
                {"Name": ["NoData"], "Curve Number": [curve_number]}
            ),
            hecras_version=version,
        )
    )

    landcover_rows = {
        str(row["Name"]): row for row in _hdf_rows(landcover_path)
    }
    infiltration_rows = {
        str(row["Name"]): row for row in _hdf_rows(infiltration_path)
    }
    observed_landcover = float(landcover_rows["Mixed Forest"]["ManningsN"])
    observed_curve_number = float(
        infiltration_rows["NoData"]["Curve Number"]
    )
    if abs(observed_landcover - landcover_value) > 1.0e-6:
        raise RuntimeError(
            "Land-cover native reload mismatch: "
            f"{observed_landcover} != {landcover_value}"
        )
    if abs(observed_curve_number - curve_number) > 1.0e-6:
        raise RuntimeError(
            "Infiltration native reload mismatch: "
            f"{observed_curve_number} != {curve_number}"
        )

    landcover_backup = Path(landcover_report["backup_path"])
    infiltration_backup = Path(infiltration_result.attrs["backup_path"])
    for backup_path in (landcover_backup, infiltration_backup):
        if not backup_path.exists():
            raise RuntimeError(f"Native transaction backup missing: {backup_path}")

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "version": version,
        "output_dir": str(output_dir),
        "landcover": {
            "requested": landcover_value,
            "observed": observed_landcover,
            "backup_path": str(landcover_backup),
            "recompute_required": bool(
                landcover_report["recompute_required"]
            ),
        },
        "infiltration": {
            "requested_curve_number": curve_number,
            "observed_curve_number": observed_curve_number,
            "backup_path": str(infiltration_backup),
            "recompute_required": bool(
                infiltration_result.attrs["recompute_required"]
            ),
            "row_count": len(infiltration_result),
        },
        "passed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-project-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--landcover-value", required=True, type=float)
    parser.add_argument("--curve-number", required=True, type=float)
    args = parser.parse_args()

    result = run_qualification(
        version=args.version,
        source_project_root=args.source_project_root.resolve(),
        output_dir=args.output_dir.resolve(),
        landcover_value=args.landcover_value,
        curve_number=args.curve_number,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
