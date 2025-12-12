# HMS-Commander Coordination Notes

This document tracks coordination between ras-commander and hms-commander repositories for linked model workflows.

## Repository Locations

- **ras-commander**: `C:\GH\ras-commander\` (this repository)
- **hms-commander**: `C:\GH\hms-commander\` (sibling repository)

## Cross-Repository Features

### HMS-RAS Linked Model Workflows (TP-40 → Atlas 14)

**Goal**: Enable automated upgrade of linked HMS-RAS models from legacy TP-40 to modern Atlas 14 precipitation.

**Workflow Coordination**:

```
┌─────────────────────────────────────────────────────────────────┐
│                    HMS-RAS UPGRADE WORKFLOW                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  hms-commander                    Handoff       ras-commander   │
│  ──────────────                   ──────        ─────────────   │
│                                                                 │
│  1. Atlas 14 Upgrade              ─────▶        4. BC Mapping   │
│     - Replace TP-40 depths                      - Map outlets   │
│     - Update met models                         - Match to RAS  │
│                                                                 │
│  2. HMS Execution                 ─────▶        5. Flow Import  │
│     - Run upgraded models                       - Read DSS      │
│     - Generate flows (DSS)                      - Write BC files│
│                                                                 │
│  3. Flow Validation               ◀─────        6. Plan Suite   │
│     - Check hydrographs                         - Multi-event   │
│     - Export to DSS                             - Batch setup   │
│                                                                 │
│                                   ─────▶        7. RAS Execute  │
│                                                 - Parallel runs │
│                                                 - Results       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Agent Roles

### hms-commander Agents

**Atlas 14 Upgrade Agent** (status: ⏸️ planned, not implemented)
- **Research Complete**: Comprehensive `Atlas14_Update_Guide.md` (1,883 lines) exists
- **Core Implementation**: `HmsMet.update_tp40_to_atlas14()` method available
- **Agent Framework**: `AgentWorkflow` base class ready (agents/_shared/workflow_base.py)
- **Backlog Status**: `agent-atlas14-001` planned, waiting on framework completion
- Capabilities: Replace TP-40 with Atlas 14 precipitation
- Input: Legacy HMS project (.met files with TP-40 depths)
- Output: Upgraded HMS project + validation report + MODELING_LOG.md

**HMS Execution Agent** (status: check conversation history)
- Capabilities: Run HMS models, export DSS results
- Input: HMS project
- Output: DSS flow hydrographs

### ras-commander Agents

**BC Linking Agent** (status: planned)
- Capabilities: Map HMS outlets to RAS boundaries
- Input: HMS basin model, RAS geometry
- Output: Outlet-to-BC mapping

**Flow Import Agent** (status: planned)
- Capabilities: Convert HMS flows to RAS BC files
- Input: HMS DSS file, outlet mapping
- Output: RAS unsteady flow files

**Linked Plan Agent** (status: planned)
- Capabilities: Generate multi-event plan suites
- Input: Base RAS plan, event list, flow files
- Output: Suite of linked plans

## Communication Protocol

### File-Based Handoff

**Option A: Shared File System** (simplest)
```
shared_workspace/
├── hms_outputs/
│   ├── atlas14_upgraded.hms
│   ├── flows_10yr.dss
│   ├── flows_25yr.dss
│   └── validation_report.json
└── ras_inputs/
    ├── outlet_mapping.json
    ├── flow_bc_10yr.u01
    └── flow_bc_25yr.u02
```

**Option B: Agent Task Queue** (future)
```json
{
  "task_id": "hms-ras-001",
  "type": "linked_upgrade",
  "status": "hms_complete",
  "hms_outputs": {
    "dss_path": "flows_100yr.dss",
    "basin_outlets": ["OUT1", "OUT2", "OUT3"]
  },
  "next_agent": "ras-bc-linker"
}
```

### Validation Handoff

**HMS → RAS Validation Data**:
```json
{
  "hms_version": "4.11",
  "precipitation": "Atlas 14",
  "events": ["10yr", "25yr", "50yr", "100yr", "500yr"],
  "peak_flows": {
    "OUT1_100yr": 5432.1,
    "OUT2_100yr": 3210.5
  },
  "hydrograph_checksums": {
    "OUT1_100yr": "sha256:abc123..."
  }
}
```

