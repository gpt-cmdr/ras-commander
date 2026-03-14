---
paths: .claude/**
---

# Agent Integration Testing Pattern

**Context**: Testing multi-agent workflows end-to-end
**Priority**: Medium - Ensures agent systems work correctly
**Auto-loads**: When testing agent implementations
**Discovered**: 2026-01-08 (HEC-RAS Operations System testing)

---

## Overview

Validate that multi-agent systems work together correctly through integration testing. Apply this pattern (which emerged from testing the HEC-RAS Operations System: inspect, plan, execute, analyze) when building systems of multiple agents and skills.

---

## Integration Test Workflow

### Phase 1: Component Testing

Test each agent/skill independently first:

```python
# Test agent X
result = Task(
    subagent_type="component-agent",
    prompt="Test with known input..."
)

# Verify output format matches schema
output = Read(result.output_path)
assert "Expected Section" in output
```

### Phase 2: Chaining Test

Verify handoff between components works correctly:

```python
# Component A produces output
output_a = Task(subagent_type="agent-a", prompt="Generate report...")

# Component B consumes output_a
output_b = Task(
    subagent_type="agent-b",
    prompt=f"Analyze report at {output_a.output_path}"
)

# Verify B correctly parsed A's output
```

### Phase 3: End-to-End Workflow

Run the complete workflow with real data:

```python
# Example: HEC-RAS inspect → execute → analyze

# 1. Extract test project
project_path = RasExamples.extract_project("Muncie", suffix="test")

# 2. Inspect
inspect_result = Task(
    subagent_type="hecras-project-inspector",
    prompt=f"Inspect {project_path}"
)

# 3. Execute (based on inspector recommendations)
exec_result = Task(
    subagent_type="general-purpose",
    prompt=f"Execute plan 01 at {project_path}"
)

# 4. Analyze
analysis_result = Task(
    subagent_type="hecras-results-analyst",
    prompt=f"Analyze plan 01 results at {project_path}"
)

# 5. Verify end-to-end success
```

---

## Validation Criteria

### Output Schema Validation

Verify each agent produces outputs matching its documented schema:

```python
# Read agent output
report = Read(output_path)

# Check required sections exist
assert "## Quick Summary" in report
assert "## Plans Analysis" in report
assert "## Execution Recommendations" in report

# Check structured content
assert "|" in report  # Tables present
assert "```python" in report  # Code examples present
```

### Data Flow Validation

Confirm information flows correctly between components:

```python
# Inspector identifies 3 runnable plans
inspect_output = Read(inspect_result.output_path)
assert "3 runnable" in inspect_output

# Planner recommends parallel execution
plan_output = Read(plan_result.output_path)
assert "compute_parallel" in plan_output

# Results analyst confirms 3 executions
analysis_output = Read(analysis_result.output_path)
assert "3 of 3" in analysis_output or "Plans executed: 3"
```

### Error Handling Validation

Ensure graceful degradation when components encounter issues:

```python
# Test with broken project (missing files)
result = Task(
    subagent_type="hecras-project-inspector",
    prompt="Inspect broken project..."
)

# Should detect issues, not crash
output = Read(result.output_path)
assert "Issues & Warnings" in output
assert "Missing" in output or "Not found" in output
```

---

## Real-World Testing Approach

### Use Example Projects

**Always test with real HEC-RAS projects** (never use mocks):

```python
from ras_commander import RasExamples

# Standard test projects
test_projects = {
    "simple_1d": "Muncie",
    "2d_mesh": "BaldEagleCrkMulti2D",
    "breach": "Dam Breaching"
}

for name, project in test_projects.items():
    path = RasExamples.extract_project(project, suffix=f"test_{name}")
    # Run integration test...
```

**Why**: Real projects have edge cases that synthetic data misses.

### Test Matrix

| Component | Test With | Validates |
|-----------|-----------|-----------|
| Project Inspector | Muncie | 1D/2D mixed, multiple plans |
| Project Inspector | BaldEagleCrk | 2D mesh focus |
| Execution Skills | All projects | Different model types |
| Results Analyst | Executed plans | HDF parsing, message extraction |

---

## Test Artifacts

### Create Test Summary Document

Write a summary after each integration test:

**Location**: `.claude/outputs/{system-name}/YYYY-MM-DD-integration-test-summary.md`

**Contents**:
```markdown
# Integration Test Summary: {System Name}

## Test Scope
- Components tested: [list]
- Test data: [projects used]
- Duration: X minutes

## Results
| Component | Test | Result |
|-----------|------|--------|
| Agent A | Test 1 | PASS |
| Agent B | Test 2 | PASS |

## Validation
- [ ] Output schemas match specifications
- [ ] Data flows correctly between components
- [ ] Error handling works gracefully
- [ ] Performance acceptable

## Issues Detected
[None or list]

## Artifacts Generated
- [List test outputs]
```

---

## Example: HEC-RAS Operations System Test

### Test Design

**System Under Test**:
- `hecras-project-inspector` agent
- `hecras_plan_execution` skill
- `hecras_compute_plans` skill
- `hecras-results-analyst` agent
- `hecras-general-agent` coordinator

**Test Workflow**:
```
1. Extract Muncie project
2. Inspector analyzes project → Project Intelligence Report
3. Planner recommends strategy → Execution Plan
4. Execute plan 01 → HDF results
5. Analyst interprets → Quality Assessment
6. Coordinator aggregates → Unified Report
```

**Validation**:
- ✅ Inspector report has all required sections
- ✅ Execution completed successfully (HDF created)
- ✅ Analyst correctly parsed compute messages
- ✅ Quality assessment accurate (PASS)

### Test Results

**Performance**: 31 seconds total (extraction → analysis)

**Outputs**:
- `2026-01-08-muncie-inspection.md` (Project Inspector)
- `2026-01-08-muncie-plan01-analysis.md` (Results Analyst)
- `2026-01-08-integration-test-complete.md` (Final validation)

**Status**: ✅ PASSED - All components working correctly

---

## Common Pitfalls

### ❌ Testing in Isolation Only

**Wrong**: Testing each component separately and assuming integration works.

**Right**: Verify component outputs are consumable by downstream components.

### ❌ Using Synthetic Data

**Wrong**: Creating fake HEC-RAS projects for testing.

**Right**: Use `RasExamples.extract_project()` for real-world validation.

### ❌ Not Validating Output Schemas

**Wrong**: Checking only that the agent runs without error, ignoring output format.

**Right**: Validate output matches the documented schema and downstream components can parse it.

### ❌ Skipping Error Cases

**Wrong**: Testing only the happy path.

**Right**: Test with missing files, broken references, and execution failures.

---

## Efficiency: Parallel Opus Subagent Strategy

### Implementation Pattern

Batch by dependencies when creating multiple independent agents/skills:

**Batch by Dependencies**:
```python
# Batch 1: No dependencies (parallel)
Task(subagent_type="general-purpose", model="opus", prompt="Create Agent A...")
Task(subagent_type="general-purpose", model="opus", prompt="Create Agent B...")
Task(subagent_type="general-purpose", model="opus", prompt="Create Skill C...")
# 4 agents in parallel = 4x faster

# Batch 2: Depends on Batch 1 (parallel within batch)
Task(subagent_type="general-purpose", model="opus", prompt="Create Agent D (uses A's output schema)...")
Task(subagent_type="general-purpose", model="opus", prompt="Create Agent E (uses C)...")

# Batch 3: Integration
Task(subagent_type="general-purpose", model="opus", prompt="Create coordinator...")
```

**Efficiency**: HEC-RAS Operations System used 3 batches:
- Batch 1: 4 parallel agents/skills
- Batch 2: 2 parallel agents
- Batch 3: 1 coordinator

**Time Savings**: ~1 hour vs ~3-4 hours sequential

---

## Integration Test Checklist

Complete all items before marking an agent system as complete:

- [ ] Each component tested independently
- [ ] Output schemas validated against specifications
- [ ] Handoff between components verified
- [ ] End-to-end workflow tested with real data
- [ ] Error handling validated (missing files, failures)
- [ ] Performance measured (execution time)
- [ ] Test artifacts documented
- [ ] README files updated with new components
- [ ] Integration test summary written

---

## Cross-References

**Rules** (related):
- `.claude/rules/testing/tdd-approach.md` -- General TDD patterns
- `.claude/rules/documentation/hierarchical-knowledge-best-practices.md` -- Agent architecture

**Agents** (test these):
- `hecras-general-agent` -- Primary integration test target
- `hecras-project-inspector` -- Component test target
- `hecras-results-analyst` -- Component test target

---

**Key Takeaway**: Integration testing validates multi-agent workflows by testing component outputs, data flow, and end-to-end execution with real HEC-RAS projects. Use parallel Opus subagents for efficient implementation.
