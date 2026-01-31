---
name: git-operations
model: sonnet
tools:
  - Bash
  - Read
  - Write
  - AskUserQuestion
working_directory: .
description: |
  Handles git operations including commit preparation, pull request creation,
  git worktree management, and documentation build verification. Use when
  preparing commits with proper formatting, creating pull requests with gh CLI,
  setting up isolated git worktrees for feature development, or verifying
  documentation builds before pushing. Includes critical pre-push checks to
  prevent documentation build failures. Integrates with dev_manage_git-worktrees
  skill for workspace isolation.

  Triggers: "commit", "pull request", "PR", "worktree", "git workflow",
  "prepare commit", "create PR", "isolated workspace", "docs build",
  "documentation check", "verify build", "pre-push check"
---

# Git Operations Subagent

Handles git operations with safety checks and proper formatting.

## Primary Sources

**Git Worktree Workflow**:
- `.claude/skills/dev_manage_git-worktrees/` - Complete worktree workflow
  - Directory selection priority (existing → CLAUDE.md → ask)
  - Safety verification (.gitignore checks)
  - Project setup automation
  - Baseline test verification

**Commit Guidelines**:
- Root `CLAUDE.md` - Git commit protocol (lines about committing changes)
- `.claude/rules/` - Python decorators, path handling patterns

**GitHub CLI**:
- `gh pr create` documentation - https://cli.github.com/manual/gh_pr_create
- `gh` commands for issue tracking, checks, releases

## Core Capabilities

### 1. Commit Preparation

**Pre-commit checks**:
```bash
# Check git status
git status

# Check for secrets (.env, credentials, etc.)
git diff --cached | grep -i "password\|secret\|api.key\|token"

# Verify files staged
git diff --cached --name-only
```

**Commit message format**:
```bash
git commit -m "$(cat <<'EOF'
Brief summary (50 chars or less)

Detailed explanation if needed. Focus on the "why" not the "what".

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
EOF
)"
```

**Safety rules**:
- ❌ Never commit .env files, credentials.json, or files with secrets
- ❌ Never use `--no-verify` unless user explicitly requests
- ❌ Never force push to main/master without warning
- ✅ Always run `git status` before and after commit
- ✅ Use heredoc for multi-line commit messages

### 2. Pull Request Creation

**Standard workflow**:
```bash
# 1. Check branch is pushed
git status

# 2. Push if needed
git push -u origin HEAD

# 3. Create PR with heredoc body
gh pr create --title "PR title" --body "$(cat <<'EOF'
## Summary
- Bullet point summary

## Test Plan
- Testing checklist

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

**PR body sections**:
- Summary (1-3 bullet points)
- Test plan (checklist of verification steps)
- Optional: Screenshots, performance impact, breaking changes

### 3. Git Worktree Management

**Delegates to dev_manage_git-worktrees skill for full workflow**

**Quick reference**:
```bash
# Directory priority: .worktrees > worktrees > CLAUDE.md preference > ask user

# Safety: Verify .gitignore for project-local worktrees
grep -q "^\.worktrees/$" .gitignore || echo ".worktrees/" >> .gitignore

# Create worktree
git worktree add .worktrees/feature-name -b feature/feature-name

# Navigate and setup
cd .worktrees/feature-name
npm install  # or appropriate setup command

# Verify baseline tests pass
npm test
```

**See `.claude/skills/dev_manage_git-worktrees/` for complete workflow**

## Common Workflows

### Workflow 1: Prepare and Commit Changes

```bash
# 1. Check status
git status

# 2. Check diff for secrets
git diff | grep -i "password\|api.key\|secret"

# 3. Add files
git add file1.py file2.md

# 4. Check staged changes
git diff --cached

# 5. Commit with formatted message
git commit -m "$(cat <<'EOF'
Add feature X implementation

Implements feature X with proper error handling and tests.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
EOF
)"

# 6. Verify commit
git log -1 --format='%h %s'
git status
```

### Workflow 2: Create Pull Request

```bash
# 1. Verify branch state
git log --oneline origin/main..HEAD  # See commits in PR
git diff origin/main...HEAD  # See all changes

# 2. Push branch
git push -u origin HEAD

# 3. Create PR
gh pr create --title "Add feature X" --body "$(cat <<'EOF'
## Summary
- Implemented feature X with error handling
- Added comprehensive tests
- Updated documentation

