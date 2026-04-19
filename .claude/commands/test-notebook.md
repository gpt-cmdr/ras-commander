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

### 2. Preflight: Scan for GUI-Blocking Cells

Before delegating, grep the notebook for GUI automation markers:
- `wait_for_user`, `open_rasmapper`, `open_and_compute`, `run_multiple_plans`

If found, warn the user: "This notebook contains GUI automation cells that will block waiting for you to close HEC-RAS. The run will pause at those cells."

### 3. Resolve the Kernel

Run `jupyter kernelspec list` to discover available kernels. Select based on context:

**Default**: Use `RasCommander` kernel (pip-installed package) to validate end-user experience.

**Switch to `rascmdr_local`** only when the current work involves unpublished library changes.

**If neither canonical kernel exists**: Check for close matches (`rascommander`, `rascmdr`, `python3`). Ask the user which to use if ambiguous, and offer to set one up per `.claude/rules/testing/environment-management.md`.

### 4. Delegate to notebook-runner Subagent

**You MUST use the Agent tool** to delegate this work. The subagent chooses the appropriate execution mode (papermill, nbconvert, or nbmake) based on the goal.

Since `/test-notebook` is for **comprehensive development QA** (hide nothing, report all errors), the subagent should use **Mode B (nbconvert with allow-errors)** to ensure ALL cells execute even after failures. Mode A (papermill) stops at the first error, which misses downstream issues.

```python
Agent(
    subagent_type="notebook-runner",
    model="sonnet",
    prompt=f"""
    Execute and test this notebook: {notebook_path}
    Use kernel: {resolved_kernel_name}

    **DEVELOPMENT TEST MODE - Report ALL issues back to main agent.**

    Goal: comprehensive post-mortem — every cell must execute, even after errors.
    Use Mode B (nbconvert with allow-errors) for full coverage.
    If Mode B is unavailable, fall back to Mode A (papermill).

    Follow the standard artifact contract:
    - Create a timestamped folder under working/notebook_runs/
    - Produce: run_command.txt, stdout.txt, stderr.txt, audit.json, audit.md
    - Save the executed notebook as {stem}_executed.ipynb

    Use --execution-timeout 0 / --ExecutePreprocessor.timeout=-1 (no hard kill).

    Return:

    1. EXECUTION STATUS
       - Pass/Fail per cell
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

    Return a complete summary - the main agent needs full details to help the developer.
    """
)
```

### 5. Report Results Back to User

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

Agent identifies notebook from context, runs preflight scan, resolves kernel, delegates to notebook-runner, receives results, and reports back with complete error details.

## Key Principle

**Hide nothing.** Developers need to see:
- Minor warnings that might become problems
- Deprecation notices for future compatibility
- All stderr output
- Anything that indicates the notebook isn't working perfectly

## Cross-References

**Agents** (delegate to):
- `notebook-runner` -- Notebook execution (chooses mode based on goal)
- `notebook-output-auditor` -- Output review (downstream)
- `notebook-anomaly-spotter` -- Anomaly detection (downstream)
- `hecras-notebook-qaqc` -- HEC-RAS project linkage verification (downstream)

**Rules** (follow these):
- `.claude/rules/documentation/notebook-standards.md` -- Notebook conventions
- `.claude/rules/testing/environment-management.md` -- Canonical kernel names
