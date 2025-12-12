"""Test script for HdfProject.get_project_extent()"""

import sys
from pathlib import Path

# Add ras-commander to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ras_commander import HdfProject

# Test with BaldEagleCrkMulti2D
hdf_path = Path(__file__).parent.parent.parent / "examples" / "example_projects" / "BaldEagleCrkMulti2D" / "BaldEagleDamBrk.g01.hdf"

print(f"Testing with: {hdf_path}")
print(f"File exists: {hdf_path.exists()}")
print()

# Test get_project_extent
print("=" * 60)
print("Testing get_project_extent()")
print("=" * 60)

extent_gdf, bounds = HdfProject.get_project_extent(hdf_path, buffer_percent=50.0)
print(f"CRS: {extent_gdf.crs}")
print(f"Geometry type: {extent_gdf.geometry.iloc[0].geom_type}")
print(f"Buffered bounds (project CRS): {bounds}")
print()

# Test get_project_bounds_latlon
print("=" * 60)
print("Testing get_project_bounds_latlon()")
print("=" * 60)

west, south, east, north = HdfProject.get_project_bounds_latlon(hdf_path, buffer_percent=50.0)
print(f"WGS84 bounds:")
print(f"  West:  {west:.6f}")
print(f"  South: {south:.6f}")
print(f"  East:  {east:.6f}")
print(f"  North: {north:.6f}")
print()

# Test get_project_crs
print("=" * 60)
print("Testing get_project_crs()")
print("=" * 60)

crs = HdfProject.get_project_crs(hdf_path)
print(f"Project CRS: {crs}")
print()

print("All tests completed successfully!")
