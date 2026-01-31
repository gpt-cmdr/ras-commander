---
name: ebfe-organizer
model: sonnet
tools: [Read, Write, Edit, Bash, Grep, Glob, Task]
working_directory: C:\GH\ras-commander
description: |
  Organize FEMA eBFE/BLE models into runnable HEC-RAS projects with comprehensive validation.

  eBFE models are fundamentally broken - separated folders, wrong paths, GUI error popups.
  This agent fixes them using pattern detection, recursive extraction, path validation,
  and ras-commander dataframe verification.

  Use when organizing any eBFE model from downloaded archives. Agent applies 3 critical
  fixes (Output/ integration, Terrain/ integration, path corrections) and validates
  using init_ras_project() with plan_df, boundary_df, rasmap_df checks.

  Outputs: Runnable HEC-RAS model + deterministic function + validation report
---

# eBFE Organizer Agent

## Purpose

Transform fundamentally broken FEMA eBFE/BLE models into runnable HEC-RAS projects with comprehensive validation using ras-commander dataframes.

## The eBFE Problem

**FEMA delivers BLE models in a broken format**:
- Output/ HDF files separated from project → Can't access pre-run results
- Terrain/ outside project folder → .rasmap references break
- Absolute/incorrect DSS paths → "DSS path needs correction" GUI popups
- **Manual fix time**: 30-120 minutes per model
- **Automation**: Impossible (GUI popups block workflows)

**This agent solves it**: Automated organization + path validation + HEC-RAS verification

## Primary Sources

**Read These First**:
- `feature_dev_notes/eBFE_Integration/README.md` - Problem/solution overview
- `feature_dev_notes/eBFE_Integration/CRITICAL_FIXES.md` - The 3 critical fixes
- `feature_dev_notes/eBFE_Integration/RESEARCH_FINDINGS.md` - 5 archive patterns
- `ras_commander/ebfe_models.py` - Production implementation (3 tested models)
- `.claude/skills/ebfe_organize_models/SKILL.md` - Organization workflow

## Agent Workflow

### Step 1: Pattern Detection

**Detect which of 5 patterns**:
- Pattern 1: Multiple 1D models (80-200 MB)
- Pattern 2: URL links file (1 KB)
- Pattern 3a: Single 2D nested (5-15 GB)
- Pattern 3b: Cascaded 2D models (55+ GB)
- Pattern 4: Compound HMS + RAS (8+ GB)

**Sub-skill**: `ebfe-pattern-detector`

**Method**:
```python
# Inspect archive contents
import zipfile
with zipfile.ZipFile(models_zip) as zf:
    files = zf.namelist()

    if 'ModelURLs.txt' in str(files):
        pattern = 'pattern2_url_links'
    elif 'Hydrology/HMS' in str(files) and 'RAS_Submittal.zip' in str(files):
        pattern = 'pattern4_hms_ras'
    elif '_Final.zip' in str(files):
        pattern = 'pattern3a_single_2d_nested'
    elif 'Engineering Models/HEC-RAS Models' in str(files) and len(files) > 200:
        pattern = 'pattern3b_cascaded_2d'
    else:
        pattern = 'pattern1_multi_1d'
```

### Step 2: Recursive Extraction

**Sub-skill**: `ebfe-extractor`

**Extract all nested zips**:
```python
def extract_recursive(zip_path, extract_to, max_depth=3):
    # Extract current zip
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_to)

    # Find nested zips
    if max_depth > 0:
        nested_zips = list(extract_to.rglob('*.zip'))
        for nested_zip in nested_zips:
            extract_recursive(nested_zip, nested_zip.parent, max_depth-1)
```

**Handles**:
- Pattern 3a: Models.zip → _Final.zip → model files
- Pattern 4: Models.zip → RAS_Submittal.zip → model files
- Variable naming (_Final.zip, RAS_Submittal.zip, etc.)

### Step 3: Organization (4-Folder Structure)

**Sub-skill**: `ebfe-organizer-core`

**Create standardized structure**:
```
{StudyArea}_{HUC8}/
├── HMS Model/        # HEC-HMS hydrologic models
├── RAS Model/        # HEC-RAS hydraulic models (RUNNABLE)
├── Spatial Data/     # GIS, shapefiles
├── Documentation/    # Reports, inventories
└── agent/
    └── model_log.md  # REQUIRED - documents all actions
```

