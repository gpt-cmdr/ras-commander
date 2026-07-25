"""Qualify native infiltration-region authoring in one fresh HEC process.

The source project must be readable by the requested HEC-RAS runtime. Use a
runtime-native fixture when testing backward compatibility.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np

from ras_commander.hdf import HdfInfiltration


BASE_VALUES = {
    "Curve Number": 64.0,
    "Abstraction Ratio": 0.19,
    "Minimum Infiltration Rate": 0.09,
}
REGION_VALUES = {
    "Curve Number": 54.0,
    "Abstraction Ratio": 0.14,
    "Minimum Infiltration Rate": 0.04,
}


def _set_values(table, values):
    result = table.copy()
    for parameter, value in values.items():
        result[parameter] = value
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-project", type=Path, required=True)
    parser.add_argument("--output-project", type=Path, required=True)
    args = parser.parse_args()

    source = args.source_project.resolve()
    output = args.output_project.resolve()
    if output.exists():
        raise FileExistsError(
            f"Qualification output must be a new disposable directory: {output}"
        )
    shutil.copytree(source, output)
    geometry = output / "BaldEagleDamBrk.g09.hdf"

    if args.version == "5.0.7":
        try:
            HdfInfiltration.create_infiltration_override_regions(
                geometry,
                region_names=["Main Channel"],
                hecras_version=args.version,
            )
        except RuntimeError as exc:
            if "qualified only" not in str(exc):
                raise
            print(
                json.dumps(
                    {
                        "version": args.version,
                        "status": "EXPECTED_UNAVAILABLE",
                        "reason": str(exc),
                    },
                    sort_keys=True,
                )
            )
            return
        raise AssertionError("HEC-RAS 5.0.7 unexpectedly exposed region authoring")

    created = HdfInfiltration.create_infiltration_override_regions(
        geometry,
        region_names=["Main Channel"],
        hecras_version=args.version,
    )
    base_written = HdfInfiltration.set_infiltration_base_overrides(
        geometry,
        _set_values(created, BASE_VALUES),
        hecras_version=args.version,
    )
    region_initial = HdfInfiltration.get_infiltration_region_overrides(
        geometry,
        region_name="Main Channel",
        hecras_version=args.version,
    )
    region_written = HdfInfiltration.set_infiltration_region_overrides(
        geometry,
        _set_values(region_initial, REGION_VALUES),
        region_name="Main Channel",
        hecras_version=args.version,
    )
    region_by_id = HdfInfiltration.get_infiltration_region_overrides(
        geometry,
        region_id=0,
        hecras_version=args.version,
    )
    base_after = HdfInfiltration.get_infiltration_baseoverrides(geometry)

    for parameter, value in BASE_VALUES.items():
        np.testing.assert_allclose(base_written[parameter], value)
        np.testing.assert_allclose(base_after[parameter], value)
    for parameter, value in REGION_VALUES.items():
        np.testing.assert_allclose(region_written[parameter], value)
        np.testing.assert_allclose(region_by_id[parameter], value)

    polygons = HdfInfiltration.get_infiltration_region_polygons(geometry)
    assert HdfInfiltration.get_infiltration_region_names(geometry) == [
        "Main Channel"
    ]
    assert len(polygons) == 1
    assert not polygons.geometry.iloc[0].interiors
    backups = [
        Path(created.attrs["backup_path"]),
        Path(base_written.attrs["backup_path"]),
        Path(region_written.attrs["backup_path"]),
    ]
    assert len(set(backups)) == 3
    assert all(path.exists() for path in backups)

    print(
        json.dumps(
            {
                "version": args.version,
                "status": "PASS",
                "class_rows": len(region_written),
                "region_name": region_written.attrs["region_name"],
                "region_id": region_written.attrs["region_id"],
                "base_values": BASE_VALUES,
                "region_values": REGION_VALUES,
                "backup_count": len(backups),
                "output_project": str(output),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
