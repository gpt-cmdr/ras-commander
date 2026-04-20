---
name: dev_gate_merge-to-main
description: Enforce the feature branch workflow — intercept any attempt to merge, push, or commit directly to main and redirect to the correct feature branch process. Triggers on "merge to main", "push to main", "PR to main", or any operation targeting the main branch.
---

# Development Gate: Merge-to-Main Policy

**Policy**: ALL development happens on feature branches. `main` is production-only. Direct pushes to `main` are never allowed.

This policy was established to prevent incomplete work from reaching the production branch. It applies universally — no exceptions without explicit user confirmation.

## Trigger Conditions

Activate this skill when you detect any of:
- User says "merge", "push to main", "commit to main", "PR to main"
- Current branch appears to be `main` and user wants to commit
- `git push origin main` is about to be run
- A PR target is set to `main` without a feature branch in the chain

## Workflow

### Step 1: Check Current Branch

```bash
git branch --show-current
```

**If on `main`**: Stop immediately — explain the policy and offer to create a feature branch.

**If on a feature branch**: Verify the merge direction (feature → main via PR, not direct push).

### Step 2: If on Main — Recover

```bash
# Create feature branch from current state
git checkout -b feature/[descriptive-name]

# Verify uncommitted changes moved with you
git status

# Optionally stash and reapply if needed
git stash
git checkout -b feature/[descriptive-name]
git stash pop
```

### Step 3: Gate Check Before Any Push to Main

Before running `git push origin main` or creating a PR to main, verify:

| Check | Command | Pass Condition |
|-------|---------|----------------|
| Not on main | `git branch --show-current` | Output ≠ "main" |
| Tests pass | `pytest` or project test command | 0 failures |
| No uncommitted changes | `git status` | "nothing to commit" |
| Feature branch exists | `git log --oneline main..HEAD` | At least 1 commit ahead |

### Step 4: Correct Merge Path

```
feature/my-work → PR → main    ✅ Correct
feature/my-work → direct push to main  ❌ Blocked
main → direct commit  ❌ Blocked
```

**Creating the PR**:
```bash
git push origin feature/my-work
gh pr create --base main --head feature/my-work --title "..." --body "..."
```

### Step 5: Hotfix Exception

Hotfixes may go directly to main **only** with:
1. Explicit user statement: "this is a hotfix"
2. User confirmation: "I understand this bypasses the feature branch policy"
3. A same-day revert plan if needed

Even then: prefer `hotfix/[name]` branch → PR → main.

## Branch Naming Convention

```
feature/[ticket-or-description]    ← new features
bugfix/[description]               ← bug fixes
hotfix/[description]               ← production emergencies only
refactor/[description]             ← refactoring passes
experiment/[description]           ← exploratory work
```

## What to Say When Intercepting

If user attempts a direct-to-main operation:

> "⚠️ You're about to [operation] directly to `main`. The ras-commander workflow requires all changes go through feature branches → PR → main.
>
> Want me to:
> 1. Create a feature branch from your current state?
> 2. Help you open a PR from your existing feature branch?
> 3. Proceed anyway (hotfix only — requires your confirmation)?"

---

**Source**: Policy re-declared 4× in conversation history (2026-03-20 to 2026-04-12). Codified to prevent future re-statements.
