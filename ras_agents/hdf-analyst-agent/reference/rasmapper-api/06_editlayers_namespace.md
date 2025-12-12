# RASMapper EditLayers Namespace Documentation

**Purpose:** Interactive editing system for all geometric features in RASMapper, including mesh manipulation and fixing operations.

**Location:** `RasMapperLib.EditLayers` and `RasMapperLib.EditLayers.EditOperations`

---

## Table of Contents

1. [Namespace Overview](#namespace-overview)
2. [Class Hierarchy](#class-hierarchy)
3. [Edit Layer Types](#edit-layer-types)
4. [Edit Operations](#edit-operations)
5. [Mesh Editing](#mesh-editing)
6. [Undo/Redo System](#undoredo-system)
7. [Python Implementation Notes](#python-implementation-notes)
8. [Automation Opportunities](#automation-opportunities)

---

## Namespace Overview

The EditLayers namespace provides RASMapper's comprehensive editing infrastructure for all geometric features. Key capabilities:

- **Interactive editing**: Mouse-based drawing, moving, inserting, and deleting features
- **Undo/redo stack**: Full history tracking with operation reversal
- **Mesh fixing**: Automated algorithms to repair incomplete/invalid meshes
- **Context menus**: Right-click operations for features and layers
- **Toolbar integration**: Add/Edit mode switching with visual feedback
- **Batch operations**: Multiple features/operations in single undo unit

**Design Philosophy:**
- **Command Pattern**: All edits wrapped as reversible `EditOperation` objects
- **State Management**: Suppressor pattern for batch operations
- **Type Safety**: Strong typing with abstract base classes
- **Event-Driven**: Redraw suppression and feature change notifications

---

## Class Hierarchy

### Base Classes

```
IEditableFeature (interface)
  └─ Feature implementations
      ├─ PointEditable
      ├─ MultiPointEditable
      ├─ PolylineEditable
      └─ PolygonEditable

FeatureEditor (abstract base)
  ├─ PointFeatureEditor
  ├─ MultiPointFeatureEditor
  │   └─ MeshPointEditor
  ├─ PolylineFeatureEditor
  │   ├─ NamedPolylineFeatureEditor
  │   ├─ CrossSectionEditor
  │   ├─ BreaklineEditor
  │   └─ FlowpathsEditor
  └─ PolygonFeatureEditor
      ├─ MeshPolygonEditor
      │   ├─ MeshPerimeterEditor
      │   └─ MeshRegionEditor
      ├─ StorageAreaEditor
      └─ IneffectiveFlowAreaEditor

EditOperation (abstract base)
  ├─ AddFeature
  ├─ DeleteFeatures
  ├─ InsertPointOnFeature
  ├─ DeletePointsOnFeature
  ├─ TransformFeatures
  └─ MultiEditOperation
```

### Key Interfaces

**IEditableFeature** - Features that support point-level manipulation:
```csharp
public interface IEditableFeature
{
    void TransformFeature(Transform transformer);
    void TransformPoint(Transform transformer, int index);
    void DeletePoints(IList<int> indexes);
    void InsertPoint(PointM point, int index);
    PointM Point(int index);
    Feature Save();
}
```

---

## Edit Layer Types

### 1. **1D River System Editors**

| Editor | Feature Type | Key Operations |
|--------|--------------|----------------|
| `RiverEditor` | River reach networks | Cross-section assignment |
| `CrossSectionEditor` | Cross-sections | Profile editing, Manning's n |
| `BanklineEditor` | Bank lines | Geometry definition |
| `FlowpathsEditor` | Flow paths | Channel/LOB/ROB paths |
| `JunctionFeatureEditor` | Junctions | River connectivity |
| `StorageAreaEditor` | Storage areas | Volume curves |

### 2. **2D Mesh Editors** ⭐

| Editor | Feature Type | Key Operations |
|--------|--------------|----------------|
| `MeshEditor` | 2D flow areas (meshes) | Properties, fix mesh, recompute |
| `MeshPerimeterEditor` | Mesh perimeters | Point generation, mesh fixing |
| `MeshPointEditor` | Mesh computation points | Add/delete points, regenerate |
| `MeshRegionEditor` | Refinement regions | Enforce region, cell size |
| `BreaklineEditor` | Breaklines | Enforce breakline, spacing |

### 3. **Boundary Condition Editors**

| Editor | Feature Type | Key Operations |
|--------|--------------|----------------|
| `BCLineEditor` | Boundary condition lines | BC assignment |
| `ICPointsEditor` | Initial condition points | IC values |

### 4. **Structure Editors**

| Editor | Feature Type | Key Operations |
|--------|--------------|----------------|
| `PierFeatureEditor` | Bridge piers | Placement, dimensions |
| `CulvertBarrelFeatureEditor` | Culvert barrels | Barrel properties |
| `GateOpeningFeatureEditor` | Gate openings | Gate curves |

### 5. **Utility Editors**

| Editor | Feature Type | Key Operations |
|--------|--------------|----------------|
| `MediaPointFeatureEditor` | Media points | Photo/video locations |
| `ReferenceAreasEditor` | Reference polygons | Comparison areas |
| `ObstructionAreaLayerEditor` | Blocked areas | Flow obstructions |

**Total:** 56 editor classes supporting all HEC-RAS geometric entities

---

## Edit Operations

All edit operations inherit from `EditOperation` abstract base class with `Apply()` and `Undo()` methods.

### Operation Types

#### 1. **Feature-Level Operations**

**AddFeature** - Create new feature:
```csharp
public AddFeature(FeatureEditor editLayer, int fid, PointM startPoint)

// Apply: Insert new feature at FID
// Undo: Delete feature at FID
```

**DeleteFeatures** - Remove features:
```csharp
public DeleteFeatures(FeatureEditor editLayer, SelectedFeatureCollection features)

// Apply: Delete features, store row data
// Undo: Re-insert features with original attributes
```

**TransformFeatures** - Move/rotate/scale:
```csharp
public TransformFeatures(FeatureEditor editLayer, SelectedFeatureCollection features, Transform transformer)

// Apply: Apply transform to all selected features
// Undo: Apply inverse transform
```

**ReplaceFeature** - Swap feature geometry:
```csharp
public ReplaceFeature(FeatureEditor editLayer, int fid, Feature newFeature)

// Apply: Replace feature at FID
// Undo: Restore original feature
```

#### 2. **Point-Level Operations** (on open features)

**InsertPointOnFeature** - Add single point:
```csharp
public InsertPointOnFeature(FeatureEditor editLayer, SelectedFeature feature, PointM point, int index)

// Apply: Insert point at index
// Undo: Delete point at index
```

**InsertPointsOnFeature** - Add multiple points:
```csharp
public InsertPointsOnFeature(FeatureEditor editLayer, SelectedFeature feature, List<PointM> points, int startIndex)

// Apply: Insert point list starting at index
// Undo: Delete inserted points
```

**DeletePointsOnFeature** - Remove points:
```csharp
public DeletePointsOnFeature(FeatureEditor editLayer, SelectedFeature feature)

// Apply: Delete selected points, store originals
// Undo: Re-insert deleted points
```

**TransformPointsOnFeature** - Move selected points:
```csharp
public TransformPointsOnFeature(FeatureEditor editLayer, SelectedFeature feature, Transform transformer)

// Apply: Transform selected points
// Undo: Inverse transform
```

#### 3. **Batch Operations**

**MultiEditOperation** - Composite operation:
```csharp
public MultiEditOperation(FeatureEditor editLayer, List<EditOperation> operations)

// Apply: Execute all operations in order
// Undo: Undo all operations in reverse order
// Uses PlotLayerConsolidator to suppress redraws until complete
```

**AddFeatureRangeWithAttributes** - Import from shapefile:
```csharp
public AddFeatureRangeWithAttributes(FeatureEditor editLayer, List<Feature> features, List<DataRow> attributes)

// Apply: Insert features with attribute mapping
// Undo: Delete all inserted features
```

#### 4. **Attribute Operations**

**SetAttributeEditOperation** - Modify attributes:
```csharp
public SetAttributeEditOperation(FeatureEditor editLayer, int fid, string columnName, object newValue)

// Apply: Set attribute value
// Undo: Restore original value
```

**MoveFeatureIndex** - Reorder features:
```csharp
public MoveFeatureIndex(FeatureEditor editLayer, int oldIndex, int newIndex)

// Apply: Move feature in table
// Undo: Move back to original position
```

---

## Mesh Editing

### MeshEditor - 2D Flow Area Editor

**Capabilities:**
- Cannot add new meshes interactively (must use MeshPerimeterEditor)
- Cannot edit existing mesh polygons (read-only)
- Provides context menu actions for mesh operations
- Launches `D2Editor` dialog for property editing

**Key Methods:**

```csharp
// Import meshes from another geometry
public void ImportMeshes(RASGeometry importedGeometry, IList<int> selectedMeshesIdxs, IList<int> replaceMeshIdxs = null)
{
    // Copies mesh perimeter, points, regions, breaklines
    // Updates spatial relationships
    // Marks mesh as "Just Imported"
}

// Recompute out-of-date meshes
public static void ComputeOutOfDateMeshes(RASGeometry g, bool showProgress = true)
{
    // Identifies meshes with IsUpToDate = false
    // Calls RASD2FlowArea.ComputeOutOfDateMeshes()
    // Reports timing and count
}
```

**Custom Actions:**
- **Edit 2D Area Properties**: Opens D2Editor dialog
- **Recompute Out-of-Date Meshes**: Batch mesh generation
- **Try to Fix Mesh**: Automated mesh repair (right-click on feature)

---

### MeshPerimeterEditor - Mesh Boundary Editor ⭐

**Primary mesh editing interface.** Handles perimeter polygons and triggers mesh generation/fixing.

**Key Methods:**

```csharp
// Auto-fix mesh problems
internal void TryToFixMeshes(List<int> meshList)
{
    foreach (int mesh in meshList)
    {
        MeshFV2D meshFV2D = _meshPerim.Geometry.D2FlowArea.Mesh(mesh);

        // Get fix suggestions from mesh
        List<PointM> suggestedNewCells = null;
        List<int> suggestedRemoveCells = null;
        List<int> suggestedRemovePerimeterPoints = null;

        meshFV2D.TryAutoFix(
            _meshPerim.Geometry.MeshPerimeters.Polygon(mesh),
            _meshPerim.Geometry.MeshPoints.GetMeshEditingPoints(),
            _meshPerim.GetCellSize2D(mesh),
            ref suggestedNewCells,
            ref suggestedRemoveCells,
            ref suggestedRemovePerimeterPoints
        );

        // Apply fixes via MeshPointEditor
        if (suggestedNewCells.Count > 0 || suggestedRemoveCells.Count > 0)
        {
            MeshPointEditor meshPointEditor = GetMeshPointEditor();
            meshPointEditor.ModifyPointsWithUndo(suggestedRemoveCells, suggestedNewCells);
        }

        // Or fix perimeter points
        if (suggestedRemovePerimeterPoints.Count > 0)
        {
            ModifyPointsWithUndo(mesh, suggestedRemovePerimeterPoints);
        }

        // Recompute mesh after fixes
        _meshPerim.Geometry.D2FlowArea.ComputeOutOfDateMesh(mesh);
    }
}

// Modify perimeter points with undo
public void ModifyPointsWithUndo(int fid, List<int> deleteIndexes)
{
    SelectedFeature feature = new SelectedFeature(fid);
    feature.OpenFeature();
    feature.SelectPoints(deleteIndexes);

    DeletePointsOnFeature deleteOp = new DeletePointsOnFeature(this, feature);
    ExecutePushUndo(new MultiEditOperation(this, new List<EditOperation> { deleteOp }));
}
```

**Right-Click Menu (Layer):**
- Edit 2D Area Properties
- Generate Computation Points with Breaklines for All Meshes
- Try to Fix All Meshes
- Regenerate Points for Selected 2D Area (Debug mode)

**Right-Click Menu (Feature):**
- Rename 2D Area
- Edit 2D Area Properties
- Generate Computation Points with All Breaklines for Mesh
- **Try to Fix Mesh** ⭐ - Automated repair
- Recompute Mesh (if out-of-date or unlocked)
- Regenerate Mesh Points (Debug mode)

---

### MeshPointEditor - Computation Point Editor

Manages the single global point collection (FID 0) used for all mesh generation.

**Key Methods:**

```csharp
// Delete all points with undo support
public void DeleteAllPointsWithUndo()
{
    SelectedFeature feature = new SelectedFeature(0);
    feature.OpenFeature();
    feature.SelectAllPoints(_meshPoints.GetMeshEditingPoints().Count);

    DeletePointsOnFeature editop = new DeletePointsOnFeature(this, feature);
    ExecutePushUndo(editop);
}

// Modify points (used by mesh fixing)
public void ModifyPointsWithUndo(List<int> deleteIndexes, List<PointM> newIndexes)
{
    List<EditOperation> ops = new List<EditOperation>();

    // Delete points
    if (deleteIndexes != null && deleteIndexes.Count > 0)
    {
        SelectedFeature feature = new SelectedFeature(0);
        feature.OpenFeature();
        feature.SelectPoints(deleteIndexes);
        ops.Add(new DeletePointsOnFeature(this, feature));
    }

    // Add new points
    if (newIndexes != null && newIndexes.Count > 0)
    {
        int count = _meshPoints.GetMeshEditingPoints().Count;
        ops.Add(new InsertPointsOnFeature(this, 0, newIndexes, count));
    }

    if (ops.Count > 0)
        ExecutePushUndo(new MultiEditOperation(this, ops));
}

// Regenerate points (calls PointGenerator)
public void RegenerateMeshPointsSuppressEvents(
    IList<int> activeBlines = null,
    IList<int> activeSA2Ds = null,
    IList<int> activeRegions = null,
    IList<int> activePerims = null,
    IList<int> regeneratePerims = null)
{
    using (new WaitCursor(SharedData.RasMapper))
    {
        using (new FeatureChangedRedrawSuppressor())
        {
            PointGenerator.RegenerateMeshPoints(
                _meshPoints.Geometry,
                activeBlines, activeSA2Ds, activeRegions,
                activePerims, regeneratePerims
            );
        }
    }
}
```

**Special Behavior:**
- **Lockdown Mode**: Cannot close feature (always editing point 0)
- **Force Redraw**: Redraws on every point change
- Automatically consolidates multiple point features into single feature (FID 0)

---

### MeshRegionEditor - Refinement Region Editor

Manages mesh refinement polygons that override default cell sizes.

**Key Methods:**

```csharp
// Edit region properties (cell size, spacing)
private void EditMeshRegionLayer(int fid)
{
    List<string> properties = new List<string>
    {
        "Name",
        "Cell Size X",
        "Cell Size Y",
        "Perimeter Spacing",
        "Near Repeats",
        "Far Spacing",
        "Enforce 1 Cell Protection Radius"
    };
    new PolylineEditorTable(this, fid, properties).ShowDialog();
}

// Enforce regions (regenerate points)
public CustomEditAction GetEnforceALLRefinementRegionAction()
{
    return new CustomEditAction(Resources.MeshReghion_16, "Enforce Refinement Regions", () =>
    {
        using (new WaitCursor(SharedData.RasMapper))
        {
            using (new FeatureChangedRedrawSuppressor(this))
            {
                // Regenerate all regions
                PointGenerator.RegenerateMeshPoints(
                    _meshRegion.Geometry,
                    new int[0],  // No breaklines
                    new int[0],  // No SA/2D connections
                    null,        // All regions
                    null,        // All perimeters
                    new int[0]   // No specific regenerate list
                );
            }
        }
    });
}
```

**Right-Click Menu:**
- Edit Refinement Region Properties
- Enforce Region(s) - Regenerates mesh points with region spacing
- Rename Refinement Region

---

### Mesh Fixing Algorithm (MeshFV2D.TryAutoFix)

Called by `MeshPerimeterEditor.TryToFixMeshes()` to identify mesh problems:

**Inputs:**
- `Polygon perimeterPolygon` - Mesh boundary
- `PointMs meshPoints` - All computation points
- `Point2D cellSize` - Target cell dimensions
- `ref List<PointM> suggestedNewCells` - **Output**: Points to add
- `ref List<int> suggestedRemoveCells` - **Output**: Point indices to delete
- `ref List<int> suggestedRemovePerimeterPoints` - **Output**: Perimeter point indices to delete

**Logic:**
1. Identifies incomplete cells (cells with < 3 facepoints)
2. Suggests adding points to fill gaps
3. Suggests removing points that create invalid topology
4. Suggests removing perimeter points that cause boundary issues

**Application:**
```csharp
// Get suggestions
meshFV2D.TryAutoFix(perimeter, points, cellSize, ref newCells, ref removeCells, ref removePerimPts);

// Apply via editors
if (newCells.Count > 0 || removeCells.Count > 0)
{
    meshPointEditor.ModifyPointsWithUndo(removeCells, newCells);
}

if (removePerimPts.Count > 0)
{
    meshPerimEditor.ModifyPointsWithUndo(meshFID, removePerimPts);
}

// Recompute mesh
d2FlowArea.ComputeOutOfDateMesh(meshFID);
```

---

## Undo/Redo System

### Architecture

**Stack-Based Command Pattern:**
```csharp
private readonly Stack<EditOperation> _undoOperations;
private readonly Stack<EditOperation> _redoOperations;
```

### Execution Flow

```csharp
// Execute operation and push to undo stack
public void ExecutePushUndo(EditOperation editop, bool supressRedrawUntilEnd = false)
{
    if (supressRedrawUntilEnd)
    {
        using (new PlotLayerConsolidator(SharedData.RasMapper))
        {
            editop.Apply();
            PushUndo(editop);
        }
    }
    else
    {
        editop.Apply();
        PushUndo(editop);
    }
}

// Push to undo stack, clear redo stack
protected void PushUndo(EditOperation editOp)
{
    _undoOperations.Push(editOp);
    _redoOperations.Clear();  // Any new operation clears redo history

    _editorToolBar.CanUndo = true;
    _editorToolBar.CanRedo = false;
}
```

### Undo

```csharp
public bool TryUndo()
{
    if (_undoOperations.Count == 0 || _isUndoingOrRedoing)
        return false;

    _isUndoingOrRedoing = true;

    using (GetSuppressor())  // Suppress redraws during undo
    {
        while (_undoOperations.Count != 0)
        {
            EditOperation op = _undoOperations.Pop();
            op.Undo();
            _redoOperations.Push(op);  // Move to redo stack

            if (!op.IsSilentOperation)  // Silent ops don't count
                break;
        }
    }

    // Update selection based on operation type
    Type opType = op.GetType();
    if (opType == typeof(DeletePointsOnFeature))
        _ftLayer.SelectedFeatures = op.CopySelectedFeatures();
    else if (opType == typeof(AddFeature))
        _ftLayer.SelectedFeatures.ClearSelection();
    // ... more type-specific selection restoration

    _ftLayer.ValidateSelectedFeatures();
    InvalidateBitmaps(forceRedraw: true);
    _isUndoingOrRedoing = false;

    return true;
}
```

### Redo

```csharp
public bool TryRedo()
{
    if (_redoOperations.Count == 0 || _isUndoingOrRedoing)
        return false;

    _isUndoingOrRedoing = true;

    EditOperation op = _redoOperations.Pop();
    _undoOperations.Push(op);  // Move back to undo stack

    // Restore selection based on operation type
    // ... (similar to undo)

    op.Apply();

    _ftLayer.ValidateSelectedFeatures();
    InvalidateBitmaps(forceRedraw: true);
    _isUndoingOrRedoing = false;

    return true;
}
```

### Keyboard Shortcuts

- **Ctrl+Z**: Undo
- **Ctrl+Y**: Redo
- **Ctrl+A**: Select All
- **Ctrl+C**: Copy
- **Ctrl+V**: Paste
- **Delete** or **D**: Delete selected
- **Tab**: Toggle Add/Edit mode
- **Escape**: Close active feature

### Silent Operations

Operations can be marked `IsSilentOperation = true` to be undone without stopping:
```csharp
EditOperation op = new AddFeature(this, fid, point);
op.IsSilentOperation = true;  // Won't stop undo chain
```

Use case: Multi-step operations where intermediate steps shouldn't be visible undo points.

---

## Redraw Suppression System

### Pattern: Disposable Suppressors

**Problem:** Batch operations trigger hundreds of redraws, slowing the UI.

**Solution:** Suppressor classes that disable redraws during operation scope.

### FeatureChangedRedrawSuppressor

```csharp
public class FeatureChangedRedrawSuppressor : IDisposable
{
    private FeatureEditor _ftEditor;

    public FeatureChangedRedrawSuppressor(FeatureEditor ftEditor = null)
    {
        _ftEditor = ftEditor;

        if (_ftEditor == null)
            FeatureEditor.SupressFeatureChangedRedrawGlobal(suppress: true);
        else
            _ftEditor.SupressFeatureChangedRedraw(suppress: true);
    }

    public void Dispose()
    {
        if (_ftEditor == null)
            FeatureEditor.SupressFeatureChangedRedrawGlobal(suppress: false);
        else
            _ftEditor.SupressFeatureChangedRedraw(suppress: false);
    }
}
```

**Usage:**
```csharp
using (new FeatureChangedRedrawSuppressor(this))
{
    // Perform 1000 point insertions
    // Only redraws once at end
}
```

### PlotLayerConsolidator

Suppresses all plot layer invalidations until disposal:
```csharp
using (new PlotLayerConsolidator(SharedData.RasMapper))
{
    operation1.Apply();
    operation2.Apply();
    operation3.Apply();
    // Single redraw after all operations
}
```

### FeatureChangedEventFireSuppressor

Suppresses feature change events (but not redraws):
```csharp
using (new FeatureChangedEventFireSuppressor(featureEditor))
{
    // Modify features without triggering change handlers
}
```

### WaitCursor

Shows hourglass cursor during long operations:
```csharp
using (new WaitCursor(SharedData.RasMapper))
{
    ComputeOutOfDateMeshes(geometry);
}
```

---

## Python Implementation Notes

### Strategy A: External Automation (Recommended)

Bypass the editor framework entirely and manipulate geometry files directly.

**Pros:**
- No GUI dependencies
- Can run headless/batch
- Full control over logic
- No COM interface issues

**Cons:**
- Must understand file formats
- No built-in undo/validation
- Mesh computation requires HEC-RAS engine

**Example: Add Mesh Points Programmatically**

```python
from ras_commander import init_ras_project, HdfMesh
import geopandas as gpd
from shapely.geometry import Point

# Initialize project
init_ras_project("path/to/project.prj", "6.6")
ras = init_ras_project._ras

# Get current mesh points
geom_hdf = "path/to/geometry.g01.hdf"
mesh_points = HdfMesh.get_mesh_cell_points(geom_hdf)  # Returns GeoDataFrame

# Add new points
new_points = [
    Point(1000, 2000),
    Point(1010, 2010),
    Point(1020, 2020)
]

# Write to geometry file (plaintext or HDF)
# ... (requires geometry file writer)

# Trigger recompute via RAS
from ras_commander import RasCmdr
RasCmdr.compute_plan("01", clear_geompre=True)
```

**Example: Fix Mesh Externally**

```python
from ras_commander import HdfMesh
import numpy as np

# Read mesh
geom_hdf = "geometry.g01.hdf"
cell_polygons = HdfMesh.get_mesh_cell_polygons(geom_hdf)
cell_faces = HdfMesh.get_mesh_cell_faces(geom_hdf)

# Identify incomplete cells
incomplete_cells = []
for idx, row in cell_polygons.iterrows():
    cell_id = row['cell_id']
    polygon = row['geometry']

    # Check if polygon has < 3 vertices
    if len(polygon.exterior.coords) < 4:  # 3 unique + closed
        incomplete_cells.append(cell_id)

print(f"Found {len(incomplete_cells)} incomplete cells")

# Suggest new point locations (simple grid fill)
cell_size = 20  # feet
suggestions = []
for cell_id in incomplete_cells:
    centroid = cell_polygons[cell_polygons['cell_id'] == cell_id].geometry.centroid.iloc[0]
    suggestions.append(Point(centroid.x, centroid.y))

# Write suggestions back to geometry
# ... (requires geometry file writer)
```

---

### Strategy B: COM Automation (Advanced)

Invoke RASMapper's editor framework via COM (similar to HECRASController).

**Pros:**
- Leverages existing validation/mesh generation
- True undo/redo support
- Access to mesh fixing algorithms

**Cons:**
- Requires RASMapper COM interface (if exists)
- Windows-only
- Session-based execution
- Complex threading

**Hypothetical Example:**

```python
import win32com.client

# Create RASMapper COM object (hypothetical API)
rasMapper = win32com.client.Dispatch("RASMapper.Application")
rasMapper.Visible = True
rasMapper.OpenProject("path/to/project.rasmap")

# Get geometry
geometry = rasMapper.ActiveGeometry

# Get mesh perimeter editor
mesh_perimeter_layer = geometry.MeshPerimeters
mesh_editor = mesh_perimeter_layer.FeatureEditor

# Try to fix mesh (calls TryToFixMeshes)
mesh_list = [0, 1, 2]  # FIDs
mesh_editor.TryToFixMeshes(mesh_list)

# Save and close
rasMapper.SaveProject()
rasMapper.Quit()
```

**Reality:** RASMapper does NOT expose a public COM interface like HECRASController. This approach is **NOT currently feasible** without reverse-engineering private COM objects.

---

### Strategy C: Hybrid - Geometry Modification + HEC-RAS Compute

Best of both worlds:

1. **Python** - Modify geometry files (add/delete/move points)
2. **HEC-RAS** - Recompute meshes using engine
3. **Python** - Extract results from HDF

**Example Workflow:**

```python
from ras_commander import init_ras_project, RasCmdr, HdfMesh
from pathlib import Path

# 1. Read geometry
init_ras_project("project.prj", "6.6")
geom_hdf = "geometry.g01.hdf"

# 2. Identify mesh issues
cell_polygons = HdfMesh.get_mesh_cell_polygons(geom_hdf)
incomplete = identify_incomplete_cells(cell_polygons)  # Custom function

# 3. Modify plaintext geometry file
geom_file = Path("geometry.g01")
add_mesh_points_to_geometry(geom_file, new_points)  # Custom function

# 4. Recompute mesh with HEC-RAS
RasCmdr.compute_plan(
    plan_number="01",
    clear_geompre=True,  # Force geometry preprocessing
    num_cores=4
)

# 5. Validate results
result_hdf = "plan.p01.hdf"
cell_polygons_new = HdfMesh.get_mesh_cell_polygons(geom_hdf)
incomplete_new = identify_incomplete_cells(cell_polygons_new)

print(f"Fixed {len(incomplete) - len(incomplete_new)} cells")
```

---

## Automation Opportunities

### 1. **Batch Mesh Fixing** ⭐⭐⭐

**Goal:** Automate `MeshPerimeterEditor.TryToFixMeshes()` for all projects in a directory.

**Approach:**
- Parse geometry HDF to identify incomplete meshes
- Call `MeshFV2D.TryAutoFix()` logic in Python (requires porting C# algorithm)
- Modify geometry files to add/remove suggested points
- Recompute meshes via `RasCmdr.compute_plan()`

**Python Pseudocode:**

```python
def auto_fix_all_meshes(project_path, ras_version="6.6"):
    init_ras_project(project_path, ras_version)

    # Get all geometries
    for geom in ras.geom_df.itertuples():
        geom_hdf = geom.hdf_path

        # Check mesh completeness
        cell_polygons = HdfMesh.get_mesh_cell_polygons(geom_hdf)
        cell_faces = HdfMesh.get_mesh_cell_faces(geom_hdf)

        for mesh_id in cell_polygons['mesh_id'].unique():
            mesh_cells = cell_polygons[cell_polygons['mesh_id'] == mesh_id]

            # Port TryAutoFix algorithm
            suggestions = try_auto_fix_mesh(mesh_cells, cell_faces)

            if suggestions['add_points'] or suggestions['remove_points']:
                apply_mesh_fixes(geom.file_path, mesh_id, suggestions)

        # Recompute after fixes
        RasCmdr.compute_plan(geom.plan_number, clear_geompre=True)
```

**Challenges:**
- Porting `MeshFV2D.TryAutoFix()` C# algorithm to Python
- Understanding mesh topology rules
- Modifying plaintext geometry files (no current writer API)

**Value:** High - Automates tedious manual mesh fixing

---

### 2. **Mesh Quality Report**

**Goal:** Generate PDF reports of mesh quality metrics.

**Metrics:**
- % complete cells (cells with valid face counts)
- Cell size distribution
- Aspect ratio violations
- Skewness violations
- Edge length distribution

**Python Implementation:**

```python
def generate_mesh_quality_report(geom_hdf, output_pdf):
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    # Read mesh
    cell_polygons = HdfMesh.get_mesh_cell_polygons(geom_hdf)
    cell_faces = HdfMesh.get_mesh_cell_faces(geom_hdf)

    # Compute metrics
    metrics = compute_mesh_quality_metrics(cell_polygons, cell_faces)

    # Generate plots
    with PdfPages(output_pdf) as pdf:
        # Plot 1: Completeness
        fig, ax = plt.subplots()
        ax.bar(['Complete', 'Incomplete'],
               [metrics['complete_count'], metrics['incomplete_count']])
        ax.set_title('Mesh Completeness')
        pdf.savefig(fig)

        # Plot 2: Cell size histogram
        fig, ax = plt.subplots()
        ax.hist(metrics['cell_areas'], bins=50)
        ax.set_title('Cell Size Distribution')
        ax.set_xlabel('Area (sq ft)')
        pdf.savefig(fig)

        # Plot 3: Aspect ratio
        fig, ax = plt.subplots()
        ax.hist(metrics['aspect_ratios'], bins=50)
        ax.axvline(3, color='r', linestyle='--', label='Max Recommended')
        ax.set_title('Aspect Ratio Distribution')
        ax.legend()
        pdf.savefig(fig)

    print(f"Report saved: {output_pdf}")
```

**Value:** Medium - Useful for QC, but doesn't modify geometry

---

### 3. **Geometry Simplification**

**Goal:** Reduce geometry complexity by removing redundant points.

**Use Case:**
- Imported shapefiles with excessive vertices
- Cross-sections with 1000+ points
- Mesh perimeters with over-dense spacing

**Algorithm (Douglas-Peucker):**

```python
from shapely.geometry import LineString

def simplify_geometry_features(geom_file, tolerance=0.1):
    """
    Simplify polyline/polygon features using Douglas-Peucker.

    Args:
        geom_file: Path to .g## file
        tolerance: Distance tolerance (ft)
    """
    from ras_commander import RasGeometry

    # Read geometry
    geom = RasGeometry(geom_file)

    # Simplify cross-sections
    xs_df = geom.get_cross_sections()
    for idx, xs in xs_df.iterrows():
        station, elevation = geom.get_station_elevation(xs['river'], xs['reach'], xs['xs_id'])

        # Create LineString and simplify
        line = LineString(zip(station, elevation))
        simplified = line.simplify(tolerance, preserve_topology=True)

        # Write back
        new_station = [pt[0] for pt in simplified.coords]
        new_elevation = [pt[1] for pt in simplified.coords]
        geom.set_station_elevation(xs['river'], xs['reach'], xs['xs_id'],
                                    new_station, new_elevation)

    # Save modified geometry
    geom.save()
    print(f"Simplified {len(xs_df)} cross-sections")
```

**Value:** Medium - Improves performance but requires careful validation

---

### 4. **Mesh Point Import from Survey Data**

**Goal:** Import field survey points as mesh computation points.

**Workflow:**

```python
def import_survey_points_to_mesh(survey_csv, geom_file, mesh_name):
    """
    Add survey points to specific 2D mesh area.

    Args:
        survey_csv: CSV with X, Y, Z columns
        geom_file: Geometry file path
        mesh_name: Name of 2D flow area
    """
    import pandas as pd
    from ras_commander import RasGeometry

    # Read survey
    survey = pd.read_csv(survey_csv)
    points = gpd.GeoDataFrame(
        survey,
        geometry=gpd.points_from_xy(survey['X'], survey['Y']),
        crs='EPSG:2230'  # Adjust to project CRS
    )

    # Get mesh perimeter
    geom = RasGeometry(geom_file)
    mesh_perims = geom.get_mesh_perimeters()
    mesh = mesh_perims[mesh_perims['name'] == mesh_name].iloc[0]

    # Filter points inside perimeter
    points_in_mesh = points[points.within(mesh.geometry)]

    # Add to mesh points
    # ... (requires geometry file writer)

    print(f"Added {len(points_in_mesh)} survey points to {mesh_name}")
```

**Value:** High - Automates tedious manual point placement

---

### 5. **Undo/Redo for Python Scripts**

**Goal:** Implement undo functionality for programmatic geometry edits.

**Approach:** Command pattern in Python

```python
class GeometryEditOperation:
    """Base class for undoable geometry edits."""

    def apply(self):
        raise NotImplementedError

    def undo(self):
        raise NotImplementedError

class AddMeshPointsOperation(GeometryEditOperation):
    def __init__(self, geom_file, points):
        self.geom_file = geom_file
        self.points = points
        self.added_indices = []

    def apply(self):
        geom = RasGeometry(self.geom_file)
        mesh_points = geom.get_mesh_points()

        # Add points and track indices
        start_idx = len(mesh_points)
        for pt in self.points:
            mesh_points = mesh_points.append({'geometry': pt}, ignore_index=True)

        self.added_indices = range(start_idx, len(mesh_points))
        geom.set_mesh_points(mesh_points)
        geom.save()

    def undo(self):
        geom = RasGeometry(self.geom_file)
        mesh_points = geom.get_mesh_points()
        mesh_points = mesh_points.drop(self.added_indices)
        geom.set_mesh_points(mesh_points)
        geom.save()

class GeometryEditor:
    def __init__(self):
        self.undo_stack = []
        self.redo_stack = []

    def execute(self, operation):
        operation.apply()
        self.undo_stack.append(operation)
        self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack:
            return False

        op = self.undo_stack.pop()
        op.undo()
        self.redo_stack.append(op)
        return True

    def redo(self):
        if not self.redo_stack:
            return False

        op = self.redo_stack.pop()
        op.apply()
        self.undo_stack.append(op)
        return True

# Usage
editor = GeometryEditor()

# Add points
add_op = AddMeshPointsOperation("geometry.g01", new_points)
editor.execute(add_op)

# Oops, made a mistake
editor.undo()

# Actually, that was right
editor.redo()
```

**Value:** Medium - Nice-to-have for interactive scripts

---

## Summary

The EditLayers namespace provides RASMapper's complete interactive editing framework:

- **56 editor classes** for all HEC-RAS geometry types
- **Command pattern** with full undo/redo
- **Mesh fixing algorithms** via `MeshPerimeterEditor.TryToFixMeshes()`
- **Suppressor pattern** for efficient batch operations
- **Mouse-driven UI** with context menus and toolbars

**Key Insight for Python Automation:**

RASMapper's mesh fixing logic (`MeshFV2D.TryAutoFix()`) is the holy grail for automation:
1. Analyzes incomplete cells
2. Suggests point additions/deletions
3. Applies fixes via undo-able operations

**Porting this to Python** would enable batch mesh repair without GUI interaction.

**Recommended Approach:**
1. Parse geometry HDF to identify mesh issues
2. Implement simplified version of `TryAutoFix()` in Python
3. Modify plaintext geometry files
4. Use `RasCmdr.compute_plan()` to recompute meshes
5. Validate results in HDF

This combines the best of RASMapper's algorithms with ras-commander's automation capabilities.
