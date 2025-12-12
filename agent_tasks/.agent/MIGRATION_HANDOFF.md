# feature_dev_notes Migration Handoff

**Created**: 2025-12-12 Session 8
**Purpose**: Critical handoff information for feature_dev_notes → ras_agents migration
**Next Session**: Start with remote-executor-researcher

## 🚨 CRITICAL SECURITY REQUIREMENT 🚨

**BEFORE MIGRATING ANY CONTENT TO ras_agents (tracked in git)**:

1. **SECURITY AUDIT REQUIRED**: Review all content for sensitive information
2. **Check for**:
   - Passwords, credentials, API keys
   - IP addresses (192.168.x.x, specific hostnames)
   - Usernames (especially with credentials)
   - Connection strings with authentication
   - Any configuration that could expose infrastructure
3. **Action if found**:
   - REDACT sensitive values (replace with placeholders like `<PASSWORD>`, `<IP_ADDRESS>`)
   - GENERALIZE examples (use `example.com`, `192.0.2.1` RFC examples)
   - DOCUMENT what was redacted in findings report
4. **DO NOT COMMIT** sensitive information to tracked files

**User's Instruction**: "make sure we have a subagent review all of that documentation to ensure no passwords are being linked before we commit"

## Critical Context

### Problem Statement
**feature_dev_notes is gitignored** - automated agents cannot reference it. Content must migrate to **ras_agents** (tracked).

### Session 8 Accomplishments

**Part 1: ras_agents Infrastructure**
- Created ras_agents/ directory (tracked location)
- Migrated decompilation-agent from feature_dev_notes
- Documented ras_agents vs feature_dev_notes distinction
- Commits: 512f9f6, 96be7c2

**Part 2: Migration Planning**
- Created FEATURE_DEV_NOTES_MIGRATION_PLAN.md (540 lines)
- Created MIGRATION_AUDIT_MATRIX.md (260 lines)
- Identified 1 CRITICAL migration: remote-executor
- Commits: a431160, 61792dd

### CRITICAL FINDING: remote-executor References Gitignored Content

**File**: `.claude/subagents/remote-executor/SUBAGENT.md`
**References** (3 instances):
- Line 8: "docs_old/feature_dev_notes/RasRemote/REMOTE_WORKER_SETUP_GUIDE.md (setup)"
- Line 53: Full path reference
- Line 400: "Setup Guide" reference

**Source File**: `docs_old/feature_dev_notes/RasRemote/REMOTE_WORKER_SETUP_GUIDE.md`
- Size: 27,460 bytes (27KB)
- Status: EXISTS (verified in Session 8)
- Contains: Critical remote worker setup documentation

**Problem**: docs_old is gitignored (line 76 in .gitignore: `/docs_old`)

## Phase 2: Next Steps (Session 9 - IMMEDIATE)

### Task 1: Create remote-executor-researcher Sub-Subagent

**Location**: `.claude/subagents/remote-executor/researchers/remote-executor-researcher.md`

