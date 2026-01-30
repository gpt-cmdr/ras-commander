# API-First Principle for HEC-RAS Agents

**Context**: All HEC-RAS domain agents working with ras-commander
**Priority**: CRITICAL - affects all HEC-RAS data operations
**Auto-loads**: Yes (all HEC-RAS code)

## Golden Rules

### Rule 1: DataFrames Are Single Source of Truth

**MUST** use ras-commander DataFrames for project metadata:

| DataFrame | Purpose | NEVER Do Instead |
|-----------|---------|------------------|
| `ras.plan_df` | Plan inventory, HDF paths, execution status | `ls *.p##` or `Grep` plan files |
| `ras.geom_df` | Geometry files and paths | `glob("*.g##")` |
| `ras.flow_df` | Flow file inventory | Manual file listing |
| `ras.unsteady_df` | Unsteady configuration | Parsing .u## files directly |
| `ras.boundaries_df` | Boundary conditions | Reading flow files manually |

### Rule 2: Use Static Class Methods for Data Extraction

**MUST** use ras-commander API classes:

| Task | USE This | NOT This |
|------|----------|----------|
| HDF results | `HdfResultsPlan.get_wse()` | `h5py.File()` directly |
| Mesh data | `HdfMesh.get_mesh_cell_points()` | `Grep` HDF paths |
| Geometry parsing | `GeomCrossSection.get_station_elevation()` | Manual fixed-width parsing |
| Cross sections | `RasGeometry.get_cross_sections()` | `Read` + regex on .g## |
| DSS data | `RasDss.get_timeseries()` | Manual DSS parsing |
| Compute messages | `HdfResultsPlan.get_compute_messages()` | Parsing .computeMsgs.txt |

### Rule 3: Exploration Tools Are for Understanding, Not Extraction

**PERMITTED** uses of Explore/Bash/Grep:
- Learning API method signatures when documentation is insufficient
- Understanding file formats (for contribution purposes only)
- Debugging when API fails unexpectedly
- Verifying API output against raw files

**PROHIBITED** uses:
- Extracting data that API methods already provide
- Bypassing DataFrames to "directly" read files
- Building parallel extraction logic outside the API
- Inventorying project files instead of using DataFrames

## Decision Tree

```
User Request for HEC-RAS Data
|
+- Does ras-commander API have a method for this?
|   |
|   +- YES -> Use the API method
|   |
|   +- NO or UNSURE
|       |
|       +- Check AGENTS.md and CLAUDE.md files for the relevant subpackage
|       |
|       +- Method exists -> Use it
|       |
|       +- Method truly missing
|           |
|           +- Complete user's task using minimal direct access
|           |
|           +- Document the gap in output markdown
|           |
|           +- Suggest contribution as follow-up action
```

## API Gap Handling Workflow

When you encounter missing API functionality:

1. **Complete the user's task first** using available methods plus minimal direct access if absolutely necessary
2. **Document the gap** clearly in your output:
   ```markdown
   ## API Gap Identified

   **Missing Functionality**: [description]
   **Workaround Used**: [what you did]
   **Suggested API Addition**: [proposed method signature]
   ```
3. **Suggest follow-up**: Recommend engaging `api-consistency-auditor` to add the missing method
4. **Do NOT block the user** waiting for API contribution

## Agent-Specific Guidance

### hecras-project-inspector

**Primary tool**: DataFrames populated by `init_ras_project()`

```python
# CORRECT: Use DataFrames
from ras_commander import init_ras_project, ras

init_ras_project("/path/to/project", "6.6")

# Plan inventory
all_plans = ras.plan_df['plan_number'].tolist()

# Execution status
executed = ras.plan_df[ras.plan_df['HDF_Results_Path'].notna()]
pending = ras.plan_df[ras.plan_df['HDF_Results_Path'].isna()]

# Boundary inventory
bc_summary = ras.boundaries_df.groupby('bc_type').size()

# Geometry files
geom_files = ras.geom_df['full_path'].tolist()
```

```python
# WRONG: File exploration
import glob
plans = glob.glob("*.p##")  # NO!
```

### hdf-analyst

**Primary tools**: `HdfResultsPlan`, `HdfResultsMesh`, `HdfMesh`, `HdfXsec`

```python
# CORRECT: Use HDF API classes
from ras_commander.hdf import HdfResultsPlan, HdfResultsMesh, HdfMesh

# Check plan type first
if HdfResultsPlan.is_steady_plan("01", ras_object=ras):
    wse = HdfResultsPlan.get_steady_wse("01", ras_object=ras)
else:
    wse = HdfResultsPlan.get_wse("01", time_index=-1, ras_object=ras)

# Mesh results
max_wse = HdfResultsMesh.get_mesh_max_ws("01", ras_object=ras)
max_vel = HdfResultsMesh.get_mesh_max_face_v("01", ras_object=ras)

# Mesh geometry
cells = HdfMesh.get_mesh_cell_points("01", ras_object=ras)
```

```python
# WRONG: Raw h5py
import h5py
with h5py.File("plan.p01.hdf") as f:  # NO!
    wse = f['/Results/...'][:]
```

### hecras-results-analyst

**Primary tools**: `HdfResultsPlan` for execution verification, `HdfResultsMesh` for results

