# Claude Code Memory System - Official Documentation

**Source**: https://code.claude.com/docs/en/memory
**Last Cached**: 2025-12-11
**Authority**: Official Claude Code documentation

---

## Memory Hierarchy Overview

Claude Code uses a **4-level hierarchical memory system** where files higher in the hierarchy take precedence:

| Level | Location | Purpose | Shared With | Precedence |
|-------|----------|---------|-------------|------------|
| **Enterprise Policy** | `/Library/Application Support/ClaudeCode/CLAUDE.md` (macOS)<br>`C:\ProgramData\ClaudeCode\CLAUDE.md` (Windows) | Organization-wide instructions enforced across all developers | All users in organization | **Highest** |
| **Project Memory** | `./CLAUDE.md` or `./.claude/CLAUDE.md` | Team-shared project instructions and conventions | Team via source control | **High** |
| **Project Rules** | `./.claude/rules/*.md` | Modular, topic-specific rules that auto-load | Team via source control | **Medium** |
| **User Memory** | `~/.claude/CLAUDE.md` | Personal preferences that apply to all projects | Individual user only | **Low** |
| **Project Local** | `./CLAUDE.local.md` | Personal project-specific preferences | Individual user only | **Lowest** |

### Precedence Rules

When the same instruction appears at multiple levels:
1. **Enterprise Policy** overrides everything
2. **Project Memory** overrides user settings
3. **User Memory** applies when project doesn't specify
4. **Project Local** for personal overrides (automatically gitignored)

## Recursive Memory Loading

### How It Works

Claude Code **automatically recurses up from your working directory** to the repository root, discovering CLAUDE.md files:

**Example Directory Structure**:
```
my-project/
├── CLAUDE.md                    # Root project memory
├── .claude/
│   ├── CLAUDE.md                # Alternative location
│   └── rules/
│       ├── code-style.md        # Auto-loaded rule
│       └── testing.md           # Auto-loaded rule
├── src/
│   ├── CLAUDE.md                # src/ specific memory
│   └── api/
│       └── CLAUDE.md            # api/ specific memory
```

**When working in `src/api/`**:
1. Loads `src/api/CLAUDE.md` (most specific)
2. Loads `src/CLAUDE.md` (parent)
3. Loads `CLAUDE.md` or `.claude/CLAUDE.md` (root)
4. Loads all `.claude/rules/*.md` (auto-loaded)
5. Loads `~/.claude/CLAUDE.md` (user prefs)
6. Loads enterprise policy (if exists)

### Subtree Discovery

**Behavior**: CLAUDE.md files in subdirectories are **only loaded when Claude reads files from those paths**.

**Example**:
- Working in root → Only root CLAUDE.md loaded
- Reading file from `src/api/` → Loads root + src + api CLAUDE.md
- Not accessing `src/` → src/CLAUDE.md remains unloaded (0 tokens)

**Benefit**: Progressive disclosure - only load context when needed

## CLAUDE.md Imports

### Syntax

Use `@path/to/file` to import additional content:

```markdown
See @README for project overview and @package.json for npm commands.

# Additional Instructions

## Git Workflow
@docs/git-instructions.md

## Project-Specific Preferences
@~/.claude/my-project-instructions.md
```

### Import Features

**Path Support**:
- ✅ Relative paths: `@docs/guide.md`
- ✅ Absolute paths: `@/home/user/docs/guide.md`
- ✅ User home: `@~/.claude/instructions.md`
- ✅ Parent directories: `@../shared/common.md`

**Limitations**:
- ❌ Max depth: **5 hops** (prevents infinite recursion)
- ❌ Not evaluated inside code spans: `` `@file` ``
- ❌ Not evaluated inside code blocks: ` ```@file``` `

**Circular Dependencies**:
- Detected automatically
- Import stops at circular reference
- Warning message in `/memory` view

### Viewing Loaded Imports

**Command**: `/memory`

**Output**:
```
📁 Loaded Memory Files:
  ✓ CLAUDE.md (root)
  ✓ @README.md (imported)
  ✓ @docs/git-instructions.md (imported from CLAUDE.md)
  ✓ .claude/rules/code-style.md (auto-loaded)
  ✓ ~/.claude/CLAUDE.md (user)
```