**Template** (use this):
```yaml
---
name: remote-executor-researcher
model: sonnet
tools: [Read, Grep, Glob]
working_directory: C:/GH/ras-commander
description: |
  Research docs_old/feature_dev_notes/RasRemote/ to identify critical remote
  execution content for migration to ras_agents/remote-executor-agent/.
  Search assigned directories, extract key patterns, document findings.
---

# Remote Executor Feature Dev Notes Researcher

## Mission
Review docs_old/feature_dev_notes/RasRemote/ and identify critical reference
content for migration to ras_agents/remote-executor-agent/.

## Assigned Directories
- docs_old/feature_dev_notes/RasRemote/ (verified exists, 27KB REMOTE_WORKER_SETUP_GUIDE.md)
- feature_dev_notes/parallel run agent/ (if exists)
- feature_dev_notes/workflow_orchestration/ (if exists)

## Research Protocol

1. **Search Phase**:
   - Read REMOTE_WORKER_SETUP_GUIDE.md (27KB)
   - Identify setup patterns, critical configs, warnings
   - List other .md files in RasRemote/
   - Grep for remote execution patterns

2. **SECURITY AUDIT** (CRITICAL - MUST DO BEFORE MIGRATION):
   - Scan for passwords, credentials, API keys
   - Check for IP addresses (may be sensitive)
   - Look for hostnames, usernames
   - Identify any sensitive configuration data
   - **If found**: Redact or generalize before migration
   - **Document**: What was redacted and why

3. **Categorize**:
   - CRITICAL: Must migrate (setup guide, configs, warnings)
   - USEFUL: Should migrate (examples, helper scripts)
   - EXPERIMENTAL: Leave in docs_old (test scripts, logs)
   - SENSITIVE: Redact or exclude (passwords, credentials)

4. **Document**:
   - Create findings report: remote-executor_MIGRATION_FINDINGS.md
   - List what to migrate, why critical, proposed structure
   - **Include security audit results**: What was redacted

4. **Propose Structure**:
   ```
   ras_agents/remote-executor-agent/
   ├── AGENT.md (200-400 lines, lightweight navigator)
   └── reference/
       ├── REMOTE_WORKER_SETUP_GUIDE.md (migrated)
       └── [other critical docs]
   ```

## Output
Create: `planning_docs/remote-executor_MIGRATION_FINDINGS.md`
```

### Task 2: Execute Research

**Spawn Task Tool**:
```python
Task(
    subagent_type="Explore",
    description="Research remote executor reference docs",
    prompt="""Use the remote-executor-researcher subagent to:
    1. Read docs_old/feature_dev_notes/RasRemote/REMOTE_WORKER_SETUP_GUIDE.md
    2. Scan other files in RasRemote/
    3. Categorize critical vs experimental
    4. Create remote-executor_MIGRATION_FINDINGS.md in planning_docs/
    """
)
```

### Task 3: Create ras_agents Structure

**After findings report**, create:
```
ras_agents/remote-executor-agent/
├── AGENT.md (lightweight navigator, 200-400 lines)
└── reference/
    └── REMOTE_WORKER_SETUP_GUIDE.md (copy from docs_old)
```

### Task 4: Update remote-executor SUBAGENT.md

**Remove lines referencing docs_old**:
- Line 8: Update to reference ras_agents/remote-executor-agent/
- Line 53: Update path
- Line 400: Update path

**Replace with**:
```markdown
**Primary Sources**:
- `ras_agents/remote-executor-agent/reference/REMOTE_WORKER_SETUP_GUIDE.md` - Complete setup guide
- `.claude/rules/hec-ras/remote.md` - Remote execution patterns
```

### Task 5: Commit Migration

```bash
git add ras_agents/remote-executor-agent/
git add .claude/subagents/remote-executor/SUBAGENT.md
git commit -m "Migrate remote-executor to ras_agents

- Created ras_agents/remote-executor-agent/
- Migrated REMOTE_WORKER_SETUP_GUIDE.md from docs_old (27KB)
- Updated SUBAGENT.md to reference ras_agents (removed docs_old refs)
- Research findings: planning_docs/remote-executor_MIGRATION_FINDINGS.md
"
```

## Remaining Migrations (Priority Order)

### High Priority (Session 10-11)
2. **quality-assurance** → feature_dev_notes/cHECk-RAS/
3. **hdf-analyst** → feature_dev_notes/RasMapper Interpolation/
4. **precipitation-specialist** → feature_dev_notes/National Water Model/

### Medium Priority (Session 11-12)
5. **usgs-integrator** → feature_dev_notes/gauge_data_import/
6. **geometry-parser** → feature_dev_notes/1D_Floodplain_Mapping/
7. **documentation-generator** → feature_dev_notes/Build_Documentation/

