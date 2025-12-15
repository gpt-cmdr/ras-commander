# Official Anthropic Documentation - Quick Reference

**Purpose**: Links and fetch commands for authoritative Claude Code documentation

**Last Updated**: 2025-12-11

---

## Primary Documentation URLs

### 1. Skills Creation Guide

**URL**: https://claude.com/blog/how-to-create-skills-key-steps-limitations-and-examples

**Content**: Official blog post on creating effective skills
- 5-step creation process
- Best practices and limitations
- Testing and validation strategies
- Common patterns and examples

**Cached Reference**: `./skills-creation.md`

**When to Fetch**:
- User asks about "latest" skills documentation
- Troubleshooting skill triggering issues
- Creating new skill for first time
- Cached reference seems outdated

**Fetch Command**:
```python
WebFetch(
    url="https://claude.com/blog/how-to-create-skills-key-steps-limitations-and-examples",
    prompt="Extract complete guidance on creating Claude Code skills, including the 5-step process, best practices, limitations, and examples."
)
```

### 2. Memory System Documentation

**URL**: https://code.claude.com/docs/en/memory

**Content**: Official docs on Claude Code memory hierarchy
- 4-level memory system (Enterprise, Project, Rules, User)
- Recursive loading behavior
- CLAUDE.md imports with `@` syntax
- .claude/rules/ modular organization
- Path-specific rules with glob patterns
- Commands: /init, /memory, #

**Cached Reference**: `./memory-system.md`

**When to Fetch**:
- User asks about memory hierarchy precedence
- Troubleshooting CLAUDE.md not loading
- Questions about imports or path-specific rules
- Verifying latest features or changes

**Fetch Command**:
```python
WebFetch(
    url="https://code.claude.com/docs/en/memory",
    prompt="Extract complete information about Claude Code memory system, including hierarchy levels, recursive loading, imports, rules organization, and path-specific rules."
)
```

## Additional Documentation Sources

### Claude Code Documentation Hub

**URL**: https://code.claude.com/docs/en/

**Content**: Complete Claude Code documentation
- Getting started guides
- Features and capabilities
- Configuration options
- Troubleshooting

**When to Fetch**: Questions beyond skills and memory (hooks, MCP servers, etc.)

### Claude Skills Repository (GitHub)

**URL**: https://github.com/anthropics/claude-skills

**Content**: Official skills repository
- Example skills
- skill-creator tool
- Templates and patterns
- Community contributions

**When to Reference**: Looking for skill examples or using skill-creator tool

### Claude API Documentation

**URL**: https://docs.anthropic.com/

**Content**: Claude API (formerly Anthropic API)
- API endpoints and parameters
- Tool use and function calling
- Prompt engineering guides
- SDK documentation

**When to Reference**: Questions about Claude API, not Claude Code CLI

## Fetch Strategy Decision Tree

```
User asks question about Claude Code?
│
├─ Is it about skills creation?
│  ├─ Cached answer sufficient? → Use ./skills-creation.md
│  └─ Need latest info? → Fetch from blog URL
│
├─ Is it about memory system?
│  ├─ Cached answer sufficient? → Use ./memory-system.md
│  └─ Need latest info? → Fetch from docs URL
│
├─ Is it about other Claude Code features?
│  └─ Fetch from https://code.claude.com/docs/en/[topic]
│
└─ Is it about Claude API (not Code)?
   └─ Fetch from https://docs.anthropic.com/
```

## Common Fetch Prompts

### Skills Creation - Specific Topics

**Triggering Accuracy**:
```python
WebFetch(
    url="https://claude.com/blog/how-to-create-skills-key-steps-limitations-and-examples",
    prompt="Focus on how skill descriptions affect triggering accuracy. Extract guidance on writing effective descriptions that improve activation."
)
```

**Testing Strategy**:
```python
WebFetch(
    url="https://claude.com/blog/how-to-create-skills-key-steps-limitations-and-examples",
    prompt="Extract the complete testing and validation strategy for skills, including the three test scenarios and functional consistency checks."
)
```

**File Size Management**:
```python
WebFetch(
    url="https://claude.com/blog/how-to-create-skills-key-steps-limitations-and-examples",
    prompt="Focus on the progressive disclosure pattern and 'menu' approach for managing large skill files. Extract recommendations for reference file organization."
)
```

### Memory System - Specific Topics

**Path-Specific Rules**:
```python
WebFetch(
    url="https://code.claude.com/docs/en/memory",
    prompt="Focus on path-specific rules in .claude/rules/ with YAML frontmatter. Extract glob pattern syntax, examples, and when to use this feature."
)
```

**Import Syntax**:
```python
WebFetch(
    url="https://code.claude.com/docs/en/memory",
    prompt="Extract complete documentation on CLAUDE.md imports using @ syntax, including max depth, supported paths, circular dependency handling, and examples."
)
```

