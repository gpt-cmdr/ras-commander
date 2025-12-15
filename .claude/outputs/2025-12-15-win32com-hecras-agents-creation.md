# Task Closeout: Win32COM & HEC-RAS Code Archaeologist Agent Creation

**Date**: 2025-12-15
**Task**: Create specialized HEC-RAS automation agents
**Status**: ✅ COMPLETE

## Summary

Created two specialized agents for HEC-RAS automation with complementary responsibilities:

1. **win32com-automation-expert** - Surface-level automation (COM + GUI)
2. **hecras-code-archaeologist** - Deep reverse engineering (renamed from dotnet-code-archaeologist)

## Files Created

### New Agent Files
| File | Lines | Purpose |
|------|-------|---------|
| `.claude/agents/win32com-automation-expert.md` | ~700 | Surface-level HEC-RAS automation via COM and GUI |
| `.claude/agents/hecras-code-archaeologist.md` | ~600 | Deep reverse engineering of HEC-RAS .NET assemblies |

### Output Directories Created
```
.claude/outputs/win32com-automation-expert/
.claude/outputs/hecras-code-archaeologist/
├── enum-references/
├── file-format-internals/
├── algorithm-summaries/
└── version-specific/
```

## Files Deleted

| File | Reason |
|------|--------|
| `.claude/agents/dotnet-code-archaeologist.md` | Renamed to hecras-code-archaeologist.md |

## Key Design Decisions

### 1. Two Separate Agents (Not Combined)

**Rationale**:
- Different user personas (automation engineers vs. debugging developers)
- Different tool chains (win32com/pywin32 vs. ILSpyCMD/decompilers)
- Different frequencies (daily automation vs. occasional deep dives)
- Different expertise domains (API usage vs. reverse engineering)

### 2. Delegation Pattern (Surface → Deep)

**Pattern**: win32com-automation-expert calls hecras-code-archaeologist when needing:
- Valid enum values for COM parameters
- Plain text file format internals
- Algorithm understanding for validation

**Example workflow**:
```
1. win32com-automation-expert discovers COM method signature
2. Method has undocumented parameter (e.g., "nType")
3. Delegate to hecras-code-archaeologist to find valid values
4. Archaeologist decompiles and documents enum values
5. win32com-automation-expert updates method documentation
```

### 3. RasExamples as Alternative Research Path

Both agents document using official HEC-RAS example projects as a research path:
- **RasExamples.extract_project()** provides known-good configurations
- Start with examples before decompiling assemblies (archaeologist)
- Mine examples for valid parameter combinations (win32com)
- Reference **example-notebook-librarian** for notebook context

### 4. Self-Improvement TODO Sections

Both agents include iterative research tasks for expanding documentation:

**win32com-automation-expert** (6 tasks):
1. COM Method Introspection
2. Output Methods Testing
3. Geometry Methods Testing
4. Plan Methods Testing
5. GUI Menu Structure Discovery
6. Version Comparison Study

**hecras-code-archaeologist** (6 tasks):
1. Enum Catalog - Complete Discovery
2. Cross Section Format Internals
3. Boundary Condition Types
4. 2D Mesh Data Structures
5. HDF Output Structure Discovery
6. Solver Algorithm Documentation

## Key Technical Content Documented

### win32com-automation-expert

1. **HECRASController COM Interface**
   - Version-specific ProgIDs (RAS66.HECRASController, etc.)
   - 25+ known COM methods documented
   - Output variable IDs table

2. **Process Topology**
   - 32-bit Ras.exe (hosts COM server)
   - 64-bit RASMapper.exe (NO COM - requires GUI automation)
   - 64-bit RasProcess.exe (compute engine)

3. **Win32 GUI Automation**
   - Window detection patterns
   - Menu enumeration
   - Dialog handling
   - Critical timing requirements

### hecras-code-archaeologist

1. **Workspace Isolation**
   - Reconstructed source → workspace/ (untracked)
   - Prose findings → .claude/outputs/ (tracked)

2. **Key HEC-RAS Assemblies**
   - RasMapperLib.dll, RasGeom.dll, RasUnsteady.dll, RAS.dll
   - Priority and purpose for each

3. **Search Pattern Library**
   - File format parsing patterns
   - Enum discovery patterns
   - Algorithm patterns (iteration, convergence)

4. **Legal Framework**
   - Fair use basis for interface discovery
   - Clean-room documentation requirements
   - No redistribution of reconstructed source

## Knowledge Placement

### Patterns Discovered → Now Documented

| Knowledge | Location |
|-----------|----------|
| Agent delegation pattern | Both agent files (Delegating section) |
| RasExamples research approach | Both agent files (Alternative Research Path) |
| Process topology | win32com-automation-expert.md |
| COM ProgID versions | win32com-automation-expert.md |
| Workspace isolation | hecras-code-archaeologist.md |
| Legal framework for reverse engineering | hecras-code-archaeologist.md |

## Files to Move to .old/

| File | Reason |
|------|--------|
| `.claude/outputs/dotnet-code-archaeologist-implementation-plan.md` | Superseded by hecras-code-archaeologist.md |

## Context for Future Sessions

### win32com-automation-expert Usage
- Trigger phrases: "win32com", "HECRASController", "COM interface", "GUI automation"
- Primary sources: RasControl.py, RasGuiAutomation.py, notebooks 16 & 17
- Delegates to hecras-code-archaeologist for deep knowledge needs

### hecras-code-archaeologist Usage
- Trigger phrases: "decompile", "code archaeology", "internal algorithm", "enum values"
- Primary sources: ILSpyCMD workflow, workspace/code-archaeology/
- Called by win32com-automation-expert for file format internals

### Research Starting Points
- RasExamples.extract_project() for known-good configurations
- example-notebook-librarian for notebook context
- examples/AGENTS.md for notebook index

## Remaining Work

None - all planned tasks completed:
- ✅ Create win32com-automation-expert.md agent
- ✅ Add delegation pattern to win32com agent
- ✅ Rename dotnet-code-archaeologist to hecras-code-archaeologist
- ✅ Add self-improvement TODO sections to both agents
- ✅ Remove old dotnet-code-archaeologist.md file
- ✅ Create output directories for both agents
- ✅ Add RasExamples research path documentation

---
*Generated by ras-commander orchestrator during task closeout*
