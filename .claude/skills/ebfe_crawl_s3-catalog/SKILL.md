---
name: ebfe_crawl_s3-catalog
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
description: Crawl FEMA's public BLE/eBFE S3 bucket to build a catalog of available Base Level Engineering datasets by state, HUC, and watershed. Cache results locally. Use when discovering what BLE models are available for a region before download.
---

# eBFE / BLE S3 Catalog Crawl Skill

Crawl FEMA's public BLE S3 bucket and build a local catalog of available Base Level Engineering datasets. Cache results so repeated sessions don't re-crawl.

## When to Use

- "What BLE models are available for [state/watershed]?"
- "Get the eBFE catalog for Texas"
- Before any BLE model download or eBFE workflow
- When `RasCatalog` / `RasSources` needs to be populated

## S3 Source

**Bucket**: `s3://fim-public-availability-data/` (FEMA public, no auth required)

**Structure**:
```
fim-public-availability-data/
└── ble/
    └── {state}/
        └── {huc8}/
            ├── Hydraulics/
            │   └── {project}.zip   ← HEC-RAS model
            ├── Terrain/
            └── Mapping/
```

**Alternative bucket** (check both):
```
s3://ras2fim-dev/
s3://fim-dev-outputs/
```

## Crawl Workflow

### Step 1: Check Local Cache First

```python
from pathlib import Path
import json

cache_path = Path(".claude/outputs/ble-catalog-cache.json")
if cache_path.exists():
    import time
    age_days = (time.time() - cache_path.stat().st_mtime) / 86400
    if age_days < 30:
        with open(cache_path) as f:
            catalog = json.load(f)
        print(f"Using cached catalog ({age_days:.0f} days old, {len(catalog)} entries)")
        # Skip crawl, use catalog
```

### Step 2: Crawl S3 (if cache miss or stale)

```python
import boto3
from botocore import UNSIGNED
from botocore.config import Config

# Public bucket — no credentials needed
s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))

bucket = "fim-public-availability-data"
prefix = "ble/"

# Optional: filter by state
state_filter = "TX"  # or None for all states
if state_filter:
    prefix = f"ble/{state_filter}/"

paginator = s3.get_paginator('list_objects_v2')
catalog = []

for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter='/'):
    for obj in page.get('Contents', []):
        key = obj['Key']
        size = obj['Size']
        # Filter to hydraulics .zip files
        if 'Hydraulics' in key and key.endswith('.zip'):
            parts = key.split('/')
            # parts: ['ble', state, huc8, 'Hydraulics', filename]
            if len(parts) >= 5:
                catalog.append({
                    'state': parts[1],
                    'huc8': parts[2],
                    'filename': parts[-1],
                    's3_path': f"s3://{bucket}/{key}",
                    'size_mb': round(size / 1e6, 1),
                })

print(f"Found {len(catalog)} BLE hydraulic models")
```

### Step 3: Save Cache

```python
import json
from pathlib import Path

cache_path = Path(".claude/outputs/ble-catalog-cache.json")
cache_path.parent.mkdir(parents=True, exist_ok=True)

with open(cache_path, 'w') as f:
    json.dump(catalog, f, indent=2)

print(f"Catalog cached: {cache_path}")
```

### Step 4: Build DataFrame for Filtering

```python
import pandas as pd

df = pd.DataFrame(catalog)
df['huc2'] = df['huc8'].str[:2]
df['huc4'] = df['huc8'].str[:4]
df['huc6'] = df['huc8'].str[:6]

# Filter examples
tx_models = df[df['state'] == 'TX']
huc_models = df[df['huc8'].str.startswith('12040')]  # Harris County HUC8s
print(f"Texas BLE models: {len(tx_models)}")
print(tx_models[['huc8', 'filename', 'size_mb']].to_string())
```

### Step 5: Write Catalog Report

```python
output_path = f".claude/outputs/ebfe-catalog/{date}-{state_filter or 'all'}-catalog.md"

content = f"""# BLE/eBFE S3 Catalog
**Date**: {date}
**State filter**: {state_filter or 'All states'}
**Total models**: {len(df)}

## Summary by State
{df.groupby('state').size().to_string()}

## Available HUC8s
{df[['huc8', 'state', 'filename', 'size_mb']].to_string()}
"""
Path(output_path).parent.mkdir(parents=True, exist_ok=True)
Path(output_path).write_text(content)
print(f"Report: {output_path}")
```

## Integration with ras-commander

After crawling, use the catalog with ras-commander's eBFE tools:

```python
from ras_commander import RasCatalog  # if available

# Or use S3 paths directly
s3_path = df[df['huc8'] == '12040104']['s3_path'].iloc[0]
# Download and process
```

See `.claude/rules/hec-ras/` for eBFE-specific rules.

## Output Location

```
.claude/outputs/
├── ble-catalog-cache.json         ← persistent cache (30-day TTL)
└── ebfe-catalog/
    └── {date}-{state}-catalog.md  ← crawl reports
```

## Troubleshooting

| Error | Fix |
|-------|-----|
| `NoCredentialsError` | Use `signature_version=UNSIGNED` for public bucket |
| `403 Forbidden` | Bucket name changed; check FEMA's current BLE data portal |
| Empty results | Try `prefix="ble/"` without state filter first |
| Very slow | Use Delimiter and paginate; avoid listing all objects at once |

---

**Source**: BLE S3 crawl rebuilt from scratch multiple times in ras-commander conversation history (2026-03-20 to 2026-04-12). Codified to eliminate repeated reconstruction.
