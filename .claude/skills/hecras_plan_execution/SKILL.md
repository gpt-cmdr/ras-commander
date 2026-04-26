---
name: hecras_plan_execution
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
description: |
  Decision support for HEC-RAS execution strategy. Analyzes project inspector output
  to recommend which plans to run, execution mode, and optimal parameters. Provides
  structured execution plans with dependency ordering, prerequisite validation, and
  resource-aware parameter recommendations.
  Use when planning execution strategy, selecting execution mode, determining plan
  order, validating prerequisites, or optimizing parallel execution parameters.
  Triggers: plan execution, execution strategy, which plans to run, execution order,
  parallel vs sequential, compute_plan, compute_parallel, mode selection, prerequisites,
  dependencies, runnable plans, blocked plans, execution plan, batch strategy.
---

# Planning HEC-RAS Execution

Analyze the Project Inspector output and generate an actionable execution plan. Select the optimal execution mode, recommend parameters, and identify blockers.

## Primary Sources

**Read the primary sources below; do not duplicate their content.**

- **`.claude/rules/hec-ras/execution.md`** - Complete execution mode documentation
- **`.claude/agents/hecras-project-inspector.md`** - Project Intelligence Report schema
- **`.claude/skills/hecras_compute_rascontrol/SKILL.md`** - Legacy HEC-RAS (< 6.0)

---

## Mode Selection Decision Tree

```
1. Is HEC-RAS version < 6.0?
   YES -> Use RasControl (hecras_compute_rascontrol skill)
   NO  -> Continue

2. How many runnable plans?
   ZERO    -> Report blockers, stop
   ONE     -> compute_plan() [+ stream_callback if monitoring needed]
   MULTIPLE -> Continue to step 3

3. Multiple Plan Decision:
   Debugging/diagnosing? -> compute_test_mode()
   Have remote workers?  -> compute_parallel_remote()
   Production/batch?     -> compute_parallel()
```

### Mode Selection Matrix

| Context | Plans | Mode | Rationale |
|---------|-------|------|-----------|
| Debugging | Any | `compute_test_mode()` | Sequential, single folder |
| Single plan, monitoring | 1 | `compute_plan()` + callback | Real-time output |
| Single plan, quick | 1 | `compute_plan()` | Simplest API |
| Multiple plans, production | 2+ | `compute_parallel()` | Fastest throughput |
| Distributed infrastructure | 2+ | `compute_parallel_remote()` | Scale-out |
| HEC-RAS < 6.0 | Any | `RasControl` | COM-based required |
| Resume interrupted | 2+ | `compute_parallel(skip_existing=True)` | Skips completed |

---

## Input: Project Intelligence Report

Expect this input format from the Project Inspector Agent:

```markdown
## Plans Analysis
| Plan | Title | Status | Geometry | Flow | Issues |
|------|-------|--------|----------|------|--------|
| 01 | Baseline | Runnable | g01 | u01 | None |
| 02 | Future | Missing geom | g03 (MISSING) | u02 | Geometry file not found |

### Execution Readiness
- **Ready to Run**: 01, 03
- **Blocked**: 02 (missing geometry g03)
```

---

## Output: Execution Plan

Generate structured execution plans in this format and return to the orchestrator:

```markdown
# Execution Plan

## Recommended Mode
`compute_parallel()` - Multiple runnable plans, production context

## Execution Order
1. Plan 01 (Baseline) - Ready
2. Plan 03 (Modified) - Ready
   [Skip: Plan 02 - blocked by missing geometry g03]

## Parameters
```python
RasCmdr.compute_parallel(
    plans_to_run=["01", "03"],
    max_workers=2,
    num_cores=4,
    force_rerun=False,
    verify=True
)
```

## Prerequisites
- None for runnable plans

## Blockers (Cannot Run)
| Plan | Issue | Resolution |
|------|-------|------------|
| 02 | Missing geometry g03 | Create geometry file or fix reference |

## Warnings
- Plan 02 blocked until g03 is created
```

