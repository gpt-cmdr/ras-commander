We are ending the conversation after this message. Ultrathink and use your remaining output to perform comprehensive task closeout.

**CRITICAL**: You have maximum context RIGHT NOW about this task's working files, findings, and learnings. This context will be lost after this session. Extract and consolidate aggressively.

## 1. Knowledge Extraction (Do This First)

While you still have full context, extract valuable knowledge to persistent locations:

### Write Task Findings
Write a consolidated markdown file capturing:
- What was accomplished
- Key findings and decisions made
- Patterns discovered that could benefit future work
- Blockers encountered and how they were resolved (or remain unresolved)
- References to files created/modified

**Location**: `.claude/outputs/{relevant-subagent}/` or `agent_tasks/.agent/PROGRESS.md`

### Identify Knowledge Placement Opportunities
Ask yourself: Does any knowledge from this task belong in the permanent hierarchy?

| Knowledge Type | Placement Location |
|----------------|-------------------|
| Coding pattern discovered | `.claude/rules/{category}/` |
| Workflow learned | `.claude/skills/{skill}/` or update existing |
| Domain insight (HEC-RAS) | `ras_commander/{subpackage}/CLAUDE.md` |
| Best practice | `.claude/rules/` or root CLAUDE.md |
| Troubleshooting solution | Relevant CLAUDE.md or rules file |

**Action**: If significant, write/update the appropriate file. If minor, note it in your closeout findings for later review.

### Update Multi-Session State (if applicable)
If this task spans sessions via `agent_tasks/`:
- Update `STATE.md` with current snapshot
- Append to `PROGRESS.md` with session summary
- Update `BACKLOG.md` with completed/new items

## 2. Pre-Consolidation

**You know which outputs are related** - consolidate them now rather than leaving scattered files for later cleanup:

### Merge Related Outputs
If you created multiple small outputs during this task:
- Consolidate into single summary document
- Move originals to `.old/` with note "consolidated into {summary-file}"

### Deduplicate
If findings overlap with existing documentation:
- Merge into existing location (if appropriate)
- Or note the overlap in closeout documentation

### Cross-Reference
Add references between related documents so future agents can navigate.

## 3. Aggressive Task-Specific Cleanup

**Only you know which files are working artifacts for THIS task.** Clean them up now.

### Move to `.old/`
Files that are task-specific and no longer needed but may have reference value:
- Intermediate analysis files
- Superseded versions
- Research notes incorporated elsewhere
- Outputs from abandoned approaches

### Move to `.old/recommend_to_delete/`
Files that should probably be deleted (user reviews):
- Scratch/temporary files created during this session
- Failed or incorrect outputs
- True duplicates
- Test artifacts that served their purpose
- Debug outputs

### Leave In Place
Files that are:
- Part of the deliverable
- Referenced by other documents
- Needed for future sessions
- Permanent additions to the knowledge hierarchy

## 4. Closeout Documentation

Write a brief closeout note (can be in PROGRESS.md or standalone):

```markdown
## Session Closeout - {Date}

### Accomplished
- {What was done}

### Files Created/Modified
- {List with brief purpose}

### Files Moved to .old/
- {List with reason}

### Knowledge Extracted To
- {Permanent locations updated}

### Remaining Work (if any)
- {What's left, where to pick up}

### Context for Next Session
- {Key context that would be lost}
```

## 5. Final Verification

Before ending:
- [ ] Valuable knowledge extracted to persistent locations
- [ ] Related outputs consolidated (not scattered)
- [ ] Task-specific working files cleaned up
- [ ] Multi-session state updated (if applicable)
- [ ] Closeout documentation written
- [ ] No files deleted (only moved to `.old/` hierarchy)

---

**Remember**: The `/agent-cleanfiles` command exists for general cleanup passes, but THIS moment is when you have the context to properly classify and consolidate YOUR task's artifacts. Be aggressive about extraction and cleanup now.
