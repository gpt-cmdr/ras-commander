Test the notebook currently being worked on using the notebook-runner subagent and report all results back.

## Purpose

This command forces delegation to the `notebook-runner` subagent for **development testing**. Use it inline when working on a notebook to get comprehensive error reporting back to the main conversation.

## When to Use

You are already working on or discussing a notebook in the current conversation. Use this command to:
- Execute the notebook and validate it works
- Get ALL errors reported back (not just critical ones)
- Force proper subagent delegation for thorough testing

## Execution

### 1. Identify the Notebook from Context

Look at the current conversation to determine which notebook is being worked on:
- Recently edited notebook
- Notebook being discussed
- Notebook mentioned in recent file operations

If unclear, ask the user which notebook to test.

### 2. Delegate to notebook-runner Subagent

**You MUST use the Task tool** to delegate this work:

```python
Task(
    subagent_type="notebook-runner",
    model="sonnet",
    prompt=f"""
    Execute and test this notebook: {notebook_path}

    **DEVELOPMENT TEST MODE - Report ALL issues back to main agent.**

    Execute the notebook and return:

    1. EXECUTION STATUS
       - Pass/Fail
       - Which cells succeeded/failed
       - Total execution time

    2. ALL ERRORS (critical AND non-critical)
       - Full tracebacks (do not truncate)
       - Cell number where each error occurred
       - Error type and message

    3. ALL WARNINGS
       - Deprecation warnings
       - Resource warnings
       - UserWarnings
       - Any stderr output

    4. OUTPUT ANOMALIES
       - Empty outputs where content expected
       - Unexpected output patterns
       - Missing expected results

    5. EXECUTION NOTES
       - Import failures (even partial)
       - Slow cells (>30 seconds)
       - Print statements suggesting issues

    Write artifacts to: working/notebook_runs/

    Return a complete summary - the main agent needs full details to help the developer.
    """
)
```

### 3. Report Results Back to User

After receiving the subagent's response, present ALL findings to the user:

- Show every error, even minor ones
- Include full tracebacks
- Note cell numbers for failures
- List all warnings
- Suggest fixes where obvious

**Do not filter or minimize issues** - this is development testing.

## Example Usage

User is editing `examples/725_atlas14_spatial_variance.ipynb`:

```
User: /test-notebook
```

Agent identifies notebook from context, delegates to notebook-runner, receives results, and reports back with complete error details.

## Key Principle

**Hide nothing.** Developers need to see:
- Minor warnings that might become problems
- Deprecation notices for future compatibility
- All stderr output
- Anything that indicates the notebook isn't working perfectly

## See Also

- `.claude/agents/notebook-runner.md` - The subagent being invoked
- `.claude/rules/testing/environment-management.md` - Environment setup
