# Gap Analysis: HDF Data Requirements vs ras-commander Functions

## Executive Summary

This document analyzes the gap between RasCheck data requirements and existing ras-commander HDF extraction functions. The analysis identifies what new functions need to be created to support the RasCheck implementation.

### Implementation Status Update (December 2024)

**COMPLETED WORK:**

| Enhancement | Status | Description |
|-------------|--------|-------------|
| `HdfXsec.get_cross_sections()` | ✅ COMPLETE | Added `n_lob`, `n_channel`, `n_rob` columns |
| `HdfResultsPlan.get_steady_results()` | ✅ COMPLETE | Single function returns ALL steady data |
| Removed redundant functions | ✅ COMPLETE | Consolidated API (see below) |

**Key API Changes:**
- `get_cross_sections()` now includes Manning's n LOB/Channel/ROB values directly
- New `get_steady_results()` matches `RasControl.get_steady_results()` schema
- Individual `get_steady_*()` functions removed in favor of single consolidated call

### Updated Gap Status

| Status | Count | Percentage |
|--------|-------|------------|
| **Available** (function exists and works) | 28 | 68% |
| **Partial** (function exists but needs enhancement) | 2 | 5% |
| **Needs Implementation** (RasCheck-specific logic) | 8 | 20% |
| **HDF Missing** (data may not exist in HDF) | 3 | 7% |
| **Total Requirements** | 41 | 100% |

**Bottom Line**: ~73% of required HDF functionality now exists. Remaining work is primarily **RasCheck-specific validation logic** rather than HDF extraction.

## Steady Flow Results: RESOLVED ✅

**Previously identified as the most significant gap - now resolved.**

The `HdfResultsPlan` class now provides comprehensive steady flow extraction:

### Available Steady Flow Functions

| Function | Status | Description |
|----------|--------|-------------|
| `is_steady_plan()` | ✅ | Check if HDF contains steady results |
| `get_steady_profile_names()` | ✅ | Get profile names |
| `get_steady_wse()` | ✅ | Get water surface elevations (single variable) |
| `get_steady_info()` | ✅ | Get metadata |
| **`get_steady_results()`** | ✅ NEW | **All variables in one call** |
| `list_steady_variables()` | ✅ | Diagnostic: list available HDF variables |

### get_steady_results() Schema

Single call returns ALL key hydraulic data:

```python
df = HdfResultsPlan.get_steady_results(plan_hdf)
# Columns: river, reach, node_id, profile, wsel, velocity, flow, froude,
#          energy, max_depth, min_ch_el, top_width, area, eg_slope, friction_slope
```

**Matches `RasControl.get_steady_results()` schema** for COM/HDF consistency, plus additional columns.

### Remaining Steady Flow Gaps

| Requirement | Status | Notes |
|-------------|--------|-------|
| Critical WSE | ⚠️ Needs Logic | Must calculate from Froude/velocity - not directly in HDF |
| Encroachment Stations | ❓ HDF Missing | May need to check plan HDF structure |
| Structure Results | ⚠️ Partial | Basic data available, needs specific extraction |

## HDF Structure Discovery

### Important Correction: Manning's n Storage

After investigating multiple models (Muncie, Baxter, ConSpan, Mixed Flow Regime), we found that Manning's n **IS** stored in a consistent format that can be mapped to LOB/Channel/ROB:

**Structure:**
- `Manning's n Info`: Array of `[start_index, count]` per XS
- `Manning's n Values`: Array of `[station, n_value]` pairs

**Interpretation:**
- For simple models (count=3):
  - Row 0: station=0, n=LOB value (applies from start to left bank)
  - Row 1: station=left_bank, n=Channel value (applies between banks)
  - Row 2: station=right_bank, n=ROB value (applies from right bank to end)
- For variable n models (count varies): Map stations to regions using bank stations from Attributes

**Verified across models:**
| Model | XS Count | n_count | Format |
|-------|----------|---------|--------|
| Muncie | 61 | All 3 | Simple LOB/Chan/ROB |
| Baxter | 173 | 2-4 | Variable (some horizontal variation) |
| ConSpan | 10 | All 3 | Simple LOB/Chan/ROB |

**Extraction function works correctly** - see `extract_mannings_n.py` for validated implementation.

### Cross Section Attributes (Compound Dataset)

The HDF file stores cross section data in a **compound dataset** at `Geometry/Cross Sections/Attributes` with these fields:

