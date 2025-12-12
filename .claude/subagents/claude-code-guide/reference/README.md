# Claude Code Guide - Reference Documentation

This directory contains cached copies of official Anthropic documentation for Claude Code, providing authoritative guidance on skills creation, memory systems, and configuration.

## Reference Files

### skills-creation.md
**Source**: https://claude.com/blog/how-to-create-skills-key-steps-limitations-and-examples
**Content**: Complete guide to creating effective Claude Code skills
**Topics**:
- 5-step creation process (requirements → name → description → instructions → upload)
- Best practices (rule of 5-10, genuine use cases, progressive disclosure)
- Testing and validation strategies
- Common patterns (API wrappers, domain workflows, code generation)
- Key limitations (triggering, file sizes, semantic understanding)

**Use When**: Creating new skills, improving skill descriptions, troubleshooting triggering

### memory-system.md
**Source**: https://code.claude.com/docs/en/memory
**Content**: Complete documentation of Claude Code memory hierarchy
**Topics**:
- 4-level hierarchy (Enterprise → Project → Rules → User → Local)
- Recursive loading from working directory to root
- CLAUDE.md imports with `@` syntax
- .claude/rules/ modular organization
- Path-specific rules with YAML frontmatter and glob patterns
- Commands (/init, /memory, #) and best practices

**Use When**: Configuring memory hierarchy, organizing CLAUDE.md files, path-specific rules

### official-docs.md
**Source**: Meta-documentation about fetching latest docs
**Content**: Links, fetch strategies, and decision trees for accessing official documentation
**Topics**:
- Primary documentation URLs
- When to fetch fresh vs use cached
- Common fetch prompts for specific topics
- Update maintenance procedures
- Error handling and fallback strategies

**Use When**: Deciding whether to fetch latest docs or use cached, updating references

## Usage Pattern

### Progressive Disclosure Approach

The claude-code-guide subagent follows progressive disclosure:

1. **Main SKILL.md**: Overview and navigation (~100 lines loaded initially)
2. **Reference files**: Detailed documentation (0 tokens until explicitly read)
3. **Official URLs**: Latest source (fetched on-demand when needed)

**Benefit**: Minimal token cost upfront, comprehensive details available when needed

### Fetch Fresh vs Use Cached

**Use cached reference when**:
- ✅ Quick lookup of well-established patterns
- ✅ Offline or avoiding rate limits
- ✅ Content matches expected knowledge
- ✅ Development workflow (not critical verification)

**Fetch fresh documentation when**:
- 🔄 User asks for "latest" or "current" documentation
- 🔄 Troubleshooting configuration issues (docs may have updates)
- 🔄 Cached reference seems incomplete or outdated
- 🔄 Verifying new features or changes
- 🔄 Critical decision requiring authoritative source

### Reading Pattern for claude-code-guide Subagent

When activated, the subagent should:

1. **Understand user question**: Skills creation? Memory config? Troubleshooting?
2. **Check cached first**: Read relevant reference file
3. **Evaluate freshness**: Does cached answer the question fully?
4. **Fetch if needed**: Get latest docs for critical/unclear cases
5. **Provide guidance**: Combine official docs with ras-commander context

## Maintenance

### Updating Cached References

**Frequency**: Quarterly or when notified of significant changes

**Process**:
1. Fetch latest from official URLs using WebFetch
2. Compare with current cached references
3. Update files if substantive changes detected
4. Update "Last Cached" date in file headers
5. Commit with message explaining what changed

**Sources to Monitor**:
- Anthropic changelog: https://anthropic.com/changelog
- Claude Code releases: Version updates and features
- GitHub claude-skills repo: https://github.com/anthropics/claude-skills

### Last Update

**Last Cached**: 2025-12-11
**Next Review**: 2025-03-11 (quarterly)

## See Also

- **Main subagent**: `.claude/subagents/claude-code-guide.md`
- **Official docs**: https://code.claude.com/docs/en/
- **Skills blog**: https://claude.com/blog/how-to-create-skills-key-steps-limitations-and-examples
- **Skills repo**: https://github.com/anthropics/claude-skills
- **Hierarchical knowledge curator**: `.claude/subagents/hierarchical-knowledge-agent-skill-memory-curator.md`

---

**Token Cost**: 0 tokens until read (progressive disclosure)
**Authority**: Official Anthropic documentation (cached 2025-12-11)
**Purpose**: Authoritative guidance for Claude Code configuration and best practices
