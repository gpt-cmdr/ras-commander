# Skills Creation Guide - Official Anthropic Documentation

**Source**: https://claude.com/blog/how-to-create-skills-key-steps-limitations-and-examples
**Last Cached**: 2025-12-11
**Authority**: Official Anthropic blog post

---

## Core Definition

Skills are custom instructions that extend Claude's capabilities for specific tasks or domains, typically defined in a `SKILL.md` file.

## The 5-Step Creation Process

### Step 1: Understand Core Requirements

**Objective**: Clarify the specific problem your skill solves

**Key Principle**: Define measurable outcomes, not vague objectives

**Questions to Answer**:
- What specific problem does this solve?
- What are the measurable success criteria?
- What are the inputs and expected outputs?
- What are the boundaries (what it should NOT do)?

**Bad Example**: "Help with documentation"
**Good Example**: "Extract API endpoints from TypeScript source files and generate OpenAPI schema with request/response examples"

### Step 2: Write the Name

**Convention**: Lowercase with hyphens

**Examples**:
- ✅ `pdf-editor`
- ✅ `api-schema-generator`
- ✅ `analyzing-hdf-files`
- ❌ `PDFEditor`
- ❌ `api_helper`
- ❌ `HDF-Helper`

**Guidelines**:
- Keep it straightforward and descriptive
- Gerund form often works well (`analyzing-`, `extracting-`, `generating-`)
- Avoid generic names (`helper`, `tool`, `utility`)

### Step 3: Write the Description ⚠️ CRITICAL

**⚠️ MOST IMPORTANT**: The name and description are **the only parts of SKILL.md that influence triggering**.

**Write from Claude's perspective**: "I am a skill that does X"

**Balance Four Elements**:
1. **Specific capabilities** - What exactly does it do?
2. **Clear triggers** - When should it activate?
3. **Relevant context** - What domain/technology?
4. **Boundaries** - What it doesn't handle

**Template**:
```markdown
description: |
  [What it does] using [technologies/methods]. Use when [trigger scenarios],
  [more trigger scenarios], or [edge case scenarios]. Handles [capabilities]
  but not [out-of-scope items].
```

**Example - HDF Analysis Skill**:
```yaml
description: |
  Analyzes HEC-RAS HDF files using h5py and numpy. Use when extracting
  water surface elevations, processing unsteady results, analyzing model
  outputs, or generating hydraulic tables. Handles both steady and unsteady
  plans, 1D/2D data, and structure results. Does not modify HDF files or
  run simulations.
```

**What Makes a Good Description**:
- ✅ Includes trigger keywords users would naturally say
- ✅ Mentions specific technologies/domains
- ✅ Lists concrete use cases
- ✅ States clear boundaries
- ❌ Too vague: "Helps with files"
- ❌ Too generic: "Processes data"
- ❌ Missing triggers: Only says what it is, not when to use it

### Step 4: Write Main Instructions

**Structure with Clear Hierarchy**:

1. **Overview** - What this skill does (1-2 paragraphs)
2. **Prerequisites** - What must exist before using this skill
3. **Execution Steps** - The actual workflow (numbered or bulleted)
4. **Examples** - Concrete usage examples with inputs/outputs
5. **Error Handling** - Common errors and solutions
6. **Limitations** - What this skill cannot do

**Use Markdown Structure**:
- Headers (`##`, `###`) for sections
- Bullet points for lists
- Code blocks for examples
- Tables for comparisons

**Progressive Disclosure Pattern** (for large skills):

Instead of putting everything in SKILL.md, use a "menu" approach:

```markdown
# My Large Skill

## Quick Start
[Basic usage here]

## Detailed Guides
For specific workflows, see:
- @reference/basic-workflow.md - Simple use cases
- @reference/advanced-workflow.md - Complex scenarios
- @reference/troubleshooting.md - Common issues

## Examples
- @examples/simple-example.md
- @examples/complex-example.md
```

**Benefit**: Main SKILL.md stays concise, details loaded on-demand (0 token cost until read).

### Step 5: Upload Your Skill

**Claude Code** (Automatic Discovery):
```
my-project/
├── skills/
│   └── my-skill/
│       └── SKILL.md
```

Claude automatically discovers and loads skills from `skills/` directory.

**Claude.ai** (Manual Upload):
- Go to Settings → Custom Skills
- Upload SKILL.md file
- Requires: Pro, Max, Team, or Enterprise subscription

**Developer Platform** (API):
```bash
POST /v1/skills
Content-Type: multipart/form-data

{
  "file": SKILL.md,
  "name": "my-skill"
}
```

## Testing & Validation

**Test Three Scenarios**:

1. **Normal Operations**
   - Provide typical inputs the skill was designed for
   - Verify expected outputs
   - Check workflow executes correctly

2. **Edge Cases**
   - Empty inputs
   - Malformed inputs
   - Boundary conditions
   - Large datasets
   - Unusual but valid scenarios

3. **Out-of-Scope Requests**
   - Verify skill correctly identifies what it can't do
   - Graceful degradation or clear error messages
   - Doesn't "hallucinate" capabilities

**Validate Triggering**:

Test with natural language:
- ✅ "Extract water surface elevations from this HDF file" → Should activate HDF skill
- ✅ "Analyze the model results" → Should activate if results are in HDF
- ❌ "Run a new simulation" → Should NOT activate (out of scope)

**Functional Consistency**:
- Run same request multiple times
- Verify consistent behavior
- Check that examples in SKILL.md work

## Best Practices

### Rule of Thumb: The 5-10 Test

