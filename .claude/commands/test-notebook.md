Test the notebook currently being worked on using the notebook-runner subagent and report all results back.

## Purpose

Force delegation to the `notebook-runner` subagent for **development testing**. Use inline when working on a notebook to get comprehensive error reporting back to the main conversation.

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

### 2. Determine the Kernel

**Default**: Use the `rascommander` kernel (pip-installed package). This validates the end-user experience.

**Switch to local dev kernel** (`rascmdr` or `rascmdr_local`) only when:
- The current work involves unpublished library changes being tested
- The user explicitly requests local dev testing

**If neither kernel is available**: Ask the user which environment to use and offer to set one up.

### 3. Delegate to notebook-runner Subagent

**You MUST use the Agent tool** to delegate this work:

```python
Agent(
    subagent_type="notebook-runner",
    model="sonnet",
    prompt=f"""
    Execute and test this notebook using **papermill**: {notebook_path}
    Use kernel: {kernel_name}

    **DEVELOPMENT TEST MODE - Report ALL issues back to main agent.**

    Run via papermill (NOT nbconvert):
    ```
    papermill {notebook_path} working/notebook_runs/{stem}_executed.ipynb \
      --cwd {notebook_dir} \
      --kernel {kernel_name} \
      --no-progress-bar
    ```

    Use `--execution-timeout 0` (no hard kill) — let cells run to completion.
    If execution seems stuck, report which cell is blocking and why, but do NOT kill it.

    Return:

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
       - GUI automation cells (will block waiting for user)

    Write artifacts to: working/notebook_runs/

    Return a complete summary - the main agent needs full details to help the developer.
    """
)
```

### 4. Report Results Back to User

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

## GUI Automation Cells

Some notebooks (e.g., 120, 320, 600) contain cells that launch HEC-RAS GUI and wait for user interaction. These cells will **block indefinitely** during automated execution. The subagent should:
- Warn about GUI-blocking cells before execution
- Note them in the execution report
- Not treat them as failures

## Cross-References

**Agents** (delegate to):
- `notebook-runner` -- Notebook execution via papermill
- `notebook-output-auditor` -- Output review (downstream)
- `notebook-anomaly-spotter` -- Anomaly detection (downstream)
- `hecras-notebook-qaqc` -- HEC-RAS project linkage verification (downstream)

**Rules** (follow these):
- `.claude/rules/documentation/notebook-standards.md` -- Notebook conventions
