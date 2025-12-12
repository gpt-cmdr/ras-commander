# feature_dev_notes to ras_agents Migration Plan

**Created**: 2025-12-12
**Purpose**: Systematically migrate critical reference data from feature_dev_notes (gitignored) to ras_agents (tracked)
**Status**: Planning Phase

## Problem Statement

**Critical Issue**: feature_dev_notes is gitignored, making it unreferenceable by automated agents.

**Current State**:
- feature_dev_notes contains ~33 subdirectories with development work
- Subagents may reference feature_dev_notes in their instructions
- Agents cannot reliably access gitignored content
- Critical domain knowledge scattered across untracked files

**Desired State**:
- All agent-referenceable content in ras_agents (tracked)
- feature_dev_notes remains for experimentation only
- Subagents reference only tracked locations
- Production-ready agents have complete reference materials

## Subagents Inventory

### Current Subagents (10 total)

1. **claude-code-guide** (exception - caches external docs)
2. **hierarchical-knowledge-agent-skill-memory-curator** (exception - meta-knowledge)
3. **documentation-generator**
4. **geometry-parser**
5. **git-operations**
6. **hdf-analyst**
7. **precipitation-specialist**
8. **quality-assurance**
9. **remote-executor**
10. **usgs-integrator**

## feature_dev_notes Inventory

### Directories Identified (33 total)

**Agent/Tool Directories**:
- agent_swarm_wisdom
- api_consistency_auditor
- cHECk-RAS
- data_quality_validator
- Decompilation Agent (✅ MIGRATED Session 8)
- FEMA Frisel Agent
- HEC-RAS_Documentation_Agent
- hecras-specialist
- hms_ras_linking_agent
- parallel run agent
- reproducible_research_facilitator
- scientific_documentation_generator
- workflow_orchestration

**Feature Development**:
- 1D_Floodplain_Mapping
- floodway analysis
- gauge_data_import
- National Water Model
- permutation_logic
- Probabilistic_Flood_Risk_Analysis
- RasMapper Interpolation

**Tools/Utilities**:
- Build_Documentation
- formalizing_example_functions
- GHNCD_Comparison_Tool
- RAS1D_BC_Visualization_Tool
- RAS2D_PostProcessing_UI
- Soil_Stats_Tool
- Streamlit Go Consequences Interface
- Terrain_Mod_Profiler

**Documentation/Research**:
- Example_Notebooks
- Hierarchical_Knowledge_Approach
- Research_Materials
- Specialist_Guides

**Staging**:
- 00_New (new/unorganized content)
- .old (archived content)

## Migration Strategy

### Phase 1: Audit (Current Phase)

**Objective**: Identify what needs to migrate

**Tasks**:
1. ✅ Create master migration plan (this document)
2. Audit each subagent for feature_dev_notes references
3. Map feature_dev_notes directories to responsible subagents
4. Identify critical vs experimental content

**Deliverables**:
- Audit matrix (subagent × feature_dev_notes mapping)
- Priority list for migration
- Reference cleanup tasks

### Phase 2: Research Sub-Subagents

**Objective**: Create specialized research agents for each domain

**Pattern**: Each subagent gets a research sub-subagent to audit feature_dev_notes

**Research Sub-Subagents to Create**:

1. **documentation-generator-researcher**
   - Search: Build_Documentation, Example_Notebooks
   - Output: Critical docs patterns, automation scripts

2. **geometry-parser-researcher**
   - Search: 1D_Floodplain_Mapping, Terrain_Mod_Profiler
   - Output: Geometry parsing edge cases, algorithms

3. **hdf-analyst-researcher**
   - Search: RasMapper Interpolation, RAS2D_PostProcessing_UI
   - Output: HDF analysis patterns, interpolation methods

4. **precipitation-specialist-researcher**
   - Search: National Water Model, gauge_data_import
   - Output: Precipitation workflows, data sources

