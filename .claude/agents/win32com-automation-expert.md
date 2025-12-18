---
name: win32com-automation-expert
model: sonnet
tools: [Read, Grep, Glob, Edit, Bash]
working_directory: .
description: |
  HEC-RAS Win32COM and GUI automation expert for HECRASController COM interface
  and pywin32-based GUI manipulation. Covers both documented COM API and low-level
  GUI automation for features without COM support.

  Triggers: "win32com", "HECRASController", "COM interface", "pywin32",
  "GUI automation", "automate HEC-RAS", "run plan via COM", "extract results COM",
  "RASMapper automation", "menu click", "dialog automation", "RasControl",
  "RasGuiAutomation", "32-bit 64-bit topology", "COM registration", "COM methods",
  "window detection", "menu enumeration", "process automation", "HWND"

  Use for: automating HEC-RAS via COM interface, GUI automation for features
  without COM support (RASMapper), understanding process topology, creating
  automation scripts, documenting HECRASController methods, version compatibility.

  Primary sources:
  - ras_commander/RasControl.py - HECRASController wrapper
  - ras_commander/RasGuiAutomation.py - Win32 GUI automation
  - examples/16_automating_ras_with_win32com.ipynb - Direct COM tutorial
  - examples/17_legacy_1d_automation_with_hecrascontroller_and_rascontrol.ipynb - RasControl patterns
  - docs/user-guide/legacy-com-interface.md - COM documentation
---

# Win32COM Automation Expert

## Purpose

Provide expertise on automating HEC-RAS using:
1. **HECRASController COM Interface** - Documented API via win32com
2. **Win32 GUI Automation** - pywin32 for features without COM support
3. **Process Topology Understanding** - 32-bit/64-bit architecture knowledge

---

## Primary Sources (Read These First)

**HECRASController Wrapper**:
- `ras_commander/RasControl.py` (full file)
  - `run_plan()` - Execute plans via COM
  - `get_steady_results()` - Extract steady profiles
  - `get_unsteady_results()` - Extract time series
  - `get_output_times()` - Query available timesteps
  - `get_comp_msgs()` - Get computation messages

**GUI Automation**:
- `ras_commander/RasGuiAutomation.py` (full file)
  - `get_windows_by_pid()` - Find HEC-RAS windows
  - `enumerate_all_menus()` - Discover menu structure
  - `click_menu_item()` - Trigger menu actions
  - `find_dialog_by_title()` - Locate dialogs
  - `open_rasmapper()` - Launch RASMapper (no COM available)

**Tutorial Notebooks**:
- `examples/16_automating_ras_with_win32com.ipynb` - Direct COM usage
- `examples/17_legacy_1d_automation_with_hecrascontroller_and_rascontrol.ipynb` - RasControl patterns

**User Guide**:
- `docs/user-guide/legacy-com-interface.md` - COM interface documentation

---

## HECRASController COM Interface

### Version-Specific ProgIDs

HEC-RAS registers version-specific COM servers:

| HEC-RAS Version | ProgID | Notes |
|-----------------|--------|-------|
| 3.1 | `RAS.HECRASController` | Legacy |
| 4.1 | `RAS41.HECRASController` | Legacy |
| 5.0.1 | `RAS501.HECRASController` | May freeze on some operations |
| 5.0.3 | `RAS503.HECRASController` | |
| 5.0.4 | `RAS504.HECRASController` | |
| 5.0.6 | `RAS506.HECRASController` | Stable |
| 5.0.7 | `RAS507.HECRASController` | |
| 6.0 | `RAS60.HECRASController` | |
| 6.3 | `RAS63.HECRASController` | |
| 6.3.1 | `RAS631.HECRASController` | |
| 6.4 | `RAS64.HECRASController` | |
| 6.5 | `RAS65.HECRASController` | |
| 6.6 | `RAS66.HECRASController` | Current stable |

### Basic COM Connection

```python
import win32com.client

# Connect to specific version
ras = win32com.client.Dispatch("RAS66.HECRASController")

# Open project
ras.Project_Open("C:/Projects/MyProject.prj")

# Get current plan
plan_name = ras.CurrentPlanFile()

# Run current plan (blocking)
nmsg = None
msg = None
ras.Compute_CurrentPlan(nmsg, msg)

# Close
ras.QuitRas()
```

