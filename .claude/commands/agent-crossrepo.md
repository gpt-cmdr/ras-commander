You are initiating a cross-repository coordination request between ras-commander and hms-commander.

## Cross-Repo Coordination Protocol

**Key Principles:**
1. Cross-repo awareness exists ONLY at the AI/documentation layer - NOT in Python code
2. All handoffs require explicit HUMAN approval before proceeding
3. Communication happens through markdown files in `feature_dev_notes/cross-repo/` or `agent_tasks/cross-repo/`
4. Python APIs remain completely independent

## Your Task

1. **Identify the request type:**
   - Research/Future Feature → Use `feature_dev_notes/cross-repo/`
   - Immediate Implementation → Use `agent_tasks/cross-repo/`

2. **Create the request file:**
   - Use naming convention: `{YYYY-MM-DD}_{source}_to_{target}_{topic}.md`
   - Source is current repo (ras-commander)
   - Target is sibling repo (hms-commander at `C:\GH\hms-commander`)

3. **Use the appropriate template:**
   - Research: `feature_dev_notes/cross-repo/_TEMPLATE_research_request.md`
   - Implementation: `agent_tasks/cross-repo/_TEMPLATE_implementation_request.md`

4. **Fill out the request completely** including:
   - Clear summary of what is needed
   - Background and context
   - Relevant files in this repo
   - Expected output from sibling repo
   - Any constraints or requirements

5. **Stop and inform the user:**
   - Explain what request was created
   - Tell them the file path
   - Instruct them to review, then open hms-commander and provide the request context
   - Remind them that YOU CANNOT directly communicate with the other repo's agent

## Sibling Repository Info

| Repository | Path | Purpose |
|------------|------|---------|
| ras-commander | `C:\GH\ras-commander` | HEC-RAS automation (current) |
| hms-commander | `C:\GH\hms-commander` | HEC-HMS automation (sibling) |

## Example Workflow

```
1. You create: agent_tasks/cross-repo/2024-12-13_ras_to_hms_dss-export.md
2. You stop and tell user: "Request created. Please review, then open hms-commander."
3. User reviews request
4. User opens hms-commander, provides context
5. hms-commander agent implements, writes response
6. User brings response back here
7. You integrate with user oversight
```

Remember: NO direct AI-to-AI communication. The human is always in the loop.