## Modular Rules with `.claude/rules/`

### Basic Organization

**Pattern**: One topic per file

```
your-project/
├── .claude/
│   ├── CLAUDE.md              # Main project memory
│   └── rules/
│       ├── code-style.md      # Formatting, naming conventions
│       ├── testing.md         # Test requirements, patterns
│       ├── security.md        # Security best practices
│       ├── documentation.md   # Doc standards
│       └── git.md             # Git workflow, commit messages
```

**Behavior**: All `.md` files in `.claude/rules/` are **automatically loaded** on startup

**Benefit**:
- Focused, maintainable files
- Easy to find and update specific guidance
- Team can own different rule files

### Path-Specific Rules

**Purpose**: Apply rules only to certain files or directories

**YAML Frontmatter Syntax**:
```markdown
---
paths: src/api/**/*.ts
---

# API Development Rules

- All endpoints must include input validation
- Use standard error response format
- Document with JSDoc comments
```

**When It Applies**:
- Rules activate only when Claude works with files matching the glob pattern
- Multiple rules can apply to same file (all load)
- More specific patterns take precedence

### Glob Pattern Examples

| Pattern | Matches |
|---------|---------|
| `**/*.ts` | All TypeScript files anywhere |
| `src/**/*` | All files under src/ (any depth) |
| `src/**/*.{ts,tsx}` | TypeScript and TSX files in src/ |
| `*.py` | Python files in root only |
| `tests/**/*` | Everything under tests/ |
| `!**/*.test.ts` | Exclude test files (negation) |

### Advanced Organization

**Subdirectories Supported**:
```
.claude/rules/
├── python/
│   ├── code-style.md
│   └── testing.md
├── typescript/
│   ├── code-style.md
│   └── testing.md
└── documentation/
    ├── api-docs.md
    └── user-guides.md
```

**Path-Specific Example**:
```markdown
---
paths: ras_commander/remote/**/*.py
---

# Remote Execution Rules

## HEC-RAS Remote Requirements
- Always use `session_id=2` for HEC-RAS remote execution
- Never use `system_account=True` for GUI applications
- Remote machine requires Group Policy configuration

## Testing
- Test with actual remote machines, not mocks
- Verify network share access before execution
```

## Automatic Configuration

### .gitignore Handling

**Behavior**: `CLAUDE.local.md` files are **automatically added to `.gitignore`**

**Purpose**: Personal preferences don't leak into team repository

**Example**:
```bash
# User's personal preferences
echo "Be extra verbose in explanations" > CLAUDE.local.md

# Automatically ignored by git
git status
# ... .gitignore prevents CLAUDE.local.md from being tracked
```

### Context Loading on Launch

**Startup Behavior**:
1. Claude Code launches
2. Scans for all memory files in hierarchy
3. Loads names and structure (~minimal tokens)
4. Full content loaded when working in specific directories

**Progressive Disclosure**:
- Metadata loaded upfront (~100 tokens per file)
- Full content loaded on-demand when needed
- Subtree CLAUDE.md files: 0 tokens until accessing that directory

## Quick Access Commands

| Command | Function | Example |
|---------|----------|---------|
| `/init` | Bootstrap a new CLAUDE.md for your project | Creates template with common sections |
| `/memory` | Open memory files in editor for editing | Quick access to edit CLAUDE.md, rules, etc. |
| `#` prefix | Quick memory shortcut | Prompts to select which memory file to view/edit |

### `/init` Command

**Usage**:
```bash
# In your project directory
/init
```

**Creates**: `CLAUDE.md` with template structure

**Template Example**:
```markdown
# Project Name

## Overview
[Project description]

## Development Guidelines

### Code Style
[Conventions]

### Testing
[Test requirements]

### Documentation
[Doc standards]

## Useful Commands
[Project-specific commands]
```

### `/memory` Command

**Usage**:
```bash
/memory
```

**Behavior**:
- Opens file picker with all memory files in hierarchy
- Select file to edit
- Opens in default editor
- Changes take effect on next Claude interaction

### `#` Quick Shortcut

**Usage**:
```bash
# in chat
```

**Behavior**:
- Prompts to select memory file
- Quick view without opening editor
- Can copy/paste content

## Best Practices

### ✅ DO: Be Specific