### Low Priority (Session 12-13)
8. **general-domain-researcher** → All unassigned directories

## Research Sub-Subagent Pattern

**Template Location**: planning_docs/FEATURE_DEV_NOTES_MIGRATION_PLAN.md (lines 167-209)

**Key Sections**:
1. YAML frontmatter (name, model, tools, working_directory, description)
2. Mission statement
3. Assigned directories
4. Research protocol (Search → Categorize → Document → Propose)
5. Output specification

**File Naming**: `{domain}-researcher.md`
**Location**: `.claude/subagents/{domain}/researchers/` OR as standalone

## Critical Files to Re-Read

**Migration Planning**:
- `planning_docs/FEATURE_DEV_NOTES_MIGRATION_PLAN.md` (540 lines) - Complete strategy
- `planning_docs/MIGRATION_AUDIT_MATRIX.md` (260 lines) - Audit results, priority order
- `agent_tasks/.agent/MIGRATION_HANDOFF.md` (THIS FILE) - Critical handoff info

**Hierarchical Knowledge**:
- `.claude/rules/documentation/hierarchical-knowledge-best-practices.md` - Migration patterns
- `ras_agents/README.md` - Agent organization guidelines
- `ras_agents/decompilation-agent/AGENT.md` - Successful migration example

**Current State**:
- `agent_tasks/.agent/STATE.md` - Current focus and next steps
- `.claude/subagents/remote-executor/SUBAGENT.md` - Lines 8, 53, 400 need updating

## Success Criteria for Session 9

- ✅ remote-executor-researcher created
- ✅ Research executed (findings report created)
- ✅ ras_agents/remote-executor-agent/ created
- ✅ REMOTE_WORKER_SETUP_GUIDE.md migrated
- ✅ remote-executor SUBAGENT.md updated (no docs_old refs)
- ✅ Pattern validated (ready to replicate for other domains)
- ✅ Committed to git

## Known Issues

1. **docs_old is gitignored** (line 76: `/docs_old`)
   - Content exists locally but not tracked
   - Migration copies to ras_agents (tracked)

2. **Multiple feature_dev_notes paths**:
   - `docs_old/feature_dev_notes/` (older location, gitignored)
   - `feature_dev_notes/` (current location, gitignored)
   - Both need migration to ras_agents

3. **hierarchical-knowledge-agent-skill-memory-curator**:
   - Has feature_dev_notes references (7 files)
   - Documented exception (meta-knowledge about system itself)
   - No migration needed

## Quick Reference Commands

**Check for docs_old refs**:
```bash
grep -rn "docs_old" .claude/subagents/ --include="*.md"
```

**Check for feature_dev_notes refs**:
```bash
grep -rn "feature_dev_notes" .claude/subagents/ --include="*.md"
```

**List docs_old/feature_dev_notes/RasRemote contents**:
```bash
ls -lah docs_old/feature_dev_notes/RasRemote/
```

**Count ras_agents**:
```bash
find ras_agents -name "AGENT.md" -o -name "README.md" | wc -l
```

## Session 8 Metrics

**Created**:
- 2 planning documents (805 lines total)
- 1 handoff document (this file)
- ras_agents infrastructure (decompilation-agent)

**Commits**:
- a431160: Migration planning documents
- 61792dd: STATE.md update
- Earlier: 512f9f6, 96be7c2 (ras_agents infrastructure)

**Identified**:
- 33 feature_dev_notes directories
- 10 subagents
- 8 high/medium priority migrations
- 1 critical immediate migration (remote-executor)

**Status**: Phase 1 (Audit) complete ✅, Phase 2 (Research) ready to start ⏳

---

**NEXT SESSION START HERE**:
1. Read this file (MIGRATION_HANDOFF.md)
2. Read FEATURE_DEV_NOTES_MIGRATION_PLAN.md
3. Read MIGRATION_AUDIT_MATRIX.md
4. Create remote-executor-researcher
5. Execute first migration
