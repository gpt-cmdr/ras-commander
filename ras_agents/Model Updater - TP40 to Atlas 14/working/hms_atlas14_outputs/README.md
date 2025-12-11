# HMS Atlas 14 DSS Output Files

**Purpose**: This folder contains HEC-HMS DSS output files with Atlas 14 precipitation-based hydrographs.

---

## Expected File

**Filename**: `A1000000_Atlas14.dss`

**Source Location**:
```
C:\GH\hms-commander\test_project\2014.08_HMS\A1000000_baseline_33\A1000000_Atlas14.dss
```

OR (if using HMS 4.11 upgrade):
```
C:\GH\hms-commander\test_project\2014.08_HMS\A1000000_upgrade_411\A1000000_Atlas14.dss
```

**Copy Command**:
```bash
cp "C:\GH\hms-commander\test_project\2014.08_HMS\A1000000_baseline_33\A1000000_Atlas14.dss" \
   "C:\GH\ras-commander\ras_agents\Model Updater - TP40 to Atlas 14\working\hms_atlas14_outputs\"
```

---

## File Contents

The DSS file should contain FLOW time series for all HMS subbasins with Atlas 14 precipitation:

### Required Subbasins (35 total)

**A100 Watershed:**
- A100L, A100M, A100N, A100O, A100P, A100Q, A100R, A100S, A100T, A100U
- A118A, A111A
- A1000000_1660_J

**A120 Watershed:**
- A120B, A120C, A120D1, A120D2
- CW103A (Cowart Creek)

**A119 (Turkey Creek) Watershed:**
- A119B, A119C
- A1190000_0231_J, A1190500_0011_J, A1190600_0012_J
- A11902A

**Junction/Confluence Points:**
- B1000000_0022_J (largest peak: ~15,433 cfs)
- COWA0100_9901_J (Cowart Creek confluence)
- CHIG0100_9901_J (Chigger Creek confluence)
- MAGN0100_9901_J (Magnolia Creek confluence)
- MARY0100_9901_J (Mary's Creek confluence)
- A1070000_0100_J

**Other Tributaries:**
- LAKE (detention basin)
- LD100A (Little Duck Lake)
- RB100A (Robinson Bayou)
- JB100A (Jones Bayou)

### DSS Path Structure

```
//{SUBBASIN}/FLOW/{DATE}/5MIN/{RUN_ID}/
```

**Examples:**
```
//A100L/FLOW/31MAY2007/5MIN/RUN:1%(100YR)RUN/
//A120B/FLOW/31MAY2007/5MIN/RUN:1%(100YR)RUN/
//CW103A/FLOW/31MAY2007/5MIN/RUN:1%(100YR)RUN/
//B1000000_0022_J/FLOW/31MAY2007/5MIN/RUN:1%(100YR)RUN/
```

### Required AEP Scenarios

| AEP | Run Identifier | Storm |
|-----|----------------|-------|
| 10% | RUN:10%(10YR)RUN | 10-year |
| 2% | RUN:2%(50YR)RUN | 50-year |
| **1%** | **RUN:1%(100YR)RUN** | **100-year** (primary) |
| 0.2% | RUN:0.2%(500YR)RUN | 500-year |

---

## Verification

After copying the DSS file, verify contents:

```python
from ras_commander import RasDss

dss_file = "A1000000_Atlas14.dss"

# Get catalog
catalog = RasDss.get_catalog(dss_file)

# Filter for FLOW paths
flow_paths = [p for p in catalog if '/FLOW/' in p]
print(f"Total FLOW paths: {len(flow_paths)}")

# Check for required subbasins
required = ['A100L', 'A100M', 'A120B', 'CW103A', 'A1190000_0231_J', 'B1000000_0022_J']
for subbasin in required:
    matches = [p for p in flow_paths if f'//{subbasin}/' in p]
    print(f"{subbasin}: {len(matches)} paths found")

# Read sample time series
sample_path = "//A100L/FLOW/31MAY2007/5MIN/RUN:1%(100YR)RUN/"
df = RasDss.read_timeseries(dss_file, sample_path)
print(f"\nSample time series (A100L):")
print(f"  Start: {df.index[0]}")
print(f"  End: {df.index[-1]}")
print(f"  Peak: {df['value'].max():.1f} cfs")
print(f"  Points: {len(df)}")
```

**Expected Output:**
```
Total FLOW paths: 400-600 (depending on AEP scenarios)
A100L: 4-6 paths found
A100M: 4-6 paths found
A120B: 4-6 paths found
CW103A: 4-6 paths found
A1190000_0231_J: 4-6 paths found
B1000000_0022_J: 4-6 paths found

Sample time series (A100L):
  Start: 2007-05-31 00:00:00
  End: 2007-06-01 00:00:00
  Peak: 520-535 cfs (expect ~6-9% > baseline 486.8 cfs)
  Points: 288 (24 hours @ 5-min intervals)
```

---

## Atlas 14 vs TP-40 Comparison

### Precipitation Change
- **TP-40 Baseline**: 13.5 inches (100-year, 24-hour)
- **Atlas 14**: 14.7 inches (100-year, 24-hour)
- **Change**: +1.2 inches (+8.9%)

### Expected Peak Flow Changes
- **Increase**: +6-9%
- **Example**: A100L baseline 486.8 cfs → Expected 517-531 cfs

### Critical Checks
- [ ] All 35 subbasins present in DSS file
- [ ] Peak flows increased by 6-9% over baseline
- [ ] Hydrograph shapes preserved (time to peak similar)
- [ ] All 4 AEP scenarios present (10%, 2%, 1%, 0.2%)

---

## Status

**Current Status**: ⏳ **WAITING FOR HMS EXECUTION**

HMS model has been updated to Atlas 14 precipitation. Next steps:
1. Execute HMS simulations with Atlas 14 met models
2. Generate DSS output file
3. Copy to this folder
4. Verify contents (see above)
5. Proceed to RAS linking (see `../task_docs/HMS_ATLAS14_TO_RAS_LINKAGE.md`)

**Last Updated**: 2025-12-11
