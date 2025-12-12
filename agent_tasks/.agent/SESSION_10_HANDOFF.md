# Session 10 Handoff - Continue feature_dev_notes Migrations

**Created**: 2025-12-12 (Session 9 closure)
**Purpose**: Handoff for Session 10 - Continue domain migrations
**Status**: 3/9 migrations complete (33%), 6 remaining

---

## Session 9 Accomplishments - Quick Summary

**Migrated 3 HIGH PRIORITY domains**:
1. ✅ **remote-executor** (8855f76) - 27KB setup guide, CRITICAL security redaction
2. ✅ **quality-assurance** (b7b29b3) - 13 FEMA specifications, ~10K lines
3. ✅ **hdf-analyst** (ce40c94) - 28 algorithm docs, clean-room ethics

**Security Protocol**: Validated 3x - prevented credential leak, excluded proprietary code

**Pattern Proven**: research → audit → selective migration → verify → commit (~45min/domain)

---

## Session 10 Strategy

### Target: Complete 2-3 More Migrations

**Recommended Order** (HIGH → MEDIUM priority):

1. **precipitation-specialist** → National Water Model
   - Source: `feature_dev_notes/National Water Model/`
   - Expected: AORC workflows, precipitation data integration
   - Estimated: 45 minutes

2. **usgs-integrator** → gauge_data_import
   - Source: `feature_dev_notes/gauge_data_import/`
   - Expected: Gauge workflows, BC generation (may be redundant with ras_commander/usgs/)
   - Estimated: 45 minutes

3. **geometry-parser** → 1D_Floodplain_Mapping
   - Source: `feature_dev_notes/1D_Floodplain_Mapping/`
   - Expected: Floodplain mapping algorithms
   - Estimated: 45 minutes

**Target Session Time**: 1.5-2.5 hours for 2-3 migrations

---

## Critical Files to Read First

**Before starting**:
1. `agent_tasks/.agent/STATE.md` - Current focus and session status
2. `planning_docs/SESSION_9_SUMMARY.md` - Complete Session 9 summary
3. `ras_agents/hdf-analyst-agent/AGENT.md` - Latest migration example (clean-room ethics)

**For each migration**:
1. Review `planning_docs/MIGRATION_AUDIT_MATRIX.md` - Domain mapping
2. Follow pattern from Session 9 findings reports

---

## Migration Workflow (Proven Pattern)

### Step 1: Create Researcher Sub-Subagent (5 min)

```bash
mkdir -p .claude/subagents/{domain}/researchers
# Create {domain}-researcher.md using template
```

**Template**: See `FEATURE_DEV_NOTES_MIGRATION_PLAN.md` lines 167-209

### Step 2: Execute Research (10-15 min)

```python
Task(
    subagent_type="Explore",
    description="Research {domain} docs",
    prompt="""Use {domain}-researcher to:
    1. List and review all files
    2. SECURITY AUDIT (mandatory)
    3. Categorize content
    4. Create findings report in planning_docs/
    """,
    model="sonnet"
)
```

### Step 3: Review Findings (5 min)

- Read `planning_docs/{domain}_MIGRATION_FINDINGS.md`
- Note security issues
- Identify files to migrate vs exclude

### Step 4: Create Structure and Migrate (20 min)

```bash
mkdir -p ras_agents/{domain}-agent/reference/{subdirs}
# Copy approved files with cp
# Apply redactions with sed if needed
```

### Step 5: Create AGENT.md (10 min)

**Target**: 200-400 lines lightweight navigator
- Primary sources section
- Quick reference
- Critical warnings (if applicable)
- Navigation map
- Migration notes

### Step 6: Verify Security (5 min)

```bash
# Check for sensitive data
grep -r -i -E "(password|192\.168|C:\\\\Users)" ras_agents/{domain}-agent/
# Should return ZERO results or only documentation references

# Check file types
find ras_agents/{domain}-agent/ -type f ! -name "*.md"
# Should return ZERO results (markdown only)
```

### Step 7: Commit (5 min)

```bash
git add .claude/subagents/{domain}/ planning_docs/{domain}_MIGRATION_FINDINGS.md ras_agents/{domain}-agent/
git commit -m "Migrate {domain} to ras_agents with security verification"
```

**Total Time**: ~45 minutes per domain

---

## Security Audit Checklist (MANDATORY)

For EVERY migration, scan for:

