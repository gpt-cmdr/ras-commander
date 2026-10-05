---
name: ras-commander-contributing
description: "Handle a suspected defect or feature gap in RAS Commander, HMS Commander, or their MCP servers found during a task. Classify it, protect the user's work, then fix it through a maintainer pull request or draft an external issue or pull request. Use when library or MCP behavior appears wrong, or when a user asks to report a bug, request a feature, or contribute."
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
---

# RAS Commander contributing

Project policy: when a maintainer's agent finds a defect, it fixes the defect and opens a pull request (PR) right away. An external user may submit an issue or a PR. A feature request is proposed only when it passes the API consistency criteria.

This workflow covers `gpt-cmdr/ras-commander`, `gpt-cmdr/hms-commander`, `gpt-cmdr/ras-commander-mcp`, and `gpt-cmdr/hms-commander-mcp`. It never merges, tags, releases, or publishes a package.

## 1. Protect the user's task

Stop at the failing step and preserve the user's inputs and outputs. Do not edit the user's project, environment, or dependency pins to work around a library defect unless the user agrees. Record the call, sanitized arguments, traceback, engine version, and the package versions from the [version snippet](references/contribution-checks.md#versions-and-platform).

## 2. Classify the problem

| Class | Indicators | Action |
|---|---|---|
| Defect | A public API, MCP tool, or packaged skill contradicts its docstring, schema, or documented behavior; crashes on valid supported input; or regresses from an earlier release | Contribute a fix or a bug report |
| User or environment error | Wrong path or input, unsupported engine version, missing extra or engine, or a release older than the fix | Explain the correction; no report. A misleading error message is itself a defect |
| Unsupported scope | The request is outside a documented contract. Example: spatial, gridded, geometry, edit, or execution requests to a project MCP server | Route to the public Python API or explain the limit. This is not a bug |
| Feature gap | A reusable capability is absent from a supported workflow | Evaluate against the API consistency criteria |

Before calling something a defect, check the latest release and `main`, and search existing issues (`gh issue list --repo gpt-cmdr/<repo> --search "<terms>"`). If an issue exists, add new evidence there instead of opening a duplicate.

## 3. Find the owning repository

Use the deepest traceback frame inside a Commander package, not the caller's code.

| Location | Repository |
|---|---|
| `ras_commander` package | `gpt-cmdr/ras-commander` |
| `hms_commander` package | `gpt-cmdr/hms-commander`. Shared DSS infrastructure belongs to `ras-commander` |
| RAS project MCP server | `gpt-cmdr/ras-commander-mcp` |
| HMS project MCP server | `gpt-cmdr/hms-commander-mcp` |
| Agent skill text | The repository that holds the canonical skill under `.claude/skills/`. The `ras-commander` Claude Code plugin (`ras-commander@ras-commander-plugin`) packages these sources; fix the source, not the bundle |

## 4. Determine the role

```sh
gh api repos/gpt-cmdr/<repo> --jq .permissions.push
```

A result of `true` selects the maintainer path; CLB staff qualify through this access. Any other result selects the external path: `false`, an error, no `gh`, no signed-in account, or no network. Check each owning repository separately. Never ask for, read, copy, or store tokens or credentials, and do not sign in on the user's behalf.

## 5. Maintainer path

The project policy authorizes a maintainer PR without a separate request. Stop and ask first if the user declines, or if the reproduction cannot be separated from confidential project data.

1. Reproduce the defect with a public example project (`RasExamples.extract_project()` or `HmsExamples.extract_project()`) or a synthetic fixture. Never use client data.
2. Create a fresh disposable clone or worktree from `origin/main` in authorized scratch space, then branch (`fix/<short-topic>`). Do not work in the user's project, installed site-packages, or a shared network checkout.
3. Read the repository's `AGENTS.md`. Fix the root cause with the smallest change that follows its API patterns.
4. Add a regression test that fails before the fix and passes after it.
5. Run the [required checks](references/contribution-checks.md#checks-before-a-pr): targeted tests, the Technical Writing Auditor on changed prose, and the API consistency criteria for any public API change.
6. Push the branch and open the PR with `gh pr create`, following the repository template. Include the problem, reproduction, root cause, fix, tests, audit results, and affected versions. Do not merge or push to `main`.
7. Give the user the PR URL. Continue the task with a safe documented workaround, such as another public API or a known-good release in a task-local environment. Install the unmerged branch into the user's environment only with consent.

If the root cause is unclear or the fix is large, open an issue with the reproduction instead and say so.

## 6. External path

Draft the contribution and show it to the user. Submit nothing publicly without explicit approval.

- **Bug report:** use the [issue fields](references/contribution-checks.md#issue-and-pr-content) with a minimal synthetic reproduction, versions, and platform.
- **Feature request:** evaluate the [API consistency criteria](references/contribution-checks.md#api-consistency-criteria) and report each criterion as pass, fail, or not applicable. Revise or drop a request that fails.
- **Pull request:** fork with `gh repo fork`, follow maintainer steps 1–5 in the fork, and open the PR after the user approves it.

Without `gh` or network access, give the user the draft text and `https://github.com/gpt-cmdr/<repo>/issues/new/choose`.

## Keep private data out

Issues, PRs, tests, and fixtures are public. Remove project and client names, local paths, coordinates, hostnames, usernames, credentials, and proprietary model content. Replace them with public example projects or synthetic fixtures, and treat logs as potentially sensitive. Never attach a user's model files.