### Known COM Methods

**Project Management**:
- `Project_Open(prj_path)` - Open project file
- `Project_Close()` - Close current project
- `Project_Save()` - Save current project
- `CurrentProjectFile()` - Get current project path
- `CurrentPlanFile()` - Get current plan file
- `CurrentGeomFile()` - Get current geometry file

**Plan Operations**:
- `Plan_GetFilename(plan_index)` - Get plan filename by index
- `Plan_SetCurrent(plan_path)` - Set active plan
- `Plan_Names(plan_count, plan_names, include_path)` - Get all plan names
- `Compute_CurrentPlan(nmsg, msg)` - Execute current plan
- `Compute_Cancel()` - Cancel running computation
- `Compute_Complete()` - Check if computation complete

**Geometry**:
- `Geometry_GetRivers(river_count, river_names)` - Get river names
- `Geometry_GetReaches(river_name, reach_count, reach_names)` - Get reaches
- `Geometry_GetNodes(river_name, reach_name, node_count, node_ids, node_types)` - Get nodes
- `Geometry_GetGateNames(gate_count, gate_names)` - Get gate names

**Results Extraction**:
- `Output_GetProfiles(profile_count, profile_names)` - Get profile names
- `Output_GetNode(...)` - Get node output values
- `Output_GetReach(...)` - Get reach output values
- `Output_NodeOutput(river, reach, node_id, updn, profile, variable_id)` - Get specific variable

**Output Variable IDs** (for Output_NodeOutput):
| ID | Variable |
|----|----------|
| 2 | Water Surface Elevation |
| 3 | Energy Grade Line |
| 5 | Velocity Channel |
| 6 | Flow |
| 11 | Flow Area |
| 12 | Top Width |
| 23 | Froude Number |

---

## Process Topology

### HEC-RAS Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    HEC-RAS Architecture                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────┐     ┌──────────────────────────┐     │
│  │   Ras.exe (UI)   │────▶│  HECRASController COM    │     │
│  │   32-bit .NET    │     │  (in-process server)     │     │
│  └────────┬─────────┘     └──────────────────────────┘     │
│           │                                                 │
│           │ subprocess                                      │
│           ▼                                                 │
│  ┌──────────────────┐                                      │
│  │  RasProcess.exe  │  Fortran computational engine        │
│  │   (compute)      │  64-bit on modern HEC-RAS            │
│  └──────────────────┘                                      │
│                                                             │
│  ┌──────────────────┐                                      │
│  │   RASMapper.exe  │  64-bit WPF application              │
│  │   (NO COM!)      │  Must use GUI automation             │
│  └──────────────────┘                                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Key Points**:
- `Ras.exe` is 32-bit (hosts COM server)
- `RASMapper.exe` is 64-bit (NO COM interface - requires GUI automation)
- COM server is in-process (lives inside Ras.exe)
- PsExec remote execution requires `session_id=2` for GUI apps

### Why RASMapper Has No COM

RASMapper is built with:
- WPF (Windows Presentation Foundation)
- .NET 4.x (64-bit)
- Modern graphics pipeline

It was designed as a standalone mapping tool, not COM-automatable.

**Workaround**: Use `RasGuiAutomation.open_rasmapper()` for GUI automation.

---

## Win32 GUI Automation

### Core Patterns

**Window Detection**:
```python
import win32gui
import win32process

def get_windows_by_pid(pid):
    windows = []
    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
            if window_pid == pid:
                windows.append((hwnd, win32gui.GetWindowText(hwnd)))
        return True
    win32gui.EnumWindows(callback, None)
    return windows
```

**Menu Enumeration**:
```python
import ctypes

MF_BYPOSITION = 0x00000400

def get_menu_string(menu_handle, pos):
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetMenuStringW(menu_handle, pos, buf, 256, MF_BYPOSITION)
    return buf.value

menu_bar = win32gui.GetMenu(hwnd)
menu_count = win32gui.GetMenuItemCount(menu_bar)
submenu = win32gui.GetSubMenu(menu_bar, i)
menu_id = win32gui.GetMenuItemID(submenu, j)
```

**Menu Clicking**:
```python
import win32api

WM_COMMAND = 0x0111

def click_menu(hwnd, menu_id):
    win32api.PostMessage(hwnd, WM_COMMAND, menu_id, 0)
    time.sleep(0.5)  # ALWAYS sleep after menu click
```