```python
# CORRECT: Use API for compute messages
messages = HdfResultsPlan.get_compute_messages("01", ras_object=ras)
runtime = HdfResultsPlan.get_runtime_data("01", ras_object=ras)

# Results metrics
max_wse = HdfResultsMesh.get_mesh_max_ws("01", ras_object=ras)
max_iter = HdfResultsMesh.get_mesh_max_iter("01", ras_object=ras)
```

```python
# WRONG: Parsing files directly
with open("plan.p01.computeMsgs.txt") as f:  # NO!
    messages = f.read()
```

### geometry-parser

**Primary tools**: `GeomCrossSection`, `GeomBridge`, `GeomCulvert`, `GeomStorage`, `GeomLateral`

```python
# CORRECT: Use Geom* classes
from ras_commander.geom import GeomCrossSection, GeomBridge, GeomStorage

# List cross sections
xs_df = GeomCrossSection.get_cross_sections("model.g01")

# Read XS data
sta_elev = GeomCrossSection.get_station_elevation(
    "model.g01", "River", "Reach", "1000"
)

# Modify XS
GeomCrossSection.set_station_elevation(
    "model.g01", "River", "Reach", "1000",
    modified_df, bank_left=50.0, bank_right=250.0
)

# Structures
bridges = GeomBridge.get_bridges("model.g01")
```

```python
# WRONG: Manual parsing
with open("model.g01") as f:  # NO!
    content = f.read()
    # Parsing fixed-width format manually...
```

### hecras-general-agent

When dispatching to specialist agents, **MUST** include API-first context in prompts:

```python
Task(
    subagent_type="hecras-project-inspector",
    prompt="""
    Analyze the HEC-RAS project at {path}.

    CRITICAL - API-First Requirement:
    - Call init_ras_project() first to populate DataFrames
    - Use ras.plan_df, ras.geom_df, ras.boundaries_df for all project analysis
    - Do NOT use Explore/Bash/Grep to inventory project files
    - See .claude/rules/python/api-first-principle.md

    [Rest of task instructions...]
    """
)
```

## Exception: ras-commander-api-expert

The `ras-commander-api-expert` agent is the **ONLY** exception to this rule.

**Why it's permitted to use Explore/Bash/Grep:**
- Its purpose is API discovery and documentation, not data extraction
- The ras-commander library is large (~50+ modules) and doesn't fit in context
- It spawns lightweight Haiku subagents specifically for codebase exploration
- It does NOT extract HEC-RAS model data

**This exception does NOT extend to:**
- hecras-project-inspector
- hdf-analyst
- hecras-results-analyst
- geometry-parser
- hecras-general-agent
- Any other HEC-RAS domain agent

## Anti-Patterns

### Anti-Pattern 1: File Exploration for Available Data

```python
# WRONG
files = glob.glob("*.p##.hdf")
for f in files:
    with h5py.File(f) as hdf:
        wse = hdf['/Results/Unsteady/Output/Output Blocks/...'][:]

# CORRECT
for plan_num in ras.plan_df['plan_number']:
    wse = HdfResultsPlan.get_wse(plan_num, ras_object=ras)
```

### Anti-Pattern 2: Grep for Data Extraction

```bash
# WRONG
Grep "River Reach=" model.g01
# Then parsing the output manually...

# CORRECT
xs_df = GeomCrossSection.get_cross_sections("model.g01")
# DataFrame already has river, reach, station columns
```

### Anti-Pattern 3: Bypassing DataFrames

```python
# WRONG
import os
plans = [f for f in os.listdir('.') if f.endswith('.p01')]
for p in plans:
    hdf_path = p.replace('.p01', '.p01.hdf')
    if os.path.exists(hdf_path):
        # ...

# CORRECT
executed_plans = ras.plan_df[ras.plan_df['HDF_Results_Path'].notna()]
for _, row in executed_plans.iterrows():
    hdf_path = row['HDF_Results_Path']
    # ...
```

### Anti-Pattern 4: Manual Compute Message Parsing

```python
# WRONG
msg_file = "project.p01.computeMsgs.txt"
with open(msg_file) as f:
    for line in f:
        if "Error" in line:
            # ...

# CORRECT
messages = HdfResultsPlan.get_compute_messages("01", ras_object=ras)
# Returns structured DataFrame with severity classification
```

## Verification Checklist

Before completing any HEC-RAS data task, verify:

- [ ] Did I call `init_ras_project()` to populate DataFrames?
- [ ] Am I using DataFrames for project metadata instead of file operations?
- [ ] Am I using static class methods (HdfResultsPlan, GeomCrossSection, etc.) for data extraction?
- [ ] If I used any file access, was it for understanding/debugging only?
- [ ] If I found an API gap, did I document it and suggest contribution?

## See Also

- `.claude/rules/python/dataframe-first-principle.md` - DataFrame patterns
- `.claude/rules/python/ras-commander-patterns.md` - Context object discipline
- `.claude/agents/api-consistency-auditor.md` - API contribution workflow
- `ras_commander/CLAUDE.md` - Library overview
- `ras_commander/hdf/AGENTS.md` - HDF API reference
- `ras_commander/geom/AGENTS.md` - Geometry API reference
