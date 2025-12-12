"""
Read DSS Catalog Example

Demonstrates how to read and explore DSS file catalogs.
"""

from pathlib import Path
from ras_commander import RasExamples, RasDss

# Extract example project with DSS file
print("Extracting BaldEagleCrkMulti2D example...")
project_path = RasExamples.extract_project("BaldEagleCrkMulti2D")

# Find DSS file
dss_file = project_path / "Bald_Eagle_Creek.dss"

if not dss_file.exists():
    print(f"DSS file not found: {dss_file}")
    exit(1)

print(f"\nDSS File: {dss_file.name}")
print("=" * 80)

# Get file info (faster than full catalog)
info = RasDss.get_info(dss_file)
print(f"\nFile Size: {info['file_size_mb']:.2f} MB")
print(f"Total Paths: {info['total_paths']}")

# Get full catalog
print("\nReading full catalog...")
catalog = RasDss.get_catalog(dss_file)
print(f"Catalog entries: {len(catalog)}")

# Analyze catalog contents
print("\n" + "=" * 80)
print("Catalog Analysis")
print("=" * 80)

# Count by parameter type
parameters = {}
for path in catalog:
    parts = path.split('/')
    if len(parts) >= 4:
        param = parts[3]  # C part (parameter)
        parameters[param] = parameters.get(param, 0) + 1

print("\nParameter Counts:")
for param, count in sorted(parameters.items(), key=lambda x: -x[1]):
    print(f"  {param:30s}: {count:4d}")

# Count by interval
intervals = {}
for path in catalog:
    parts = path.split('/')
    if len(parts) >= 6:
        interval = parts[5]  # E part (interval)
        if interval:  # Skip empty intervals
            intervals[interval] = intervals.get(interval, 0) + 1

print("\nInterval Counts:")
for interval, count in sorted(intervals.items(), key=lambda x: -x[1]):
    print(f"  {interval:30s}: {count:4d}")

# Find flow time series
print("\n" + "=" * 80)
print("Flow Time Series")
print("=" * 80)

flow_paths = [p for p in catalog if '/FLOW/' in p]
print(f"\nFound {len(flow_paths)} flow time series")

print("\nFirst 10 flow paths:")
for i, path in enumerate(flow_paths[:10], 1):
    print(f"  {i:2d}. {path}")

# Find specific scenario
print("\n" + "=" * 80)
print("PMF Event Data")
print("=" * 80)

pmf_paths = [p for p in catalog if 'PMF' in p]
print(f"\nFound {len(pmf_paths)} PMF-related paths")

for path in pmf_paths[:15]:
    print(f"  {path}")

# Export catalog to text file
output_file = project_path / "dss_catalog.txt"
with open(output_file, 'w') as f:
    f.write(f"DSS Catalog: {dss_file.name}\n")
    f.write(f"Total Paths: {len(catalog)}\n")
    f.write("=" * 80 + "\n\n")

    for path in catalog:
        f.write(path + "\n")

print(f"\n\nCatalog exported to: {output_file}")

# Export summary to CSV
import pandas as pd

summary_data = []
for path in catalog:
    parts = path.split('/')
    if len(parts) >= 7:
        summary_data.append({
            'pathname': path,
            'project': parts[1],
            'location': parts[2],
            'parameter': parts[3],
            'start_date': parts[4],
            'interval': parts[5],
            'version': parts[6],
        })

summary_df = pd.DataFrame(summary_data)
summary_file = project_path / "dss_catalog_summary.csv"
summary_df.to_csv(summary_file, index=False)

print(f"Summary exported to: {summary_file}")

print("\n" + "=" * 80)
print("Complete!")
print("=" * 80)