**Bad**:
```markdown
- Format code properly
- Write good tests
- Document your work
```

**Good**:
```markdown
- Use 2-space indentation for JavaScript/TypeScript
- Use 4-space indentation for Python
- All functions must have unit tests with >80% coverage
- All public functions must have JSDoc comments with @param and @returns
```

**Why**: Specificity prevents ambiguity and hallucination

### ✅ DO: Use Markdown Structure

**Bad**:
```markdown
Code style: Use 2 spaces for indentation, prefer const over let, use async/await not callbacks. Testing: Write unit tests for all functions, use Jest, mock external dependencies. Documentation: Add JSDoc comments, keep README updated.
```

**Good**:
```markdown
## Code Style

- **Indentation**: 2 spaces (JavaScript/TypeScript)
- **Variables**: Prefer `const` over `let`
- **Async**: Use `async/await`, not callbacks

## Testing

- **Framework**: Jest
- **Coverage**: All functions must have unit tests
- **Mocking**: Mock external dependencies (API, file system)

## Documentation

- **JSDoc**: Required for all public functions
- **README**: Keep updated with new features
```

**Why**: Headers and bullets make content scannable and memorable

### ✅ DO: Keep Rules Focused

**Bad** (everything in one file):
```markdown
# rules/everything.md (500 lines of mixed topics)
```

**Good** (topic per file):
```markdown
# rules/code-style.md (50 lines)
# rules/testing.md (75 lines)
# rules/security.md (60 lines)
# rules/documentation.md (40 lines)
```

**Why**: Easy to find, update, and maintain

### ✅ DO: Review and Update Periodically

**Pattern**: Quarterly review

**Questions to Ask**:
- Are these rules still relevant?
- Have new patterns emerged?
- Are there contradictions?
- What's missing?

**Action**: Update, archive outdated rules, add new guidance

### ✅ DO: Use Path-Specific Rules Selectively

**Good Use Cases**:
- API code has different validation rules than UI code
- Test files have different import rules
- Generated code directories have relaxed linting

**Bad Use Cases**:
- Every single file has custom rules (too granular)
- Path patterns so broad they apply to everything (not selective)

### ✅ DO: Organize Large Projects with Subdirectories

**Pattern**:
```
.claude/rules/
├── languages/
│   ├── python.md
│   ├── typescript.md
│   └── rust.md
├── frameworks/
│   ├── react.md
│   ├── django.md
│   └── fastapi.md
└── processes/
    ├── code-review.md
    ├── deployment.md
    └── incident-response.md
```

**Why**: Scales to 50+ rule files without chaos

### ❌ DON'T: Create Overly Broad Rules

**Bad**:
```markdown
---
# No path specified - applies to ALL files!
---

# API Development Rules
- All endpoints must include input validation
```

**Good**:
```markdown
---
paths: src/api/**/*.ts
---

# API Development Rules
- All endpoints must include input validation
```

**Why**: Broad rules without `paths` apply everywhere, even where inappropriate

### ❌ DON'T: Mix Multiple Unrelated Topics

**Bad**:
```markdown
# rules/misc.md

## Code Style
[formatting rules]

## Database Schema
[schema rules]

## Deployment Process
[deployment rules]

## Marketing Copy Guidelines
[???]
```

**Good**:
```markdown
# rules/code-style.md
# rules/database-schema.md
# rules/deployment.md
# rules/marketing-copy.md (probably belongs elsewhere!)
```

**Why**: Mixed topics hard to find, update, and maintain

## Organization-Level Management

### Enterprise Deployment

**Purpose**: Enforce organization-wide policies across all developers

**Locations**:
- **macOS**: `/Library/Application Support/ClaudeCode/CLAUDE.md`
- **Windows**: `C:\ProgramData\ClaudeCode\CLAUDE.md`
- **Linux**: `/etc/claudecode/CLAUDE.md`

**Deployment Methods**:
- **MDM** (Mobile Device Management): Jamf, Intune
- **Group Policy**: Windows domain policies
- **Ansible**: Configuration management
- **Manual**: System administrator installation

