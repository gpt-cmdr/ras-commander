# feature_dev_notes Migration Audit Matrix

**Created**: 2025-12-12
**Updated**: 2025-12-12 Session 10
**Status**: Phase 2 - Migrations in Progress (4/9 migrated, 2 excluded, 44% complete)

## Subagent Audit Results

### Subagents with feature_dev_notes References

| Subagent | References Found | File(s) | Type | Priority | Status |
|----------|------------------|---------|------|----------|--------|
| **remote-executor** | docs_old/feature_dev_notes/RasRemote/REMOTE_WORKER_SETUP_GUIDE.md | SUBAGENT.md (3 refs: lines 8, 53, 400) | CRITICAL | HIGH | ✅ MIGRATED Session 9 (8855f76) |
| **hierarchical-knowledge-agent-skill-memory-curator** | Multiple feature_dev_notes refs | AGENT.md + 7 reference files | META | EXCEPTION | ✅ Documented Exception |
| **README.md** | General docs | .claude/subagents/README.md | DOCS | LOW | ⏳ Review Needed |

### Subagents WITHOUT feature_dev_notes References (Verified Clean)

| Subagent | Verified | Primary Source | Notes |
|----------|----------|----------------|-------|
| **claude-code-guide** | ✅ | Caches external docs | Documented exception |
| **documentation-generator** | ⏳ TBD | .claude/subagents/documentation-generator/ | Needs audit |
| **geometry-parser** | ⏳ TBD | .claude/subagents/geometry-parser/ | Needs audit |
| **git-operations** | ⏳ TBD | .claude/subagents/git-operations/ | Likely clean |
| **hdf-analyst** | ⏳ TBD | .claude/subagents/hdf-analyst/ | Needs audit |
| **precipitation-specialist** | ⏳ TBD | .claude/subagents/precipitation-specialist/ | Needs audit |
| **quality-assurance** | ⏳ TBD | .claude/subagents/quality-assurance/ | Needs audit |
| **usgs-integrator** | ⏳ TBD | .claude/subagents/usgs-integrator/ | Needs audit |

## feature_dev_notes Mapping to Subagents

### High Priority Mappings (Clear Ownership)

