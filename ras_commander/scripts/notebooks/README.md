# Notebook Audit Tooling

Utilities for auditing Jupyter notebooks without executing them.

## Overview

This directory contains tools for scanning example notebooks for issues, generating audit digests, and supporting the notebook testing workflow.

**Core Tool**: `audit_ipynb.py` - Scans notebooks for exceptions, anomalies, and security leaks

**Related Subagents**:
- `.claude/subagents/notebook-runner.md` - Executes notebooks and generates artifacts
- `.claude/subagents/example-notebook-librarian.md` - Notebook quality and conventions
- `.claude/subagents/notebook-output-auditor.md` - Reviews exception/stderr digests (Haiku)
- `.claude/subagents/notebook-anomaly-spotter.md` - Reviews unexpected behavior (Haiku + H&H expert)

## audit_ipynb.py

### Purpose

Scans Jupyter notebook outputs **without executing them** to identify:

1. **Stored Exceptions**: `output_type: "error"` in saved outputs
2. **Stderr Outputs**: Warning/error messages in stderr stream
3. **Anomalies**: Empty results, missing files, suspicious values
4. **Security Leaks**: Absolute paths with usernames, private network IPs

### Usage

**Audit all example notebooks** (default):
```bash
python scripts/notebooks/audit_ipynb.py
```

**Audit specific notebook**:
```bash
python scripts/notebooks/audit_ipynb.py examples/11_2d_hdf_data_extraction.ipynb
```

**Custom output directory**:
```bash
python scripts/notebooks/audit_ipynb.py --out-dir working/notebook_runs/manual_audit_01
```

**CI mode** (fail if errors found):
```bash
# Exit with code 1 if any error outputs found
python scripts/notebooks/audit_ipynb.py --fail-on-error-outputs

# Exit with code 1 if any security leaks found
python scripts/notebooks/audit_ipynb.py --fail-on-security-leaks
```

### Output Artifacts

**Default location**: `working/notebook_runs/<timestamp>/`

**Files generated**:
- `audit.json` - Structured findings (machine-readable)
- `audit.md` - Combined summary (human-readable)
- `audit_<notebook>.md` - Individual notebook reports

**Example output structure**:
```
working/notebook_runs/20251214_103045/
├── audit.json                               # All findings, structured
├── audit.md                                 # Combined summary table
├── audit_11_2d_hdf_data_extraction.md       # Individual report
├── audit_12_2d_hdf_data_extraction.md
└── ...
```

### Scan Categories

#### 1. Stored Exceptions

**What**: Cells with saved exception outputs

**Pattern**: `output_type: "error"` in notebook JSON

**Why Bad**: Indicates notebook was committed with failures

**Example Finding**:
```markdown
### Cell [12]: FileNotFoundError
**Error Value**: `Muncie.p01.hdf not found`
**Traceback**:
...
FileNotFoundError: [Errno 2] No such file or directory: 'Muncie.p01.hdf'
```

#### 2. Stderr Outputs

**What**: Warning/error messages in stderr stream

**Pattern**: `output_type: "stream"` with `name: "stderr"`

**Why Reviewed**: May indicate deprecation warnings, resource issues

**Example Finding**:
```markdown
### Cell [8]
DeprecationWarning: `np.find_common_type` is deprecated.
Use `np.result_type` or `np.promote_types` instead.
```

#### 3. Anomalies

**What**: Unexpected behavior patterns in outputs

**Patterns Detected**:
- `0 rows`, `empty`, `no data` - Empty results
- `file not found`, `does not exist` - Missing files
- `0 maps generated` - RASMapper no-output
- `all NaN` - Invalid data
- `-999`, `-9999` - Sentinel values

**Example Finding**:
```markdown
### Cell [15]: empty_results
**Pattern**: `0 rows`
**Context**:
DataFrame: 0 rows × 5 columns
Index: []
Columns: [river, reach, xs_id, wse, timestamp]
```

#### 4. Security Leaks

**What**: Sensitive information in saved outputs

