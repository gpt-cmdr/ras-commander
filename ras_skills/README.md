# ras_skills - Production-Ready Claude Skills

This directory contains production-ready Claude Skills for domain-specific hydraulic modeling automation using ras-commander.

## What are Skills?

**Skills** are Claude's official framework for specialized capabilities. Each skill is a folder containing:
- `SKILL.md` - Main skill instructions with YAML frontmatter
- `README.md` - Quick reference and overview
- `reference/` - Detailed documentation (loaded on-demand)
- `examples/` - Usage examples and workflows
- `scripts/` - Executable utilities (token-free execution)

## Skills vs Library Workflows

| Type | Location | Purpose | Distribution |
|------|----------|---------|--------------|
| **Library Skills** | `.claude/skills/` | How to use ras-commander APIs | Part of ras-commander repo |
| **Domain Skills** | `ras_skills/` | Production automation capabilities | Standalone, shareable |

Both use Claude Skills framework - the distinction is scope and intended use.

## Current Skills

### Production-Ready ✅

- **dss-linker** - HEC-DSS boundary condition integration
- **historical-flood-reconstruction** - Historical flood event modeling

### In Development 🚧

See `feature_dev_notes/` for skills under development.

## Creating New Skills

1. **Create skill folder**: `ras_skills/my-skill-name/`
2. **Add SKILL.md** with YAML frontmatter:
   ```yaml
   ---
   name: my-skill-name
   description: What it does, when to use it, trigger terms...
   ---

   # My Skill Name

   [Skill instructions here]
   ```

3. **Add README.md** for quick reference
4. **Optional**: Add `reference/`, `examples/`, `scripts/` subdirectories

## Guidelines

- **Keep skills focused**: One clear capability per skill
- **Use gerund naming**: `executing-plans`, not `execute-plans`
- **Rich descriptions**: Include trigger terms for discovery
- **Progressive disclosure**: Main SKILL.md < 500 lines, details in reference files
- **No large files**: Development work stays in `feature_dev_notes/`

## See Also

- [Claude Skills Documentation](https://claude.com/skills)
- [Hierarchical Knowledge Approach](../feature_dev_notes/Hierarchical_Knowledge_Approach/)
- [Library Skills](../.claude/skills/) - ras-commander usage workflows