- [ ] **Passwords/Credentials**: Search for "password", "passwd", "credential", "api_key", "secret", "token"
- [ ] **IP Addresses**: Look for patterns `192.168.x.x`, `10.x.x.x`, real hostnames
- [ ] **Usernames**: Especially in file paths or examples
- [ ] **File Paths**: `C:\Users\username\`, `D:\`, machine-specific paths
- [ ] **Client Data**: Real project names, proprietary information
- [ ] **Proprietary Code**: Decompiled source, binaries, installers
- [ ] **Test Data**: Large binary files, HEC-RAS projects

**Action if found**:
- **REDACT**: Replace with generic placeholders
- **EXCLUDE**: Don't migrate proprietary/large content
- **DOCUMENT**: Note what was excluded and why

---

## Exclusion Guidelines

### Always Exclude

❌ **Decompiled source code** (.cs, .java files from decompilers)
❌ **Binaries** (.dll, .exe, .msi installers)
❌ **Large test data** (HEC-RAS projects > 100MB, raster files)
❌ **Scripts with hard-coded paths** (C:\Users, D:\M3, machine-specific)
❌ **Client/proprietary data** (real project names, sensitive configurations)

### Always Include (if clean)

✅ **Algorithm specifications** (behavioral descriptions)
✅ **Validation standards** (public FEMA/USACE standards)
✅ **API documentation** (RASMapper, HEC-RAS public APIs)
✅ **Research findings** (discoveries, analyses, methodologies)
✅ **Best practices** (design patterns, workflows)

### Review Case-by-Case

⚠️ **Code examples** - Redact hard-coded paths, make generic
⚠️ **Test scripts** - Extract logic, exclude machine-specific
⚠️ **Configuration files** - Generalize, remove sensitive data

---

## Expected Remaining Migrations

### precipitation-specialist

**Expected content**:
- AORC precipitation data workflows
- National Water Model integration
- Atlas 14 design storm procedures

**Security concerns**:
- API keys (if NOAA/NWM access)
- File paths (precipitation data storage)
- Client project examples

**Estimated size**: Medium (~100-200KB documentation)

### usgs-integrator

**Expected content**:
- Gauge data import workflows
- Boundary condition generation patterns
- USGS NWIS API usage

**Note**: Much of this may already exist in `ras_commander/usgs/CLAUDE.md`

**Estimated size**: Small-Medium (~50-100KB, may have high redundancy)

### geometry-parser

**Expected content**:
- 1D floodplain mapping algorithms
- Geometry parsing patterns
- Cross section interpolation

**Security concerns**:
- Client project geometries
- Proprietary floodplain methods

**Estimated size**: Medium (~100-200KB)

---

## Session 10 Success Criteria

✅ **Complete 2-3 migrations** (target 5-6/9 total, 55-67%)
✅ **All security audits PASS** (zero sensitive info committed)
✅ **All AGENT.md within range** (200-400 lines)
✅ **Findings reports created** for each migration
✅ **Efficient execution** (~45min per domain)
✅ **Documentation updated** (STATE.md, PROGRESS.md, audit matrix)

---

## Quick Commands Reference

### Check Migration Status

```bash
# Count ras_agents
ls ras_agents/ | grep "agent$" | wc -l

# List all AGENT.md files
find ras_agents/ -name "AGENT.md"

# Check for security issues
grep -r -i -E "(password|192\.168|C:\\\\Users)" ras_agents/
```

### Create Researcher Template

```bash
# Copy template from existing
cp .claude/subagents/hdf-analyst/researchers/hdf-analyst-researcher.md \
   .claude/subagents/{new-domain}/researchers/{new-domain}-researcher.md

# Edit to update domain-specific details
```

### Verify Migration Clean

```bash
# Should return ZERO non-markdown files
find ras_agents/{domain}-agent/ -type f ! -name "*.md"

# Should return ZERO sensitive strings
grep -r "Katzen84\|192\.168\.3\.8\|D:\\\\M3" ras_agents/{domain}-agent/
```

---

## Handoff Status

**Session 9**: ✅ COMPLETE
**Migrations**: 3/9 (33%)
**Security**: Protocol validated 3x
**Documentation**: All closure docs committed (ae04554)
**Working tree**: Clean for migration work
**Branch**: main (53 commits ahead of origin)
**Ready**: Session 10 continuation

---

**Next Action**: Start Session 10 by reading STATE.md, then execute next 2-3 migrations following proven pattern.