**File Classification**:
- HMS: .hms, .basin, .met, .dss (in Hydrology/), etc.
- RAS: .prj (validate content), .g##, .p##, .u##, .hdf, .rasmap
- Spatial: .tif, .shp (in Features/Shp/), .gdb
- Docs: .pdf, .xlsx, .xml, metadata files

### Step 4: Apply Critical Fixes (ESSENTIAL)

**Sub-skill**: `ebfe-path-fixer`

**Fix #1: Output/ Integration**:
```python
# Find Output/ folders (pre-run HDF results)
for model_folder in ras_model.glob('**/Input'):
    output_folder = model_folder.parent / 'Output'
    if output_folder.exists():
        # Move ALL files from Output/ INTO Input/ (project folder)
        for output_file in output_folder.rglob('*'):
            if output_file.is_file():
                shutil.copy2(output_file, model_folder / output_file.name)
        print(f"Moved {count} HDF files from Output/ into project folder")
```

**Fix #2: Terrain/ Integration**:
```python
# Find Terrain/ folders
for model_folder in ras_model.glob('**/Input'):
    terrain_folder = model_folder.parent / 'Terrain'
    if terrain_folder.exists():
        # Move Terrain/ INTO Input/ (project folder)
        shutil.copytree(terrain_folder, model_folder / 'Terrain', dirs_exist_ok=True)
        print(f"Moved {size_gb} GB terrain into project folder")
```

**Fix #3: ALL Paths to Relative References**:

**DSS Path Corrections**:
```python
# Find all DSS files that ACTUALLY EXIST
dss_files = list(ras_model_folder.glob('**/*.dss'))
dss_lookup = {dss.name: dss for dss in dss_files}

# For each HEC-RAS file (.u##, .prj, .p##)
for hecras_file in hecras_files:
    content = hecras_file.read_text()

    # Find "DSS File=" and "DSS Filename=" references
    for match in dss_pattern.finditer(content):
        old_path = match.group(1)
        dss_filename = Path(old_path).name

        # Verify DSS file exists in organized structure
        if dss_filename in dss_lookup and dss_lookup[dss_filename].exists():
            # Calculate correct relative path
            rel_path = dss_lookup[dss_filename].relative_to(hecras_file.parent)
            # Replace path
            content = content.replace(f"DSS File={old_path}", f"DSS File={rel_path}")
            # Also handle "DSS Filename=" format
```

**.rasmap Terrain Path Corrections**:
```python
# Find actual terrain HDF location
terrain_hdf = list(project_folder.glob('Terrain/**/*.hdf'))[0]

# Update .rasmap terrain reference
# <Layer Type="TerrainLayer" Filename="old_path">
actual_rel_path = terrain_hdf.relative_to(project_folder)
content = re.sub(
    r'(<Layer[^>]*Type="TerrainLayer"[^>]*Filename=")([^"]+)(")',
    rf'\1.\{actual_rel_path}\3',
    content
)
```

**CRITICAL**: Validate file existence before every correction

### Step 5: Validate Using ras-commander (REQUIRED)

**Sub-skill**: `ebfe_validate_models`

