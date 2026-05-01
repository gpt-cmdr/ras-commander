# Working with eBFE Models

## The Problem: eBFE Models Are Broken

FEMA's Estimated Base Flood Elevation (eBFE) database provides valuable Base Level Engineering (BLE) HEC-RAS models for 400+ study areas nationwide. However, **these models are delivered in a format that makes them completely unusable without extensive manual fixes**.

### What's Wrong with eBFE Models

**eBFE models are intentionally separated into folders that prevent them from running:**

1. **Output/ Folder Separation**
   - Pre-run HDF result files (often 40+ GB) stored separately from project
   - HEC-RAS can't find results → Can't view expected runtime
   - **Manual fix required**: Move gigabytes of HDF files into project folder

2. **Terrain/ Misplacement**
   - Terrain data (often 15+ GB) placed outside project folder
   - .rasmap files reference `Terrain\RAS_Terrain\Terrain.hdf` (doesn't exist)
   - Actual terrain location: `Terrain\Terrain.hdf` (different path)
   - **Manual fix required**: Move terrain folders + edit .rasmap XML manually

3. **Absolute and Incorrect DSS Paths**
   - DSS references use paths from original FEMA system: `C:\eBFE\Projects\...`
   - Also wrong relative paths: `.\DSS_Input\file.dss` (subdirectory doesn't exist)
   - HEC-RAS shows GUI popup: **"DSS path needs correction"**
   - **Manual fix required**: Click through 30+ GUI dialogs or edit .u## files manually

### User Experience Without This Library

```
1. Download eBFE model (hours for large models)
2. Extract nested archives (complex structure)
3. Open in HEC-RAS → ERROR: "Terrain not found"
4. Manually move Terrain/ folder (15+ GB)
5. Open again → ERROR: "DSS path needs correction"
6. Click through GUI dialogs fixing 30+ DSS paths
7. Try to view results → ERROR: Can't find HDF files
8. Manually move Output/ folder (40+ GB)
9. Open again → ERROR: More path corrections needed
10. Edit .rasmap XML manually to fix terrain references
11. Finally works (30-120 minutes later)
```

**Automation**: Impossible - GUI error popups block automated workflows

## The Solution: RasEbfeModels

The `RasEbfeModels` class solves this problem by applying delivery-format
normalization that transforms broken eBFE archives into runnable HEC-RAS models.

### Quick Start

```python
from ras_commander.sources import RasEbfeModels
from ras_commander import init_ras_project
from pathlib import Path

# Download/cache, extract, and organize by model slug
organized = RasEbfeModels.organize_model(
    "upper-guadalupe",
    download_root=Path(r"H:/Testing/eBFE Model Organization/Downloads"),
    output_root=Path(r"H:/Testing/eBFE Model Organization/Organized"),
    validate_dss=True
)

# Use immediately - no manual fixes needed
init_ras_project(organized / "RAS Model/UPGU1", "6.5")

# Opens without errors
# No "DSS path needs correction" dialog
# Terrain and land cover load from local folders
# Pre-run results are accessible from project folders
# Ready for automation and preprocessor validation
```

**Time**: 15 minutes vs 60-120 minutes manual fixes

To inspect the built-in model catalog:

```python
from ras_commander.sources import RasEbfeModels

RasEbfeModels.available_models()
```

!!! note "Current import paths"
    Use `from ras_commander.sources import RasEbfeModels` for model-source
    organizers. The `ras_commander.sources` package intentionally exports model
    sources only. Coastal forecast helpers now live under
    `ras_commander.boundaries.CoastalBoundary`; the old
    `ras_commander.sources.federal.CoastalBoundary` path remains a deprecated
    compatibility shim for notebooks that have not been cleaned up yet.

Current built-in organizers include:

| Slug | HUC8 | Delivery Notes |
|---|---:|---|
| `spring-creek` | 12040102 | Single 2D model with nested final archive. |
| `north-galveston-bay` | 12040203 | Compound HMS plus nested 2D RAS delivery. |
| `upper-guadalupe` | 12100201 | Four cascaded 2D watershed models. |
| `eleven-point` | 11010011 | Small split-delivery 2D model archive; organized, path-audited, results-ready, and geometry-preprocessor validated with HEC-RAS 6.6. |
| `spring-river` | 11010010 | Distinct Spring HUC model archive using `SpringRiver_11010010` naming to avoid confusion with `spring-creek` / `SpringCreek_12040102`. |
| `lower-colorado-cummins` | 12090301 | 1D steady BLE reach-model collection. |
| `rio-hondo` | 13060008 | 1D steady BLE reach-model collection. |
| `amite` | 08070202 | Louisiana component delivery with terrain rebuild handling for CRS mismatches. |
| `tickfaw` | 08070203 | Large Louisiana 2D model archive. |
| `lake-maurepas` | 08070204 | Louisiana 2D model archive. |
| `lower-brazos` | 12070104 | Very large component delivery; manifest-only by default. |

## Delivery Validation Gate

An organized eBFE model is not considered fully delivery-ready until it passes
preprocessor validation. File organization and dataframe path checks confirm
that the project is self-contained, but the key proof is running the geometry
preprocessor and reviewing compute messages for missing terrain, land cover,
projection, DSS, or file path errors.

Use the reusable checklist in
[`eBFE Delivery Validation`](user-guide/ebfe-delivery-validation.md) for the
standard readiness gates:

1. `organized`
2. `hms_validated`
3. `path_validated`
4. `preprocessor_validated`
5. `results_validated`
6. `notebook_validated`

For combined hms-commander plus ras-commander examples, `hms_validated` means
that delivered HEC-HMS projects are copied under `HMS Model/` and their HMS
file references resolve locally, then hms-commander can load the organized
project without path repair. RAS-only deliveries should keep a
`HMS Model/README.md` explaining whether hydrology is supplied by steady flow
files, DSS inputs, gridded precipitation, or another documented source.

Use `GeomPreprocessor.run_geometry_preprocessor()` as the assembly validation
hook for both 1D steady and 2D/unsteady models. It enables detailed logging,
runs the HEC-RAS geometry preprocessor through ras-commander, and reviews
compute messages without requiring full unsteady calculations or floodplain
mapping/post-processing as the delivery-format gate. For 1D steady BLE reach
models, document terrain or land cover checks only when mapper layers exist.

For repeatable end-to-end checks from the repository, use:

```powershell
.\.venv\Scripts\python scripts\ebfe_end_to_end_validation.py `
  --models north-galveston-bay `
  --download-root "H:\Testing\eBFE Model Organization\Downloads" `
  --output-root "H:\Testing\eBFE Model Organization\Organized" `
  --report-root "H:\Testing\eBFE Model Organization\Validation\ebfe_delivery" `
  --run-preprocessor `
  --max-wait 7200
```

The script uses `RasEbfeModels.organize_model()` for download/extraction and
organization, then uses `GeomPreprocessor.run_geometry_preprocessor()` through
the reusable batch validation flow.

## Core Delivery Fixes

Early eBFE organizers focused on three recurring breakages: separated outputs,
terrain paths, and DSS paths. The current delivery format also standardizes
projection and land-cover assets because those are required for reliable
geometry-preprocessor validation.

### Fix #0: Shared HDF Asset Reference Normalization

Compiled geometry and plan/result HDFs can carry `/Geometry` attributes that
point at terrain, land-cover, and infiltration sidecars. Recent organizer work
standardizes those references across the normalized `Terrain/`, `Land Cover/`,
and legacy `Land Classification/` folders.

- If a delivered model already points at a legacy
  `.\Land Classification\...` sidecar, ras-commander preserves that HDF
  attribute and copies the required sidecars into the legacy folder instead of
  forcing a rename.
- If the organized project needs normalized terrain or land-cover references,
  the organizer rewrites those HDF attributes to the local asset that actually
  exists in the standardized project tree.

This keeps geometry-HDF association checks aligned with the organized delivery
format while still supporting legacy eBFE asset layouts that appear in the
wild.

### Fix #1: Output/ Folder Integration

**Problem**: Pre-run HDF result files separated from project folder

**eBFE delivers**:
```
UPGU1/
├── Input/ (project folder)
│   └── UPGU1.prj ✗ Can't find results
└── Output/
    └── UPGU1.p01.hdf (1.1 GB) ✗ Inaccessible
```

**RasEbfeModels fixes**:
```
RAS Model/UPGU1/
├── UPGU1.prj ✓ Finds results
└── UPGU1.p01.hdf ✓ Accessible
```

**Implementation**:
```python
# Move all Output/*.hdf files INTO Input/ folder
output_source = model_source / "Output"
if output_source.exists():
    for output_file in output_source.rglob('*'):
        if output_file.is_file():
            shutil.copy2(output_file, input_dest / output_file.name)
```

**Result**: Can view expected runtime from pre-computed results

### Fix #2: Terrain/ Integration

**Problem**: Terrain folder placed outside project, .rasmap references break

**eBFE delivers**:
```
UPGU1/
├── Input/
│   └── UPGU1.rasmap ✗ References "..\Terrain\RAS_Terrain\Terrain.hdf"
└── Terrain/
    └── Terrain.hdf (3.98 GB) ✗ At "..\Terrain\Terrain.hdf"
```

**RasEbfeModels fixes**:
```
RAS Model/UPGU1/
├── UPGU1.rasmap ✓ References ".\Terrain\Terrain.hdf"
└── Terrain/
    └── Terrain.hdf ✓ Exactly where .rasmap expects
```

**Implementation**:
```python
# Move Terrain/ INTO Input/ folder
terrain_source = model_source / "Terrain"
if terrain_source.exists():
    shutil.copytree(terrain_source, input_dest / "Terrain", dirs_exist_ok=True)

# Correct .rasmap terrain path to actual location
actual_terrain_hdf = list(project_folder.glob('Terrain/**/*.hdf'))[0]
rel_path = actual_terrain_hdf.relative_to(project_folder)
# Update <Layer Type="TerrainLayer" Filename="...">
```

**Result**: Model runs without terrain errors, RAS Mapper loads terrain

### Fix #3: ALL Paths to Relative References

**Problem**: Absolute and incorrect paths cause GUI error popups

**eBFE delivers** (in UPGU1.u01):
```
DSS Filename=.\DSS_Input\UPGU_precip.dss  ✗ Wrong subdirectory
```

**Also** (in other files):
```
DSS File=C:\eBFE\Projects\12100201\UPGU1\Input\UPGU1.dss  ✗ Absolute path
```

**RasEbfeModels fixes**:
```
DSS Filename=UPGU_precip.dss  ✓ Relative, verified exists
```

**Implementation**:
```python
# Find where DSS files ACTUALLY exist
dss_files = list(ras_model_folder.glob('**/*.dss'))
dss_lookup = {dss.name: dss for dss in dss_files}

# For each HEC-RAS file (.u##, .prj, .p##)
for hecras_file in hecras_files:
    # Find "DSS File=" or "DSS Filename=" references
    for match in dss_pattern.finditer(content):
        old_path = match.group(1).strip()
        dss_filename = Path(old_path).name

        # Check if DSS file exists in organized structure
        if dss_filename in dss_lookup and dss_lookup[dss_filename].exists():
            # Calculate correct relative path
            rel_path = dss_lookup[dss_filename].relative_to(hecras_file.parent)
            # Replace with verified path
            content = content.replace(f"DSS File={old_path}", f"DSS File={rel_path}")
```

**Result**: No GUI error popups, automation works

## Available Models

### Spring Creek (12040102) - Pattern 3a

**Model Type**: Single 2D unsteady flow model
**Size**: 9.7 GB
**Plans**: 8 with pre-computed results
**Terrain**: 504.6 MB self-contained

**Usage**:
```python
from ras_commander.sources import RasEbfeModels
from ras_commander import init_ras_project

organized = RasEbfeModels.organize_spring_creek(
    downloaded_folder,
    validate_dss=True
)

init_ras_project(organized / "RAS Model", "5.0.7")
```

**Fixes Applied**:
- DSS path corrections
- .rasmap terrain path corrections
- Output/ integration (if present)

**Example Notebook**: `examples/950_ebfe_spring_creek.ipynb`

### North Galveston Bay (12040203) - Pattern 4

**Model Type**: Compound HMS + RAS (coastal flood analysis)
**Size**: 8.2 GB
**HMS**: 7 storm frequencies (10yr-500yr) + sensitivity
**RAS**: 2D coastal model (nested 6.1 GB zip)

**Usage**:
```python
from ras_commander.sources import RasEbfeModels

organized = RasEbfeModels.organize_north_galveston_bay(
    downloaded_folder,
    extract_ras_nested=True,
    validate_dss=True
)

# HMS and normalized RAS model folders are ready
hms_project = organized / "HMS Model/NorthGalvestonBay/NorthGalvestonBay.hms"
ras_project = organized / "RAS Model"
```

**Fixes Applied**:
- HMS/RAS separation
- DSS path corrections (when RAS extracted)
- Output/, Terrain/, Land Cover/, and Projection/ integration

**Note**: `extract_ras_nested=True` extracts and normalizes the nested
RAS_Submittal archive in place.

**Example Notebook**: `examples/951_ebfe_north_galveston_bay.ipynb`

### Upper Guadalupe (12100201) - Pattern 3b

**Model Type**: 4 cascaded 2D watershed models
**Size**: 55 GB
**Models**: UPGU1 → UPGU2 → UPGU3 → UPGU4 (hydraulic cascade)
**Plans**: 28 total (7 AEP frequencies × 4 models)
**DSS**: 10,248 pathnames validated

**Usage**:
```python
from ras_commander.sources import RasEbfeModels
from ras_commander import init_ras_project, RasCmdr, RasPrj

# Organize (applies delivery normalization across all 4 models)
organized = RasEbfeModels.organize_upper_guadalupe(
    downloaded_folder,
    validate_dss=True  # Validates 10,248 pathnames
)

# Execute cascade (upstream to downstream)
for model in ['UPGU1', 'UPGU2', 'UPGU3', 'UPGU4']:
    ras_obj = RasPrj()
    init_ras_project(organized / "RAS Model" / model, "6.5", ras_object=ras_obj)
    RasCmdr.compute_plan("01", ras_object=ras_obj, num_cores=4)
```

**Fixes Applied**:
- 56 HDF files (~41 GB) moved into project folders
- 4 Terrain folders (~15.7 GB) moved into project folders
- DSS assets copied into per-project `DSS Inputs/` folders and references rewritten
- Land cover copied into per-project `Land Cover/` folders
- Projection copied or generated under per-project `Projection/` folders
- `.rasmap` terrain, land cover, and projection paths rewritten to local folders

**Validated**: UPGU1, UPGU2, and UPGU3 passed geometry-preprocessor validation
with a 1-hour timeout. UPGU4 produced preprocessor artifacts but exceeded the
1-hour cap and remains an explicit long-runtime validation item.

**Example Notebook**: `examples/952_ebfe_upper_guadalupe_cascade.ipynb`

## API Reference

### RasEbfeModels.organize_spring_creek()

```python
@staticmethod
@log_call
def organize_spring_creek(
    downloaded_folder: Path,
    output_folder: Optional[Path] = None,
    validate_dss: bool = True
) -> Path
```

**Organizes**: Spring Creek (12040102) - Pattern 3a

**Parameters**:
- `downloaded_folder`: Path to extracted 12040102_Spring_Models folder
- `output_folder`: Output location (default: ./ebfe_organized/SpringCreek_12040102/)
- `validate_dss`: Run DSS validation checks (default: True)

**Returns**: Path to organized model with runnable HEC-RAS project

**Fixes Applied**:
1. Extracts nested _Final.zip (9.67 GB)
2. Organizes into 4 folders (HMS/RAS/Spatial/Documentation)
3. Corrects DSS paths to relative references
4. Corrects .rasmap terrain paths
5. Validates DSS pathnames
6. Creates agent/model_log.md

**Output Structure**:
```
SpringCreek_12040102/
├── RAS Model/           # Runnable HEC-RAS project
├── Spatial Data/        # Shapefiles, terrain copy
├── Documentation/       # Inventory, reports
├── HMS Model/           # (empty for Pattern 3a)
└── agent/model_log.md   # Documents fixes applied
```

### RasEbfeModels.organize_north_galveston_bay()

```python
@staticmethod
@log_call
def organize_north_galveston_bay(
    downloaded_folder: Path,
    output_folder: Optional[Path] = None,
    extract_ras_nested: bool = False,
    validate_dss: bool = True
) -> Path
```

**Organizes**: North Galveston Bay (12040203) - Pattern 4

**Parameters**:
- `downloaded_folder`: Path to extracted 12040203_NorthGalvestonBay_Models folder
- `output_folder`: Output location (default: ./ebfe_organized/NorthGalvestonBay_12040203/)
- `extract_ras_nested`: Extract and normalize RAS_Submittal.zip when True.
  `RasEbfeModels.organize_model("north-galveston-bay")` enables this by default.
- `validate_dss`: Run DSS validation checks (default: True)

**Returns**: Path to organized model

**Fixes Applied**:
1. Separates HMS from RAS content
2. Organizes 7 storm frequencies + sensitivity analysis
3. Handles nested 6.1 GB RAS zip extraction
4. Corrects DSS paths when RAS extracted
5. Moves Output/, Terrain/, Land Cover/, and Projection/ assets into the project
6. Creates agent/model_log.md

**Output Structure**:
```
NorthGalvestonBay_12040203/
├── HMS Model/           # HEC-HMS with 7 storm frequencies
├── RAS Model/           # 2D coastal model (after extraction)
├── Spatial Data/        # (pending RAS extraction)
├── Documentation/       # BLE reports, metadata
└── agent/model_log.md
```

### RasEbfeModels.organize_upper_guadalupe()

```python
@staticmethod
@log_call
def organize_upper_guadalupe(
    downloaded_folder: Path,
    output_folder: Optional[Path] = None,
    validate_dss: bool = True
) -> Path
```

**Organizes**: Upper Guadalupe (12100201) - Pattern 3b

**Parameters**:
- `downloaded_folder`: Path to extracted 12100201_UpperGuadalupe_Models folder
- `output_folder`: Output location (default: ./ebfe_organized/UpperGuadalupe_12100201/)
- `validate_dss`: Run DSS validation (default: True, validates 10,248 pathnames)

**Returns**: Path to organized model with 4 runnable cascaded HEC-RAS projects

**Fixes Applied** (x 4 models):
1. Moves 56 HDF files (~41 GB) INTO project folders
2. Moves 4 Terrain folders (~15.7 GB) INTO project folders
3. Copies DSS assets into per-project `DSS Inputs/` folders and rewrites references
4. Copies land-cover assets into per-project `Land Cover/` folders
5. Copies or creates project CRS files under per-project `Projection/` folders
6. Rewrites `.rasmap` terrain, land cover, and projection references
7. Creates comprehensive agent/model_log.md

**Output Structure**:
```
UpperGuadalupe_12100201/
└── RAS Model/
    ├── UPGU1/  # Upstream watershed (runnable)
    ├── UPGU2/  # Receives UPGU1 flow via DSS (runnable)
    ├── UPGU3/  # Receives UPGU2 flow via DSS (runnable)
    └── UPGU4/  # Downstream watershed (runnable)
```

**Cascade Execution** (sequential required):
```python
for model in ['UPGU1', 'UPGU2', 'UPGU3', 'UPGU4']:
    ras_obj = RasPrj()
    init_ras_project(organized / "RAS Model" / model, "6.5", ras_object=ras_obj)
    RasCmdr.compute_plan("01", ras_object=ras_obj, num_cores=4)
    # Upstream results feed downstream via DSS
```

## Standardized 4-Folder Structure

All organized models use the same structure:

```
{ModelName}_{HUC8}/
├── HMS Model/          # HEC-HMS hydrologic models (if present)
├── RAS Model/          # HEC-RAS hydraulic models (RUNNABLE)
│   └── {Model}/
│       ├── *.prj, *.g##, *.p##, *.u##
│       ├── *.hdf (pre-run results, moved from Output/)
│       ├── DSS Inputs/ (DSS paths corrected)
│       ├── Projection/ (project CRS copied or generated)
│       ├── *.rasmap (terrain paths corrected)
│       ├── Terrain/ (moved here, where HEC-RAS expects it)
│       └── Land Cover/ (local land cover and sidecar assets)
├── Spatial Data/       # GIS data, shapefiles
├── Documentation/      # BLE reports, inventories
└── agent/
    └── model_log.md    # REQUIRED - documents all fixes applied
```

## agent/model_log.md Requirement

**Every organized model MUST have** `agent/model_log.md` documenting:
- Organization actions taken
- Files classified and moved (HMS/RAS/Spatial/Docs)
- **Critical fixes applied** (Output/, DSS Inputs/, Projection/, Terrain/, Land Cover/)
- Number of corrections made
- DSS validation results
- Compute test instructions

**Why**: Provides audit trail of what was fixed, enables troubleshooting, documents decisions made

## Validation Features

### DSS Pathname Validation

All organize methods include comprehensive DSS validation:

```python
from ras_commander.dss import RasDss

# Validates all pathnames in all DSS files
for dss_file in dss_files:
    catalog = RasDss.get_catalog(dss_file)
    for pathname in catalog['pathname']:
        result = RasDss.check_pathname(dss_file, pathname)
        # Invalid pathnames documented in agent/model_log.md
```

**Upper Guadalupe Achievement**: 10,248 pathnames validated, 100% valid ✓

### Path Existence Validation

**Before correcting any path**, we verify the target file actually exists:

```python
if dss_filename in dss_lookup:
    actual_dss_path = dss_lookup[dss_filename]

    # CRITICAL: Verify file exists
    if actual_dss_path.exists():
        # Calculate correct relative path
        rel_path = actual_dss_path.relative_to(hecras_file.parent)
        # Replace path
    else:
        print(f"WARNING: DSS file not found: {dss_filename}")
```

**Result**: Only corrects paths to files that actually exist

## Example Notebooks

Complete working examples demonstrating each model:

### 950_ebfe_spring_creek.ipynb

**Demonstrates**:
- Organizing Pattern 3a (single 2D model)
- The 3 critical fixes (before/after comparison)
- DSS validation
- Extracting pre-computed 2D results
- Visualizing water surface elevations
- Terrain validation

**Key Sections**:
- Problem explanation (why eBFE models are broken)
- Automated fixes (what RasEbfeModels does)
- Before/after file structure
- Time savings (30 min → 5 min)

### 951_ebfe_north_galveston_bay.ipynb

**Demonstrates**:
- Organizing Pattern 4 (compound HMS + RAS)
- HMS storm frequency exploration (7 frequencies)
- HMS → RAS workflow understanding
- Handling large nested RAS extraction
- DSS time series validation

**Key Sections**:
- Compound model complexity
- HMS/RAS separation
- Manual extraction handling (6.1 GB nested zip)

### 952_ebfe_upper_guadalupe_cascade.ipynb

**Demonstrates**:
- Organizing Pattern 3b (cascaded watersheds)
- Massive scale fixes (57 GB moved, 96 corrections)
- 10,248 DSS pathname validation
- Cascaded model execution (UPGU1→2→3→4)
- Gridded precipitation DSS
- Pre-run results extraction

**Key Sections**:
- Complete before/after breakdown
- All 3 fixes explained with file sizes
- Cascade structure and execution
- Emphasis: "This library exists to solve this exact problem"

### 953_ebfe_rio_hondo_steady_collection.ipynb

**Demonstrates**:
- Organizing and validating the Rio Hondo 1D steady BLE reach-model collection.
- Sequential steady-plan validation for 253 projects.
- Reading generated HDF compute messages after successful steady-plan execution.
- Distinguishing 1D steady result generation from 2D preprocessor validation.

### 954_ebfe_lake_maurepas_validation.ipynb

**Demonstrates**:
- Organizing Pattern 3 single-archive Louisiana 2D model delivery.
- Validating the delivered Lake Maurepas HEC-HMS project from `HMS Model/` with hms-commander.
- Confirming local projection, terrain, land-cover, and RASMapper assets.
- Reusing saved ras-commander geometry-preprocessor evidence for plan 02.
- Documenting a preprocessor-valid model where full hydraulic result HDFs are absent from the source archive.

### 955_ebfe_tickfaw_validation.ipynb

**Demonstrates**:
- Organizing Pattern 3 single-archive Louisiana 2D model delivery with results.
- Confirming local projection, terrain, land-cover, and RASMapper assets.
- Reusing saved ras-commander geometry-preprocessor evidence for plan 13.
- Verifying that all seven plan result HDF paths resolve inside the organized RAS project folder.

### 957_ebfe_spring_river_validation.ipynb

**Demonstrates**:
- Organizing the distinct Spring River HUC 11010010 delivery without confusing it with Spring Creek.
- Confirming local projection, terrain, land-cover, legacy land-classification compatibility assets, DSS inputs, and RASMapper references.
- Executing a fresh HEC-RAS 6.1 geometry-preprocessor validation for plan 01 / geometry 01.
- Archiving the fresh preprocessor HDF before restoring the delivered full-result `Spring_BLE.p01.hdf`.
- Verifying that all seven plan result HDF paths resolve inside the organized RAS project folder.

## Organizing New Models

For eBFE models not included in RasEbfeModels, use the **ebfe_organize_models agent skill**:

```bash
# In Claude Code:
"Organize West Fork San Jacinto (12040101) using ebfe_organize_models skill"
```

**Agent produces**:
1. Organized 4-folder structure with all 3 critical fixes
2. agent/model_log.md documenting fixes
3. MANIFEST.md with file inventory
4. **Generated function**: `organize_westforksanjacinto_12040101.py`
5. DSS validation results
6. Compute test instructions
7. Haiku results check template

**After testing**: Promote generated function to RasEbfeModels class

**Growing Library**: Each organization adds a tested function

## Time Savings

| Model | Manual Fix Time | With RasEbfeModels | Savings |
|-------|----------------|-------------------|---------|
| Spring Creek | 30-45 min | 5-10 min | 20-35 min |
| North Galveston Bay | 45-90 min | 10-15 min plus nested zip extraction | 30-75 min |
| Upper Guadalupe | 60-120 min | 15-20 min | 45-100 min |

**Additional Benefit**: Enables automation (no GUI popups)

## Automation Benefits

### Without Path Corrections

```python
# Automation FAILS - GUI popup blocks workflow
init_ras_project(broken_ebfe_model, "6.5")
RasCmdr.compute_plan("01")  # Hangs on "DSS path needs correction" dialog
```

### With Path Corrections

```python
# Automation WORKS - no GUI interruptions
organized = RasEbfeModels.organize_upper_guadalupe(source, validate_dss=True)
init_ras_project(organized / "RAS Model/UPGU1", "6.5")
RasCmdr.compute_plan("01", num_cores=4)  # Runs to completion
```

## Testing and Validation

### End-to-End Evidence

Current validation is tracked in the repository-level
`VALIDATION_MATRIX.md`, with generated audit reports under the H: workspace:
`H:\Testing\eBFE Model Organization\Validation\ebfe_delivery`.

- Lower Colorado-Cummins sample: geometry preprocessor passed.
- Rio Hondo: 253 1D steady reach projects passed sequential geometry preprocessor validation, and 253/253 steady plans computed successfully in `steady_plan_validation_20260424_160022.json`.
- Spring Creek: 2D geometry preprocessor passed.
- North Galveston Bay: nested download/extract/organize path passed geometry preprocessor validation; delivered HMS project loads through hms-commander.
- Upper Guadalupe: UPGU1, UPGU2, and UPGU3 passed; UPGU4 requires the 7200-second validation record because its geometry preprocessor can exceed one hour.
- Eleven Point: organized from the split `Input.zip`, `Terrain.zip`, and `Land_Cover.zip` delivery; path-audited with zero issues, seven local plan HDFs, and a passing ras-commander geometry-preprocessor run using HEC-RAS 6.6.
- Spring River: cataloged separately from Spring Creek as `spring-river` / `SpringRiver_11010010`; downloaded, organized, path-audited with zero issues, preprocessor-valid in HEC-RAS 6.1, and results-ready with seven local plan HDFs. The validation notebook preserves the legacy `Land Classification` compatibility copy referenced by `Spring_BLE.g01.hdf`, archives fresh preprocessor evidence, and restores the delivered full-result plan HDF; see `examples/957_ebfe_spring_river_validation.ipynb`.
- Lower Brazos: LB_MA01, LB_MA02, and LB_MA03 are downloaded, extracted, organized, path-audited with zero issues, and results-ready with 61 local plan HDFs in the latest audit. LB_MA02 passed ras-commander geometry-preprocessor validation in 3846.3 seconds; LB_MA01 exceeded the 7200-second timeout with no compute messages, and LB_MA03 returned without producing compute messages, so Lower Brazos remains partially preprocessor-validated.
- Amite: full E2E organization completed for five RAS projects. WA1, WA2,
  WA3, and WA5 passed geometry preprocessor validation; WA4 is blocked by a
  `RasGeomWriter` / `ERROR: Incorrect Type in ./Projection. (Expected String)`
  failure and requires manual terrain rebuild or repair inside RASMapper.
- Tickfaw: organized, path-audited, preprocessor-valid, and results-ready with seven local hydraulic plan HDFs; see `examples/955_ebfe_tickfaw_validation.ipynb`.
- Lake Maurepas: organized, HMS-validated through hms-commander, path-audited, and preprocessor-valid; source archive scan found no RAS plan-result HDFs, so it is not yet a results-ready demo; see `examples/954_ebfe_lake_maurepas_validation.ipynb`.

### Notebook Testing

Current eBFE notebooks `950`-`957` execute against the shared
`H:\Testing\eBFE Model Organization` workspace by default, with
`RAS_COMMANDER_EBFE_ROOT` available for overrides. Stored notebook outputs were
refreshed after delivery-format updates, and notebook QA confirmed no error
outputs in the eBFE notebook set.

### DSS Validation Scale

**Largest validation ever**:
- Model: Upper Guadalupe
- DSS files: 10
- Total pathnames: 10,248
- Validation rate: 100% (0 errors)
- Breakdown:
  - Gridded precipitation: 6,720 pathnames
  - Boundary conditions: 3,528 pathnames

## Why This Matters

### For Engineers

**Before this library**:
1. Download valuable BLE model from FEMA
2. Spend 30-120 minutes manually fixing broken file structure
3. Risk missing corrections → Model still doesn't work
4. Frustration, wasted time

**With this library**:
1. Download BLE model
2. One function call → Runnable model
3. Confidence: All paths validated, all fixes documented
4. Start analysis immediately

### For Automation

**eBFE models enable**:
- Automated flood risk analysis at scale
- Batch processing of multiple study areas
- Programmatic model execution
- Integration with other workflows

**But GUI error popups kill automation**

**Our path corrections** eliminate GUI popups → Automation works

## See Also

- [eBFE Delivery Validation](user-guide/ebfe-delivery-validation.md)
- `VALIDATION_MATRIX.md`
- [950_ebfe_spring_creek.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/950_ebfe_spring_creek.ipynb)
- [955_ebfe_tickfaw_validation.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/955_ebfe_tickfaw_validation.ipynb)
- [957_ebfe_spring_river_validation.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/957_ebfe_spring_river_validation.ipynb)

---

**The Bottom Line**: eBFE models are fundamentally broken and unusable without significant manual effort. RasEbfeModels fixes them automatically, creating runnable HEC-RAS models that work for automation. This is what the library is for.
