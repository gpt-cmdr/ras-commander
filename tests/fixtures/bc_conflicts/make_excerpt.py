"""Write the BC-conflict excerpt from the public corpus plan HDF.

Usage: python make_excerpt.py <BaldEagleDamBrk.p18.all2d.hdf> <output.hdf>

Copies, unchanged (h5py ``copy`` keeps dtypes, values, attributes and storage
filters), only the tables ``GeomMesh.detect_bc_conflicts`` reads.
"""
import sys

import h5py

AREA_DATASETS = (
    "Cells Center Coordinate",  # the native mesh read family indexes faces against it
    "Faces Cell Indexes",
    "Faces FacePoint Indexes",
    "FacePoints Coordinate",
    "Faces Perimeter Info",
    "Faces Perimeter Values",
)


def main(source, output):
    with h5py.File(source, "r") as src, h5py.File(output, "w") as dst:
        for name, value in src.attrs.items():
            dst.attrs[name] = value
        geometry = dst.require_group("Geometry")
        for name, value in src["Geometry"].attrs.items():
            geometry.attrs[name] = value
        src.copy(src["Geometry/Boundary Condition Lines"], geometry, "Boundary Condition Lines")
        areas = geometry.require_group("2D Flow Areas")
        src.copy(src["Geometry/2D Flow Areas/Attributes"], areas, "Attributes")
        for row in src["Geometry/2D Flow Areas/Attributes"][()]:
            area = row["Name"].decode()
            target = areas.require_group(area)
            for dataset in AREA_DATASETS:
                src.copy(src[f"Geometry/2D Flow Areas/{area}/{dataset}"], target, dataset)
        events = dst.require_group("Event Conditions/Unsteady")
        src.copy(src["Event Conditions/Unsteady/Boundary Conditions"], events, "Boundary Conditions")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