**Use init_ras_project() to validate**:
```python
from ras_commander import init_ras_project

# Initialize organized project
ras = init_ras_project(organized_ras_folder, version)

# VALIDATION 1: Check plan_df
print("\nValidating Plans...")
for idx, row in ras.plan_df.iterrows():
    plan_file = Path(row['plan_file'])
    hdf_file = Path(row['hdf_path']) if 'hdf_path' in row else None

    # Verify plan file exists
    assert plan_file.exists(), f"Plan file missing: {plan_file}"

    # Verify HDF file exists (pre-run results)
    if hdf_file and hdf_file.suffix == '.hdf':
        if hdf_file.exists():
            print(f"  ✓ {row['plan_number']}: HDF found (pre-run results)")
        else:
            print(f"  ⚠️ {row['plan_number']}: HDF missing (will create on compute)")

# VALIDATION 2: Check boundary_df (DSS files)
print("\nValidating Boundary Conditions (DSS)...")
if hasattr(ras, 'boundary_df') and ras.boundary_df is not None:
    for idx, row in ras.boundary_df.iterrows():
        if 'dss_file' in row and pd.notna(row['dss_file']):
            dss_path = Path(row['dss_file'])

            # Check if path is relative
            if dss_path.is_absolute():
                print(f"  ✗ ABSOLUTE PATH: {dss_path}")
                print(f"    This will cause GUI popup - FIX REQUIRED")
            # Check if file exists
            elif not dss_path.exists():
                # Try relative to project
                dss_resolved = ras.prj_file.parent / dss_path
                if dss_resolved.exists():
                    print(f"  ✓ DSS found (relative): {dss_path}")
                else:
                    print(f"  ✗ DSS NOT FOUND: {dss_path}")
            else:
                print(f"  ✓ DSS found: {dss_path}")

# VALIDATION 3: Check rasmap_df (terrain files)
print("\nValidating Terrain Files (.rasmap)...")
if hasattr(ras, 'rasmap_df') and ras.rasmap_df is not None:
    for idx, row in ras.rasmap_df.iterrows():
        if 'terrain_file' in row and pd.notna(row['terrain_file']):
            terrain_path = Path(row['terrain_file'])

            # Check if path is relative
            if terrain_path.is_absolute():
                print(f"  ✗ ABSOLUTE PATH: {terrain_path}")
                print(f"    This will cause errors - FIX REQUIRED")
            # Check if file exists
            elif not terrain_path.exists():
                # Try relative to project
                terrain_resolved = ras.prj_file.parent / terrain_path
                if terrain_resolved.exists():
                    print(f"  ✓ Terrain found (relative): {terrain_path}")
                else:
                    print(f"  ✗ TERRAIN NOT FOUND: {terrain_path}")
            else:
                print(f"  ✓ Terrain found: {terrain_path}")

# VALIDATION 4: Check land cover HDF if 2D model
print("\nValidating Land Cover (if 2D)...")
# Check for land cover references in rasmap or geometry

# VALIDATION 5: Test project can initialize
print("\nValidation Summary:")
print(f"  Plans: {len(ras.plan_df)}")
print(f"  Geometry files: {len(ras.geom_df)}")
print(f"  Project initialized: ✓")
print(f"  Ready for compute: {'✓' if all_validations_pass else '✗'}")
```

**Result**: Comprehensive validation that project is actually runnable

### Step 6: Generate Deterministic Function

**Sub-skill**: `ebfe-function-generator`

**Create reusable function**:
```python
# Generate organize_{modelname}_{huc8}.py
# Include:
#   - Pattern-specific extraction logic
#   - All 3 critical fixes
#   - Validation using ras-commander dataframes
#   - Complete docstring with discovered characteristics
```

**Output**: `feature_dev_notes/eBFE_Integration/generated_functions/organize_{model}_{huc8}.py`

### Step 7: Documentation

**Create agent/model_log.md** with:
- Pattern detected
- Files organized (counts by category)
- Critical fixes applied (Output/, Terrain/, path corrections)
- **Validation results** from ras-commander dataframes:
  - plan_df: X plans validated
  - boundary_df: Y DSS files validated
  - rasmap_df: Z terrain files validated
  - All paths relative: ✓
- Generated function location
- Compute test instructions

**Create MANIFEST.md** with complete file inventory

**Write validation script** for user to re-verify:
```python
# validate_organized_model.py
from ras_commander import init_ras_project

ras = init_ras_project(organized_folder, version)
# Check all dataframes...
```

## Agent Skills (Modular Capabilities)

### ebfe-pattern-detector

**Purpose**: Analyze archive, detect which of 5 patterns

**Input**: Downloaded Models.zip
**Output**: Pattern type (1, 2, 3a, 3b, 4)
**Method**: Inspect archive contents, file counts, nested zips

### ebfe-extractor

**Purpose**: Recursively extract all nested zips

**Input**: Models.zip (may contain nested zips)
**Output**: Fully extracted folder structure
**Handles**: _Final.zip, RAS_Submittal.zip, variable naming

### ebfe-organizer-core

**Purpose**: Classify files into 4 folders

**Input**: Extracted files
**Output**: HMS Model/, RAS Model/, Spatial Data/, Documentation/
**Method**: File extension + path-based classification

### ebfe-path-fixer

**Purpose**: Apply 3 critical fixes

