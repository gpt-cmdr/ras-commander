---
name: qa_review_triple-model
description: |
  Launch four independent AI code reviewers (Opus, Gemini, Codex, Kimi K2.5) to QA/QC code or notebooks.
  Each reviewer writes findings to separate markdown files, then orchestrator synthesizes.
  Use for critical code review, bug investigation, quality assurance tasks,
  validation of complex logic, cross-checking findings before major changes,
  edge case detection, or security reviews requiring thorough analysis.

  Triggers: triple review, quad review, four model review, independent code review, QAQC,
  quality assurance, multi-model analysis, cross-validation, bug investigation, critical review,
  kimi review, togetherai review, complex logic validation, security review, edge case detection
---

# Multi-Model Code Review (4 Models)

## Overview

This skill launches four independent AI subagents (Opus, Gemini, Codex, and **Kimi K2.5**) to perform parallel code review. Each agent writes findings to markdown files in a workspace directory, then the orchestrator synthesizes a final report with consensus findings.

## Usage

```
/triple_model_code_review [target] [focus_area]
```

**Examples**:
- `/triple_model_code_review examples/720_precipitation_methods_comprehensive.ipynb "plotting logic"`
- `/triple_model_code_review ras_commander/hdf/HdfResultsPlan.py "return type consistency"`
- `/triple_model_code_review ras_commander/precip/ "API contract validation"`
- `/triple_model_code_review src/auth/login.py "security vulnerabilities"`

## Workflow

1. **Create Workspace**: `workspace/{task}QAQC/{opus,gemini,codex,kimi,final}-analysis/`

2. **Launch 4 Parallel Subagents**:
   - **Opus** (general-purpose, model=opus): Deep reasoning, architecture analysis
   - **Gemini** (code-oracle-gemini): Large context, multi-file pattern analysis
   - **Codex** (code-oracle-codex): Code archaeology, API contract analysis
   - **Kimi K2.5** (code-oracle-kimi): Edge case detection, test generation focus, QA verification

3. **Handle Model Failures** (Graceful Degradation):
   - If a model fails or is unavailable, note it and continue
   - Synthesis works with 1-4 successful models
   - Report which models succeeded/failed to user

4. **Each Agent**:
   - Reads target files independently
   - Writes `qaqc-report.md` to their subfolder
   - Returns file path only (no large text in response)
   - If agent fails, creates empty report with error note

5. **Orchestrator Synthesizes**:
   - Reads all available reports (1-4)
   - Identifies consensus findings from successful models
   - Creates `FINAL_QAQC_REPORT.md` with agreement matrix
   - Highlights unique insights from each successful model
   - Notes which models were unavailable

## Subagent Prompts

### Opus Subagent

```
You are conducting an independent QA/QC analysis of [TARGET].

## Critical Issue
[DESCRIBE THE PROBLEM]

## Your Task
1. Read and analyze the target files
2. Identify root cause of the issue
3. Document specific line numbers and code evidence
4. Provide recommended fixes

## Output
Write comprehensive analysis to: workspace/[TASK]QAQC/opus-analysis/qaqc-report.md

Return ONLY the file path when complete.
```

### Gemini Subagent

```
You are conducting an independent QA/QC analysis using large context capabilities.

## Critical Issue
[DESCRIBE THE PROBLEM]

## Your Task
1. Read ALL relevant files in the target area
2. Trace data flow from source to symptom
3. Document column/type confusion if applicable
4. Provide method-by-method analysis

## Output
Write analysis to: workspace/[TASK]QAQC/gemini-analysis/qaqc-report.md

Return ONLY the file path when complete.
```

### Codex Subagent

```
You are conducting deep code analysis for QA/QC.

## Critical Issue
[DESCRIBE THE PROBLEM]

## Your Task
1. Deep analysis of target code
2. Code archaeology - how was bug introduced
3. API contract analysis - promises vs delivery
4. Test cases that would catch this bug

## Output
Write analysis to: workspace/[TASK]QAQC/codex-analysis/qaqc-report.md

Return ONLY the file path when complete.
```

### Kimi K2.5 Subagent (NEW)