```
Fields in compound dataset:
- River: |S16 (string)
- Reach: |S16 (string)
- RS: |S8 (string - river station)
- Name: |S16
- Description: |S512
- Len Left: float32 (LOB reach length)
- Len Channel: float32 (channel reach length)
- Len Right: float32 (ROB reach length)
- Left Bank: float32 (left bank station)
- Right Bank: float32 (right bank station)
- Friction Mode: |S32
- Contr: float32 (contraction coefficient)
- Expan: float32 (expansion coefficient)
- HP Count: int32
- HP Start Elev: float32
- HP Vert Incr: float32
- HP LOB Slices: int32
- HP Chan Slices: int32
- HP ROB Slices: int32
- Ineff Block Mode: uint8
- Obstr Block Mode: uint8
- Default Centerline: uint8
- Last Edited: |S18
```

### Manning's n Values (Indexed Array)

Manning's n values are stored in two related datasets:

1. **Manning's n Info** (`shape=(n_xs, 2)`): Index array with `[start_idx, count]` per XS
2. **Manning's n Values** (`shape=(total_values, 2)`): Actual values `[n_value, station]`

The current HDF structure does **NOT** directly store LOB/Channel/ROB n values - instead it stores n values with their stations. To get LOB/Channel/ROB:
1. Use bank stations from Attributes
2. Map Manning's n stations to LOB (< left bank), Channel (between banks), ROB (> right bank)

### Ineffective Flow Areas (Compound Dataset)

```
Geometry/Cross Sections/Ineffective Info: shape=(n_xs, 2) - [start_idx, count]
Geometry/Cross Sections/Ineffective Blocks: shape=(total_blocks,)
  Fields: ('Left Sta', 'Right Sta', 'Elevation', 'Permanent')
```

### Structure Attributes (Compound Dataset)

```
Geometry/Structures/Attributes: shape=(n_structures,)
Fields: Type, Mode, River, Reach, RS, Connection, Groupname,
        US Type, US River, US Reach, US RS, US SA/2D,
        DS Type, DS River, DS Reach, DS RS, DS SA/2D,
        Node Name, Description, Last Edited,
        Weir Width, Weir Max Submergence, Weir Min Elevation, Weir Coef,
        BR Contraction, BR Expansion, ...
        (90+ fields total)
```

### Steady Flow Results Structure (Verified)

From the WaterQualityExamp.p01.hdf file, the steady flow output structure is:

```
Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/
├── Profile Names                           # shape=(n_profiles,), dtype=S16
├── Cross Sections/
│   ├── Flow                                # shape=(n_profiles, n_xs), dtype=float32
│   ├── Water Surface                       # shape=(n_profiles, n_xs), dtype=float32
│   ├── Cross Section Variables             # shape=(n_profiles, 34, n_xs), dtype=float32
│   └── Additional Variables/
│       ├── Area Flow Channel               # shape=(n_profiles, n_xs)
│       ├── Area Flow Total                 # shape=(n_profiles, n_xs)
│       ├── Conveyance Channel              # shape=(n_profiles, n_xs)
│       ├── Conveyance Total                # shape=(n_profiles, n_xs)
│       ├── EG Slope                        # shape=(n_profiles, n_xs)
│       ├── Flow Channel                    # shape=(n_profiles, n_xs)
│       ├── Flow Total                      # shape=(n_profiles, n_xs)
│       ├── Friction Slope                  # shape=(n_profiles, n_xs)
│       ├── Hydraulic Depth Channel         # shape=(n_profiles, n_xs)
│       ├── Hydraulic Depth Total           # shape=(n_profiles, n_xs)
│       ├── Hydraulic Radius Channel        # shape=(n_profiles, n_xs)
│       ├── Hydraulic Radius Total          # shape=(n_profiles, n_xs)
│       ├── Manning n Channel               # shape=(n_profiles, n_xs)
│       ├── Manning n Total                 # shape=(n_profiles, n_xs)
│       ├── Maximum Depth Total             # shape=(n_profiles, n_xs)
│       ├── Top Width Channel               # shape=(n_profiles, n_xs)
│       ├── Top Width Total                 # shape=(n_profiles, n_xs)
│       ├── Velocity Channel                # shape=(n_profiles, n_xs)
│       ├── Velocity Total                  # shape=(n_profiles, n_xs)
│       ├── Water Surface Total             # shape=(n_profiles, n_xs)
│       ├── Wetted Perimeter Channel        # shape=(n_profiles, n_xs)
│       └── Wetted Perimeter Total          # shape=(n_profiles, n_xs)
└── Structures/
    └── [Structure outputs if present]
```

