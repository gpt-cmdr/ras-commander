Perform a general cleanup pass on the repository. This is for periodic maintenance, NOT task-specific cleanup (use `/agent-taskclose` for that).

## Context Difference

| Command | When | Context Level | Aggressiveness |
|---------|------|---------------|----------------|
| `/agent-taskclose` | End of task | Maximum (knows task files) | High - consolidate & clean task artifacts |
| `/agent-cleanfiles` | Periodic | Limited (general scan) | Moderate - clean completed tasks, flag uncertain |

## 1. Agent Tasks Cleanup (DO THIS FIRST)

**Review `agent_tasks/.agent/BACKLOG.md` for completed tasks:**

### Identify Completed Tasks
Scan BACKLOG.md for tasks marked `[x]` or in the "Completed" section:
- Note task IDs (e.g., `gauge-001`, `lib-001`, `gui-001`)
- Check if they have associated folders in `agent_tasks/tasks/`

### Archive Completed Task Folders
For each completed task with a folder in `agent_tasks/tasks/`:

```
agent_tasks/tasks/{task-id}-{name}/
├── TASK.md      # Task description
├── RESULT.md    # Completion summary
└── {files}      # Working files
```

**Action**: Move entire folder to `agent_tasks/.old/tasks/`
```bash
# Example
mv agent_tasks/tasks/gui-automation-integration agent_tasks/.old/tasks/
```

### Clean Orphaned Task Files
Check for standalone files in `agent_tasks/` that relate to completed work:
- Planning documents for completed features
- Session handoffs that are now stale
- Research notes incorporated elsewhere

**Action**: Move to `agent_tasks/.old/planning/` or `agent_tasks/.old/sessions/`

### Update STATE.md Reference
If STATE.md references completed tasks as "current focus", note this for user to update.

## 2. Subagent Outputs Cleanup

**Scan `.claude/outputs/` for stale outputs:**

### Identify Stale Outputs
- Files older than 30 days with no references
- Outputs superseded by newer analysis
- Findings already incorporated into permanent hierarchy

### Archive Stale Outputs
**Move to `.old/`**: Outdated but potentially useful for reference
**Move to `.old/recommend_to_delete/`**: Obviously temporary or failed outputs

## 3. Feature Dev Notes Cleanup

**Scan `feature_dev_notes/` for completed feature research:**

### Cross-Reference with BACKLOG.md
- If feature is marked complete, research notes may be archivable
- Check if insights were extracted to permanent locations

### Archive Completed Research
Move to `feature_dev_notes/.old/` (create if needed)

## 4. General Repository Cleanup

**Scan for accumulated clutter:**

- Root directory orphaned files
- Temporary test outputs
- Debug artifacts
- Duplicate content across locations

## Non-Destructive Actions

**Move to `.old/`**: Files that are outdated but may have reference value

**Move to `.old/recommend_to_delete/`**: Files that appear to be:
- Temporary/scratch (naming suggests temp use)
- Obviously incorrect or failed outputs
- Clear duplicates
- Orphaned artifacts

**DO NOT delete** - always move so user can review

## Flag Uncertain Files

If you can't determine a file's purpose or relevance:
- List it in your output for user decision
- Don't move it - you lack context

## Output Summary

Provide a structured summary:

```markdown
## Cleanup Pass - {Date}

### Completed Tasks Archived
| Task ID | Folder | Moved To |
|---------|--------|----------|
| gui-001 | agent_tasks/tasks/gui-automation-integration | agent_tasks/.old/tasks/ |

### Orphaned Task Files Archived
- {file}: {reason} → {destination}

### Subagent Outputs Archived
- {file}: {reason} → {destination}

### Feature Research Archived
- {folder}: {reason} → {destination}

### Moved to .old/recommend_to_delete/
- {file}: {reason}

### Flagged for User Decision
- {file}: {uncertainty}

### Suggested Updates
- STATE.md: {suggestion}
- BACKLOG.md: {suggestion}
```

## Consult When Needed

For complex organizational decisions:
- Use the hierarchical-knowledge-agent-skill-memory-curator subagent
- Or flag for user decision

---

**Remember**: This is a PERIODIC maintenance pass. You have LIMITED context about why files exist. Be aggressive with clearly completed tasks, but conservative with uncertain files.
