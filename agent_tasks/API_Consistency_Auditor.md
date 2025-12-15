# API Consistency Auditor - Task Tracking

**Status**: ⚪ Not Started (Phase 1 Planned)
**Priority**: 🔴 Critical - Pre-Sprint Requirement
**Created**: 2025-12-15
**Target Completion**: Phase 1 by 2026-01-05 (before next sprint)
**Owner**: Development Team
**Related Spec**: `feature_dev_notes/Subagents_Under_Construction/api_consistency_auditor/SPECIFICATION.md`

## Executive Summary

Build an AST-based static analysis tool to enforce ras-commander's API conventions automatically. Catches pattern violations before code review, ensuring consistency across 60+ modules.

**Critical Need**: Recent code additions (catalog.py, HdfPipe.py) show API inconsistencies (missing @staticmethod, @log_call). Next sprint involves new functions - need automated enforcement NOW.

## Scope

### Phase 1 (Pre-Sprint) - CRITICAL
**Timeline**: 2-3 weeks (Dec 16, 2025 - Jan 5, 2026)
**Goal**: Core auditor operational before next sprint

**Deliverables**:
1. AST parser extracting class/function metadata
2. Top 5 critical rules implemented
3. CLI tool (`ras-audit check`)
4. Clear violation reports with fix suggestions
5. Documentation and examples

**Rules**:
- ✅ Static class pattern detection
- ✅ `@log_call` decorator requirement
- ✅ `@staticmethod` decorator requirement
- ✅ Parameter naming (plan_number, ras_object)
- ✅ Path handling (Path/str acceptance)

**Out of Scope (Phase 1)**:
- Docstring validation (Phase 2)
- Pre-commit hooks (Phase 2)
- GitHub Actions integration (Phase 2)
- Auto-fix capabilities (Phase 2)

### Phase 2 (Post-Sprint) - Enhanced
**Timeline**: 3-4 weeks (Jan 2026 - Feb 2026)
**Goal**: Full-featured auditor with CI/CD integration

**Additional Deliverables**:
- Docstring completeness validation
- Pre-commit hook integration
- GitHub Actions workflow
- Optional auto-fix suggestions
- IDE integration guides

## Motivation

### Current Pain Points

1. **Manual Review Burden**: Maintainer catches issues in code review (time-consuming)
2. **Inconsistencies Slipping Through**: catalog.py shipped with missing decorators
3. **No Living Documentation**: Conventions exist in CLAUDE.md but not enforced
4. **Contributor Confusion**: New contributors unaware of static class pattern
5. **Technical Debt**: Inconsistencies accumulate over time

### Immediate Triggers

**Recent Violations Found**:
- `ras_commander/usgs/catalog.py` (v0.89.0+):
  - ❌ Missing `@staticmethod` on 5 functions
  - ❌ Missing `@log_call` on 5 functions
  - ❌ Not in static class (inconsistent with library pattern)

- `ras_commander/hdf/HdfPipe.py`:
  - ⚠️ 8/11 functions with `@staticmethod` (3 missing)
  - ⚠️ 10/11 functions with `@log_call` (1 missing)

**Next Sprint Risk**:
- User planning to add new functions
- Without auditor: high risk of repeating catalog.py mistakes
- Manual review catches issues late (wasted effort)

### Benefits

**Immediate**:
- Catch violations before merge (CI gate)
- Reduce maintainer burden (automated checking)
- Provide fix suggestions (actionable errors)
- Serve as live documentation (rules = code)

**Long-term**:
- Prevent technical debt accumulation
- Enable confident contributions (clear patterns)
- Consistent API across all modules
- Easier onboarding (automated guidance)

## Implementation Plan

See detailed plan: `feature_dev_notes/Subagents_Under_Construction/api_consistency_auditor/IMPLEMENTATION_PLAN.md`

### Phase 1 Weeks

**Week 1**: Core Infrastructure
- AST parser (ast module)
- Metadata extraction (classes, functions, decorators)
- Rule engine architecture
- Configuration loading (rules.yaml)

**Week 2**: Rule Implementation
- Top 5 critical rules coded and tested
- Violation detection logic
- Fix suggestion generation
- Test suite (50+ test cases)

**Week 3**: CLI & Documentation
- CLI tool (`ras-audit check`)
- Report formatting (clear, actionable)
- Usage documentation
- Example workflows
- Integration with existing codebase

### Success Criteria (Phase 1)

**Functional**:
- ✅ Detects all 5 critical pattern violations
- ✅ Provides clear, actionable error messages
- ✅ Runs in <5 seconds on full codebase
- ✅ Zero false positives on existing code
- ✅ CLI produces formatted reports

**Quality**:
- ✅ 90%+ test coverage
- ✅ Handles edge cases (nested classes, inheritance)
- ✅ Clear error messages with file:line:column
- ✅ Fix suggestions actionable (copy-paste ready)

**Documentation**:
- ✅ README with installation and usage
- ✅ Rule documentation (what, why, how to fix)
- ✅ Example violations and fixes
- ✅ Integration guide (CLI workflow)

## Pre-Work Required

### Immediate (Before Phase 1 Start)

1. **Fix catalog.py** ⚠️ BLOCKING
   - Convert to static class pattern (UsgsGaugeCatalog)
   - Add @staticmethod to all functions
   - Add @log_call to all functions
   - Ensures auditor baseline is clean