**Patterns Detected**:
- Windows paths: `C:\Users\<username>\`
- Unix paths: `/home/<username>/`
- Private IPs: `192.168.x.x`, `10.x.x.x`, `172.16-31.x.x`

**Example Finding**:
```markdown
### Cell [5]: windows_path_leak
**Usernames Leaked**: billk
**Context**:
Project path: C:\Users\billk\Documents\ras-commander\examples\...
```

**Why Critical**: Should NOT be committed to public repository

### Integration with Subagents

**Workflow**:

1. **notebook-runner** executes notebooks → generates outputs
2. **audit_ipynb.py** scans outputs → generates `audit.json` + `audit.md`
3. **notebook-runner** checks digest size:
   - If small (<50KB) → Direct review
   - If large (>50KB) → Delegate to Haiku reviewers
4. **notebook-output-auditor** (Haiku) → Reviews exceptions/stderr
5. **notebook-anomaly-spotter** (Haiku + H&H) → Reviews anomalies + engineering validation
6. **notebook-runner** → Combines findings and reports back

**Example**:
```bash
# 1. Run notebook
pytest --nbmake examples/11_2d_hdf_data_extraction.ipynb -vv > run_01/stdout.txt 2> run_01/stderr.txt

# 2. Generate audit
python scripts/notebooks/audit_ipynb.py examples/11_2d_hdf_data_extraction.ipynb --out-dir run_01

# 3. Review audit.md (or delegate to Haiku if large)
cat run_01/audit.md

# 4. If issues found, fix notebook and re-run
```

## Anomaly Detection Details

### Empty Results

**Triggers**:
- Regex: `\b0\s+rows?\b`
- Regex: `\bempty\s+(dataframe|array|list)\b`
- Regex: `\bno\s+data\b`

**Common Causes**:
- Plan execution failed silently
- Wrong time index for result extraction
- HDF dataset path incorrect

### Missing Files

**Triggers**:
- Regex: `file not found`
- Regex: `does not exist`
- Regex: `no such file`

**Common Causes**:
- RasExamples.extract_project() path wrong
- compute_plan() didn't create HDF
- Wrong destination folder

### Sentinel Values

**Triggers**:
- Regex: `-9{3,}(?:\.\d+)?` (matches -999, -9999, -999.0)

**Common Causes**:
- No-data values in HDF
- Plan didn't converge
- Results not written to HDF

## Security Leak Detection

### Path Leaks

**Windows Pattern**:
```regex
[A-Z]:\\Users\\([^\\]+)\\
```

**Unix Pattern**:
```regex
/home/([^/]+)/
```

**Fix**:
- Use relative paths in outputs
- Redact before committing
- Re-run with clean environment

### IP Leaks

**Patterns** (RFC1918 private addresses):
- `10.0.0.0/8`: `\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b`
- `172.16.0.0/12`: `\b172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3}\b`
- `192.168.0.0/16`: `\b192\.168\.\d{1,3}\.\d{1,3}\b`

**Fix**:
- Don't print remote worker IPs in outputs
- Redact network configuration details
- Use placeholder values for documentation

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Audit Notebooks

on: [push, pull_request]

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'

      - name: Audit notebooks
        run: |
          python scripts/notebooks/audit_ipynb.py \
            --fail-on-error-outputs \
            --fail-on-security-leaks

      - name: Upload audit results
        if: always()
        uses: actions/upload-artifact@v2
        with:
          name: notebook-audit
          path: working/notebook_runs/
```

### Pre-Commit Hook Example

```bash
#!/bin/bash
# .git/hooks/pre-commit

echo "Auditing notebooks..."
python scripts/notebooks/audit_ipynb.py \
  --fail-on-error-outputs \
  --fail-on-security-leaks

if [ $? -ne 0 ]; then
  echo "❌ Notebook audit failed. Fix issues before committing."
  exit 1
fi

echo "✅ Notebook audit passed"
```

## Future Enhancements

**Planned Features**:
- H&H validation integration (WSE ranges, velocity checks)
- Expected behavior registry (per-notebook acceptable patterns)
- Output size tracking (flag notebooks with excessive outputs)
- Cross-notebook duplicate detection (repeated helpers)
- Notebook metadata validation (title cell, kernel selection)

**Proposed Tools**:
- `clean_ipynb.py` - Clear outputs and redact sensitive data
- `execute_ipynb.py` - Execute with reproducibility tracking
- `compare_ipynb.py` - Diff notebook outputs across runs

## See Also

- **Notebook Standards**: `.claude/rules/documentation/notebook-standards.md`
- **Testing Philosophy**: `.claude/rules/testing/tdd-approach.md`
- **Notebook Index**: `examples/AGENTS.md`
- **Subagents**: `.claude/subagents/notebook-*.md`
- **Review Findings**: `feature_dev_notes/Example_Notebook_Holistic_Review/`