**Hierarchy Precedence**:
```python
WebFetch(
    url="https://code.claude.com/docs/en/memory",
    prompt="Clarify the exact precedence order of the 4-level memory hierarchy and how conflicts are resolved when same instruction appears at multiple levels."
)
```

## Cached Reference Files

### When Cached is Sufficient

✅ **Use cached reference when**:
- Well-established patterns (unlikely to change)
- Quick lookup during development
- Offline or avoiding rate limits
- Content matches expected knowledge

**Example Questions**:
- "What's the naming convention for skills?" → Cached
- "How many levels in memory hierarchy?" → Cached
- "What's the syntax for imports?" → Cached
- "What glob patterns are supported?" → Cached

### When Fresh Fetch is Needed

🔄 **Fetch fresh documentation when**:
- User explicitly asks for "latest" or "current" docs
- Troubleshooting configuration issues (docs may have updates)
- Cached reference seems incomplete
- Verifying new features or changes
- Critical decision requiring authoritative source

**Example Questions**:
- "What's the latest guidance on skill triggering?" → Fetch
- "Has the memory hierarchy changed recently?" → Fetch
- "Are there new features for path-specific rules?" → Fetch
- "This isn't working as documented, did it change?" → Fetch

## Combining Multiple Sources

### Example: Creating a New Skill

**Workflow**:
1. **Fetch latest skills guide**: Get current best practices
2. **Check cached memory docs**: Understand where to place SKILL.md
3. **Reference GitHub repo**: Look for similar skill examples
4. **Apply to ras-commander context**: Use hierarchical-knowledge-curator for repo-specific patterns

**Why**: Latest creation guide + established memory patterns + real examples = best result

### Example: Troubleshooting Configuration

**Workflow**:
1. **Check cached memory docs**: Review hierarchy and loading behavior
2. **Fetch latest docs**: Verify nothing changed recently
3. **Test locally**: Use /memory command to see what's actually loaded
4. **Compare**: Cached vs fresh vs actual behavior

**Why**: Systematic approach catches version mismatches or recent changes

## Update Maintenance

### Updating Cached References

**Frequency**: Quarterly or when notified of significant changes

**Process**:
1. Fetch latest from both URLs
2. Compare with cached references
3. Update cached files if substantive changes
4. Note update date in file headers
5. Document what changed in git commit

**Command**:
```bash
# Fetch both and compare
# If changes, update ./skills-creation.md and ./memory-system.md
# Update "Last Cached" dates in file headers
# Commit with message explaining changes
```

### Monitoring for Changes

**Sources to Watch**:
- Anthropic changelog: https://anthropic.com/changelog
- Claude Code releases: Check for version updates
- GitHub claude-skills repo: Watch for commits

**Action When Changes Detected**:
1. Fetch latest documentation
2. Update cached references
3. Test impact on existing skills/memory
4. Update ras-commander guidance if needed

## Quick Reference: What to Use When

| Question Type | First Source | If Insufficient |
|--------------|--------------|-----------------|
| "How do I create a skill?" | `./skills-creation.md` | Fetch latest blog post |
| "What's the memory hierarchy?" | `./memory-system.md` | Fetch latest docs |
| "Why isn't my skill triggering?" | `./skills-creation.md` | Fetch latest (may have updates) |
| "How do path-specific rules work?" | `./memory-system.md` | Usually sufficient |
| "What's new in Claude Code?" | Fetch docs hub | Browse changelog |
| "How do I use MCP servers?" | Fetch docs hub | Not in cached refs |
| "Claude API vs Claude Code?" | Explain difference | Fetch relevant docs |

## Error Handling

### If WebFetch Fails

**Fallback Strategy**:
1. Use cached reference files (always available)
2. Note to user: "Using cached docs from [date]"
3. Suggest checking official docs directly if critical
4. Retry fetch if temporary network issue

**Example**:
```python
try:
    result = WebFetch(url, prompt)
except Exception as e:
    # Fall back to cached reference
    result = Read("./skills-creation.md")
    print("Note: Using cached documentation from 2025-12-11")
```

### If Cached Reference Missing

**Fallback Strategy**:
1. Fetch fresh from URL (create new cached copy)
2. If fetch fails, provide general guidance from training
3. Note uncertainty and recommend checking official docs

### If Documentation Contradicts Experience

**Resolution**:
1. Note the discrepancy
2. Fetch latest docs to verify
3. Test actual behavior in Claude Code
4. Document finding for future reference

**Example**: "The cached docs say X, but you're experiencing Y. Let me fetch the latest documentation to see if this changed recently..."

---

**Quick Commands**:

**Fetch Latest Skills Guide**:
```python
WebFetch("https://claude.com/blog/how-to-create-skills-key-steps-limitations-and-examples", "Extract complete skills creation guidance")
```

**Fetch Latest Memory Docs**:
```python
WebFetch("https://code.claude.com/docs/en/memory", "Extract complete memory system documentation")
```

**View Cached References**:
```bash
Read("./skills-creation.md")
Read("./memory-system.md")
```
