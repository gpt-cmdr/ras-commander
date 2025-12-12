# RasMapperLib.Structures Namespace Documentation

**Purpose:** This namespace manages hydraulic structure data storage, retrieval, and connectivity for bridges, culverts, weirs, lateral structures, and SA/2D connections in HEC-RAS geometry and results HDF files.

**Location:** `RasMapperLib.Structures`

**Key Role:** Provides data models and HDF I/O for structure geometry components (piers, abutments, openings, groups) and connectivity information (cell intersections, station mapping, HW/TW references).

---

## Table of Contents

1. [Namespace Overview](#namespace-overview)
2. [Class Hierarchy](#class-hierarchy)
3. [Structure Data Classes](#structure-data-classes)
4. [Interface System](#interface-system)
5. [Extension Methods](#extension-methods)
6. [HDF Storage Patterns](#hdf-storage-patterns)
7. [Python Implementation Notes](#python-implementation-notes)
8. [Automation Opportunities](#automation-opportunities)

---

## Namespace Overview

### Primary Responsibilities

1. **Structure Geometry Storage**: Store bridge/culvert/weir geometry details in HDF files
2. **Connectivity Tracking**: Map structures to mesh cells and 1D cross sections
3. **Profile Management**: Store station-elevation profiles for piers, abutments, weir crests
4. **Hierarchical Grouping**: Organize openings (culverts/weir gates) into groups within parent structures
5. **Advanced Rules**: Store pump station operation rules with triggers

### Data Flow

```
Geometry File (.g##)
    ↓ [RASMapper Preprocessing]
Geometry HDF (.g##.hdf)
    ↓ [Structure Data Classes]
HDF Datasets
    - Bridge Coefficient Attributes
    - Pier Attributes / Pier Data
    - Abutment Attributes / Abutment Data
    - Multiple Opening Attributes
    - User Defined Weir Connectivity
    - Pump Advanced Rules
```

---

## Class Hierarchy

### Inheritance and Interface Relationships

```
FeatureLayer (base class from RasMapperLib)
    ↑
IStructureElementLayer (interface)
    ↑
    ├── IGroupLayer (interface) → groups of openings
    │       ↑
    │       └── IOpeningLayer (interface) → individual openings
    │               ↑
    │               └── IStructurePolylineLayer
    │
    └── IStructurePolylineLayer (interface) → polyline-based structure elements
```

### Data Storage Classes (No Inheritance)

- `AbutmentData` - Bridge abutment profiles (US/DS)
- `PierData` - Bridge pier profiles (US/DS) with debris options
- `MultipleOpeningData` - Multiple opening station ranges
- `BridgeParameters` - Bridge coefficient and method settings
- `AdvancedRulesData` - Pump station operation rules
- `UserDefinedWeirConnectivityData` - Weir HW/TW connectivity

### Utility Classes

- `StructureConstants` - String constants for types, modes, column names
- Extension classes for each interface

---

## Structure Data Classes

### 1. AbutmentData

**Purpose:** Store bridge abutment geometry profiles (upstream and downstream faces)

#### Properties
```csharp
public Profile UpstreamProfile;
public Profile DownstreamProfile;
```

#### HDF Structure
- **Attributes Dataset:** `{h5Group}/Abutment Attributes`
  - Columns: `Structure ID`, `US Profile (Index)`, `US Profile (Count)`, `DS Profile (Index)`, `DS Profile (Count)`
- **Profile Data:** `{h5Group}/Abutment Data`
  - 2D float array: `[n_points, 2]` (station, elevation pairs)

#### Key Methods
- `ReadCollection(H5Reader, h5Group)` → `Dictionary<int, List<AbutmentData>>`
  - Returns dictionary keyed by Structure ID
  - Reads indexed profile data using start/count pointers
- `WriteCollection(H5Writer, h5Group, abutmentMap[])`
  - Writes compound dataset with structure associations
  - Combines US/DS profiles into single dataset with offset indexing

#### Python Implementation Notes
```python
# Read abutment profiles
from ras_commander import HdfStruct

abutments = HdfStruct.get_bridge_abutments(geom_hdf, structure_id=5)
# Returns: {'upstream': [(sta, elev), ...], 'downstream': [(sta, elev), ...]}

# Profile format: List of (x, y) tuples representing station-elevation pairs
```

---

### 2. PierData

**Purpose:** Store bridge pier geometry profiles with debris accumulation options

#### Properties
```csharp
private Profile _upstreamProfile;
private Profile _downstreamProfile;
public float UpstreamStation;
public float DownstreamStation;
public bool UseDebris;
public float DebrisWidth;
public float DebrisHeight;
```

#### HDF Structure
- **Attributes Dataset:** `{h5Group}/Pier Attributes`
  - Columns: `Structure ID`, `US Station`, `DS Station`, `Use Debris`, `Debris Width`, `Debris Height`, `US Profile (Index)`, `US Profile (Count)`, `DS Profile (Index)`, `DS Profile (Count)`
- **Profile Data:** `{h5Group}/Pier Data`
  - 2D float array: `[n_points, 2]` (station, elevation pairs)

#### Key Methods
- `ReadCollection(H5Reader, h5Group)` → `Dictionary<int, List<PierData>>`
- `WriteCollection(H5Writer, h5Group, pierMap[])`

#### Profile Access Pattern
```csharp
public Profile UpstreamProfile
{
    get
    {
        Profile profile = new Profile();
        profile.AddRange(_upstreamProfile);
        return profile;
    }
}
```
**Note:** Returns a copy to prevent external modification

#### Python Implementation
```python
# Read pier data
piers = HdfStruct.get_bridge_piers(geom_hdf, structure_id=5)
# Returns list of dicts with:
# {'us_station': float, 'ds_station': float,
#  'use_debris': bool, 'debris_width': float, 'debris_height': float,
#  'us_profile': [(sta, elev), ...], 'ds_profile': [(sta, elev), ...]}
```

---

### 3. MultipleOpeningData

**Purpose:** Define station ranges for multiple opening types (slices) on a bridge

#### Properties
```csharp
public int TypeInt;           // Opening type code
public float USStationLeft;
public float USStationRight;
public float DSStationLeft;
public float DSStationRight;
```

#### HDF Structure
- **Dataset:** `{h5Group}/Multiple Opening Attributes`
  - Columns: `Structure ID`, `Type`, `US Sta L`, `US Sta R`, `DS Sta L`, `DS Sta R`

#### Key Methods
- `ReadCollection(H5Reader, h5Group)` → `Dictionary<int, List<MultipleOpeningData>>`
- `WriteCollection(H5Writer, h5Group, multipleOpeningMap[])`

#### Python Implementation
```python
# Read multiple opening data
openings = HdfStruct.get_multiple_openings(geom_hdf, structure_id=5)
# Returns: [{'type': int, 'us_sta_left': float, 'us_sta_right': float,
#            'ds_sta_left': float, 'ds_sta_right': float}, ...]
```

---

### 4. BridgeParameters

**Purpose:** Store bridge hydraulic analysis methods and coefficients (Momentum, Yarnell, WSPro)

#### Data Storage
```csharp
public DataRow Row;  // Stores all parameter values
```

#### Column Schema (34 fields)
**Method Settings:**
- `Method` (int), `Low Standard Step` (bool), `Use Momentum` (bool), `Momentum Cd` (float)
- `Use Yarnell` (bool), `Yarnell K` (float)
- `Use High Standard Step` (bool), `Submerged Inlet Cd` (float), `Submerged Inlet-Outlet Cd` (float)
- `Low Cord Weir Check` (float)

**WSPro Settings (23 fields):**
- `Use WSPro` (bool)
- Abutment geometry: `El Top L/R`, `El Toe L/R`, `Type`, `Slope`, `Width`, `Centroid Sta`
- Wing walls: `Type`, `Width`, `Angle`, `Radius`
- Guide banks: `Type`, `Length`, `Offset`, `Angle`
- Options: `Piers Continuous`, `Sf Geom Mean`, `Use Tables`
- C/E flags: `Use C/E Approach`, `Use C/E Guide Banks`, `Use C/E US XS`, `Use C/E US BR`, `Use C/E DS BR`

#### HDF Structure
- **Dataset:** `{h5Group}/Bridge Coefficient Attributes`
- Uses `DatatableLoadManager` for automatic DataTable ↔ HDF conversion

#### Key Methods
- `ColumnList()` → `List<Tuple<string, Type>>` - Schema definition
- `ReadCollection(H5Reader, h5Group)` → `Dictionary<int, List<BridgeParameters>>`
- `WriteCollection(H5Writer, h5Group, map[])`

#### Python Implementation
```python
# Read bridge parameters
params = HdfStruct.get_bridge_coefficients(geom_hdf, structure_id=5)
# Returns dict with all 34 fields
# {'method': 0, 'low_standard_step': True, 'use_momentum': False, ...}
```

---

### 5. AdvancedRulesData

**Purpose:** Store pump station operation rules with flow/stage triggers and time windows

#### Properties
```csharp
public float FlowMax, FlowMin, FlowMaxTrans, FlowMinTrans;
public int RuleType;
public string StorageArea, River, Reach, RS, ReferencePoint;
public float FlowMinTrigger, FlowMaxTrigger, WSMinTrigger, WSMaxTrigger;
public string StartDay, StartHour, EndDay, EndHour;
```

#### Constructor
```csharp
public AdvancedRulesData(object[] row)
```
Parses data from HDF compound dataset row (position-based)

#### HDF Structure
- **Dataset:** `{h5Group}/Pump Advanced Rules` (inferred from code pattern)
- Compound dataset with 18 fields

#### Key Methods
- `CreateCompoundDefinition(maxStrLen)` → `CompoundTypeDefinition`
- `MaxStrLen()` → int - Find max string length for HDF storage
- `AsObjectArray(ctd, pumpStationID)` → object[] - Convert to HDF row

#### Python Implementation
```python
# Read pump rules
rules = HdfPump.get_advanced_rules(plan_hdf, pump_id=3)
# Returns: {'flow_max': float, 'flow_min': float, 'rule_type': int,
#           'storage_area': str, 'river': str, 'reach': str, 'rs': str,
#           'flow_min_trigger': float, 'ws_max_trigger': float, ...}
```

---

### 6. UserDefinedWeirConnectivityData

**Purpose:** Map user-defined weirs to headwater/tailwater cross sections or face points

#### Data Storage
```csharp
public DataRow Row;  // Stores: SID, HW/TW, RS/FP, Station
```

#### Column Schema
- `SID` (int) - Structure ID
- `HW/TW` (string) - "Headwater" or "Tailwater"
- `RS/FP` (string) - River Station or Face Point identifier
- `Station` (float) - Connection station

#### HDF Structure
- **Dataset:** `{h5Group}/User Defined Weir Connectivity`

#### Key Methods
- `ReadCollection(H5Reader, h5Group)` → `Dictionary<int, List<UserDefinedWeirConnectivityData>>`
- `WriteCollection(H5Writer, h5Group, map[])`

#### Python Implementation
```python
# Read weir connectivity
conn = HdfStruct.get_weir_connectivity(geom_hdf, structure_id=7)
# Returns: [{'hw_tw': 'Headwater', 'rs_fp': '1234.56', 'station': 450.2}, ...]
```

---

## Interface System

### IStructureElementLayer

**Purpose:** Base interface for all structure sub-elements

```csharp
public interface IStructureElementLayer
{
    int TryGetStructureIndex(int fid);
    IStructureLayer GetAssociatedStructureLayer();
}
```

**Functionality:**
- Link feature IDs (fid) to parent structure indices
- Access parent structure layer for metadata lookup

---

### IStructurePolylineLayer

**Purpose:** Polyline-based structure elements with width and connectivity

```csharp
public interface IStructurePolylineLayer : IStructureElementLayer
{
    int AddNewElement(int parentIndex, string elementName = "");
    float GetWidth(int fID);
    bool ShouldProcessGeospatialHwTwConnectivity(int fID);
}
```

**Key Features:**
- Adds element creation capability
- Width property for hydraulic calculations
- Geospatial connectivity flag

---

### IGroupLayer

**Purpose:** Manage groups of openings (e.g., multiple culvert barrels)

```csharp
public interface IGroupLayer : IStructureElementLayer
{
    float GetWidth(int fID);
    void SetWidth(int fID, float width);
    int AddNewGroup(int parentStructureIndex, string groupName = "");
    void SetAssociatedStructure(int fID, int parentStructureIndex);
    void UpdateAssociations(int fromStructureFID, int toStructureFID);
    void SetActualStructureIndex(int fid, int idx);
}
```

**Functionality:**
- Width management (hydraulic property)
- Group creation and naming
- Parent structure associations
- Re-association when structures merge/split

---

### IOpeningLayer

**Purpose:** Individual openings (culvert barrels, weir gates) within groups

```csharp
public interface IOpeningLayer : IStructurePolylineLayer
{
    void SetGroup(int fid, int groupFid);
    int TryGetGroupIndex(int fid);
    IGroupLayer GetAssociatedGroupLayer();
    void UpdateAssociations(int fromGroupFID, int toGroupFID);
}
```

**Hierarchy:** Opening → Group → Structure

**Example:**
- Structure: Bridge #5
  - Group: "Culvert Group 1" (3 barrels)
    - Opening: "Culvert #1" (fid=10)
    - Opening: "Culvert #2" (fid=11)
    - Opening: "Culvert #3" (fid=12)

---

## Extension Methods

### IStructurePolylineLayerExtensions

**Purpose:** Manage cached segments and cell intersection lists

#### Key Methods

##### Segment Caching
```csharp
public static SegmentM GetUSSegment<T>(this T lyr, int fid)
public static SegmentM GetDSSegment<T>(this T lyr, int fid)
```
- Computes upstream/downstream cross-structure segments
- Caches in DataRow columns: `US Segment`, `DS Segment`
- Uses width and polyline geometry to create offset polygons

##### Cell Intersection Tracking
```csharp
public static List<MeshFV2D.ProfileCellRange> GetUSCellList<T>(this T lyr, int fID)
public static List<MeshFV2D.ProfileCellRange> GetDSCellList<T>(this T lyr, int fID)
public static void SetUSCellList<T>(this T lyr, int fID, List<MeshFV2D.ProfileCellRange> list)
public static void SetDSCellList<T>(this T lyr, int fID, List<MeshFV2D.ProfileCellRange> list)
```
- Stores which mesh cells a structure intersects
- `ProfileCellRange`: `{Cell: int, StationStart: double, StationEnd: double}`

##### Auto-Invalidation
```csharp
private static void NotifyStructurePolylineChanged<T>(this T lyr, int fID)
{
    SetUSCellList(lyr, fID, null);
    SetDSCellList(lyr, fID, null);
    lyr.FeatureRow(fID)["US Segment"] = DBNull.Value;
    lyr.FeatureRow(fID)["DS Segment"] = DBNull.Value;
}
```
- Invalidates cached data when geometry changes
- Triggered by `FeatureChanged` event

#### Python Equivalent
```python
# Cell intersection data available in HDF
from ras_commander import HdfStruct

cells = HdfStruct.get_structure_cells(geom_hdf, structure_id=5, side='upstream')
# Returns: [{'cell_index': 1234, 'station_start': 100.5, 'station_end': 120.3}, ...]
```

---

### IGroupLayerExtensions

**Purpose:** Group management and unique naming

#### Key Methods

##### Group Lookup
```csharp
public static int FindMatchingGroup<T>(this T lyr, StructureGroupIdentifier g)
```
Finds group by structure and name identifier

##### Structure-Group Mapping
```csharp
public static Dictionary<int, List<int>> ComputeStructureGroupMap<T>(this T lyr)
```
Returns: `{structure_index: [group_fid1, group_fid2, ...]}`

##### Group Creation
```csharp
public static int AddNewGroup<T>(this T lyr, int parentStructureIndex, string groupName = "")
```
- Auto-generates unique name if not provided
- Returns new group feature ID

##### Unique Naming
```csharp
public static int GetGroupNameCharacterLimit<T>(this T lyr) => 12;
```
HEC-RAS limitation: 12 characters for group names

---

### IOpeningLayerExtensions

**Purpose:** Opening management within groups

#### Key Methods

##### Width from Group
```csharp
public static float GetWidthFromGroup<T>(this T lyr, int fid)
```
Retrieves width from parent group (inherited property)

##### Unique Naming
```csharp
public static string GetUniqueNameWithinGroup<T>(this T lyr, int groupFId)
```
- Generates unique name like "Culvert #1", "Culvert #2"
- Scoped to group, not entire layer

##### Opening-Group Mapping
```csharp
public static Dictionary<int, List<int>> ComputeGroupOpeningMap<T>(this T lyr)
```
Returns: `{group_fid: [opening_fid1, opening_fid2, ...]}`

##### Cell Connectivity Writing
```csharp
public static void WriteCellsConnectivity<T>(
    this T lyr, H5Writer hw, string datasetname,
    string structIdColName, string groupColName, string openingColName,
    Func<int, List<MeshFV2D.ProfileCellRange>> getCellList)
```
Writes compound dataset with:
- Columns: `Structure ID`, `Group Index`, `Opening Index`, `Cell Index`, `Station Start`, `Station End`
- Used for mapping openings to intersected mesh cells

##### Naming Limits
```csharp
public static int GetOpeningNameCharacterLimit<T>(this T lyr) => 32;
```
HEC-RAS limitation: 32 characters for opening names

---

### StructureElementLayerExtensions

**Purpose:** Common operations across all structure elements

#### Key Methods

##### Find Elements in Structure
```csharp
public static List<int> FindElementsWithinStructure<T>(this T lyr, int structIdx)
```
Returns all feature IDs belonging to a structure

##### Unique Naming
```csharp
public static string GetUniqueNameWithinStructure<T>(this T lyr, int structFId)
```
Generates unique name scoped to structure

##### Group Polygon Recomputation
```csharp
public static Polygon RecomputeGroupPolygon<T, K>(
    this T lyr, K barrelLayer, int groupFID)
    where T : IGroupLayer, IGeometryLayer, FeatureLayer
    where K : IOpeningLayer, PolylineFeatureLayer
```
- Merges opening polygons into group polygon
- Accounts for georeferencing and station scaling
- Returns multipart polygon if openings are disconnected

---

## HDF Storage Patterns

### Pattern 1: Compound Attributes + Profile Data

**Used by:** `AbutmentData`, `PierData`

**Structure:**
```
{h5Group}/
├── {Element} Attributes      [Compound Dataset]
│   ├── Structure ID          [int]
│   ├── US Profile (Index)    [int]
│   ├── US Profile (Count)    [int]
│   ├── DS Profile (Index)    [int]
│   ├── DS Profile (Count)    [int]
│   └── ... (element-specific fields)
└── {Element} Data            [2D float array: [n_points, 2]]
    └── (station, elevation) pairs
```

**Advantages:**
- Efficient storage of variable-length profiles
- Single dataset for all profiles (indexed access)
- Minimal metadata overhead

**Read Pattern:**
```csharp
// Read attributes
CompoundDataset attrs = hr.ReadCompoundDataset(attrPath);
int[] structIds = attrs.GetColumn<int>("Structure ID");
int[] usStarts = attrs.GetColumn<int>("US Profile (Index)");
int[] usCounts = attrs.GetColumn<int>("US Profile (Count)");

// Read profile data
float[,] profileData;
hr.ReadDataset(dataPath, ref profileData);

// Extract profiles using indexing
List<Profile> usProfiles = Profile.FromInfoValues(profileData, usStarts, usCounts);
```

---

### Pattern 2: Compound Dataset Only

**Used by:** `MultipleOpeningData`, `UserDefinedWeirConnectivityData`

**Structure:**
```
{h5Group}/
└── {Element} Attributes      [Compound Dataset]
    ├── Structure ID          [int]
    └── ... (all data columns)
```

**Advantages:**
- Simple flat structure
- Direct row ↔ object mapping
- No indexing required

---

### Pattern 3: DataTable-Based Compound

**Used by:** `BridgeParameters`, `AdvancedRulesData`

**Structure:**
```
{h5Group}/
└── {Element} Attributes      [Compound Dataset]
    └── (uses DatatableLoadManager for schema)
```

**Features:**
- Schema defined in static constructor
- Automatic type conversion
- DataRow storage for flexibility

**Schema Definition:**
```csharp
static BridgeParameters()
{
    _dtManager = new DatatableLoadManager();
    _dtManager.Add("Structure ID", typeof(int), outputMessageIfNotFound: true);
    _dtManager.Add("Method", typeof(int));
    _dtManager.Add("Low Standard Step", typeof(bool));
    // ... 31 more fields
}
```

---

### Common Write Pattern

All classes use this deletion/recreation pattern:

```csharp
Action deleteExisting = () =>
{
    if (hw.ExistsAsDataset(datasetPath))
        hw.Delete(datasetPath);
};

if (map.Length == 0 || noDataToWrite)
{
    deleteExisting();
    return;
}

if (!hw.ExistsAsGroup(h5Group))
    hw.CreateGroup(h5Group);

// Write data
// ...
```

**Purpose:** Ensures clean slate for each write (avoids partial updates)

---

## Python Implementation Notes

### Recommended API Design

```python
from ras_commander import HdfStruct

# Abutments
abutments = HdfStruct.get_bridge_abutments(geom_hdf, structure_id=5)
# Returns: {'upstream': [(sta, elev), ...], 'downstream': [(sta, elev), ...]}

# Piers
piers = HdfStruct.get_bridge_piers(geom_hdf, structure_id=5)
# Returns: [{'us_station': float, 'ds_station': float,
#            'use_debris': bool, 'debris_width': float, 'debris_height': float,
#            'us_profile': [(sta, elev), ...], 'ds_profile': [(sta, elev), ...]}]

# Multiple openings
openings = HdfStruct.get_multiple_openings(geom_hdf, structure_id=5)
# Returns: [{'type': int, 'us_sta_left': float, 'us_sta_right': float, ...}]

# Bridge coefficients
params = HdfStruct.get_bridge_coefficients(geom_hdf, structure_id=5)
# Returns: {'method': 0, 'use_momentum': False, 'momentum_cd': 0.8, ...}

# Weir connectivity
conn = HdfStruct.get_weir_connectivity(geom_hdf, structure_id=7)
# Returns: [{'hw_tw': 'Headwater', 'rs_fp': '1234.56', 'station': 450.2}, ...]

# Cell intersections
cells = HdfStruct.get_structure_cells(geom_hdf, structure_id=5, side='upstream')
# Returns: [{'cell_index': 1234, 'station_start': 100.5, 'station_end': 120.3}, ...]
```

### Implementation Strategy

#### 1. Read Compound Datasets
```python
import h5py

with h5py.File(geom_hdf, 'r') as f:
    attrs = f['Geometry/Structures/Attributes/Pier Attributes'][:]
    profiles = f['Geometry/Structures/Attributes/Pier Data'][:]

    # Filter by structure ID
    mask = attrs['Structure ID'] == structure_id
    filtered = attrs[mask]

    # Extract profiles using index/count
    for row in filtered:
        us_start = row['US Profile (Index)']
        us_count = row['US Profile (Count)']
        us_profile = profiles[us_start:us_start+us_count]
```

#### 2. Profile Reconstruction
```python
def extract_profile(profile_data, start_idx, count):
    """Extract (station, elevation) tuples from profile array."""
    if count == 0:
        return []
    subset = profile_data[start_idx:start_idx+count]
    return [(pt[0], pt[1]) for pt in subset]
```

#### 3. Handle Missing Data
```python
def safe_get_column(compound_dataset, column_name, default=None):
    """Safely extract column with fallback for missing fields."""
    if column_name in compound_dataset.dtype.names:
        return compound_dataset[column_name]
    return default
```

---

### Key Considerations

1. **Version Compatibility**: Column names/structure may vary by HEC-RAS version
2. **String Handling**: HDF strings may be fixed-length with padding
3. **NULL Values**: Handle missing profiles (count=0) gracefully
4. **Index Validation**: Check that index+count doesn't exceed profile data bounds

---

## Automation Opportunities

### 1. Structure Geometry Validation

**Goal:** Verify pier/abutment profiles are within bridge deck limits

```python
def validate_bridge_geometry(geom_hdf, structure_id):
    """Check that pier/abutment profiles fit within bridge bounds."""
    abutments = HdfStruct.get_bridge_abutments(geom_hdf, structure_id)
    piers = HdfStruct.get_bridge_piers(geom_hdf, structure_id)

    # Check pier stations are between abutments
    us_abutment_stations = [sta for sta, elev in abutments['upstream']]
    min_sta, max_sta = min(us_abutment_stations), max(us_abutment_stations)

    for pier in piers:
        if not (min_sta <= pier['us_station'] <= max_sta):
            print(f"Warning: Pier at station {pier['us_station']} outside abutments")
```

---

### 2. Opening Group Management

**Goal:** Programmatically create culvert groups from templates

```python
def create_culvert_group(geom_file, structure_name, num_barrels, barrel_width):
    """Add culvert group with multiple barrels to existing bridge."""
    # This would require write capability (not currently in ras-commander)
    # Potential future API:

    from ras_commander import RasStruct

    group_id = RasStruct.add_culvert_group(
        geom_file,
        structure_name=structure_name,
        group_name=f"Culvert Group {num_barrels}x{barrel_width}ft"
    )

    for i in range(num_barrels):
        RasStruct.add_culvert_barrel(
            geom_file,
            group_id=group_id,
            width=barrel_width,
            station_offset=i * barrel_width * 1.5
        )
```

---

### 3. Pump Rule Automation

**Goal:** Generate pump operation rules from design criteria

```python
def create_pump_rules(plan_file, pump_id, design_criteria):
    """Generate advanced pump rules from design specs."""
    from ras_commander import RasPlan

    rule = {
        'flow_max': design_criteria['design_flow'],
        'flow_min': design_criteria['design_flow'] * 0.1,
        'flow_max_trans': design_criteria['ramp_time'],
        'flow_min_trans': design_criteria['ramp_time'],
        'rule_type': 1,  # Flow-based
        'storage_area': design_criteria['wet_well'],
        'ws_min_trigger': design_criteria['low_level'],
        'ws_max_trigger': design_criteria['high_level'],
        'start_day': '01JAN2000',
        'start_hour': '00:00',
        'end_day': '31DEC2100',
        'end_hour': '23:59'
    }

    # Write to plan file (requires new API method)
    RasPlan.set_pump_advanced_rules(plan_file, pump_id, rule)
```

---

### 4. HW/TW Connectivity Reporting

**Goal:** Generate report of weir connectivity for QA/QC

```python
def report_weir_connectivity(geom_hdf, output_csv):
    """Export weir connectivity to CSV for review."""
    import pandas as pd
    from ras_commander import HdfStruct

    all_structures = HdfStruct.list_structures(geom_hdf)
    rows = []

    for struct_id in all_structures:
        struct_info = HdfStruct.get_structure_info(geom_hdf, struct_id)
        if struct_info['type'] == 'Lateral':
            conn = HdfStruct.get_weir_connectivity(geom_hdf, struct_id)
            for c in conn:
                rows.append({
                    'Structure': struct_info['name'],
                    'HW/TW': c['hw_tw'],
                    'Location': c['rs_fp'],
                    'Station': c['station']
                })

    df = pd.DataFrame(rows)
    df.to_csv(output_csv, index=False)
```

---

### 5. Cell Intersection Analysis

**Goal:** Identify structures with insufficient mesh resolution

```python
def analyze_structure_mesh_resolution(geom_hdf):
    """Check if structures intersect enough cells for accurate modeling."""
    from ras_commander import HdfStruct, HdfMesh

    all_structures = HdfStruct.list_structures(geom_hdf)
    warnings = []

    for struct_id in all_structures:
        us_cells = HdfStruct.get_structure_cells(geom_hdf, struct_id, side='upstream')
        ds_cells = HdfStruct.get_structure_cells(geom_hdf, struct_id, side='downstream')

        if len(us_cells) < 3:
            warnings.append(f"Structure {struct_id}: Only {len(us_cells)} US cells (recommend ≥3)")

        # Check for very short intersection lengths
        for cell in us_cells:
            length = cell['station_end'] - cell['station_start']
            if length < 5.0:  # feet
                warnings.append(f"Structure {struct_id}: Cell {cell['cell_index']} intersection length {length:.1f} ft")

    return warnings
```

---

### 6. Bridge Coefficient Standardization

**Goal:** Apply consistent bridge analysis methods across project

```python
def standardize_bridge_methods(geom_hdf, method_template):
    """Apply standard bridge analysis settings to all bridges."""
    from ras_commander import HdfStruct

    bridges = [s for s in HdfStruct.list_structures(geom_hdf)
               if HdfStruct.get_structure_info(geom_hdf, s)['type'] == 'Bridge']

    changes = []
    for bridge_id in bridges:
        current = HdfStruct.get_bridge_coefficients(geom_hdf, bridge_id)

        # Check if already compliant
        if current['method'] != method_template['method']:
            changes.append({
                'structure_id': bridge_id,
                'old_method': current['method'],
                'new_method': method_template['method']
            })

            # Update (requires write API)
            # HdfStruct.set_bridge_coefficients(geom_hdf, bridge_id, method_template)

    return changes
```

---

## Summary

### Key Takeaways

1. **Hierarchical Structure**: Structure → Group → Opening model enables flexible representation
2. **Efficient Storage**: Indexed profile arrays minimize HDF file size
3. **Cached Computation**: Segments and cell lists cached in DataRows, auto-invalidated on change
4. **Extension Pattern**: Interface + extension methods provide clean separation of concerns
5. **Compound Datasets**: Primary storage mechanism for attribute data

### Python Implementation Priority

**High Priority:**
1. Read pier/abutment profiles (`HdfStruct.get_bridge_piers/abutments`)
2. Read bridge coefficients (`HdfStruct.get_bridge_coefficients`)
3. Read cell intersections (`HdfStruct.get_structure_cells`)

**Medium Priority:**
4. Read multiple opening data
5. Read weir connectivity
6. Read pump advanced rules

**Low Priority (Write Operations):**
7. Modify bridge coefficients
8. Create/delete openings and groups
9. Update pump rules

### Next Steps for ras-commander

1. **Add `HdfStruct` class** similar to existing `HdfStruc` (note spelling difference)
2. **Implement read methods** for all structure data types
3. **Add validation utilities** for geometry QA/QC
4. **Consider write API** for automation workflows (requires careful testing)

---

**Document Version:** 1.0
**Date:** 2025-12-09
**Decompiled Source:** RasMapperLib.dll (RASMapper 6.x)
**Related Documentation:**
- `01_core_architecture.md` - Overall RASMapper architecture
- `02_geometry_namespace.md` - Structure geometry layers
- `03_results_namespace.md` - Structure results extraction
- `04_utilities_namespace.md` - Profile and hash utilities