| feature_dev_notes Directory | Primary Subagent | Secondary Subagent(s) | Priority | Status |
|-----------------------------|------------------|----------------------|----------|--------|
| **cHECk-RAS** | quality-assurance | - | HIGH | ✅ MIGRATED Session 9 (b7b29b3) |
| **RasMapper Interpolation** | hdf-analyst | - | HIGH | ✅ MIGRATED Session 9 (ce40c94) |
| **parallel run agent** | remote-executor | - | HIGH | ✅ MIGRATED Session 9 (8855f76) |
| **Decompilation Agent** | (none - standalone) | hdf-analyst | HIGH | ✅ MIGRATED Session 8 |
| **precip/ + precipitation_investigation/** | precipitation-specialist | - | HIGH | ✅ MIGRATED Session 10 (6b6b1d3) |
| **gauge_data_import** | usgs-integrator | - | MEDIUM | 🔴 SKIP Session 10 - 100% redundant (ras_commander/usgs/) |
| **1D_Floodplain_Mapping** | geometry-parser | - | MEDIUM | 🔴 EXCLUDE Session 10 - Wrong domain (floodplain mapping) |
| **Build_Documentation** | documentation-generator | - | MEDIUM | ⏳ Pending |

### Medium Priority Mappings (Shared or Utility)

| feature_dev_notes Directory | Potential Owner(s) | Type | Priority |
|-----------------------------|-------------------|------|----------|
| **workflow_orchestration** | remote-executor | Utility | MEDIUM |
| **data_quality_validator** | quality-assurance | Tool | MEDIUM |
| **GHNCD_Comparison_Tool** | quality-assurance | Tool | MEDIUM |
| **RAS1D_BC_Visualization_Tool** | usgs-integrator | Tool | MEDIUM |
| **RAS2D_PostProcessing_UI** | hdf-analyst | Tool | MEDIUM |
| **Terrain_Mod_Profiler** | geometry-parser | Tool | LOW |
| **Soil_Stats_Tool** | precipitation-specialist | Tool | LOW |

### Low Priority Mappings (Documentation or Research)

| feature_dev_notes Directory | Type | Disposition |
|-----------------------------|------|-------------|
| **Example_Notebooks** | Docs | Review for patterns |
| **Research_Materials** | Docs | Keep as reference |
| **Specialist_Guides** | Docs | Extract to ras_agents |
| **Hierarchical_Knowledge_Approach** | Meta | Already documented |
| **00_New** | Staging | Review individually |
| **.old** | Archive | Ignore |

### Unassigned Directories (Needs Research)

| feature_dev_notes Directory | Notes |
|-----------------------------|-------|
| **agent_swarm_wisdom** | General agent patterns? |
| **api_consistency_auditor** | Quality assurance tool? |
| **FEMA Frisel Agent** | Specialized FEMA tool |
| **floodway analysis** | Geometry or HDF analysis? |
| **formalizing_example_functions** | Documentation task? |
| **HEC-RAS_Documentation_Agent** | Documentation generator? |
| **hecras-specialist** | General patterns? |
| **hms_ras_linking_agent** | Integration tool |
| **permutation_logic** | Execution patterns? |
| **Probabilistic_Flood_Risk_Analysis** | Analysis tool |
| **reproducible_research_facilitator** | Documentation tool? |
| **scientific_documentation_generator** | Documentation generator? |
| **Streamlit Go Consequences Interface** | UI tool |

## Migration Tasks by Priority

### Immediate (Session 9)

1. **remote-executor Migration**
   - Source: docs_old/feature_dev_notes/RasRemote/REMOTE_WORKER_SETUP_GUIDE.md
   - Destination: ras_agents/remote-executor-agent/reference/
   - Action: Create remote-executor-researcher sub-subagent
   - Execute: Migrate REMOTE_WORKER_SETUP_GUIDE.md
   - Update: .claude/subagents/remote-executor/SUBAGENT.md (remove docs_old refs)

### High Priority (Sessions 10-11)

2. **quality-assurance Migration**
   - Source: feature_dev_notes/cHECk-RAS/
   - Destination: ras_agents/quality-assurance-agent/
   - Action: Create quality-assurance-researcher sub-subagent
   - Execute: Extract QA patterns, validation rules

3. **hdf-analyst Migration**
   - Source: feature_dev_notes/RasMapper Interpolation/
   - Destination: ras_agents/hdf-analyst-agent/
   - Action: Create hdf-analyst-researcher sub-subagent
   - Execute: Extract interpolation algorithms, findings

4. **precipitation-specialist Migration**
   - Source: feature_dev_notes/National Water Model/
   - Destination: ras_agents/precipitation-specialist-agent/
   - Action: Create precipitation-specialist-researcher sub-subagent
   - Execute: Extract NWM workflows, data sources

### Medium Priority (Sessions 12-13)

5. **usgs-integrator Migration**
   - Source: feature_dev_notes/gauge_data_import/, RAS1D_BC_Visualization_Tool/
   - Destination: ras_agents/usgs-integrator-agent/
   - Action: Create usgs-integrator-researcher sub-subagent
   - Execute: Extract gauge workflows, BC generation

6. **geometry-parser Migration**
   - Source: feature_dev_notes/1D_Floodplain_Mapping/
   - Destination: ras_agents/geometry-parser-agent/
   - Action: Create geometry-parser-researcher sub-subagent
   - Execute: Extract floodplain mapping algorithms

7. **documentation-generator Migration**
   - Source: feature_dev_notes/Build_Documentation/
   - Destination: ras_agents/documentation-generator-agent/
   - Action: Create documentation-generator-researcher sub-subagent
   - Execute: Extract doc generation patterns

### Low Priority (As Needed)

8. **general-domain-researcher**
   - Source: All unassigned feature_dev_notes directories
   - Destination: TBD (based on findings)
   - Action: Comprehensive sweep of remaining directories
   - Execute: Identify cross-cutting patterns

## Research Sub-Subagent Creation Order

### Session 9 (Immediate)
1. **remote-executor-researcher** (template + execute)

### Session 10 (High Priority)
2. **quality-assurance-researcher**
3. **hdf-analyst-researcher**
4. **precipitation-specialist-researcher**

### Session 11 (Medium Priority)
5. **usgs-integrator-researcher**
6. **geometry-parser-researcher**
7. **documentation-generator-researcher**

### Session 12 (Final Sweep)
8. **general-domain-researcher**

## Success Metrics

### Before Migration (Session 8)
- Subagents with feature_dev_notes refs: 3 (remote-executor, hierarchical-knowledge, README)
- ras_agents: 1 (decompilation-agent)
- feature_dev_notes directories: 33 total
- Gitignored references: 3+ instances

### Current State (Session 10)
- Subagents with feature_dev_notes refs: 0 active (hierarchical-knowledge is documented exception)
- ras_agents: 5 (decompilation, remote-executor, quality-assurance, hdf-analyst, precipitation-specialist)
- Domains migrated: 4/9 (44%)
- Domains excluded: 2 (usgs-integrator redundant, geometry-parser wrong domain)
- Files migrated: 53 files, ~20,047 KB
- Security audits: 4 completed (1 CRITICAL redaction, 3 clean)
- Future features identified: 3 data downloaders (terrain, NLCD, SSURGO) added to roadmap

### After Migration (Target State)
- Subagents with feature_dev_notes refs: 0 (except documented exceptions)
- ras_agents: 9-10 (all domains needing reference data)
- feature_dev_notes directories: Same (experimental space)
- Gitignored references: 0 in production agents

### Key Performance Indicators
- ✅ All production subagents reference only tracked content
- ✅ Each migrated agent has lightweight navigator (200-400 lines)
- ✅ Single source of truth maintained
- ✅ Zero duplication across ras_agents
- ✅ feature_dev_notes remains for experimentation

## Next Steps

1. ✅ Complete this audit matrix
2. Create remote-executor-researcher sub-subagent (first template)
3. Execute first migration (remote-executor)
4. Validate pattern, refine template
5. Create remaining research sub-subagents
6. Execute migrations in priority order
7. Final audit and cleanup
8. Update hierarchical knowledge best practices

## Related Documents

- `planning_docs/FEATURE_DEV_NOTES_MIGRATION_PLAN.md` - Master migration strategy
- `.claude/rules/documentation/hierarchical-knowledge-best-practices.md` - Migration patterns
- `ras_agents/README.md` - Agent organization guidelines
- `ras_agents/decompilation-agent/AGENT.md` - Migration example

---

**Status**: Audit matrix created, ready for Phase 2 (Research Sub-Subagents)
**Next Session**: Create remote-executor-researcher and execute first migration