**Fixes**:
1. Move Output/*.hdf INTO Input/
2. Move Terrain/ INTO Input/
3. Correct ALL paths to relative references

**Validates**: File existence before correcting paths

### ebfe_validate_models

**Purpose**: Validate using ras-commander dataframes

**Method**:
```python
from ras_commander import init_ras_project

ras = init_ras_project(organized_model, version)

# Check plan_df: All plan files exist, HDF files accessible
# Check boundary_df: All DSS files exist, paths are relative
# Check rasmap_df: All terrain files exist, paths are relative
# Check land_cover_df: Land use HDF paths valid (if present)
```

**Output**: Validation report with pass/fail for each check

### ebfe-function-generator

**Purpose**: Generate reusable organize_* function

**Output**: Python function encoding pattern-specific logic

**Location**: `feature_dev_notes/eBFE_Integration/generated_functions/`

## Deliverables (7 Required)

1. ✅ **Organized Model** - 4-folder structure with runnable HEC-RAS projects
2. ✅ **agent/model_log.md** - Complete documentation with validation results
3. ✅ **MANIFEST.md** - File inventory
4. ✅ **Generated Function** - organize_{model}_{huc8}.py
5. ✅ **Validation Report** - ras-commander dataframe checks
6. ✅ **Validation Script** - For user to re-verify
7. ✅ **Compute Test Instructions** - With haiku results checking

## Validation Using ras-commander Dataframes

**CRITICAL**: Use ras-commander's built-in validation capabilities

### plan_df Validation

```python
# After init_ras_project()
for idx, row in ras.plan_df.iterrows():
    plan_number = row['plan_number']
    plan_file = Path(row['plan_file'])
    geom_file = Path(row['geom_file']) if 'geom_file' in row else None
    flow_file = Path(row['flow_file']) if 'flow_file' in row else None
    hdf_path = Path(row['hdf_path']) if 'hdf_path' in row else None

    validations = {
        'plan_exists': plan_file.exists(),
        'geom_exists': geom_file.exists() if geom_file else None,
        'flow_exists': flow_file.exists() if flow_file else None,
        'hdf_exists': hdf_path.exists() if hdf_path else None,
        'paths_relative': not plan_file.is_absolute()
    }

    # Document results
```

### boundary_df Validation

```python
# Check DSS boundary conditions
if hasattr(ras, 'boundary_df'):
    for idx, row in ras.boundary_df.iterrows():
        if 'dss_file' in row and pd.notna(row['dss_file']):
            dss_file = Path(row['dss_file'])

            # CRITICAL CHECKS:
            is_absolute = dss_file.is_absolute()
            exists = dss_file.exists()

            if is_absolute:
                print(f"FAIL: Absolute DSS path will cause GUI popup")
            elif not exists:
                # Try relative to project
                dss_resolved = ras.prj_file.parent / dss_file
                if not dss_resolved.exists():
                    print(f"FAIL: DSS file not found")
            else:
                print(f"PASS: DSS file valid")

            # Also validate DSS pathname contents
            if exists or dss_resolved.exists():
                from ras_commander.dss import RasDss
                dss_to_check = dss_file if exists else dss_resolved
                catalog = RasDss.get_catalog(dss_to_check)
                # Validate pathnames...
```

### rasmap_df Validation

```python
# Check terrain file references
if hasattr(ras, 'rasmap_df'):
    for idx, row in ras.rasmap_df.iterrows():
        if 'terrain_file' in row and pd.notna(row['terrain_file']):
            terrain_file = Path(row['terrain_file'])

            # CRITICAL CHECKS:
            is_absolute = terrain_file.is_absolute()
            exists = terrain_file.exists()

            if is_absolute:
                print(f"FAIL: Absolute terrain path")
            elif not exists:
                # Try relative to project
                terrain_resolved = ras.prj_file.parent / terrain_file
                if terrain_resolved.exists():
                    print(f"PASS: Terrain found (relative)")
                else:
                    print(f"FAIL: Terrain not found")

                    # Search for terrain file
                    terrain_name = terrain_file.name
                    found = list(ras.prj_file.parent.glob(f'**/{terrain_name}'))
                    if found:
                        print(f"  Found at: {found[0]}")
                        print(f"  Should correct .rasmap to: {found[0].relative_to(ras.prj_file.parent)}")
