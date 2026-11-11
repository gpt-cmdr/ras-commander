# RasMapperLib terrain modifications: storage, reading and application (6.6 / 7.0 / 7.0.1)

**Date**: 2026-11-11
**Agent**: hecras-code-archaeologist
**Assemblies**: RasMapperLib (plus Utility.Core and H5Assist for 6.6 only, see "Coverage limits")
**Evidence root** (untracked): `workspace/code-archaeology/reconstructed/HEC-RAS-{6.6,7.0,7.0.1}/` (untracked).
Paths below are relative to `...\HEC-RAS-<ver>\RasMapperLib\RasMapperLib\` unless stated. Line numbers are approximate and given for 7.0.1 unless a version is named.
Statements marked **(inferred)** were deduced, not read directly.

## 1. Summary

- Modifications live in the terrain HDF under `/Modifications/<layer name>`. One group per layer. The group attributes `Type`, `Subtype` and `Priority` select the layer class and order. The export applies them only when the terrain's `.rasmap` layer has an `ElevationModificationGroup` child element (any content; measured, section 12). Per-layer XML entries and `Checked` states are ignored.
- The layer class is chosen **only** from the group attribute `Type`: Circle, Rectangle, Triangle, Polygon, Encroachment Polygon, Levee, Levee1, Pier, Tree. Any other value is silently skipped on load, and RAS Mapper deletes such groups the next time it saves the group (`ElevationModificationGroup.cs` ~156-185).
- Ground lines are `Type=Levee` (class GroundLineModificationLayer) with `Subtype` Levee or Channel. Datasets: `Polyline Info/Parts/Points`, `Profile Info` + `Profile Values`, `Attributes`, optional `Control Points` subgroup. A dataset literally named `Profile` is never read.
- The stored ground-line profile is (station along the polyline, absolute elevation) in float32. `Top Elevation` is read from disk but not used by the computation in any of the three versions.
- A non-empty `System Name` routes the feature through a separate "system" (advanced) path, even for a single feature. That path auto-fills and clamps width, reach and slopes and builds the TIN from perpendicular cross-section ribbons. The per-feature path does not validate and does not use Transition Percent at all.
- Priority: lower number wins. Layers are applied in reverse list order, so Priority 0 is applied last. Priority is written only by the group's save routine, as the index of the layer in the group.
- The `.rasmap` Checked state is not consulted by the export/resample path in any version.
- 7.0 vs 7.0.1: after normalising decompiler style differences I found **no semantic difference** in any modification, TIN, profile or terrain-resample class. The "||" mask accumulation and the forced rendering of ground lines at export both appear in 7.0 and 7.0.1 and are absent from 6.6. The 7.0.0 export defect is not located in this code (see section 8).
- 6.6 differs materially from 7.x: polygons do not store a profile at all; ground lines smaller than one cell are skipped at export; the polygon boundary-elevation logic differs.

## 2. Common storage layer (all layer types)

### 2.1 Group layout and group attributes

| Item | Value | Evidence |
|---|---|---|
| Group path | `/Modifications/<LayerName>`; layer name has `/` and `\` replaced by `_` on the way to HDF | `ElevationModificationGroup.cs` ~611 (SanitizeHDFDatasetName); layer `HDFGroup` ~642 |
| `Type` attribute | string; written by each layer's save. Ground line "Levee", advanced ground line "Levee1", polygon "Polygon", circle "Circle" | `GroundLineModificationLayer.cs` ~992; `GroundLineModificationLayer1.cs` ~819; `PolygonElevationModificationLayer.cs` ~442; `EllipseFeatureLayer.cs` ~100 |
| `Subtype` attribute | string, written only by ground-line layers: enum name Levee or Channel (Unknown exists). Read with a case-sensitive enum parse; failure means Unknown | `GroundLineModificationLayer.cs` ~993; `ElevationModificationGroup.cs` ~241-248 |
| `Priority` attribute | int32 **(type inferred from the generic int read)**. Written only by the group save, value = index of the layer among the group's nodes. Missing means int.MaxValue (sorted last). Order is ascending with a stable sort | `ElevationModificationGroup.cs` ~156-185 and ~268-272 |
| Root attribute `Version` | string "1.2" in 6.6, 7.0, 7.0.1 (`LatestVersion` constant). Written by the group save. If absent on read, treated as 1.0 and nothing else keys off it | `TerrainLayer.cs` ~1192, ~1475-1505, ~1507 |
| Root attribute `CanEdit` | bool; if absent the terrain is editable | `TerrainLayer.cs` ~1470, ~1475 |

No other root-level terrain attribute relevant to modifications was found, and none changes between versions.

Loading is lazy and fault-tolerant. Each layer's load routine wraps everything in a catch that swallows errors, so a malformed dataset yields an **empty layer with no message**.

### 2.2 The `Attributes` dataset (managed columns)

All layer types use one compound-type 1-D dataset `<group>/Attributes`, one row per feature (`DatatableLoadManager.cs`, `HDF5MemoryDiskMap.cs` ~163-300, ~435-520).

- Read is by **disk field name**. Fields that are absent are silently left at their default (null). Extra fields are ignored. Order does not matter.
- Disk type per column: float columns are float32; a float NaN on disk becomes "null" in memory; null is written back as NaN. bool columns are 1-byte HBOOL (H5Assist `CompoundTypeDefinition.cs` ~97, 6.6 tree). string columns are fixed-length strings sized to the longest value. int columns int32.
- Enum columns that have a registered serializer are stored as **fixed-length strings**, not integers. In 7.0 and 7.0.1 an enum with no serializer and no integer registration throws (`HDF5MemoryDiskMap.cs` ~277). Elevation Type is registered as a string serializer in all three versions (`ElevationModificationGroup.cs` ~285).
- Elevation Type disk names: `SetValue`, `SetIfHigher`, `SetIfLower`, `Add` (memory enum values 0..3 named SetValue, TakeHigher, TakeLower, AddValue). Source `ElevationModificationType.cs` (identical in all three versions). Deserialisation is exact and case-sensitive. Any unknown, empty or non-string content silently becomes SetValue (`Utility.Core/Utility.Extensions/DiskNameAttribute.cs` in the 6.6 tree; fallback argument is SetValue). So `Add` is valid, and an integer column on disk would silently read as SetValue. The longest disk name is 11 characters.
- The `.rasmap` stores the same enum differently: as the integer enum value (see section 7).

### 2.3 Feature geometry datasets

| Dataset | Layout | Evidence |
|---|---|---|
| `<name> Info` (name = `Polyline` or `Polygon`) | int32 [n,4]: point start index, point count, part start index, part count. Dataset attribute `Feature Type` = "Polyline" or "Polygon" | `HDF5Storage.cs` ~427-440 (BeginPolyBhw), ~351-365 (BeginPolyBhr) |
| `<name> Parts` | int32 [parts,2]: point start, point count. Optional on read (absent means one part per feature) | same |
| `<name> Points` | float64 [points,k], k = 2 (X,Y), 3 (X,Y,Z or X,Y,M) or 4 (X,Y,Z,M). With k = 3 the dataset attribute `Column` must name the third column "Z" or "M" (read directly) | `HDF5Storage.cs` PointBhwZM ~315-345 |

`Feature Type` is read only to decide whether the layer holds polygons. **A polygon dataset written without `Feature Type` = "Polygon" is read as polylines (inferred consequence: the polygon layer gets wrong feature types or fails and is swallowed).** `Polygon` objects always close themselves (first point equals last, appended if missing, `Polygon.cs` ~466), so RAS-authored polygons are closed rings and perimeter stations are measured on the closed ring.

### 2.4 Profile datasets (`Profile Info` and `Profile Values`)

- Dataset names are the group path plus `/Profile Info` and `/Profile Values`. The reader (`HDF5Storage.ReadProfileMetadata`, ~1731) needs **both**; if either is missing it returns zero profiles and every feature gets an empty profile.
- `Profile Info`: int32 [n,2] = (starting row in Values, count). One row per feature in feature order. Count 0 means "no profile". Attributes written: `Column` = (Starting Index, Count), `Row` = "Feature" (not read).
- `Profile Values`: float32 [m,2] = (X, Y). Attribute `Column` = (X, Y). Read as float32.
- X is a station along the feature (see per-type sections) and Y is an elevation. If the number of Info rows differs from the feature count, **all** profiles are discarded for that layer and defaults are recomputed.
- Writers in the library: `HDF5Storage.WritePointCollection` ~1694. Write logic is identical in all three versions (7.0.1 additionally has a `DeleteProfileMetadata` helper that 6.6 lacks; not relevant to layout).

### 2.5 Layer ordering and application (applies to every type)

- `ElevationModificationGroup.ObstructRaster` (~639), `ObstructProfiles` (~669) and `ObstructPoints` (~701) iterate the group's nodes **in reverse**. The first node (Priority 0) is therefore applied last. For SetValue the last application wins, so the lowest Priority number wins. Mixed Elevation Types are order-dependent in the obvious way (SetIfHigher after SetValue can raise the result).
- Per cell, `GetReplacementValue` (~715): if the underlying value is nodata (-9999) the modification value is used whatever the type; if the modification value is nodata nothing changes; otherwise SetValue replaces, Add adds, SetIfHigher and SetIfLower compare. The modification value is the rasterised TIN or ellipse value.
- Nodes are listed from HDF sorted by Priority. Moving a layer in the GUI changes its node index; the new index is written as Priority on the next group save.
- The group's save also removes every `/Modifications/*` subgroup that is not currently a node (unknown Type included).
- Checked state: the group and layer ObstructRaster routines never read `Checked`; `TerrainLayer.ObstructRaster` (~2062) and `ResampleInternal` (~2172, call at ~2257) call the group directly. `Checked` is used only for display (`NodeAndAllParentsChecked`, ~5992). Conclusion: unchecked modification layers are still applied at export (7.0.1; 7.0 and 6.6 are equivalent in this respect).

## 3. Ground lines (Type = Levee)

Class: `GroundLineModificationLayer.cs` (columns ~861-877, load ~880, save ~940). Compare 6.6 at ~832, ~845, ~903.

### 3.1 Attributes dataset columns (identical in all versions)

| Memory name | Disk name / dtype | Notes |
|---|---|---|
| SystemName | `System Name`, string | empty or null means not part of a system (see 3.4) |
| Name | `Name`, string | label only |
| Elevation Type | `Elevation Type`, string | SetValue / SetIfHigher / SetIfLower / Add. Layer default for new layers is SetIfHigher |
| Top Elevation | `Top Elevation`, float32 | **not used**: only the editor touches it; the one reader of it in 6.6 is a never-called legacy method (`ComputeDevTin_OLD`, 6.6 ~2823; still present, still uncalled, in 7.0 ~3030 and 7.0.1 ~3016) |
| Width | `Top Width`, float32 | flat top width in map units |
| LeftSlope | `Left Slope`, float32 | horizontal run per unit of vertical, always entered positive |
| RightSlope | `Right Slope`, float32 | same |
| Max Extent | `Max Reach`, float32 | **total** footprint width (half on each side), not a one-sided reach |
| Transition Fraction | `Transition Percent`, float32 | system path only, see 3.5 |
| Elev Pt Tolerance | `Elev Pt Tolerance`, float32 | search distance for control points; layer default 50 |

In-memory only (not stored): Computed System Name, Profile object, Cached Levee Info.

### 3.2 Datasets read and ignored

| Dataset under the group | 6.6 | 7.0 | 7.0.1 |
|---|---|---|---|
| `Polyline Info/Parts/Points` | read | read | read |
| `Profile Info` + `Profile Values` | read | read (bulk in-memory load) | read (bulk in-memory load) |
| `Attributes` | read | read | read |
| `Control Points/Points` + `Control Points/Attributes` (fields Name, Elevation float32) | read | read | read |
| dataset named exactly `Profile` | ignored | ignored | ignored |
| `Top Elevation` field | read, unused | read, unused | read, unused |

If `Attributes` is missing the load returns early before Subtype resolution. If `Subtype` is missing or unparsable the layer becomes Unknown, and RAS Mapper then **guesses** Levee or Channel from slope signs and Elevation Type (`ResolveUnknownSubtype` ~1042), possibly splitting the layer into two and rewriting slopes. Always write `Subtype`.

### 3.3 Profile semantics (per-feature path, `ComputeLeveeProfile` ~2231)

- X is distance along the polyline in map units from its first vertex, measured on the 2-D polyline (cumulative along segments). Y is **absolute elevation** of the centre line (levee top or channel invert), not an offset from ground. Under Elevation Type Add, the TIN value (this same Y) is added to the terrain, so Y then acts as a height increment.
- If the first station is not 0 the whole profile is shifted so it starts at 0. Stations beyond the polyline length are clamped to the length. Duplicate stations keep the first. A last point at the full length is appended (copying the last Y) if the profile does not end within 0.01 of the length. Segments longer than 100 units (100/3.281 in SI) get extra points by interpolation, in memory only.
- Control points (`Control Points` subgroup) within Elev Pt Tolerance of the line override or add profile points. With no control points and an empty profile, a default profile is built from the terrain at the two end points (`GetDefaultProfile` ~2412). With no control points and a non-empty stored profile (the normal RAS-authored case) the stored profile is used as is.
- 7.x prints a message when a layer has no stored profile ("created with a previous version... Edit and Save"). 6.6 prints a similar message in its ObstructRaster. Both then derive defaults, so a missing profile is tolerated but then follows terrain end elevations.

### 3.4 Per-feature path vs system path

Routing: `IsPartOfASystem` is "name is non-empty" in all three versions (6.6 ~1420, 7.0 ~1499, 7.0.1 ~1485). `ComputeLeveeCache` (~1443) takes the system path whenever the feature's computed system name is non-empty.

System construction (`CreateFIDToSystemName` ~2444): features with a non-empty name and a valid polyline are chained by endpoint proximity. The next member is one whose **last** vertex is within 60 map units of this feature's first vertex (and symmetrically at the other end), has the identical System Name, **identical Elevation Type and identical Elev Pt Tolerance**. Direction matters: a reversed line does not chain. Chains with the same name that are not connected become separate systems with numeric suffixes. A single feature with no partner is simply a system of one. NaN tolerances never compare equal, so use finite values **(inferred from the comparison)**.

| Aspect | Per-feature path (empty System Name) | System path (non-empty System Name, even alone) |
|---|---|---|
| Implementation | `ComputeDevTinMFractionMethod` ~2708 (default mode; `NearestPoP` method ~2561 only reachable from a debug menu) | `EnsureAdvancedGroundLineLayerUpToDate` ~1496, builder in `GroundLineModificationLayer1.cs` 26-180, ribbons in `ComputeRibbonsXSOffsetMFraction` ~1869 |
| Profile | feature's own profile | one profile for the whole system: member profiles concatenated, each member's stations offset by the cumulative length of the previous members |
| Top Width <= 0 | feature skipped (returns no TIN) | width 0 with reach 0 skips; reach 0 is set to width; width greater than reach is clamped to reach |
| Max Reach NaN or <= 0 | `<= 0` skips; **NaN is not guarded** (inferred: degenerate TIN) | replaced by 2 x Top Width (builder `AddNew`) |
| Slope NaN or 0 | NaN becomes 3, 0 becomes 0.001 (`GetUsableLeftSlope` ~3214, `GetUsableRightSlope` ~3245) | NaN filled from the nearest valid control section, default 3; 0 becomes 0.001 (`EnsureValidValues` ~2699) |
| Transition Percent | **not used** | used only between consecutive control sections whose width or reach differ (3.5) |
| Cross-section geometry | offsets of the polyline itself at half-reach and half-width | perpendicular cross-section lines at each control station and a final one at the line end (`TrapezoidalControlCrossSection.cs` ~126-200) |
| Rasterisation | each feature separately | only the system's TIN, once per system (duplicates removed in ObstructRaster) |
| Small features | skipped when Max Reach / cell size <= 1 in 6.6; forced at export in 7.x (3.6) | same gating but uses the retained member's own Max Reach |

Cross-section geometry (both paths, read from `TrapezoidalControlCrossSection.GetProfile`): half-reach minus half-width is the side run; side elevation = centre elevation minus run / slope for a Levee (both sides drop), and plus run / slope for a Channel (both sides rise). Slope signs are applied from the Subtype, so stored slopes are positive for both. If Top Width equals Max Reach the width is reduced by a small amount to keep a sloped edge (system path).

Equivalence for a lone feature with a System Name: elevation along the line is the same, but the footprint can differ at bends (perpendicular sections vs offset polylines), invalid or NaN width/reach/slope inputs are repaired instead of rejected, and Transition Percent has no effect (a single section repeated at the end has identical width and reach). A system of one is **not** treated as a per-feature line, so writer-authored single features with a non-empty System Name should not be used to "disable" the system path; leave `System Name` empty for a plain line.

### 3.5 Transition Percent / Transition Fraction

- Disk NaN reads as null and `GetTransitionPercent` (~3290) returns 0 for null. So NaN and 0 are the same: no transition.
- Value p > 0 is a fraction of the earlier control section's Top Width, expressed as a length: the earlier section's trapezoid is held until station (next section station minus Top Width x p), then blends to the next section (`InjectTransitionStationsIntoProfile` ~1759 and the ribbon loop ~2000 in `GroundLineModificationLayer1.cs`). So 0.5 means a blend zone of half the Top Width, clipped so it never starts before the earlier section. It is only invoked when consecutive sections differ in width or reach; otherwise no effect.
- Unit and exact meaning of "percent" is inferred from the arithmetic, not from UI text (no label text found in the decompiled source).
- The advanced `Levee1` layer stores the same quantity as float32 field `TransitionPercent` in its control-section table.

### 3.6 Export behaviour and version differences

| Behaviour | 6.6 | 7.0 | 7.0.1 |
|---|---|---|---|
| Per-feature gate `Max Reach / cell size <= 1` | always applied (`ShouldRender` ~1635) so small features are skipped, including at export | applied only when not forced | same as 7.0 |
| Forced rendering at export | none (no field exists) | `GenerateNewRasTerrain` sets `ForceRenderRegardlessOfCellSize` on every ground-line layer when vector modifications are resampled (`TerrainLayer.cs` ~5200, ~5367); the tile `Resample` overload forces too (~2221) | same (~5019, ~5181, ~2169); `ElevationModificationGroup.ObstructRaster` ~646 |
| Mask accumulation in the per-cell write | mask = used (overwrites) | mask = previous OR used (`GroundLineModificationLayer.cs` ~126; same in polygon layer ~154) | same as 7.0 |
| System MBR and max reach used for gating | raw member Max Reach values | builder values (NaN becomes 2 x width) | same as 7.0 |
| TIN validity guards (invalid offset polylines return no TIN) | absent | present | present |
| Stored profile load | per-feature lazy | bulk in-memory (`LoadAllProfilesIntoMemory`) | same |

The mask changes do not affect a plain export because the export passes no mask (mask is used by the tiled/vectorised resample). The rendering force flag is the only change in 7.x that alters exported cell values: features narrower than one cell are now burned in at export where 6.6 skipped them.

## 4. Polygons (Type = Polygon)

Class: `PolygonElevationModificationLayer.cs` (columns ~328-340, load ~343, save ~389, `ComputePerimeterProfile` ~553, `ComputePolygonCtrlPts` ~611, `EnsureProfiles` ~1045, `ObstructRaster` ~1000). 6.6: load ~241, save ~276, `ComputePerimeterProfile` ~416.

### 4.1 Datasets and columns

| Item | 6.6 | 7.0 / 7.0.1 |
|---|---|---|
| `Polygon Info/Parts/Points` | read and written | read and written (Feature Type "Polygon" required) |
| `Profile Info` + `Profile Values` | **not read, not written** | read; written on save after `EnsureProfiles` |
| `Attributes` fields | Name (string), Elevation Value (f32), Elevation Type (string), Elev Pt Tolerance (f32), Generate Boundary Elevations (bool), Use ShapeFile Z Elevations (bool) | same, plus in-memory ProfileHash (not stored) |
| Group attributes | Type = "Polygon" only (no Subtype); Priority from group save | same |
| `Control Points` subgroup | read | read |

`Boundary Elevation Method` and a `Subtype` of "Multipoint" do not occur anywhere in the decompiled code of any of the three versions; RAS Mapper neither reads nor writes them. They are harmless extras.

### 4.2 Meaning of the fields at application time

Per polygon the layer builds a perimeter profile (station along the closed ring to elevation), places those elevations on the perimeter vertices, and triangulates (perimeter plus interior control points as mass points) into a TIN that is rasterised. A polygon whose Elevation Value is NaN (or invalid ring) is skipped entirely (`EnsureProfiles` ~1045-1060).

| Setting | 7.0 / 7.0.1 behaviour (`ComputePerimeterProfile` ~553) | 6.6 behaviour (~416) |
|---|---|---|
| Neither flag set, no control points | constant: profile (0, v) to (length, v), v = Elevation Value. **Stored Profile is ignored.** | identical |
| Use ShapeFile Z true, Generate false | profile from each polygon vertex's Z (needs Z in `Polygon Points` with `Column` naming "Z"). Stored profile ignored | vertex Z used (same rule); as in all 6.6 cases nothing is stored |
| Generate true (any Use ShapeFile Z), no perimeter control points | stored profile is used if non-empty; else terrain is sampled along the perimeter (`ComputeProfilesForPerimeteProfileFromAssociatedLayer`). Vertex Z is ignored whenever Generate is true | profile points at vertices from terrain values; plus terrain-sampled stations when Use ShapeFile Z is false. Both flags true means terrain at vertices, not vertex Z |
| Control points within tolerance of the perimeter | picked up only when Generate true **and** Use ShapeFile Z false; stored profile ignored for those stations | same rule |
| Control points inside the polygon | become interior mass points in all cases | same |
| Elevation Value | the constant when no profile points exist; also gate for NaN skip | same |

Therefore for a **constant** polygon only Elevation Value, Elevation Type, the ring geometry and Type matter. For a **varying boundary** the writer must either (a) put Z on the polygon vertices with Use ShapeFile Z = true and Generate = false (works in all three versions), or (b) set Generate = true with a stored Profile (works in 7.x; in 6.6 the stored profile does not exist and terrain is sampled instead, so a varying boundary cannot be reproduced faithfully there).

Stored polygon profile: X is distance along the closed ring from its first vertex, Y absolute elevation; the in-memory profile is filtered at 0.01 ft before use (`ComputeDevTin` ~873). The stored profile is not re-read when neither flag is set, so a constant polygon's `Profile Info` rows may be empty (count 0).

Elev Pt Tolerance is used only to gather control points (RAS-authored layers carry a finite value; the ground-line layer default is 50). A NaN tolerance gives an empty/odd search extent **(inferred)**.

## 5. Ellipses and circles (Type = Circle)

Classes: `EllipseFeatureLayer.cs` (~60-120), `EllipseElevationModificationLayer.cs` (HDF group override and ObstructRaster ~106), `HDF5Storage.cs` ReadEllipseFeatures ~656 and WriteEllipseFeatures ~699, `Ellipse.cs` ~308. Identical in all three versions except the mask OR (7.x) and decompiler style.

| Item | Value |
|---|---|
| Group | `/Modifications/<name>`; attributes `Type` = "Circle", `Priority`. **No Subtype** |
| `Circles` dataset | float64 [n,5] at `/Modifications/<name>/Circles`. Columns: centre X, centre Y, RadiusX, RadiusY, AngleRotation. Dataset attribute `Column Ordering` = "X, Y, RadiusX, RadiusY, AngleRotation" (informational). float32 is also accepted on read. A column count other than 5 raises and is swallowed (empty layer) |
| Rotation units | **degrees** (contains test multiplies by pi/180). Sense: a positive angle rotates the RadiusX axis clockwise in map axes (x east, y north), derived from the containment arithmetic **(inferred sign)** |
| Circle vs ellipse | RadiusX equals RadiusY is treated as a circle and the angle is ignored |
| `Attributes` | Name (string), Elevation Value (f32), Elevation Type (string) |
| Application | each feature: skipped if Elevation Value is NaN; otherwise every raster cell whose centre is inside the ellipse takes `GetReplacementValue(old, type, Elevation Value)`. Flat value, no TIN, no profile, no control points |
| No separate "Profile" | none |

No difference between 6.6, 7.0 and 7.0.1 in layout. In 7.x the mask is OR-ed.

## 6. Advanced ground line (Type = Levee1)

Class `GroundLineModificationLayer1.cs`. Same `Polyline`, `Profile Info/Values`, `Attributes` datasets as ground lines, plus `Control Cross Sections` (compound table: station, elevation, cross-section type, then Width, LeftSideSlope, RightSideSlope, MaxReach, TransitionPercent as float32) and `Control Points`. Attribute table fields are only System/feature name, Elevation Type and Elev Pt Tolerance (`GroundLineModificationLayer1.cs` ~668-680, ~746-824). `Type` = "Levee1". On save it rewrites its own `.rasmap` Type to "GroundLineModificationLayer" when it can be saved as a simple layer (~907-921), so third-party tools can meet either name. It is also the in-memory "system layer" owned by each ground-line layer. Layout appears the same in the three versions (only 7.0.1 was read closely for this class). Note its XML reads `DefaultElevPtTol` as an integer, while the plain ground-line layer reads it as a float.

## 7. `.rasmap` XML

> **Correction (section 12):** the export requires the terrain layer's `ElevationModificationGroup` element. The code reading below, which treats the `.rasmap` as optional for application, is superseded on that point; per-layer entries and `Checked` states remain optional.

Generic layer XML (`Layer.cs` ~1543-1650):

- Element `Layer`. Attributes in order: `Name` (omitted when equal to the class name), `Type` (CLR class name), `Checked="True"` only if checked, `Expanded="True"` only if expanded, and for non-geometry layers `Filename` (relative to the `.rasmap`). Children: optional `Symbology`, `PlotOption`, `PlotOptionOff`, and nested `Layer` elements.
- Load: `Checked` is **false when the attribute is absent** (`XML.BooleanAttribute`). Name and Type are read; Type from XML is used only by the loader that creates the object.

Terrain/modifications structure (`TerrainLayer.cs` ~1539-1578, `ElevationModificationGroup.cs` ~131-155):

| Element | Required for export? | Notes |
|---|---|---|
| Terrain `Layer` Type `TerrainLayer`, with `Filename` pointing at the terrain HDF | yes, to locate the HDF | normal terrain layer |
| Child `Layer` with first attribute `Name="Modifications"` and `Type="ElevationModificationGroup"` | **no** | if no child has first attribute value "Modifications" the group node is removed from the **tree**, but the group object and its loaded modifications still exist (`LoadModificationsFromHDF5` is called from the terrain constructor, ~1456) and are applied by ObstructRaster. First attribute must be `Name` for the tree node to be kept |
| Child `Layer` per modification, `Name` equal to the HDF group name, `Type` = class name (GroundLineModificationLayer, PolygonElevationModificationLayer, EllipseElevationModificationLayer) | **no** | `XMLLoadChildren` matches by name to layers that already exist from HDF; elements for names not in HDF are ignored; layers not in the XML keep Checked = false (display only) |
| Ground-line layers: child `DefaultModificationType` with attribute `Value` = integer enum value (0 SetValue, 1 SetIfHigher, 2 SetIfLower, 3 Add) and child `DefaultElevPtTol` with attribute `Value` (default 50) | no | defaults for new features drawn in the GUI only (`GroundLineModificationLayer.cs` ~1016-1040) |
| Nested `Layer` named "Control Points" under ground-line/polygon layers | no | restores control-point layer display state by name |
| Polygon and circle layers | none beyond the generic attributes | no layer-specific XML |

Present in all three versions with the same structure.

## 8. Cross-version summary and the 7.0 to 7.0.1 question

| Topic | 6.6 | 7.0 | 7.0.1 |
|---|---|---|---|
| Terrain HDF Version attribute | "1.2" | "1.2" | "1.2" |
| Group layer type strings | same nine | same | same |
| Ground-line HDF layout | as above | same | same |
| Polygon stored profile | none | yes | yes |
| Polygon boundary logic | terrain-sampled vertices | stored profile or terrain-sampled; vertex Z only if Generate false | same as 7.0 |
| Ground lines below one cell wide at export | skipped | burned in (forced) | burned in (forced) |
| Per-cell mask accumulation | overwrite | OR | OR |
| Enum disk serialisation | string via registered serializer | string (plus new integer-serialiser option, unused here) | same |

**7.0.0 export defect**: I diffed 7.0 against 7.0.1 for GroundLineModificationLayer (both classes), PolygonElevationModificationLayer, EllipseElevationModificationLayer, ElevationModificationGroup, ElevationControlPointLayer, TerrainLayer, HDF5MemoryDiskMap, DatatableLoadManager, Tin, DevelopmentTin, RibbonTINFactory, DelaunayTINFactory, Profile, SavedProfileInfo, InMemoryProfileInfo, TrapezoidalControlCrossSection, Polyline and Polygon. After normalising variable names, using-statement style, cast noise and namespace qualification, the remaining differences are logging, progress reporting, a dropped chunk-size argument to a parallel helper, and null-check phrasing. **I found no behavioural change.** The "||" mask line is not a 7.0 to 7.0.1 change: it is a 6.6 to 7.0 change that persists in 7.0.1. A defect, if it exists in the 7.0.0 build, must come from a layer this tree does not contain for 7.0 (see below) or from the executable that drives the export (RasProcess), not from these classes. Do not attribute it to the modification code on this evidence.

## 9. Coverage limits

- The 7.0 reconstruction contains only RasMapperLib, H5Assist, HecCs, RAS, RASViewModel and RasProcess. It has no Geospatial.*, Utility.Core or TiffAssist, so TIFF writing, raster tile writing and utility math cannot be compared for 7.0 (the visible constructor differences for the TIFF writer in 7.0 versus 7.0.1 reflect that missing context, not a verified difference). The 7.0.1 tree has Geospatial.Core, Geospatial.IO and TiffAssist; 6.6 has Geospatial.*, Utility.Core and H5Assist.
- I did not decompile or read `RasProcess` export orchestration in this pass.
- `DataTableExtensions` and `DiskNameAttribute` were read from the 6.6 tree; assumed unchanged in 7.x **(inferred)**.
- HDF type codes beyond .NET types (e.g. exact HDF5 class of bool) were read only from the 6.6 H5Assist; no check of byte order or compound alignment.

## 10. Implications for a third-party writer

### 10.1 Fields to write, to be treated like a RAS-authored feature

All layers:

- Group `/Modifications/<name>` with `<name>` free of `/` and `\`. Write `Type` as a string. Write `Priority` as int32 equal to the intended node index (0 = top, wins). Write a root `Version` = "1.2" (string) if creating a new terrain HDF; do not touch `CanEdit` unless needed.
- `Attributes` as one compound dataset, row per feature, with the exact field names above. Floats float32 (NaN = null). Strings fixed-length large enough. Elevation Type string exactly one of `SetValue`, `SetIfHigher`, `SetIfLower`, `Add`; never an integer; Add is valid.
- Never leave stray datasets expecting RAS to keep them: RAS rewrites the whole layer group (and deletes unknown-Type groups) on save.

Ground line (plain, no system):

- `Type` = "Levee", `Subtype` = "Levee" or "Channel" (case-sensitive enum names).
- `Polyline Info` int32 [n,4] with `Feature Type` attribute "Polyline"; `Polyline Points` float64 [p,2] X,Y (with Z or M only with a `Column` attribute); `Polyline Parts` int32 [parts,2] (optional but write it).
- `Profile Info` int32 [n,2] and `Profile Values` float32 [m,2]; X = cumulative planar distance along the polyline starting at 0, never beyond the length; Y = absolute elevation. Put the last station at the line length. Do not rely on a `Profile` dataset.
- Attributes: `System Name` empty; `Top Width` > 0; `Max Reach` > 0 and at least Top Width (total width); `Left Slope` and `Right Slope` finite, positive (0 is treated as 0.001, NaN as 3); `Elev Pt Tolerance` finite (use 50); `Elevation Type` consistent with intent (SetIfHigher for Levee, SetIfLower for Channel are RAS defaults); `Transition Percent` NaN or 0; `Top Elevation` any value (unused; NaN is fine).
- Omitting `Control Points` is valid.

Ground line with system semantics: set `System Name` non-empty and identical across members, identical Elevation Type and Elev Pt Tolerance across members, members digitised head-to-tail within 60 map units. Then Max Reach and slopes may be NaN (repaired) but do not depend on that. Set `Transition Percent` between 0 and 1 only when widths differ between consecutive members.

Polygon (constant): `Type` = "Polygon"; `Polygon Info` with `Feature Type` = "Polygon", closed ring; attributes Elevation Value, Elevation Type, Elev Pt Tolerance (finite), Generate Boundary Elevations = false, Use ShapeFile Z Elevations = false. `Profile Info/Values` may be empty or omitted (in 7.x omission is fine when neither flag is set; if both exist the counts must match the polygon count). Do not write `Subtype` or `Boundary Elevation Method` (ignored).

Polygon (varying boundary): preferred portable form is vertex Z in `Polygon Points` (3 columns with `Column` = X, Y, Z), Use ShapeFile Z = true, Generate = false. Stored-profile form (Generate = true, valid `Profile Info/Values` with ring stations and absolute elevations) is read faithfully only in 7.0 and 7.0.1.

Circle/ellipse: `Type` = "Circle" (no Subtype); `Circles` float64 [n,5] with degrees rotation; attributes Name, Elevation Value, Elevation Type.

`.rasmap`: the terrain layer needs an `ElevationModificationGroup` child element, or the export applies none of the HDF modifications (measured, section 12). Its per-layer children and `Checked` states are not required. For the GUI tree to show the group, a `Layer` child of the terrain with first attribute `Name="Modifications"` and `Type="ElevationModificationGroup"`, and one child per layer whose `Name` equals the HDF group name and `Type` is its class name; add `Checked="True"`. Ground-line layers may add `DefaultModificationType` (integer enum value) and `DefaultElevPtTol`.

### 10.2 Forms that cannot be reproduced faithfully

- Polygon varying boundaries from a stored profile in 6.6 (no profile storage; terrain is sampled instead). Constant polygons and ShapeFile-Z polygons are portable across all three.
- Single ground-line features that rely on the per-feature path's lack of validation, or on Transition Percent: the per-feature path ignores Transition Percent, and the system path ignores nothing else; switching System Name on or off changes footprints at bends and how bad inputs are repaired.
- Features narrower than one cell: 6.6 skips them at export, 7.0 and 7.0.1 burn them in. A file cannot be made to behave identically across versions; pick the version being targeted.
- Unknown or mistyped `Type`/`Subtype`: dropped, deleted on the next RAS save, or auto-reclassified by slope-sign heuristics.
- Exactly reproducing RAS's own cached profile values (densification, control-point merging, default-from-terrain endpoints) is not possible; the stored profile is an input, and RAS recomputes the dense profile in memory.
- `Priority` ties or missing `Priority` (treated as last, ordering among missing then follows HDF group enumeration order, which I did not verify).

## 11. Evidence index (all under the untracked `workspace/code-archaeology/reconstructed/`)

- `HEC-RAS-7.0.1\RasMapperLib\RasMapperLib\GroundLineModificationLayer.cs`, `GroundLineModificationLayer1.cs`, `PolygonElevationModificationLayer.cs`, `EllipseElevationModificationLayer.cs`, `EllipseFeatureLayer.cs`, `Ellipse.cs`, `ElevationModificationGroup.cs`, `ElevationModificationType.cs`, `ElevationControlPointLayer.cs`, `TrapezoidalControlCrossSection.cs`, `TerrainLayer.cs`, `Layer.cs`, `HDF5Storage.cs`, `HDF5MemoryDiskMap.cs`, `DatatableLoadManager.cs`, `Polygon.cs`, `RasMapperLib.EditLayers\GroundLineFeatureEditor.cs` (defaults: width 20, slopes 2, reach 100).
- Same file names under `HEC-RAS-7.0` and `HEC-RAS-6.6` for the version comparisons; `HEC-RAS-6.6\Utility.Core\Utility.Extensions\DiskNameAttribute.cs`; `HEC-RAS-6.6\RasMapperLib\RasMapperLib\DataTableExtensions.cs`; `HEC-RAS-6.6\H5Assist\H5Assist.Identifiers\CompoundTypeDefinition.cs`.
- Orientation only: `ras_commander/terrain/RasTerrainModWriter.py` (before the 2026-11-11 fixes) currently writes polygon `Subtype` "Multipoint", a `Boundary Elevation Method` attribute, a dataset named `Profile`, and a `Type` attribute on control-point groups; none of these is read by RAS Mapper in 6.6, 7.0 or 7.0.1 (the `Profile` dataset and the others are ignored, not harmful, but they are not what RAS writes).

---
*Generated by hecras-code-archaeologist. Prose only; no decompiled source reproduced.*

## 12. Empirical checks against HEC-RAS exports (added 2026-11-11)

Measured with `RasTerrain.export_rasmapper_terrain(downsample_factor=1)` on HEC-RAS 6.6 and 7.0.1 (this host has no 7.0.2), using single-source synthetic terrains clipped from the public Bald Eagle Creek example, plus two RAS-Mapper-authored terrains from a HEC-RAS 6.6 project kept outside the repository. Results were identical on both versions unless stated otherwise. Details are in `2026-11-11-terrain-modification-roundtrip-validation.md`.

- **Correction to sections 2.5, 7 and 10.1: the `.rasmap` is not optional.** The export applies a terrain's HDF modifications only when the terrain's `.rasmap` layer has an `ElevationModificationGroup` child element. With no such element, nothing is applied (0 of 12,507 px). With an empty group element, a group listing one of six layers, or a group whose layers are all unchecked, all six layers are applied (12,507 px each time). The code reading in section 7 inferred the opposite. Per-layer XML elements and `Checked` states are indeed ignored.
- Confirmed: a non-empty `System Name` changes a lone feature's pixels (sections 3.4 and 3.6). The differences cluster at interior bends.
- Confirmed: `Transition Percent` 0.5 versus NaN gives 0 px difference for an unnamed line (section 3.5).
- Confirmed: a ground line stored as `Type=Channel` is ignored (0 px) by both 6.6 and 7.0.1 (section 2.1).
- Confirmed: the stored profile is absolute elevation (section 3.3). A profile of -10 cut the terrain to -10 ft.
- Confirmed (section 3.6): with 36.5 ft cells and `Max Reach` 20 ft, 6.6 skips the levee (0 px) while 7.0.1 burns it in (171 px).
- RAS Mapper 6.6 GUI-authored ground lines store an empty `System Name`, NaN `Transition Percent`, and `Top Elevation` 0. Layers created through RasMapperLib 6.6/7.0.1 classes store NaN for `Top Elevation`. A polygon created through RasMapperLib defaults to `Generate Boundary Elevations` = true.