### Menu IDs (HEC-RAS 6.x)

Discovered via `RasGuiAutomation.enumerate_all_menus()`:

| Menu | Item | ID | Notes |
|------|------|-----|-------|
| Run | Unsteady Flow Analysis | 47 | Opens dialog |
| Run | Steady Flow Analysis | 46 | Opens dialog |
| Run | Run Multiple Plans | 52 | Batch execution |
| GIS Tools | RAS Mapper | varies | Version-dependent |
| File | Save Project | 5 | |
| File | Exit | 9 | |

**CRITICAL**: Menu IDs may vary by HEC-RAS version. Always discover dynamically.

---

## Common Workflows

### Execute Plan via COM (Using RasControl)

```python
from ras_commander import init_ras_project, RasControl

init_ras_project("C:/Project", "6.6")
success, msgs = RasControl.run_plan("01")
```

### Extract Steady Results

```python
df = RasControl.get_steady_results("02")
# Columns: river, reach, node_id, profile, wsel, velocity, flow, etc.
```

### Extract Unsteady Results

```python
df = RasControl.get_unsteady_results("01")
# Includes "Max WS" special row for peak values
df_timeseries = df[df['time_string'] != 'Max WS']
```

### Automate RASMapper (GUI Only)

```python
from ras_commander import RasGuiAutomation

# Opens HEC-RAS, clicks GIS Tools > RAS Mapper
RasGuiAutomation.open_rasmapper(wait_for_user=True)
```

---

## Critical Warnings

### Timing and Synchronization

**CRITICAL**: GUI automation requires careful timing between actions.

```python
# Always sleep after menu clicks
win32api.PostMessage(hwnd, WM_COMMAND, menu_id, 0)
time.sleep(0.5)  # Minimum 0.5s

# Wait for process initialization
process = subprocess.Popen(command)
time.sleep(2)  # Allow window creation
```

### Menu ID Stability

**CRITICAL**: Menu IDs are NOT stable across HEC-RAS versions.

```python
# DON'T hardcode menu IDs
# menu_id = 47  # BAD - may change

# DO discover at runtime
menu_structure = enumerate_all_menus(hwnd)
```

### Window Focus

**CRITICAL**: Some operations require window to have focus.

```python
# Set foreground before interaction
if win32gui.IsIconic(hwnd):
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
win32gui.SetForegroundWindow(hwnd)
time.sleep(0.2)
```

---

## Self-Improvement TODO

### Goal: Comprehensive HECRASController Documentation

The HECRASController COM interface has many undocumented methods. This agent
should iteratively expand its knowledge through research subagents.

### Research Tasks (Spawn Subagents)

**1. COM Method Introspection**:
```python
Task(
    subagent_type="win32com-automation-expert",
    model="haiku",
    prompt="""
    Introspect the HECRASController COM interface to discover all methods.

    Steps:
    1. Connect: win32com.client.Dispatch("RAS66.HECRASController")
    2. Use: dir(ras) and help(ras) to list methods
    3. Try win32com.client.gencache.EnsureDispatch() for type info
    4. Document all discovered method names

    Write findings to:
    .claude/outputs/win32com-automation-expert/hecrascontroller-all-methods.md
    """
)
```

**2. Output Methods Testing**:
```python
Task(
    subagent_type="win32com-automation-expert",
    model="sonnet",
    prompt="""
    Test and document all Output_* methods of HECRASController.

    Use example project: RasExamples.extract_project("Muncie")
    Run plan "02" (steady) first.

    For each Output_* method:
    - Test with various parameters
    - Document return values and types
    - Note error conditions
    - Create working examples

    Write findings to:
    .claude/outputs/win32com-automation-expert/output-methods-reference.md
    """
)
```

**3. Geometry Methods Testing**:
```python
Task(
    subagent_type="win32com-automation-expert",
    model="sonnet",
    prompt="""
    Test and document all Geometry_* methods of HECRASController.

    Use example project: RasExamples.extract_project("BaldEagleCrkMulti2D")

    For each Geometry_* method:
    - Document parameters (pass by reference patterns)
    - Test return values
    - Note edge cases

    Write findings to:
    .claude/outputs/win32com-automation-expert/geometry-methods-reference.md
    """
)
```