**Create a skill when**:
- You've done this task **at least 5 times already**
- You anticipate doing it **10+ times in the future**

**Don't create a skill for**:
- One-off tasks
- Exploratory work
- Tasks you might never do again

### Define Explicit Success Criteria

Include in the SKILL.md what "success" looks like:

```markdown
## Success Criteria

This skill succeeds when:
- ✅ All API endpoints extracted from source files
- ✅ OpenAPI schema validates with official validator
- ✅ Request/response examples match actual types
- ✅ Generated schema includes descriptions from JSDoc comments

This skill fails when:
- ❌ Source files are not TypeScript
- ❌ No API endpoints found in files
```

### Use the skill-creator Tool

Anthropic provides a `skill-creator` tool in the GitHub Skills repository that guides you through the creation process with templates and validation.

### Balance File Size

**Problem**: Large SKILL.md files can be unwieldy

**Solution**: "Menu" approach with reference files

**Pattern**:
```markdown
# Main Skill (SKILL.md)

## Overview
[Keep main instructions here]

## Detailed Processes
Different workflows have different steps:
- Simple extraction: @reference/simple.md
- Complex transformation: @reference/complex.md
- Batch processing: @reference/batch.md

Choose the workflow that matches your use case.
```

**Benefit**:
- Main SKILL.md stays focused
- Reference files loaded only when needed
- 0 token cost for unloaded references
- Easier to maintain and update

### Start with Genuine Use Cases

**Bad Approach**: "This might be useful someday"
**Good Approach**: "I've done this 5 times and it's tedious"

**Questions to Ask**:
- Have I personally done this task multiple times?
- Do teammates ask me how to do this regularly?
- Is this a common workflow in my domain?
- Would automating this save significant time?

## Key Limitations

### Triggering Relies on Semantic Understanding

**How It Works**:
- Claude reads name and description
- Uses semantic understanding to decide relevance
- Vague descriptions reduce triggering accuracy

**Implication**: Spend time crafting a good description with clear triggers

**Example**:
- ❌ "Helps with files" - Too vague, won't trigger reliably
- ✅ "Extracts text from PDF files using OCR" - Clear triggers (PDF, extract, OCR)

### Multiple Skills Can Activate Simultaneously

**Behavior**: Complex tasks may activate multiple skills

**Example**: User asks to "Extract data from PDF and create Excel report"
- `pdf-extraction` skill activates (PDF handling)
- `excel-generation` skill activates (Excel creation)
- Both skills contribute to the solution

**Design Implication**: Skills should work together, not conflict

### File Sizes Matter

**Reality**: Larger files consume more tokens

**Best Practice**: Use progressive disclosure
- Main SKILL.md: Overview and navigation
- Reference files: Detailed procedures
- Examples: Separate files with complete workflows

**Pattern**: Only load what's needed for the current task

## Technical Structure for Claude Code

### Basic Structure
```
my-project/
├── skills/
│   └── my-skill/
│       └── SKILL.md
```

### With YAML Frontmatter
```yaml
---
name: my-skill
description: |
  Clear description with trigger keywords and capabilities.
---

# My Skill

[Instructions here]
```

### With Progressive Disclosure
```
my-project/
├── skills/
│   └── my-skill/
│       ├── SKILL.md
│       ├── reference/
│       │   ├── workflow-a.md
│       │   └── workflow-b.md
│       └── examples/
│           ├── basic.md
│           └── advanced.md
```

### Discovery Behavior

**Automatic**:
- Claude Code scans `skills/` directory on startup
- Loads name and description (~100 tokens per skill)
- Full SKILL.md loaded only when skill activates

**Manual**:
- Use `/skills` command to see all available skills
- Force activate with skill name in prompt

## Common Patterns

### Pattern: API/Library Wrapper Skill

**Use Case**: Teach Claude how to use a specific library

**Structure**:
```markdown
---
name: library-name-integration
description: |
  Integrates with LibraryName API. Use when calling LibraryName endpoints,
  handling LibraryName authentication, or processing LibraryName responses.
---

# LibraryName Integration

## Authentication
[How to auth]

## Common Operations
1. Operation A: [details]
2. Operation B: [details]

## Error Handling
[Common errors and solutions]
```

### Pattern: Domain-Specific Workflow Skill

**Use Case**: Encode expert knowledge for a specific domain

**Structure**:
```markdown
---
name: analyzing-hydraulic-models
description: |
  Analyzes hydraulic model results following industry best practices.
  Use when reviewing HEC-RAS output, validating water surface profiles,
  or checking model stability.
---

# Hydraulic Model Analysis

## Standard Checks
1. Mass balance verification
2. Profile stability analysis
3. Boundary condition validation

## Interpretation Guidelines
[Domain expertise here]
```

### Pattern: Code Generation Skill

**Use Case**: Generate code following specific patterns

**Structure**:
```markdown
---
name: generating-api-boilerplate
description: |
  Generates REST API boilerplate using Express and TypeScript.
  Use when creating new API endpoints, setting up route handlers,
  or scaffolding API structure.
---

# API Boilerplate Generator

## Generated Structure
[What gets created]

## Conventions
[Code style, patterns, testing approach]

## Example Output
[Complete example]
```

---

**Remember**: The description is critical - it's the only thing (besides the name) that determines when your skill activates. Spend time getting it right!

**Quick Reference**:
1. ✅ Genuine use case (5+ past, 10+ future)
2. ✅ Lowercase-with-hyphens name
3. ✅ Description with clear triggers
4. ✅ Structured instructions
5. ✅ Test normal, edge, out-of-scope cases