**Key Finding**: The steady flow results contain extensive output in the "Additional Variables" group, which provides all the data needed for RasCheck validation:
- Water Surface, Flow, Velocity, Top Width (all available)
- EG Slope, Friction Slope (for flow regime checks)
- Area, Conveyance, Wetted Perimeter (for advanced validation)

**Note**: Critical Water Surface may not be directly available - flow regime must be determined from velocity/depth relationships.

## Detailed Gap Analysis by Check

### check_nt

| Requirement | Status | Existing Function | Notes |
|-------------|--------|-------------------|-------|
| Cross Section Attributes | Partial | `HdfXsec.get_cross_sections()` | Returns geometry, need attributes separately |
| Manning's n Info | Missing | - | Index array pointing to values |
| Manning's n Values | Missing | - | Raw n values with stations |
| Contraction Coefficient | Missing | - | Field in Attributes compound dataset |
| Expansion Coefficient | Missing | - | Field in Attributes compound dataset |
| Bank Stations | Missing | - | Left Bank, Right Bank fields |
| Reach Lengths | Missing | - | Len Left/Channel/Right fields |
| Structure Identification | Partial | `HdfStruc.get_structures()` | Need section number mapping |

**New Function Needed**: `get_xs_attributes()` to extract all compound dataset fields

### check_xs

| Requirement | Status | Existing Function | Notes |
|-------------|--------|-------------------|-------|
| Cross Section Attributes | Partial | `HdfXsec.get_cross_sections()` | Need all fields |
| Ineffective Flow Info | Missing | - | Index array |
| Ineffective Flow Blocks | Missing | - | Compound dataset |
| Station Elevation | Available | `HdfXsec.get_cross_sections()` | Works |
| Steady Profile Names | Available | `HdfResultsPlan.get_steady_profile_names()` | Works |
| Water Surface | Available | `HdfResultsPlan.get_steady_wse()` | Works |
| Flow | Needs New | - | Need `get_steady_flow()` |
| Critical WSE | Needs New | - | Need `get_steady_critical_wse()` |
| Velocity | Needs New | - | Need `get_steady_velocity()` |
| Top Width | Needs New | - | Need `get_steady_top_width()` |

### check_structures

| Requirement | Status | Existing Function | Notes |
|-------------|--------|-------------------|-------|
| Structure Attributes | Partial | `HdfStruc.get_structures()` | May need more fields |
| Bridge Coefficient Attrs | Missing | - | Separate compound dataset |
| Structure Profile Data | Missing | - | Deck/weir geometry |
| Culvert Data | Available | `RasStruct.get_culverts()` | Plaintext parser |
| Bridge Data | Available | `RasStruct.get_bridges()` | Plaintext parser |
| Structure Results | Needs New | - | Need `get_steady_structure_results()` |

### check_floodways

| Requirement | Status | Existing Function | Notes |
|-------------|--------|-------------------|-------|
| Cross Section Attributes | Partial | `HdfXsec.get_cross_sections()` | Need all fields |
| Encroachment Data | HDF Missing | - | May be in plan HDF |
| Bank Stations | Missing | - | From Attributes |
| Steady Profile Names | Available | `HdfResultsPlan.get_steady_profile_names()` | Works |
| Water Surface | Available | `HdfResultsPlan.get_steady_wse()` | Works |
| Flow | Needs New | - | Need `get_steady_flow()` |
| Encroachment Stations | Needs New | - | Need `get_steady_encroachment_stations()` |
| Encroachment Parameters | Needs New | - | Need `get_encroachment_parameters()` |

### check_profiles

| Requirement | Status | Existing Function | Notes |
|-------------|--------|-------------------|-------|
| Cross Section Attributes | Partial | `HdfXsec.get_cross_sections()` | Need River, Reach, RS |
| Steady Profile Names | Available | `HdfResultsPlan.get_steady_profile_names()` | Works |
| Water Surface | Available | `HdfResultsPlan.get_steady_wse()` | Works |
| Flow | Needs New | - | Need `get_steady_flow()` |
| Top Width | Needs New | - | Need `get_steady_top_width()` |
| Critical WSE | Needs New | - | Need `get_steady_critical_wse()` |

## New Functions to Implement

### Priority 1: Geometry HDF Functions

These should be added to `HdfXsec.py` or a new `HdfXsecAttr.py`:

```python
@staticmethod
@log_call
@standardize_input
def get_xs_attributes(hdf_path: Path) -> pd.DataFrame:
    """
    Extract all cross section attributes from geometry HDF.

    Returns DataFrame with columns:
    - River, Reach, RS (identifiers)
    - Len_Left, Len_Channel, Len_Right (reach lengths)
    - Left_Bank, Right_Bank (bank stations)
    - Contr, Expan (transition coefficients)
    - And other attribute fields
    """

@staticmethod
@log_call
@standardize_input
def get_xs_mannings_n(hdf_path: Path) -> pd.DataFrame:
    """
    Extract Manning's n values for each cross section.

    Returns DataFrame with columns:
    - River, Reach, RS (identifiers)
    - n_lob (left overbank n)
    - n_channel (main channel n)
    - n_rob (right overbank n)

    Note: Calculates LOB/Channel/ROB from station positions
    and bank stations.
    """

@staticmethod
@log_call
@standardize_input
def get_xs_ineffective_areas(hdf_path: Path) -> pd.DataFrame:
    """
    Extract ineffective flow areas for all cross sections.

    Returns DataFrame with columns:
    - River, Reach, RS (identifiers)
    - Left_Sta, Right_Sta (ineffective stations)
    - Elevation (ineffective trigger elevation)
    - Permanent (boolean)
    """
```

### Priority 2: Plan HDF Functions (Steady Flow)

These should be added to `HdfResultsPlan.py`:

```python
@staticmethod
@log_call
@standardize_input
def get_steady_flow(hdf_path: Path) -> pd.DataFrame:
    """
    Extract steady flow discharge for all profiles.

    Returns DataFrame with:
    - River, Reach, RS as index
    - One column per profile with discharge values
    """

@staticmethod
@log_call
@standardize_input
def get_steady_velocity(hdf_path: Path) -> pd.DataFrame:
    """Extract steady flow velocity for all profiles."""

@staticmethod
@log_call
@standardize_input
def get_steady_top_width(hdf_path: Path) -> pd.DataFrame:
    """Extract steady flow top width for all profiles."""

@staticmethod
@log_call
@standardize_input
def get_steady_critical_wse(hdf_path: Path) -> pd.DataFrame:
    """Extract critical WSE for flow regime determination."""

@staticmethod
@log_call
@standardize_input
def get_steady_encroachment_stations(hdf_path: Path) -> pd.DataFrame:
    """Extract encroachment stations for floodway profiles."""

@staticmethod
@log_call
@standardize_input
def get_steady_structure_results(hdf_path: Path) -> pd.DataFrame:
    """Extract structure output (WSE at sections, flow type, etc.)."""
```

### Priority 3: Structure Functions

```python
@staticmethod
@log_call
@standardize_input
def get_structure_attributes(hdf_path: Path) -> pd.DataFrame:
    """Extract all structure attributes including coefficients."""

@staticmethod
@log_call
@standardize_input
def get_bridge_coefficients(hdf_path: Path) -> pd.DataFrame:
    """Extract bridge-specific hydraulic coefficients."""
```

## Test Project Requirements

The existing example projects (Muncie, BaldEagleCrkMulti2D) have **unsteady** results only. For testing RasCheck, we need:

1. **A project with steady flow results** - Required for all steady flow extraction functions
2. **A project with floodway analysis** - Required for encroachment testing
3. **A project with bridges/culverts** - Required for structure validation

### Options:
1. Create a new steady flow test project
2. Run an existing example project in steady flow mode
3. Download a FEMA example project with steady flow

## Implementation Recommendations

### Phase 1: Core Geometry Functions
1. Implement `get_xs_attributes()` - needed by ALL checks
2. Implement `get_xs_mannings_n()` - needed by check_nt
3. Implement `get_xs_ineffective_areas()` - needed by check_xs

### Phase 2: Steady Flow Results
1. Implement `get_steady_flow()` - needed by xs, floodways, profiles
2. Implement `get_steady_top_width()` - needed by xs, profiles
3. Implement `get_steady_critical_wse()` - needed by xs, profiles
4. Implement `get_steady_velocity()` - needed by xs

### Phase 3: Advanced Functions
1. Implement `get_steady_structure_results()` - needed by structures
2. Implement `get_steady_encroachment_stations()` - needed by floodways
3. Implement `get_structure_attributes()` - enhancement
4. Implement `get_bridge_coefficients()` - enhancement

## Verified HDF Paths

All required geometry HDF paths have been verified to exist in test files:

```
[OK] Geometry/Cross Sections/Attributes: shape=(61,)
[OK] Geometry/Cross Sections/Manning's n Info: shape=(61, 2)
[OK] Geometry/Cross Sections/Manning's n Values: shape=(183, 2)
[OK] Geometry/Cross Sections/Ineffective Info: shape=(61, 2)
[OK] Geometry/Cross Sections/Ineffective Blocks: shape=(16,)
[OK] Geometry/Cross Sections/Station Elevation Info: shape=(61, 2)
[OK] Geometry/Cross Sections/Station Elevation Values: shape=(5158, 2)
[OK] Geometry/Structures/Attributes: shape=(12,)
[OK] Geometry/Structures/Bridge Coefficient Attributes: shape=(10,)
```

Plan HDF paths for steady flow results need to be verified with a steady flow model.

## Conclusion

The ras-commander library provides a solid foundation for RasCheck implementation, with ~40% of required functionality already available. The main gaps are:

1. **Geometry attribute extraction** - Need functions to extract compound dataset fields
2. **Steady flow results** - Need multiple new extraction functions
3. **Manning's n processing** - Need function to map n values to LOB/Channel/ROB

With the implementation of 12 new functions, RasCheck will have full HDF data access.

## Appendix A: Validated Manning's n Extraction Code

The following code has been tested and validated against multiple HEC-RAS models:

```python
def extract_mannings_n(geom_hdf: Path) -> pd.DataFrame:
    """
    Extract Manning's n values from geometry HDF.

    VALIDATED against: Muncie, Baxter, ConSpan models.

    Returns DataFrame with columns:
    - River, Reach, RS (identifiers)
    - n_lob, n_channel, n_rob (Manning's n values)
    - n_count (number of n change points)
    - left_bank, right_bank (bank stations)
    """
    with h5py.File(geom_hdf, 'r') as hdf:
        attrs = hdf['Geometry/Cross Sections/Attributes'][:]
        n_info = hdf["Geometry/Cross Sections/Manning's n Info"][:]
        n_values = hdf["Geometry/Cross Sections/Manning's n Values"][:]

        results = []
        for i in range(len(attrs)):
            row = attrs[i]

            # Extract identifiers
            river = row['River'].decode('utf-8').strip() if isinstance(row['River'], bytes) else str(row['River']).strip()
            reach = row['Reach'].decode('utf-8').strip() if isinstance(row['Reach'], bytes) else str(row['Reach']).strip()
            rs = row['RS'].decode('utf-8').strip() if isinstance(row['RS'], bytes) else str(row['RS']).strip()

            # Get bank stations
            left_bank = float(row['Left Bank'])
            right_bank = float(row['Right Bank'])

            # Get n values for this XS
            start_idx = n_info[i, 0]
            count = n_info[i, 1]
            xs_n_values = n_values[start_idx:start_idx + count]

            # Interpret based on count
            # Format is [station, n_value] pairs
            if count == 3:
                # Simple LOB/Channel/ROB: values at station 0, left_bank, right_bank
                n_lob = xs_n_values[0, 1]
                n_channel = xs_n_values[1, 1]
                n_rob = xs_n_values[2, 1]
            elif count >= 4:
                # Variable n - find values for each region
                n_lob = n_channel = n_rob = None
                for j in range(count):
                    sta, n_val = xs_n_values[j]
                    if sta < left_bank:
                        n_lob = n_val
                    elif sta < right_bank:
                        if n_channel is None:
                            n_channel = n_val
                    else:
                        if n_rob is None:
                            n_rob = n_val
                # Fill missing
                if n_lob is None: n_lob = xs_n_values[0, 1]
                if n_channel is None: n_channel = n_lob
                if n_rob is None: n_rob = n_channel
            else:
                # 1-2 values - simplified handling
                n_lob = n_channel = n_rob = xs_n_values[0, 1] if count > 0 else np.nan

            results.append({
                'River': river, 'Reach': reach, 'RS': rs,
                'n_lob': n_lob, 'n_channel': n_channel, 'n_rob': n_rob,
                'n_count': count, 'left_bank': left_bank, 'right_bank': right_bank
            })

        return pd.DataFrame(results)
```

## Appendix B: Test Projects Available

### Extracted and Available for Testing