```
You are conducting QA/QC analysis with focus on edge cases, testing gaps, and quality verification.

## Critical Issue
[DESCRIBE THE PROBLEM]

## Your Task
1. Identify edge cases and boundary conditions not handled
2. Find gaps in error handling and validation
3. Analyze test coverage - what tests are missing?
4. Check for race conditions and concurrency issues
5. Verify API contracts and type safety
6. Suggest specific test cases that would catch bugs

## Unique Focus Areas
- Edge case detection (null, undefined, empty inputs, extreme values)
- Test coverage gaps
- Error handling completeness
- Security vulnerabilities
- Performance bottlenecks

## Output
Write analysis to: workspace/[TASK]QAQC/kimi-analysis/qaqc-report.md

Return ONLY the file path when complete.
```

## Output Structure

```
workspace/{task}QAQC/
├── opus-analysis/
│   └── qaqc-report.md          # Deep reasoning analysis
├── gemini-analysis/
│   └── qaqc-report.md          # Large context analysis
├── codex-analysis/
│   └── qaqc-report.md          # Code archaeology analysis
├── kimi-analysis/              # NEW
│   └── qaqc-report.md          # Edge case & testing analysis
└── final-synthesis/
    └── FINAL_QAQC_REPORT.md    # Consensus findings
```

## Report Template

### Individual Reports

```markdown
# QA/QC Analysis Report: [Target]

**Analyst**: [Model Name]
**Date**: YYYY-MM-DD
**Target**: [file/folder]
**Status**: [CRITICAL/HIGH/MEDIUM/LOW]

## 1. Summary of Findings
## 2. Root Cause Analysis
## 3. Code Evidence (with line numbers)
## 4. Impact Assessment
## 5. Recommended Fixes
## 6. Verification Steps
## 7. Test Cases Needed (Kimi specific)
```

### Final Synthesis

```markdown
# Final QA/QC Synthesis Report

## Executive Summary
## Consensus Bug List
## Agreement Matrix (which reviewers found what)
  - Opus: [findings]
  - Gemini: [findings]
  - Codex: [findings]
  - Kimi: [findings]  # Edge cases & testing gaps
## Unique Insights by Model
  - Opus: [architectural issues]
  - Gemini: [multi-file patterns]
  - Codex: [API contract violations]
  - Kimi: [edge cases, missing tests, security gaps]
## Required Fixes (with exact code changes)
## Test Coverage Recommendations
## Verification Criteria
```

## Model Strengths Matrix

| Model | Best For | Unique Strengths |
|-------|----------|------------------|
| **Opus** | Architecture, logic flow | Deep reasoning, system design |
| **Gemini** | Large codebases | 1M+ token context, multi-file analysis |
| **Codex** | Implementation details | Code archaeology, API contracts |
| **Kimi K2.5** | Edge cases, testing | Boundary conditions, test gaps, security |

## Best Practices

1. **Be Specific**: Give clear problem description to all four agents
2. **Parallel Launch**: Launch all four agents in single message for speed
3. **File-Based Communication**: Agents write files, return paths only
4. **Consensus Focus**: Weight findings by agreement across reviewers
5. **Preserve Evidence**: Keep all reports in workspace for audit trail
6. **Consider Kimi's Edge Cases**: Kimi often finds issues others miss - don't ignore unique findings
7. **Test Generation**: Use Kimi's test recommendations to improve coverage

## Error Handling, Examples, and Troubleshooting

For graceful degradation protocols, example sessions, model failure troubleshooting, and partial results handling, see [references/error-handling-and-examples.md](references/error-handling-and-examples.md).

## Integration with Other Skills

**Works with:**
- `dev_invoke_kimi-cli` - Follow up with Kimi-specific testing
- `dev_invoke_gemini-cli` - Deep dive on Gemini findings
- `dev_invoke_codex-cli` - Implement fixes identified
- `using-git-worktrees` - Create isolated workspace for fixes

## See Also

- **Kimi CLI Skill**: `.claude/skills/dev_invoke_kimi-cli/SKILL.md`
- **Subagent Output Pattern**: `.claude/rules/subagent-output-pattern.md`
- **Agent Integration Testing**: `.claude/rules/testing/agent-integration-testing.md`
- **Orchestrator Pattern**: Root `CLAUDE.md` - Orchestrator section
