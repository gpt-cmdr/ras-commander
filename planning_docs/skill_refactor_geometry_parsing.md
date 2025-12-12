# Skill Refactor: parsing-hecras-geometry

## Summary
Refactored `.claude/skills/parsing-hecras-geometry/` from 1,914 lines of duplicated content to 379 lines of focused navigation.

## Before (1,914 lines total)
```
.claude/skills/parsing-hecras-geometry/
├── SKILL.md (490 lines) - Full documentation
├── reference/
│   ├── parsing.md (418 lines) - Duplicated parsing details
│   └── modification.md (495 lines) - Duplicated modification patterns
└── examples/
    ├── read-geometry.py (181 lines) - Example code
    └── modify-xs.py (330 lines) - Example code
```

## After (379 lines total)
```
.claude/skills/parsing-hecras-geometry/
└── SKILL.md (379 lines) - Navigator to primary sources
```

## Changes Made

### 1. Rewrote SKILL.md as Lightweight Navigator
- **Line count**: 490 → 379 (23% reduction)
- **Structure**: Quick-reference patterns + navigation to primary sources
- **Primary sources identified**:
  - `ras_commander/geom/AGENTS.md` (144 lines) - Implementation guide, API reference
  - `examples/20_plaintext_geometry_operations.ipynb` - Working demonstrations

### 2. Deleted Duplicate Content
- **Deleted**: `reference/parsing.md` (418 lines)
- **Deleted**: `reference/modification.md` (495 lines)
- **Deleted**: `examples/read-geometry.py` (181 lines)
- **Deleted**: `examples/modify-xs.py` (330 lines)
- **Deleted**: `README.md` (duplicate index)

### 3. Content Consolidation
**Removed duplicates**:
- Fixed-width format details → `ras_commander/geom/AGENTS.md`
- Complete API reference → `ras_commander/geom/AGENTS.md`
- Working examples → `examples/20_plaintext_geometry_operations.ipynb`

**Kept in SKILL.md**:
- Quick-start patterns (copy-paste ready code)
- Module organization table
- Critical implementation notes (450 point limit, bank stations, etc.)
- Common workflows (batch operations, surveys)
- Error handling patterns
- Clear navigation to primary sources

## Verification

### Primary Sources Exist
```bash
# Implementation guide (144 lines)
C:\GH\ras-commander\ras_commander\geom\AGENTS.md

# Working examples (337 KB notebook)
C:\GH\ras-commander\examples\20_plaintext_geometry_operations.ipynb
```

### Final Skill Structure
```bash
$ find .claude/skills/parsing-hecras-geometry -type f
.claude/skills/parsing-hecras-geometry/SKILL.md

$ wc -l .claude/skills/parsing-hecras-geometry/SKILL.md
379 .claude/skills/parsing-hecras-geometry/SKILL.md
```

## Benefits

1. **Reduced redundancy**: Single source of truth for each concept
2. **Easier maintenance**: Update once in primary sources, not in 4 files
3. **Clearer navigation**: Explicit links to authoritative documentation
4. **Better context**: Notebook examples show integration with real projects
5. **Focused skill**: Quick patterns without drowning in details

## Pattern Applied

**Skill as Navigator Pattern**:
- Provide quick-reference code patterns
- Point to primary sources for depth
- Don't duplicate what exists elsewhere
- Target: 300-400 lines for complex topics