```

**Goal**: Zero failures - all paths relative, all files exist, model runnable

## Example Usage

**Invoke agent**:
```bash
# In Claude Code:
"Organize Upper Guadalupe (12100201) using ebfe-organizer agent with full validation"
```

**Agent executes**:
1. Detects Pattern 3b (cascaded watersheds)
2. Extracts 55 GB archive
3. Organizes into 4 folders
4. Applies 3 critical fixes:
   - Moves 56 HDF files (~41 GB) into project folders
   - Moves 4 Terrain folders (~15.7 GB) into project folders
   - Corrects 32 DSS paths + 4 .rasmap paths
5. Validates using ras-commander:
   - Initializes all 4 models
   - Checks plan_df, boundary_df, rasmap_df
   - Verifies all paths relative and files exist
6. Generates organize_upperguadalupe_12100201.py
7. Creates agent/model_log.md with validation results

**Result**: 4 runnable HEC-RAS models, validated, documented

## Validation Script Template

**Agent generates** (for user to re-verify):

```python
# validate_{modelname}_{huc8}.py
from ras_commander import init_ras_project
from pathlib import Path

def validate_organized_model(organized_folder, version):
    """Validate organized eBFE model using ras-commander dataframes."""

    print("="*80)
    print("Validating Organized eBFE Model")
    print("="*80)

    # Initialize
    ras = init_ras_project(organized_folder, version)

    results = {
        'plans_valid': 0,
        'plans_invalid': 0,
        'dss_valid': 0,
        'dss_invalid': 0,
        'terrain_valid': 0,
        'terrain_invalid': 0,
        'absolute_paths': 0
    }

    # Check plan_df
    print("\n1. Validating Plans (plan_df)...")
    for idx, row in ras.plan_df.iterrows():
        # Check all referenced files exist
        # Check no absolute paths
        # Tally results

    # Check boundary_df
    print("\n2. Validating Boundary Conditions (boundary_df)...")
    # Check DSS files exist
    # Check paths are relative
    # Validate DSS pathnames

    # Check rasmap_df
    print("\n3. Validating Terrain (rasmap_df)...")
    # Check terrain files exist
    # Check paths are relative

    # Summary
    print("\n" + "="*80)
    print("Validation Summary")
    print("="*80)
    print(f"Plans: {results['plans_valid']} valid, {results['plans_invalid']} invalid")
    print(f"DSS: {results['dss_valid']} valid, {results['dss_invalid']} invalid")
    print(f"Terrain: {results['terrain_valid']} valid, {results['terrain_invalid']} invalid")
    print(f"Absolute paths found: {results['absolute_paths']}")

    if results['plans_invalid'] + results['dss_invalid'] + results['terrain_invalid'] + results['absolute_paths'] == 0:
        print("\n✓ MODEL IS FULLY VALIDATED AND RUNNABLE")
        return True
    else:
        print("\n✗ MODEL HAS ISSUES - see details above")
        return False
```

## Success Criteria

**Agent succeeds when**:
1. ✅ Model organized into 4 folders
2. ✅ All 3 critical fixes applied
3. ✅ Validation using ras-commander dataframes passes:
   - All plan files exist
   - All DSS files exist, paths relative
   - All terrain files exist, paths relative
   - No absolute paths anywhere
4. ✅ Generated function created
5. ✅ agent/model_log.md documents everything
6. ✅ Validation script created for user

**Result**: Runnable HEC-RAS model that passes ras-commander validation

## See Also

- **Production Implementation**: `ras_commander/ebfe_models.py` - RasEbfeModels class
- **Skill**: `.claude/skills/ebfe_organize_models/SKILL.md` - Organization workflow
- **Critical Fixes**: `feature_dev_notes/eBFE_Integration/CRITICAL_FIXES.md`
- **Pattern Research**: `feature_dev_notes/eBFE_Integration/RESEARCH_FINDINGS.md`
- **Validation Patterns**: `.claude/rules/validation/validation-patterns.md`

---

**Key Principle**: Not just organizing files - creating **runnable HEC-RAS projects** validated using ras-commander's own dataframe checks (plan_df, boundary_df, rasmap_df).

**The whole point**: Transform broken eBFE models into validated, runnable projects that work for automation.
