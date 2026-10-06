# Contribution checks

Supporting detail for the `ras-commander-contributing` skill. In a repository clone, that repository's `AGENTS.md`, `CONTRIBUTING.md`, and `.github/` templates take precedence over this summary.

## Versions and platform

Report installed versions with `importlib.metadata`; do not infer them from source folders.

```python
import importlib.metadata as md
import platform
import sys

for name in ("ras-commander", "hms-commander", "ras-commander-mcp", "hms-commander-mcp"):
    try:
        print(name, md.version(name))
    except md.PackageNotFoundError:
        print(name, "not installed")
print("python", sys.version.split()[0])
print("platform", platform.platform())
```

Add the HEC-RAS or HEC-HMS version when the engine is involved. Omit hostnames and usernames.

## Checks before a PR

| Check | Applies to | ras-commander | hms-commander | MCP repositories |
|---|---|---|---|---|
| Regression test | Every defect fix | `pytest` test under `tests/` | `pytest` test under `tests/` | Repository test suite |
| Targeted and affected tests | Every change | `python -m pytest <paths>` | `python -m pytest <paths>` | Repository instructions |
| Technical Writing Auditor | Changed docs, docstrings, messages, skills, release notes | `technical-writing-auditor` skill | `AGENTS.md` authoring rules, reviewed with the `ras-commander` auditor skill when available | Repository instructions |
| API consistency criteria | New or changed public API | `.claude/agents/api-consistency-auditor.md` and `CONTRIBUTING.md` | `CONTRIBUTING.md` and `STYLE_GUIDE.md` | MCP scope criteria below |
| Plugin contracts | Changed skills or plugin selection | `scripts/agent_framework` tests, bridge `--check`, `build_plugin.py` | Same | Not applicable |

Report each check as passed, failed, or not run, with the reason. Tests that need an installed engine may be unavailable on the host; say so rather than claiming a pass.

## API consistency criteria

A feature request or public API change states pass, fail, or not applicable for each criterion. Criteria 1–5 are the five API consistency auditor rules in each library's `CONTRIBUTING.md`. Criteria 6–8 restate related requirements from `AGENTS.md`, the pull request template, and the feature request template.

1. **Static class pattern.** Library classes are static namespaces unless listed as an instantiation exception (`.auditor.yaml` in `ras-commander`).
2. **`@log_call` on public methods.** Public methods use the repository logging decorator.
3. **`@staticmethod` on static-class methods.** Placed above `@log_call`.
4. **Parameter naming.** Standard names such as `plan_number` and `geom_file` in `ras-commander`, and `STYLE_GUIDE.md` names in `hms-commander`. Multi-project methods accept `ras_object=None` or `hms_object=None`.
5. **Path handling.** Path parameters accept both `str` and `pathlib.Path`.
6. **Consistent returns and schemas.** Tabular results return DataFrames. A new or changed project DataFrame column updates `schemas.py` in the same change. `__all__` lists new public names.
7. **Library-first execution.** Engine execution goes through the library APIs. In `ras-commander`, direct `Ras.exe` invocation is prohibited.
8. **Reusable scope.** The capability serves general HEC-RAS or HEC-HMS workflows and belongs in the chosen repository, not in one project's scripts.

For an MCP feature request, criterion 8 also requires the project MCP boundary: read-only, bounded, text-based, non-spatial and non-gridded output. A request for geometry, rasters, meshes, binary HDF or DSS reads, edits, or execution through MCP fails this criterion. Propose it for the Python API instead.

## Issue and PR content

| Field | Bug issue | Feature issue | PR |
|---|---|---|---|
| Summary | Observed problem | Problem or use case | Change and reason |
| Reproduction | Minimal synthetic or public example code | Example of intended use | Regression test |
| Expected and actual behavior | Required, with trimmed traceback | Not applicable | Before and after behavior |
| Versions and platform | Required | Optional | Versions tested |
| API consistency criteria | Not applicable | Required | Required for public API changes |
| Checks | Not applicable | Not applicable | Tests and audits with results |

Use the repository's `.github` templates when present. Link the issue from the PR when both exist.