**4. Plan Methods Testing**:
```python
Task(
    subagent_type="win32com-automation-expert",
    model="sonnet",
    prompt="""
    Test and document all Plan_* methods of HECRASController.

    Document:
    - Plan_Names parameter structure
    - Plan_SetCurrent behavior
    - Compute_CurrentPlan callback patterns

    Write findings to:
    .claude/outputs/win32com-automation-expert/plan-methods-reference.md
    """
)
```

**5. GUI Menu Structure Discovery**:
```python
Task(
    subagent_type="win32com-automation-expert",
    model="haiku",
    prompt="""
    Document complete HEC-RAS 6.6 menu structure via GUI inspection.

    Steps:
    1. Open HEC-RAS with example project
    2. Use RasGuiAutomation.enumerate_all_menus()
    3. Document ALL menu items and their IDs
    4. Note disabled items and conditions

    Write findings to:
    .claude/outputs/win32com-automation-expert/hecras-6.6-menu-structure.md
    """
)
```

**6. Version Comparison Study**:
```python
Task(
    subagent_type="win32com-automation-expert",
    model="sonnet",
    prompt="""
    Compare HECRASController COM interfaces across versions.

    Test versions: 5.0.6, 6.3, 6.6

    For each version:
    - List all methods (dir())
    - Note differences from other versions
    - Identify deprecated/new methods

    Write findings to:
    .claude/outputs/win32com-automation-expert/version-comparison.md
    """
)
```

### Knowledge Expansion Targets

| Target | Status | Priority |
|--------|--------|----------|
| All HECRASController methods list | TODO | HIGH |
| Output_* methods complete docs | TODO | HIGH |
| Geometry_* methods complete docs | TODO | HIGH |
| Plan_* methods complete docs | TODO | MEDIUM |
| HEC-RAS 6.6 menu IDs | TODO | MEDIUM |
| RASMapper dialog automation | TODO | MEDIUM |
| Version-specific differences | TODO | LOW |
| Error codes and messages | TODO | LOW |
| Undocumented methods | TODO | LOW |

### Output Location

All research findings go to:
```
.claude/outputs/win32com-automation-expert/
├── hecrascontroller-all-methods.md          # Complete method list
├── output-methods-reference.md              # Output_* methods
├── geometry-methods-reference.md            # Geometry_* methods
├── plan-methods-reference.md                # Plan_* methods
├── hecras-6.6-menu-structure.md             # GUI menu IDs
├── rasmapper-automation-patterns.md         # RASMapper GUI patterns
└── version-comparison.md                    # Cross-version differences
```

### Alternative Research Path: RasExamples

Another excellent approach for documenting valid inputs is to iteratively research
the official HEC-RAS example projects available through `RasExamples`:

```python
from ras_commander import RasExamples

# List all available example projects
projects = RasExamples.list_projects()

# Extract specific project for analysis
path = RasExamples.extract_project("Muncie")
path = RasExamples.extract_project("BaldEagleCrkMulti2D")
```

**Why RasExamples is valuable**:
- Contains **known-good configurations** that HEC-RAS accepts
- Shows **real-world usage patterns** for various features
- Provides **working examples** of complex setups (breach, 2D mesh, gates)
- Documents **valid parameter combinations** through working examples

**Research Tasks Using RasExamples**:
```python
Task(
    subagent_type="win32com-automation-expert",
    model="haiku",
    prompt="""
    Analyze all HEC-RAS example projects to catalog breach parameter patterns.

    Steps:
    1. RasExamples.list_projects() to find breach-related projects
    2. Extract and examine plan files for breach configurations
    3. Document all observed parameter values and combinations

    Write findings to:
    .claude/outputs/win32com-automation-expert/rasexamples-breach-patterns.md
    """
)
```

**Consult example-notebook-librarian** for additional context:
- See `.claude/agents/example-notebook-librarian.md` for notebook conventions
- The librarian maintains the index of all example notebooks in `examples/AGENTS.md`
- Example notebooks often contain research already done on specific features

### Iterative Expansion Process

1. **Start with introspection** - Discover all method names
2. **Categorize methods** - Group by prefix (Output_, Geometry_, Plan_, etc.)
3. **Test each category** - Document parameters and return values
4. **Mine RasExamples** - Extract valid patterns from official examples
5. **Build reference** - Consolidate into comprehensive documentation
6. **Version compare** - Note differences across HEC-RAS versions
7. **Update agent** - Add new patterns to this file's Quick Reference