5. **quality-assurance-researcher**
   - Search: cHECk-RAS, data_quality_validator
   - Output: QA patterns, validation rules

6. **remote-executor-researcher**
   - Search: parallel run agent, workflow_orchestration
   - Output: Remote execution patterns, worker configs

7. **usgs-integrator-researcher**
   - Search: gauge_data_import, RAS1D_BC_Visualization_Tool
   - Output: USGS workflows, boundary generation

8. **general-domain-researcher**
   - Search: All remaining directories
   - Output: Cross-cutting patterns, unassigned content

**Research Sub-Subagent Template**:
```yaml
---
name: {domain}-researcher
model: sonnet
tools: [Read, Grep, Glob]
working_directory: C:/GH/ras-commander
description: |
  Research feature_dev_notes to identify critical {domain} content for
  migration to ras_agents. Search assigned directories, extract key patterns,
  document findings, and propose migration structure.

  CRITICAL: Perform security audit before migration - check for passwords,
  credentials, IP addresses, and sensitive configuration.
---

# {Domain} Feature Dev Notes Researcher

## Mission
Systematically review feature_dev_notes directories assigned to {domain},
identify critical reference content, and prepare migration to ras_agents.

## Assigned Directories
[List of feature_dev_notes subdirectories]

## Research Protocol
1. Search each assigned directory for:
   - Documentation (*.md files)
   - Reference materials (guides, specifications)
   - Algorithms and patterns (code, pseudocode)
   - Critical warnings and lessons learned

2. **SECURITY AUDIT** (CRITICAL - DO BEFORE MIGRATION):
   - Scan for passwords, credentials, API keys
   - Check for IP addresses, hostnames, usernames
   - Identify connection strings with authentication
   - **If found**: REDACT or GENERALIZE before migration
   - **Document**: What was redacted and why

3. Categorize findings:
   - CRITICAL: Must migrate (core algorithms, reference data)
   - USEFUL: Should migrate (helper patterns, examples)
   - EXPERIMENTAL: Leave in feature_dev_notes (WIP, testing)
   - SENSITIVE: Redact or exclude (passwords, credentials)

4. Document in findings report:
   - What was found
   - Why it's critical
   - Proposed ras_agents location
   - Migration priority
   - **Security audit results**: What was redacted

5. Output: {domain}_MIGRATION_FINDINGS.md

## Success Criteria
- All assigned directories searched
- Critical content identified
- Migration proposal documented
- No feature_dev_notes references in final output
```

### Phase 3: Execute Migrations

**Objective**: Move critical content to ras_agents

**Process** (per domain):
1. Spawn research sub-subagent
2. Review findings report
3. Create ras_agents/{domain}-agent/ structure
4. Migrate reference materials
5. Update subagent to reference ras_agents
6. Verify no feature_dev_notes references remain

**Migration Checklist** (per agent):
- [ ] Research sub-subagent executed
- [ ] Findings report reviewed
- [ ] ras_agents/{agent-name}/ created
- [ ] AGENT.md written (200-400 lines, lightweight navigator)
- [ ] reference/ folder created (if needed)
- [ ] Content migrated from feature_dev_notes
- [ ] Subagent updated to reference ras_agents
- [ ] feature_dev_notes references removed
- [ ] Committed to git

### Phase 4: Cleanup

**Objective**: Remove feature_dev_notes references, document results

**Tasks**:
1. Audit all subagents for lingering feature_dev_notes references
2. Update hierarchical knowledge docs with all migrations
3. Document what remains in feature_dev_notes (experimental only)
4. Create MIGRATION_SUMMARY.md

## Prioritization

### High Priority (Immediate)

Agents with likely feature_dev_notes dependencies:

1. **quality-assurance** → cHECk-RAS (extensive QA patterns)
2. **precipitation-specialist** → National Water Model, gauge data
3. **remote-executor** → parallel run agent, workflow orchestration
4. **hdf-analyst** → RasMapper Interpolation (decompilation findings)

### Medium Priority (Next)

