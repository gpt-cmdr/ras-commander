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
  and git worktree management. Use when preparing commits with proper formatting,
  creating pull requests with gh CLI, or setting up isolated git worktrees for
  feature development. Integrates with using-git-worktrees skill for workspace
  isolation.

  Triggers: "commit", "pull request", "PR", "worktree", "git workflow",
  "prepare commit", "create PR", "isolated workspace"
---

# Git Operations Subagent

Handles git operations with safety checks and proper formatting.

## Primary Sources

**Git Worktree Workflow**:
- `.claude/skills/using-git-worktrees/` - Complete worktree workflow
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

**Delegates to using-git-worktrees skill for full workflow**

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

**See `.claude/skills/using-git-worktrees/` for complete workflow**

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

**Delegates to using-git-worktrees skill**

```bash
# Announce usage
echo "I'm using the using-git-worktrees skill to set up an isolated workspace."

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
- `using-git-worktrees` skill - For worktree setup workflow
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
| **Create worktree** | Delegate to `using-git-worktrees` skill |
| **Check secrets** | `git diff \| grep -i "password\|secret"` |
| **View commits** | `git log --oneline -10` |

## Navigation Map

**For detailed workflows**:
- Git worktrees → `.claude/skills/using-git-worktrees/` (complete workflow)
- Commit guidelines → Root `CLAUDE.md` (Git Safety Protocol section)
- GitHub CLI → `gh --help` or https://cli.github.com/manual/

**For safety rules**:
- Never commit secrets → Check diff before staging
- Never force push to main → Warn user first
- Never skip hooks → Use `--no-verify` only with user permission
- Always use heredoc → For multi-line messages

**For integration**:
- Worktree setup → Delegates to `using-git-worktrees` skill
- Worktree cleanup → Delegates to `finishing-a-development-branch` skill
- PR creation → Uses `gh pr create` with formatted body