**Example Enterprise Policy**:
```markdown
# Acme Corp Claude Code Policy

## Security Requirements

### Secrets Management
- Never commit API keys, passwords, or credentials
- Use environment variables or secret management tools
- Scan commits with git-secrets before push

### Code Review
- All changes require peer review before merge
- Follow least-privilege principle for API access

### Compliance
- HIPAA: No PHI in prompts or code comments
- SOC 2: Log all Claude interactions for audit

## Code Standards

### Language-Specific
@/etc/claudecode/rules/python.md
@/etc/claudecode/rules/typescript.md

### Documentation
- All public APIs must have OpenAPI specs
- All repositories must have README with quickstart
```

**Precedence**: Enterprise policies **override** all other memory levels (highest precedence)

## Common Patterns

### Pattern: Monorepo Organization

**Structure**:
```
monorepo/
├── CLAUDE.md                      # Shared conventions
├── .claude/rules/
│   ├── code-style.md              # Repo-wide
│   └── testing.md                 # Repo-wide
├── packages/
│   ├── api/
│   │   ├── CLAUDE.md              # API-specific
│   │   └── .claude/rules/
│   │       └── api-patterns.md    # API-specific rules
│   ├── ui/
│   │   ├── CLAUDE.md              # UI-specific
│   │   └── .claude/rules/
│   │       └── ui-patterns.md     # UI-specific rules
│   └── shared/
│       └── CLAUDE.md              # Shared lib specific
```

**Behavior**: Working in `packages/api/` loads api + root memory

### Pattern: Progressive Disclosure for Complex Projects

**Root CLAUDE.md** (strategic only):
```markdown
# My Complex Project

## Overview
[High-level description]

## Development Areas

Different areas have specific guidance:
- API development: See `src/api/CLAUDE.md`
- Frontend: See `src/ui/CLAUDE.md`
- Infrastructure: See `infra/CLAUDE.md`

## Cross-Cutting Concerns
@.claude/rules/security.md
@.claude/rules/testing.md
```

**Benefit**: Root stays <200 lines, details in subtrees (loaded on-demand)

### Pattern: Team-Specific Rules

**Use Case**: Different teams have different standards

**Structure**:
```
.claude/rules/
├── shared/
│   ├── git-workflow.md        # Everyone
│   └── security.md            # Everyone
├── backend/
│   ├── api-standards.md       # Backend team
│   └── database-patterns.md   # Backend team
└── frontend/
    ├── react-patterns.md      # Frontend team
    └── accessibility.md       # Frontend team
```

**Path-Specific Application**:
```markdown
---
# backend/api-standards.md
paths: src/api/**/*.py
---

# Backend API Standards
[Backend-specific rules]
```

```markdown
---
# frontend/react-patterns.md
paths: src/ui/**/*.{tsx,jsx}
---

# Frontend React Patterns
[Frontend-specific rules]
```

## Troubleshooting

### Issue: Rules Not Loading

**Check**:
1. File location: Is it in `.claude/rules/`?
2. File extension: Is it `.md`?
3. YAML frontmatter: Is it valid?
4. Glob patterns: Do they match actual file paths?

**Debug**:
```bash
# List all rules
ls -la .claude/rules/

# Check YAML syntax
head -n 10 .claude/rules/my-rule.md

# View loaded memory
/memory
```

### Issue: Import Not Resolving

**Common Causes**:
- Typo in path
- Relative path incorrect
- Circular dependency
- Max depth (5 hops) exceeded

**Debug**:
```bash
# Check import path exists
ls -la path/to/imported/file.md

# View import chain
/memory
```

### Issue: Path-Specific Rule Not Applying

**Check**:
1. Glob pattern correct?
2. File actually matches pattern?
3. YAML frontmatter formatted properly?

**Test**:
```bash
# Check what files match pattern
find . -path "src/api/**/*.ts"

# Verify YAML syntax
cat .claude/rules/my-rule.md | head -n 5
```

---

**Quick Reference**:

1. **Hierarchy**: Enterprise > Project > Rules > User > Local
2. **Recursive**: Loads up from working directory to root
3. **Imports**: `@path/to/file` (max 5 hops)
4. **Rules**: `.claude/rules/*.md` auto-load
5. **Path-Specific**: YAML frontmatter with `paths: glob/pattern/**/*`
6. **Commands**: `/init`, `/memory`, `#`
7. **Best Practices**: Be specific, use structure, focus topics, review periodically