5. **usgs-integrator** → gauge_data_import, BC visualization
6. **geometry-parser** → 1D floodplain mapping, terrain tools
7. **documentation-generator** → Build_Documentation, example notebooks

### Low Priority (As Needed)

8. **git-operations** (likely no feature_dev_notes dependencies)
9. Unassigned feature_dev_notes directories (general research)

## Expected Outcomes

### Metrics

**Before Migration**:
- Subagents: 10 total
- ras_agents: 1 agent (decompilation-agent)
- feature_dev_notes references: Unknown (to be audited)
- Tracked agent reference data: Minimal

**After Migration**:
- Subagents: 10 total (unchanged)
- ras_agents: 7-10 agents (all domains with reference needs)
- feature_dev_notes references: 0 in subagents
- Tracked agent reference data: Complete for all production agents

### Success Criteria

- ✅ All subagents reference only ras_agents or .claude/rules
- ✅ No feature_dev_notes paths in subagent instructions
- ✅ Critical reference data tracked in git
- ✅ feature_dev_notes remains for experimentation only
- ✅ Migration documented in hierarchical knowledge best practices
- ✅ Each production agent has lightweight navigator (200-400 lines)
- ✅ Single source of truth maintained (no duplication)

## Estimated Effort

**Phase 1 (Audit)**: 1-2 hours
- Read all subagents
- Map feature_dev_notes directories
- Create audit matrix

**Phase 2 (Research Sub-Subagents)**: 2-3 hours
- Create 7-8 research sub-subagent definitions
- Test one research agent end-to-end
- Refine template

**Phase 3 (Execute Migrations)**: 4-8 hours (depends on findings)
- High priority agents: 1-2 hours each (4 agents = 4-8 hours)
- Medium priority agents: 30-60 min each (3 agents = 1.5-3 hours)
- Commits and verification: 1-2 hours

**Phase 4 (Cleanup)**: 1 hour
- Final audit
- Documentation updates
- Summary report

**Total**: 8-14 hours across multiple sessions

## Next Steps

### Immediate (This Session)

1. ✅ Create this master plan
2. Begin subagent audit for feature_dev_notes references
3. Create audit matrix (subagent × feature_dev_notes)

### Session 9 (Next)

1. Complete audit matrix
2. Prioritize migration order
3. Create first research sub-subagent (quality-assurance-researcher)
4. Execute first migration (quality-assurance → cHECk-RAS)

### Future Sessions

1. Execute remaining high-priority migrations
2. Create medium-priority research agents
3. Execute medium-priority migrations
4. Final cleanup and documentation

## Related Documents

- `.claude/rules/documentation/hierarchical-knowledge-best-practices.md` - Migration patterns
- `ras_agents/README.md` - Agent organization guidelines
- `ras_agents/decompilation-agent/AGENT.md` - First successful migration example
- `planning_docs/SESSION_SUMMARY_2025-12-11.md` - Phase 4 refactoring context

## Appendix: Audit Matrix Template

```
| Subagent | feature_dev_notes Directories | References Found | Priority | Status |
|----------|-------------------------------|------------------|----------|--------|
| quality-assurance | cHECk-RAS, data_quality_validator | TBD | High | Pending |
| precipitation-specialist | National Water Model, gauge_data_import | TBD | High | Pending |
| remote-executor | parallel run agent, workflow_orchestration | TBD | High | Pending |
| hdf-analyst | RasMapper Interpolation, RAS2D_PostProcessing_UI | TBD | High | Pending |
| usgs-integrator | gauge_data_import, RAS1D_BC_Visualization_Tool | TBD | Medium | Pending |
| geometry-parser | 1D_Floodplain_Mapping, Terrain_Mod_Profiler | TBD | Medium | Pending |
| documentation-generator | Build_Documentation, Example_Notebooks | TBD | Medium | Pending |
| git-operations | (likely none) | TBD | Low | Pending |
```

(To be populated during Phase 1 audit)