2. **Audit Recent Additions** ⚠️ BLOCKING
   - Check ras_commander/usgs/spatial.py
   - Check ras_commander/usgs/rate_limiter.py
   - Fix any violations found
   - Document baseline state

3. **Review Specification** ✅ COMPLETE
   - Specification exists and is comprehensive
   - 50+ rules defined across 6 categories
   - AST parsing examples provided
   - Integration guides included

### Optional (Nice to Have)

- Create `.auditor.yaml` config template
- Document exception cases (RasPrj, workers)
- List known conforming classes as test cases

## Task List

See detailed breakdown: `feature_dev_notes/Subagents_Under_Construction/api_consistency_auditor/TASK_LIST.md`

**Summary**:
- 15 Phase 1 tasks across 3 weeks
- 12 Phase 2 tasks for enhanced features
- 3 ongoing maintenance tasks

## Dependencies

**Technical**:
- Python 3.10+ (ast module, match statements)
- PyYAML (configuration)
- Click or argparse (CLI)
- pytest (testing)

**Knowledge**:
- ras-commander API patterns (.claude/rules/python/)
- Static class pattern (static-classes.md)
- Decorator usage (decorators.md)
- AST parsing (Python ast module)

**Blocking Tasks**:
- catalog.py fixes (must complete before Phase 1)
- Recent additions audit (identify baseline)

## Risks & Mitigation

### Risk 1: False Positives on Edge Cases
**Impact**: High (breaks developer trust)
**Likelihood**: Medium
**Mitigation**:
- Extensive test suite (50+ cases)
- Test against all existing ras_commander modules
- Document exception patterns (RasPrj, workers)
- Allow rule disabling via config

### Risk 2: Performance on Large Codebase
**Impact**: Medium (slow CI)
**Likelihood**: Low
**Mitigation**:
- Target <5 seconds for full scan
- Cache AST parsing results
- Parallel file processing
- Benchmark against 60+ modules

### Risk 3: Specification Drift
**Impact**: Low (rules become outdated)
**Likelihood**: Medium
**Mitigation**:
- Version rules.yaml
- Document rule rationale
- Review rules quarterly
- Update with library evolution

### Risk 4: Adoption Resistance
**Impact**: Medium (tool unused)
**Likelihood**: Low
**Mitigation**:
- Clear, actionable error messages
- Fix suggestions (not just complaints)
- Minimal false positives
- Easy to run (CLI + CI)

## Integration Points

### Existing Systems

**Hierarchical Knowledge**:
- Rules documented in `.claude/rules/python/`
- Auditor enforces documented patterns
- Violations reference rule files

**Subagents**:
- ras-commander-api-expert: Documents API patterns
- best-practice-extractor: Identifies patterns to enforce
- Auditor: Enforces extracted patterns

**CI/CD** (Phase 2):
- GitHub Actions workflow
- Pre-commit hook
- Block merge on violations

### Workflow Integration

**Development**:
```bash
# Before commit
ras-audit check ras_commander/

# Review violations
# Fix issues
# Re-run until clean
```

**Code Review**:
- Auditor runs in CI
- Violations block merge
- Reviewer focuses on logic, not patterns

**New Contributions**:
- Contributors run auditor locally
- Get immediate feedback
- Self-serve pattern guidance

## Metrics & Success

### Phase 1 Success Metrics

**Adoption**:
- All developers run auditor before commit
- Zero violations in new PRs (after adoption)
- CI gate blocks non-conforming code

**Quality**:
- 90%+ test coverage
- <5 second full codebase scan
- Zero false positives on existing code

**Impact**:
- 80% reduction in pattern-related review comments
- 100% detection of missing @staticmethod
- 100% detection of missing @log_call

### Phase 2 Success Metrics

**CI Integration**:
- GitHub Actions workflow active
- Pre-commit hook optional install
- Violation trends tracked over time

**Coverage**:
- All 50+ rules implemented
- Docstring validation operational
- Auto-fix suggestions for 50%+ violations

## Related Documents

**Specification**:
- `feature_dev_notes/Subagents_Under_Construction/api_consistency_auditor/SPECIFICATION.md`

**Planning**:
- `feature_dev_notes/Subagents_Under_Construction/api_consistency_auditor/IMPLEMENTATION_PLAN.md`
- `feature_dev_notes/Subagents_Under_Construction/api_consistency_auditor/TASK_LIST.md`

**Rules Documentation**:
- `.claude/rules/python/static-classes.md`
- `.claude/rules/python/decorators.md`
- `.claude/rules/python/path-handling.md`
- `.claude/rules/python/naming-conventions.md`

**Examples**:
- `ras_commander/RasCmdr.py` - Gold standard static class
- `ras_commander/hdf/HdfResultsPlan.py` - HDF method patterns
- `ras_commander/usgs/core.py` - Modern parameter naming

## Session Log

### 2025-12-15 - Task Creation (Session 17)
- **Status**: Task created, planning complete
- **Deliverables**:
  - Main task tracking (this file)
  - Implementation plan (IMPLEMENTATION_PLAN.md)
  - Detailed task list (TASK_LIST.md)
  - BACKLOG.md updated (Phase 0 added)
  - STATE.md updated (current focus)
- **Next**: Fix catalog.py violations, audit recent additions, begin Phase 1 Week 1

---

**Last Updated**: 2025-12-15
**Next Review**: 2025-12-22 (end of Week 1)
**Status Health**: 🟢 Green (ready to start)