| Project | Location | Type | Has Results |
|---------|----------|------|-------------|
| Muncie | `examples/example_projects/Muncie/` | Unsteady | Yes (unsteady) |
| BaldEagleCrkMulti2D | `examples/example_projects/BaldEagleCrkMulti2D/` | Unsteady | Yes (unsteady) |
| Baxter RAS Mapper | `feature_dev_notes/cHECk-RAS/test_projects/1D Steady Flow Hydraulics/Baxter RAS Mapper/` | Steady | No (needs compute) |
| ConSpan Culvert | `feature_dev_notes/cHECk-RAS/test_projects/1D Steady Flow Hydraulics/ConSpan Culvert/` | Steady | No (needs compute) |
| Mixed Flow Regime | `feature_dev_notes/cHECk-RAS/test_projects/1D Steady Flow Hydraulics/Mixed Flow Regime Channel/` | Steady | No (needs compute) |
| WaterQualityExamp | `feature_dev_notes/cHECk-RAS/test_projects/Water Quality/Nutrient Example/` | Steady | **Yes (steady)** |

### Key Test Project: WaterQualityExamp

This is the only extracted project with **computed steady flow results**. Use it for testing steady flow extraction functions:
- Plan HDF: `WaterQualityExamp.p01.hdf`
- Geometry HDF: `WaterQualityExamp.g01.hdf`
- Profiles: 1 profile ("PF 1")
- Cross Sections: 18

### Projects Available in Example_Projects_6_6.zip

Additional 1D Steady Flow projects that can be extracted:
- `1D Steady Flow Hydraulics/Baxter RAS Mapper/`
- `1D Steady Flow Hydraulics/Chapter 4 Example Data/`
- `1D Steady Flow Hydraulics/ConSpan Culvert/`
- `1D Steady Flow Hydraulics/Mixed Flow Regime Channel/`
- `1D Steady Flow Hydraulics/Wailupe GeoRAS/`

## Appendix C: HDF Path Quick Reference

### Geometry HDF Paths (Verified)

```
Geometry/Cross Sections/
├── Attributes                    # Compound: River, Reach, RS, banks, coefficients
├── Manning's n Info              # [start_idx, count] per XS
├── Manning's n Values            # [station, n_value] pairs
├── Ineffective Info              # [start_idx, count] per XS
├── Ineffective Blocks            # Compound: Left Sta, Right Sta, Elevation, Permanent
├── Station Elevation Info        # [start_idx, count] per XS
├── Station Elevation Values      # [station, elevation] pairs
├── Obstruction Info              # (if present)
└── Obstruction Blocks            # (if present)

Geometry/Structures/
├── Attributes                    # Compound: Type, River, Reach, RS, coefficients (90+ fields)
├── Bridge Coefficient Attributes # Bridge-specific coefficients
├── Centerline Info/Parts/Points  # Structure geometry
└── Profile Data                  # Deck/weir profile
```

### Plan HDF Paths (Steady Flow - Verified)

```
Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/
├── Profile Names                 # shape=(n_profiles,)
├── Cross Sections/
│   ├── Flow                      # shape=(n_profiles, n_xs)
│   ├── Water Surface             # shape=(n_profiles, n_xs)
│   ├── Cross Section Variables   # shape=(n_profiles, 34, n_xs)
│   └── Additional Variables/
│       ├── Velocity Channel      # shape=(n_profiles, n_xs)
│       ├── Velocity Total
│       ├── Top Width Channel
│       ├── Top Width Total
│       ├── EG Slope
│       ├── Friction Slope
│       ├── Area Flow Channel/Total
│       ├── Conveyance Channel/Total
│       ├── Hydraulic Depth Channel/Total
│       ├── Hydraulic Radius Channel/Total
│       ├── Manning n Channel/Total
│       ├── Maximum Depth Total
│       ├── Water Surface Total
│       └── Wetted Perimeter Channel/Total
└── Structures/                   # (if present)
```

## Appendix D: Exploration Scripts Created

The following scripts were created during this investigation and are available in `feature_dev_notes/cHECk-RAS/`:

| Script | Purpose |
|--------|---------|
| `hdf_exploration.py` | Initial HDF structure exploration |
| `hdf_detailed_exploration.py` | Detailed compound dataset analysis |
| `gap_analysis.py` | Automated gap analysis with status tracking |
| `compare_mannings_n.py` | Compare n structure across multiple models |
| `extract_mannings_n.py` | **Validated** extraction function for LOB/Chan/ROB |
| `check_steady_results.py` | Find models with steady flow results |
| `explore_steady_results.py` | Document steady flow HDF structure |

All scripts are self-contained and can be run with `python <script>.py` from the ras-commander root directory.