---

## Parameter Recommendation

### Worker/Core Allocation

| System Cores | Model Type | `max_workers` | `num_cores` |
|--------------|------------|---------------|-------------|
| 4-8 | 1D | 2-4 | 2 |
| 8-16 | 2D | 2-4 | 4 |
| 16+ | Mixed | 4-6 | 4 |

**Formula**: `max_workers = min(num_plans, total_cores // num_cores)`

### Geometry Flags

| Scenario | `clear_geompre` | `force_geompre` |
|----------|-----------------|-----------------|
| Geometry unchanged | `False` | `False` |
| Minor edits (Manning's n) | `True` | `False` |
| Major changes (new mesh) | `False` | `True` |
| Geometry corruption | `False` | `True` |

### Skip/Rerun Flags

| Scenario | `force_rerun` | `skip_existing` |
|----------|---------------|-----------------|
| Normal (smart skip) | `False` | `False` |
| Force fresh results | `True` | `False` |
| Resume interrupted | `False` | `True` |

---

## Dependency Analysis

### Check for Blockers

```python
def get_runnable_plans(plan_df):
    """Identify which plans can execute."""
    runnable, blocked = [], {}

    for _, plan in plan_df.iterrows():
        plan_num = plan['plan_number']
        geom_ok = Path(plan['Geom Path']).exists() if plan.get('Geom Path') else True
        flow_ok = Path(plan['Flow Path']).exists() if plan.get('Flow Path') else True

        if geom_ok and flow_ok:
            runnable.append(plan_num)
        else:
            blocked[plan_num] = "Missing geometry" if not geom_ok else "Missing flow"

    return runnable, blocked
```

### Dependencies to Consider

1. **Shared Geometry** - Plans using same geometry can run in parallel
2. **Upstream/Downstream** - Cascade models need sequential execution
3. **DSS Dependencies** - Plans reading same DSS may conflict

---

## Context-Specific Templates

### Debugging Context

```python
RasCmdr.compute_test_mode(
    plans_to_run=["01", "02", "03"],
    dest_folder_suffix="[Debug]",
    num_cores=2,
    verify=True
)
```

### Production Context

```python
RasCmdr.compute_parallel(
    plans_to_run=["01", "02", "03"],
    max_workers=4,
    num_cores=4,
    verify=True
)
```

### Monitoring Context

```python
from ras_commander.callbacks import ConsoleCallback

RasCmdr.compute_plan(
    "01",
    stream_callback=ConsoleCallback(verbose=True),
    verify=True
)
```

---

## Common Blockers

| Blocker | Resolution |
|---------|------------|
| Missing geometry file | Create geometry or fix .prj reference |
| Missing flow file | Create flow file or fix reference |
| Missing DSS file | Download/create DSS or update path |
| Geometry HDF outdated | Run with `force_geompre=True` |
| Results already current | Use `force_rerun=True` if needed |
| HEC-RAS < 6.0 | Use RasControl skill instead |

---

## Cross-References

**Rules** (follow these):
- `.claude/rules/hec-ras/execution.md` -- Detailed execution mode parameters
- `.claude/rules/hec-ras/remote.md` -- Read when remote execution is needed

**Agents** (delegate when needed):
- `hecras-general-agent` -- Full workflow coordinator
- `hecras-project-inspector` -- Project analysis to inform mode selection
- `remote-executor` -- Remote execution setup and management

**Skills** (related workflows):
- `hecras_compute_plans` -- Downstream: execute plans using the selected mode
- `hecras_compute_remote` -- Downstream: distributed execution across workers
- `hecras_compute_rascontrol` -- Downstream: legacy COM execution

**Primary sources**:
- `ras_commander/AGENTS.md` -- Execution modes overview
- `ras_commander/RasCmdr.py` -- compute_plan, compute_parallel, compute_test_mode
