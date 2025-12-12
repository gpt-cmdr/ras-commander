# ras_skills/ - Claude Skills Context

When working in this directory, you're creating or modifying **production-ready Claude Skills** for hydraulic modeling domain automation.

## What You're Working With

This directory contains **domain skills** - standalone capabilities that users can deploy for specialized hydraulic modeling tasks. These are different from library skills in `.claude/skills/` which teach how to use ras-commander APIs.

## Skill Structure Pattern

Each skill follows this structure:
```
skill-name/
├── SKILL.md              # Main instructions with YAML frontmatter
├── README.md             # Quick reference
├── STATUS.md             # Development status (optional)
├── reference/            # Detailed docs (load on-demand)
├── examples/             # Usage demonstrations
└── scripts/              # Executable utilities
```

## Critical Guidelines

### 1. No Large Files in Git

**IMPORTANT**: Development work, template projects, and large files belong in `feature_dev_notes/`, NOT here.

✅ **DO track**:
- SKILL.md, README.md, STATUS.md
- Small reference documentation (< 100KB each)
- Python scripts (actual .py files, not full projects)

❌ **DON'T track**:
- HEC-RAS project files (.prj, .g##, .p##, .hdf)
- HMS models or large datasets
- Working directories or temporary files
- Development notes (use feature_dev_notes/)

### 2. Skills vs Development

**Active development**: Use `feature_dev_notes/{skill-name}/` with full context, examples, and iteration.

**Production ready**: Move minimal, polished skill to `ras_skills/{skill-name}/` when complete.

### 3. Claude Skills Framework

Follow official Claude Skills conventions:
- **Gerund naming**: `executing-plans`, `linking-boundaries`
- **Rich descriptions**: Include trigger keywords for discovery
- **YAML frontmatter**: Required in SKILL.md
- **Progressive disclosure**: < 500 lines in SKILL.md, details in reference/

### 4. Testing Skills

Test skills by:
1. Working in a sample project directory
2. Verifying the skill activates correctly
3. Confirming instructions are clear and complete
4. Checking all reference files load properly

## Workflow: Development → Production

```
1. Plan in feature_dev_notes/{skill-name}/
   └── Full development context, examples, iteration

2. Implement and test
   └── Use ras-commander on real projects

3. Refine and document
   └── Write clear SKILL.md, create examples

4. Move to production (ras_skills/)
   └── Only essential files, clean and tested

5. Update STATUS.md
   └── Mark as production-ready
```

## Example: Creating a New Skill

```bash
# 1. Develop in feature_dev_notes/
cd feature_dev_notes
mkdir my-new-skill
# [work with full context, examples, large files]

# 2. When ready, create production version
cd ../ras_skills
mkdir my-new-skill

# 3. Create minimal structure
cat > my-new-skill/SKILL.md << 'EOF'
---
name: my-new-skill
description: Brief description with trigger keywords...
---

# My New Skill

[Clear, focused instructions]
EOF

cat > my-new-skill/README.md << 'EOF'
# My New Skill - Quick Reference
[One-page overview]
EOF

# 4. Test in real project
# 5. Commit to git
```

## Quality Checklist

Before marking a skill as production-ready:

- [ ] SKILL.md has valid YAML frontmatter
- [ ] Description includes trigger keywords
- [ ] Instructions are clear and tested
- [ ] No large files or development artifacts
- [ ] README.md provides quick reference
- [ ] Examples work with real ras-commander projects
- [ ] Skill activates correctly via Claude discovery

## See Also

- [Claude Skills official docs](https://claude.com/skills)
- [Hierarchical Knowledge Approach](../feature_dev_notes/Hierarchical_Knowledge_Approach/research/claude_skills_framework.md)
- Root CLAUDE.md for repository-wide patterns
- `.claude/skills/` for library usage skills
