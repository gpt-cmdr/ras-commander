"""
End-to-end workflow test: Extract HEC-RAS project extent, download AORC precipitation.

This test demonstrates the complete workflow from a HEC-RAS project to precipitation data.
"""

import sys
from pathlib import Path

# Add ras-commander to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ras_commander import HdfProject
from ras_commander.precip import PrecipAorc

# Paths
project_dir = Path(__file__).parent.parent.parent / "examples" / "example_projects" / "BaldEagleCrkMulti2D"
hdf_path = project_dir / "BaldEagleDamBrk.g01.hdf"
output_dir = Path(__file__).parent / "test_output"

print("=" * 70)
print("AORC Precipitation Download - Full Workflow Test")
print("=" * 70)
print()

# Step 1: Extract project bounds
print("Step 1: Extract project bounds from HEC-RAS HDF file")
print("-" * 70)
print(f"HDF file: {hdf_path}")

west, south, east, north = HdfProject.get_project_bounds_latlon(
    hdf_path,
    buffer_percent=50.0  # 50% buffer to capture upstream areas
)
bounds = (west, south, east, north)

print(f"WGS84 bounds (50% buffer):")
print(f"  West:  {west:.6f}")
print(f"  South: {south:.6f}")
print(f"  East:  {east:.6f}")
print(f"  North: {north:.6f}")
print()

# Step 2: Check AORC availability
print("Step 2: Check AORC data availability")
print("-" * 70)

start_time = "2018-09-15"
end_time = "2018-09-17"

avail = PrecipAorc.check_availability(bounds, start_time, end_time)
print(f"Available: {avail['available']}")
print(f"Message: {avail['message']}")
print()

# Step 3: Download AORC precipitation
print("Step 3: Download AORC precipitation data")
print("-" * 70)
print(f"Time range: {start_time} to {end_time}")

output_path = output_dir / "BaldEagle_precip_sep2018.nc"

result = PrecipAorc.download(
    bounds=bounds,
    start_time=start_time,
    end_time=end_time,
    output_path=output_path
)
print()

# Step 4: Verify downloaded data
print("Step 4: Verify downloaded NetCDF")
print("-" * 70)
print(f"Output file: {result}")
print(f"File size: {result.stat().st_size / 1024:.1f} KB")
print()

import xarray as xr
ds = xr.open_dataset(result)

print("Dataset dimensions:")
for dim, size in ds.dims.items():
    print(f"  {dim}: {size}")
print()

print("Precipitation statistics:")
precip = ds['APCP_surface'].values
print(f"  Min: {precip.min():.4f} kg/m^2")
print(f"  Max: {precip.max():.4f} kg/m^2")
print(f"  Mean: {precip.mean():.4f} kg/m^2")
print()

print("Time range:")
print(f"  Start: {ds.time.values[0]}")
print(f"  End: {ds.time.values[-1]}")
print()

print("=" * 70)
print("Workflow completed successfully!")
print("=" * 70)
print()
print("The NetCDF file can now be imported into HEC-RAS as gridded")
print("precipitation using RAS Mapper's GDAL Raster data source.")