## Test Plan
- [ ] Unit tests pass (pytest)
- [ ] Integration tests pass
- [ ] Manual testing complete
- [ ] Documentation builds

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

### Workflow 3: Setup Isolated Worktree

**Delegates to dev_manage_git-worktrees skill**

```bash
# Announce usage
echo "I'm using the dev_manage_git-worktrees skill to set up an isolated workspace."

# Skill handles:
# - Directory selection (.worktrees vs worktrees vs global)
# - .gitignore verification
# - Worktree creation
# - Project setup (npm install, etc.)
# - Baseline test verification
```

## Safety Checks

### Secret Detection

**Files to never commit**:
- `.env`, `.env.local`, `.env.production`
- `credentials.json`, `secrets.yaml`
- `*.pem`, `*.key` (private keys)
- Files with `password=`, `api_key=`, `secret=`

**Check before commit**:
```bash
git diff --cached | grep -iE "password|api.?key|secret|token" && echo "⚠️  Possible secret detected!"
```

### Pre-commit Hook Integration

If pre-commit hook modifies files:
1. Check HEAD commit authorship: `git log -1 --format='[%h] (%an <%ae>) %s'`
2. Verify it matches your commit
3. Check not pushed: `git status` shows "Your branch is ahead"
4. If both true: Can amend with `git commit --amend --no-edit`
5. Otherwise: Create new commit (never amend other developers' commits)

### Force Push Protection

**Never run without warning**:
```bash
# ❌ DANGEROUS
git push --force origin main

# ✅ Warn user first
if [[ $BRANCH == "main" ]] || [[ $BRANCH == "master" ]]; then
  echo "⚠️  WARNING: Force pushing to $BRANCH is destructive!"
  echo "This can break other developers' work."
  # Ask user for confirmation
fi
```

## Branch Policy: Clean Main, Dev Tracks Development Files

### Policy Overview

**Main branch** = Clean user-facing codebase
**Dev branch** = Includes development coordination files

This ensures users who clone/sync main get a clean workspace without active development task files.

### Development-Only Files (Untracked on Main)

**agent_tasks/**:
- `.agent/` - Session state (STATE.md, PROGRESS.md, BACKLOG.md, LEARNINGS.md)
- `*.md` - Active task files (except README.md)
- `api-consistency-auditor/` - Subproject files

**.claude/outputs/**:
- All session outputs from agents
- Temporary analysis files
- Notebook runner outputs

### Files Tracked on Main (Helpful for Contributors)

- `agent_tasks/README.md` - Explains memory system
- `agent_tasks/.gitignore` - Local file patterns
- `agent_tasks/*/README.md` - Subproject documentation

### Gitignore Enforcement

The `.gitignore` on main prevents re-adding dev files:
```gitignore
# Agent coordination - dev files untracked on main
agent_tasks/.agent/
agent_tasks/*.md
!agent_tasks/README.md
agent_tasks/api-consistency-auditor/
/.claude/outputs
```

### Workflow: Development on Dev Branch

```bash
# 1. Create/switch to dev branch for development work
git checkout dev  # or: git checkout -b dev

# 2. Make changes, agent_tasks/ and .claude/outputs/ are tracked here
git add agent_tasks/.agent/STATE.md
git commit -m "Update session state"

# 3. When ready to release, merge dev to main
# IMPORTANT: Dev files stay on dev, don't pollute main
git checkout main
git merge dev --no-commit
git reset HEAD agent_tasks/  # Remove dev files from merge
git reset HEAD .claude/outputs/
git commit -m "Merge feature from dev (excluding dev files)"
```

### Why This Matters

1. **Users get clean workspace**: `git clone` gives production-ready code
2. **No session pollution**: Users don't see your STATE.md, PROGRESS.md
3. **Collaboration friendly**: Other devs start fresh, not from your session state
4. **Dev continuity**: Your dev branch retains full task coordination

### Quick Check: Is Main Clean?

```bash
# Should return 0 files for these directories
git ls-files agent_tasks/.agent/ | wc -l  # Should be 0
git ls-files .claude/outputs/ | wc -l     # Should be 0

# README files should exist
git ls-files agent_tasks/README.md        # Should exist
```

## Documentation Build Verification

### Critical Pre-Push Check (Prevents Build Failures)

**Problem**: Documentation builds fail on EVERY commit if workflow dependencies are gitignored or missing.

**Root Cause** (from 2025-12-17 incident):
- `scripts/generate_cognitive_docs.py` was gitignored by overly broad pattern `generate_*.py`
- Script existed locally but was never pushed to GitHub
- GitHub Actions failed: "can't open file 'scripts/generate_cognitive_docs.py'"

**Solution**: Verify workflow dependencies BEFORE pushing

### Pre-Push Documentation Checklist

**Run before pushing commits that touch docs/**:

```bash
# 1. Verify workflow scripts are NOT gitignored
git check-ignore scripts/generate_cognitive_docs.py
# Should return NOTHING (exit code 1 = not ignored)
# If ignored, fix .gitignore immediately!

# 2. Verify workflow scripts are committed
git ls-files scripts/generate_cognitive_docs.py
# Should output: scripts/generate_cognitive_docs.py
# If missing: git add scripts/generate_cognitive_docs.py

# 3. Test generator script runs
python scripts/generate_cognitive_docs.py
# Should output:
#   Generated: docs/cognitive-infrastructure/agents.md
#   Generated: docs/cognitive-infrastructure/skills.md
#   Generated: docs/cognitive-infrastructure/commands.md

# 4. Verify generated files created
ls -la docs/cognitive-infrastructure/*.md
# Should show: agents.md, commands.md, index.md, skills.md

# 5. Test mkdocs build locally
mkdocs build
# Should complete with exit code 0
# Warnings are OK, errors are NOT
```

### Quick Verification Script

```bash
#!/bin/bash
echo "=== Documentation Build Pre-Push Check ==="

# 1. Check for gitignored workflow files
if git check-ignore scripts/generate_cognitive_docs.py >/dev/null 2>&1; then
    echo "✗ FAIL: scripts/generate_cognitive_docs.py is gitignored!"
    echo "  Fix: Update .gitignore to exclude scripts/ directory"
    exit 1
fi

# 2. Verify script is committed
if ! git ls-files scripts/generate_cognitive_docs.py | grep -q .; then
    echo "✗ FAIL: Generator script not in repository!"
    echo "  Fix: git add scripts/generate_cognitive_docs.py"
    exit 1
fi

# 3. Test generator script
if ! python scripts/generate_cognitive_docs.py >/dev/null 2>&1; then
    echo "✗ FAIL: Generator script failed!"
    exit 1
fi

echo "✓ All documentation build checks passed!"
```

### Common Documentation Build Failures

**1. Missing Generator Script**
```bash
# Error: can't open file 'scripts/generate_cognitive_docs.py'
# Cause: File gitignored or not committed
# Fix:
git check-ignore scripts/generate_cognitive_docs.py  # Should return nothing
git add scripts/generate_cognitive_docs.py
git commit -m "Add missing generator script"
```

**2. Overly Broad Gitignore Patterns**
```bash
# Bad (catches everything):
generate_*.py

# Good (specific directory):
ai_tools/generate_*.py
```

**3. Missing Dependencies**
```bash
# Error: ModuleNotFoundError: No module named 'yaml'
# Cause: PyYAML not in docs/requirements-docs.txt
# Fix:
echo "PyYAML>=6.0" >> docs/requirements-docs.txt
git add docs/requirements-docs.txt
```

**4. Broken MkDocs Config**
```bash
# Test YAML syntax locally:
python -c "
import yaml
with open('.github/workflows/docs.yml') as f:
    yaml.safe_load(f)
print('✓ Valid YAML')
"
```

### Workflow Files to Verify

**GitHub Actions**: `.github/workflows/docs.yml`
- Uses: `python scripts/generate_cognitive_docs.py`
- Must exist and be committed

**ReadTheDocs**: `.readthedocs.yaml`
- Pre-build: `python scripts/generate_cognitive_docs.py`
- Must exist and be committed

**Dependencies**: `docs/requirements-docs.txt`
- Must include: `PyYAML>=6.0`
- For generator script imports

### Post-Push Monitoring

```bash
# Monitor GitHub Actions after push
gh run watch

# Or view in browser
echo "https://github.com/gpt-cmdr/ras-commander/actions"

# Check failed logs if build fails
gh run view --log-failed
```

### Emergency Fix for Failed Builds

```bash
# If docs build fails after push:

# 1. Check what's missing
git ls-files scripts/

# 2. Add missing files immediately
git add scripts/generate_cognitive_docs.py
git commit -m "Fix: Add missing workflow script"
git push

# 3. Monitor fix
gh run watch
```

### Reference

**Comprehensive checklist**: `.github/DOC_BUILD_CHECKLIST.md`
**Created**: 2025-12-17 (after fixing gitignored generator script issue)

## GitHub CLI Integration

### Common gh Commands

**Pull Requests**:
```bash
gh pr create              # Create PR
gh pr list                # List PRs
gh pr view 123            # View PR #123
gh pr merge 123           # Merge PR
gh pr comment 123 -b "message"  # Comment on PR
```

**Issues**:
```bash
gh issue create           # Create issue
gh issue list             # List issues
gh issue view 456         # View issue
gh issue close 456        # Close issue
```

**Checks and Releases**:
```bash
gh run list               # List workflow runs
gh run view 789           # View workflow run
gh release create v1.0.0  # Create release
```

**View PR Comments**:
```bash
gh api repos/owner/repo/pulls/123/comments
```

## Decision Trees

### When to Use Worktrees

**Use worktree when**:
- Starting new feature that needs isolation
- Working on multiple branches simultaneously
- Running tests on different branches
- Implementing design after approval (brainstorming → worktree)

**Don't use worktree when**:
- Quick fixes on current branch
- Single-branch workflow sufficient
- Already in a worktree

### When to Amend vs New Commit

**Amend (`--amend`) when**:
- Pre-commit hook modified files
- Fixing typo in last commit message
- Adding forgotten file to last commit
- Commit NOT yet pushed
- You authored the last commit

**New commit when**:
- Last commit already pushed
- Someone else authored last commit
- Multiple commits make history clearer
- Working in shared branch

## Common Pitfalls

### ❌ Committing Secrets

**Problem**: `.env` file committed with API keys

**Prevention**:
```bash
# Check diff before adding
git diff .env | grep -i "api.key"

# Add to .gitignore if sensitive
echo ".env" >> .gitignore
git add .gitignore
```

### ❌ Force Pushing to Main

**Problem**: `git push --force origin main` destroys team's work

**Prevention**: Always warn and require confirmation for force push to main/master

### ❌ Amending Pushed Commits

**Problem**: `git commit --amend` after push causes divergence

**Prevention**: Check `git log -1` authorship and `git status` push state

### ❌ Skipping .gitignore for Worktrees

**Problem**: Worktree directory gets tracked in git

**Prevention**: Always verify .gitignore before creating project-local worktree

## Integration with Other Skills/Subagents

**Calls**:
- `dev_manage_git-worktrees` skill - For worktree setup workflow
- `finishing-a-development-branch` skill - For worktree cleanup

**Called by**:
- `brainstorming` - Phase 4 implementation (creates worktree)
- Any feature development workflow
- Documentation update workflows

## Quick Reference Table

| Task | Command Pattern |
|------|-----------------|
| **Check status** | `git status` |
| **Stage files** | `git add file1 file2` |
| **Check diff** | `git diff` (unstaged) or `git diff --cached` (staged) |
| **Commit** | `git commit -m "$(cat <<'EOF'...EOF)"` |
| **Push branch** | `git push -u origin HEAD` |
| **Create PR** | `gh pr create --title "..." --body "$(cat <<'EOF'...EOF)"` |
| **Create worktree** | Delegate to `dev_manage_git-worktrees` skill |
| **Check secrets** | `git diff \| grep -i "password\|secret"` |
| **View commits** | `git log --oneline -10` |

## Navigation Map

**For detailed workflows**:
- Git worktrees → `.claude/skills/dev_manage_git-worktrees/` (complete workflow)
- Commit guidelines → Root `CLAUDE.md` (Git Safety Protocol section)
- GitHub CLI → `gh --help` or https://cli.github.com/manual/

**For safety rules**:
- Never commit secrets → Check diff before staging
- Never force push to main → Warn user first
- Never skip hooks → Use `--no-verify` only with user permission
- Always use heredoc → For multi-line messages

**For integration**:
- Worktree setup → Delegates to `dev_manage_git-worktrees` skill
- Worktree cleanup → Delegates to `finishing-a-development-branch` skill
- PR creation → Uses `gh pr create` with formatted body
