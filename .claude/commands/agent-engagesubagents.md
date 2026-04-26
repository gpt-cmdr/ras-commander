Search through your agents and skills and make a detailed plan to execute the user's query. Use the agents to save context and use shared documents in agent_tasks as a form of memory and passive coordination layer.

First, list the proposed agents for the user's review and approval. Then, ultrathink and write a detailed execution plan that can be expanded and progress summaries noted by multiple agents, as well as a place to provide references to external files that document their individual work product and findings.

## Subagent Engagement Protocol

### 1. Plan and List Proposed Agents

Before dispatching, present the user with:
- Which subagents will be used
- What each subagent will do
- Expected output files and locations
- Estimated complexity (Haiku / Sonnet / Opus)

Wait for user approval before proceeding.

### 2. Model Selection Guidance

| Complexity | Model | Use When |
|------------|-------|----------|
| Simple, focused, fast | Haiku | Documentation lookup, file reads, scanning, summarization |
| Moderate, multi-step | Sonnet | Analysis, code generation, multi-file coordination |
| Complex, deep reasoning | Opus | Architecture decisions, cross-domain synthesis, hard problems |

Default to Sonnet unless there is clear reason to go up or down.

### 3. Context Handoff Pattern (Critical)

**Always pass context via file paths, never raw text.**

Correct pattern:
- Pass relative file paths in the subagent prompt
- Subagent reads those files for context
- Subagent writes output to .claude/outputs/{subagent}/{date}-{task}.md
- Subagent returns the output file path (not raw text)

Wrong pattern:
- Embedding large text blobs directly in the prompt
- Subagent returning large text instead of writing a file

Path format: Always use relative paths from repository root.
  CORRECT: agent_tasks/.agent/STATE.md
  CORRECT: .claude/outputs/hdf-analyst/analysis.md
  WRONG: C:/GH/ras-commander/agent_tasks/.agent/STATE.md (absolute)

### 4. Execution Plan File

Before dispatching agents, write an execution plan to agent_tasks:

Write to: agent_tasks/.agent/STATE.md or a task-specific folder.

Include:
- Task name and date
- List of agents with model, task, and expected output file
- Coordination notes (which agent feeds which)
- Progress checklist

### 5. Dispatch Pattern

Dispatch independent agents in the first wave.
After first wave completes, read output file paths and dispatch dependent agents.
Pass first-wave output file paths to second-wave agents via their prompt.

### 6. Collecting and Presenting Results

After all agents complete:
1. Read each output file
2. Synthesize key findings
3. Update agent_tasks/.agent/PROGRESS.md
4. Present summary to user with links to detailed output files

## Available Agent Roster

Consult .claude/agents/README.md for the full list. Key agents by domain:

| Domain | Agent |
|--------|-------|
| HEC-RAS execution | hecras-general-agent, remote-executor |
| HDF results | hdf-analyst, hecras-results-analyst |
| Geometry | geometry-parser |
| USGS integration | usgs-integrator |
| Quality assurance | quality-assurance |
| Documentation | documentation-generator, hec-hms-documentation-scout |
| Dev tooling | code-oracle-codex; code-oracle-gemini only on explicit Gemini request |
| Notebooks | notebook-runner, notebook-output-auditor, notebook-anomaly-spotter |

## Cross-References

**Rules** (follow these):
- .claude/rules/subagent-output-pattern.md -- Subagent output conventions (write files, return paths)

**Agents** (available for dispatch):
- .claude/agents/README.md -- Full agent registry with model assignments

**Commands** (related):
- /agent-taskupdate -- Update task state after agent runs
- /agent-taskclose -- Close out when all agents complete