## Research Requirements

### hms-commander Conversation History Review ✅ COMPLETE

**Date Reviewed**: 2025-12-10

**Key Findings**:

1. **Atlas 14 Documentation** ✅
   - Location: `test_project/2014.08_HMS/File Parsing Guide/A100_B100_Project/Atlas14_Update_Guide.md`
   - Comprehensive 1,883-line guide with step-by-step TP-40 → Atlas 14 conversion
   - Includes: NOAA PFDS data retrieval, HMS .met file modification, Python examples, validation workflows

2. **Core Implementation** ✅
   - Module: `hms_commander/HmsMet.py`
   - Methods: `update_tp40_to_atlas14()`, `set_precipitation_depths()`, `get_precipitation_method()`
   - Returns validation data: old depths, new depths, percent changes

3. **Agent Framework** ✅
   - Infrastructure ready: `agents/_shared/workflow_base.py`, `comparison_utils.py`
   - Features: Session save/resume, change tracking, quality verdicts (GREEN/YELLOW/RED)
   - Proven: A1000000 project (3.3 → 4.11 upgrade, 0.00% deviation)

4. **Atlas 14 Agent Status** ⏸️
   - Task `agent-atlas14-001` planned but not implemented
   - Dependency: Waiting on agent framework completion
   - Estimated effort: 6-8 hours

5. **Test Projects** ✅
   - Example: `test_project/2014.08_HMS/A100_B100/` (Region 3 TP-40 data)
   - Files: `1__24HR.met` (100-yr), `10__24HR.met` (10-yr)

6. **Common Issues** ✅
   - Documented: Subduration interpretation, units confusion, AEP selection, file corruption
   - Solutions: Python verification scripts included in guide

**Next Steps**: hms-commander to complete `agent-atlas14-001`, ras-commander to design BC linking

### Technical Integration Points

**Shared Dependencies** (both repositories):
- HEC Monolith libraries (DSS reading/writing)
- pyjnius (Java bridge)
- dataretrieval (USGS data)
- NOAA Atlas 14 API access

**ras-commander Assets for HMS-RAS**:
- `RasDss` - Read HMS DSS outputs
- `RasUnsteady` - Write boundary condition files
- `RasPlan.clone_plan()` - Multi-event plan creation
- `RasCmdr.compute_parallel()` - Batch execution
- `StormGenerator` - Atlas 14 data (for validation)

**hms-commander Assets for HMS-RAS** (to be confirmed):
- HMS model file parsing
- Atlas 14 precipitation depth lookup
- HMS execution automation
- DSS export utilities

## Example Application: HCFCD M3 Models

**Available Models**: 22 linked HMS-RAS models via `M3Model` class

**Test Workflow**:
1. Extract M3 model (e.g., Model C - Clear Creek)
2. Use hms-commander to upgrade HMS to Atlas 14
3. Execute HMS, generate flows
4. Use ras-commander to link flows to RAS
5. Run RAS scenarios
6. Compare TP-40 vs Atlas 14 results

**Expected Outcome**:
- Atlas 14 depths typically 10-30% higher than TP-40
- Resulting flows and stages will increase proportionally
- Validation metrics: peak flow difference, volume difference, timing

## Next Steps

### Immediate (Week 1-2)
- [ ] Review hms-commander conversation history
- [ ] Document existing Atlas 14 agent capabilities
- [ ] Identify test HMS-RAS linked model
- [ ] Design outlet-to-BC mapping algorithm

### Short-term (Week 3-6)
- [ ] Implement BC linking utilities in ras-commander
- [ ] Test with HCFCD M3 model
- [ ] Create cross-repository coordination protocol
- [ ] Develop validation workflow

### Long-term (Week 7-8)
- [ ] Complete linked plan generation
- [ ] Create example notebook
- [ ] Document HMS-RAS upgrade guide
- [ ] Test with multiple HCFCD models

## Notes

- hms-commander development should proceed in parallel with ras-commander
- Both repositories benefit from shared learnings and patterns
- Agent coordination protocol can evolve as both mature
- Consider eventual unified CLI tool for HMS-RAS workflows

**Last Updated**: 2025-12-10
**Status**: Planning phase