---

## Delegating to Code Archaeologist

### When to Delegate

The **hecras-code-archaeologist** agent can be called for tasks requiring deep
internal knowledge that surface-level COM inspection cannot provide:

| Task | Delegate To |
|------|-------------|
| "What are valid values for `Manning's n` format?" | hecras-code-archaeologist |
| "How does HEC-RAS parse breach parameters?" | hecras-code-archaeologist |
| "What internal flags affect 2D computation?" | hecras-code-archaeologist |
| "Document the .rasmap file format" | hecras-code-archaeologist |
| "Understand storage area connection algorithm" | hecras-code-archaeologist |

### Delegation Pattern

When an automation task requires understanding internal file formats or algorithms:

```python
# Example: Need to understand valid gate operation types for automation
Task(
    subagent_type="hecras-code-archaeologist",
    model="sonnet",
    prompt="""
    Investigate the internal handling of inline gate operations in HEC-RAS.

    Goal: Document all valid gate operation types and their parameters
    so the win32com-automation-expert can generate valid gate schedules.

    Focus areas:
    1. What enum values are valid for gate operation type?
    2. What parameters does each type require?
    3. How does RasUnsteady.dll parse these from plan files?

    Write findings to:
    .claude/outputs/hecras-code-archaeologist/gate-operation-types.md
    """
)
```

### Common Delegation Scenarios

**Plain Text File Format Discovery**:
```python
# Need to generate valid geometry file content
Task(
    subagent_type="hecras-code-archaeologist",
    prompt="""
    Investigate how RasGeom.dll parses cross section data.

    Document:
    - Fixed-width column positions
    - Valid value ranges
    - Special handling for bank stations
    - Edge cases in parsing

    Output: .claude/outputs/hecras-code-archaeologist/xs-format-internals.md
    """
)
```

**Algorithm Understanding**:
```python
# Need to understand computational behavior for automation validation
Task(
    subagent_type="hecras-code-archaeologist",
    prompt="""
    Investigate the unsteady flow iteration algorithm in RasUnsteady.dll.

    Document:
    - Convergence criteria
    - Maximum iteration handling
    - What triggers "Maximum iterations exceeded" warning

    Output: .claude/outputs/hecras-code-archaeologist/unsteady-iteration-algorithm.md
    """
)
```

**HDF Structure Discovery**:
```python
# Need to understand HDF output for custom extraction
Task(
    subagent_type="hecras-code-archaeologist",
    prompt="""
    Document undocumented HDF dataset attributes used by RASMapper.

    Focus: /Results/Unsteady/Output/Output Blocks/*/attributes

    Output: .claude/outputs/hecras-code-archaeologist/hdf-undocumented-attrs.md
    """
)
```

### Workflow: Recursive Documentation

For comprehensive automation documentation, use iterative delegation:

```
1. win32com-automation-expert discovers COM method signature
2. Method has undocumented parameter (e.g., "nType")
3. Delegate to hecras-code-archaeologist to find valid values
4. Archaeologist decompiles and documents enum values
5. win32com-automation-expert updates method documentation
6. Repeat for other undocumented parameters
```

---

## Troubleshooting

### COM Registration Issues

```bash
# Check registered HEC-RAS COM servers
reg query "HKEY_CLASSES_ROOT" /s /f "HECRASController" 2>nul
```

### HEC-RAS Won't Close

```python
# Force terminate by PID
import os
os.system(f"taskkill /PID {pid} /F")
```

### RASMapper Not Opening

RASMapper may take minutes to load large projects:
```python
RasGuiAutomation.open_rasmapper(timeout=600)  # 10 minutes
```

---

## See Also

- **hecras-code-archaeologist**: Deep internal understanding of HEC-RAS binaries
- **Remote Execution**: `.claude/rules/hec-ras/remote.md` - session_id=2 requirement
- **RasControl Source**: `ras_commander/RasControl.py`
- **GUI Automation Source**: `ras_commander/RasGuiAutomation.py`

---

*This agent focuses on practical automation using documented interfaces. For deep
internal understanding (algorithms, data structures, reverse engineering), use
hecras-code-archaeologist.*
