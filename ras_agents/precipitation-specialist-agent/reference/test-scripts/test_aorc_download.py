"""Test script for PrecipAorc.download()"""

import sys
from pathlib import Path

# Add ras-commander to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ras_commander.precip import PrecipAorc

# BaldEagleCrkMulti2D bounds (with 50% buffer) from test_project_extent.py
bounds = (-77.708454, 41.010214, -77.251087, 41.219666)  # west, south, east, north

# Test with a short time period (2 days)
start_time = "2018-09-01"
end_time = "2018-09-02"

output_path = Path(__file__).parent / "test_output" / "aorc_test.nc"

print("=" * 60)
print("Testing PrecipAorc.download()")
print("=" * 60)
print(f"Bounds: {bounds}")
print(f"Time range: {start_time} to {end_time}")
print(f"Output: {output_path}")
print()

# First test get_info
print("=" * 60)
print("Testing PrecipAorc.get_info()")
print("=" * 60)
info = PrecipAorc.get_info()
for key, value in info.items():
    print(f"  {key}: {value}")
print()

# Test check_availability
print("=" * 60)
print("Testing PrecipAorc.check_availability()")
print("=" * 60)
avail = PrecipAorc.check_availability(bounds, start_time, end_time)
for key, value in avail.items():
    print(f"  {key}: {value}")
print()

# Test download
print("=" * 60)
print("Testing PrecipAorc.download()")
print("=" * 60)
try:
    result = PrecipAorc.download(
        bounds=bounds,
        start_time=start_time,
        end_time=end_time,
        output_path=output_path
    )
    print(f"Download successful: {result}")
    print(f"File size: {result.stat().st_size / 1024:.1f} KB")
except ImportError as e:
    print(f"Missing dependencies: {e}")
except Exception as e:
    print(f"Download failed: {e}")
    import traceback
    traceback.print_exc()

print()
print("Test completed!")
