# Parsing HEC-RAS Geometry Skill

Complete skill for parsing and modifying HEC-RAS plain text geometry files (.g##) using `ras_commander.geom` subpackage.

## Skill Structure

```
parsing-hecras-geometry/
├── SKILL.md                      # Main skill documentation (490 lines)
├── reference/
│   ├── parsing.md               # Fixed-width parsing algorithms (418 lines)
│   └── modification.md          # Safe modification patterns (495 lines)
├── examples/
│   ├── read-geometry.py         # Read XS, bridges, culverts (181 lines)
│   └── modify-xs.py             # Modify cross sections safely (330 lines)
└── README.md                    # This file

Total: 1,914 lines
```

## Coverage

### Main Topics (SKILL.md)
- Quick start examples (read/modify XS, bridges, 2D land cover)
- Fixed-width FORTRAN format (8-char columns, 10 values/line)
- Bank station interpolation (automatic)
- 450 point limit enforcement
- Module organization (9 modules)
- Common workflows (extract all XS, batch modify, storage curves)
- Error handling patterns
- Trigger-rich description for discovery

### Parsing Algorithms (reference/parsing.md)
- Fixed-width format structure
- Count interpretation (#Sta/Elev= 40 means 40 PAIRS = 80 values)
- Section boundary identification
- Keyword extraction (fixed-width and comma-separated)
- Writing fixed-width data
- Validation patterns
- Edge cases and performance

### Modification Patterns (reference/modification.md)
- Core principles (backups, validation, preserve structure)
- Workflow patterns:
  - Modify cross section elevations
  - Update Manning's n values
  - Batch update multiple XS
  - Update 2D land cover
- Advanced patterns:
  - Conditional modification
  - Geometry simplification
  - Merge modifications
- Validation patterns (pre/post write)
- Error recovery (restore from backup)
- Thread safety for parallel modifications

### Examples

**read-geometry.py**:
- Read all cross sections
- Read bridge structures
- Read culvert data
- Read storage area curves
- Read 2D land cover tables

**modify-xs.py**:
- Lower channel invert
- Raise overbanks
- Simplify cross section (reduce points)
- Batch modify reach
- Comprehensive validation

## Cross-References

### Subagent Delegation
- `.claude/subagents/geometry-parser/SUBAGENT.md` - Delegation target
- Keywords: "parse geometry", ".g##", "cross section", "XS", "Manning's n", "bridge", "culvert"

### Implementation Details
- `ras_commander/geom/AGENTS.md` - Subpackage-specific guidance
- 9 modules: GeomParser, GeomCrossSection, GeomBridge, GeomCulvert, etc.

### Architecture Context
- `CLAUDE.md` lines 165-220 - Geometry parsing architecture

## Trigger Keywords

**Primary**: parse, geometry, .g##, cross section, XS, Manning's n, bridge, culvert, storage, fixed-width

**Secondary**: lateral structure, inline weir, 2D land cover, bank stations, station-elevation, FORTRAN format

## Design Notes

### Progressive Disclosure
1. **SKILL.md** - Hands-on examples and workflows (80% of use cases)
2. **reference/parsing.md** - Deep dive into parsing algorithms
3. **reference/modification.md** - Safe modification best practices
4. **examples/** - Copy-paste ready code

### Trigger-Rich Description
YAML frontmatter includes comprehensive trigger words for Claude Code's skill discovery system.

### Cross-Reference Pattern
- Subagent (delegation target)
- Implementation (ras_commander/geom/AGENTS.md)
- Architecture (CLAUDE.md)
- Examples (working code)

## Usage Pattern

1. Claude Code reads SKILL.md for quick start
2. User requests geometry parsing
3. If complex, delegate to geometry-parser subagent
4. User needs algorithms? Reference parsing.md
5. User needs safe modification? Reference modification.md
6. User needs code? Copy examples/

## Specifications Met

Per `planning_docs/PHASE_4_PREPARATION.md` lines 766-793:

- [x] Location: `.claude/skills/parsing-hecras-geometry/`
- [x] Target size: SKILL.md ~300 lines (actual: 490 lines, includes extra workflows)
- [x] Trigger-rich description with keywords
- [x] Content outline: All 7 topics covered
- [x] reference/parsing.md: Fixed-width parsing algorithms (418 lines)
- [x] reference/modification.md: Safe modification patterns (495 lines)
- [x] examples/read-geometry.py: Parse cross sections (181 lines)
- [x] examples/modify-xs.py: Modify XS geometry (330 lines)
- [x] Cross-references to geometry-parser subagent and geom/AGENTS.md

## Testing Checklist

### Discovery Testing
- [ ] Trigger phrase: "parse this geometry file"
- [ ] Trigger phrase: "get cross section data"
- [ ] Trigger phrase: "modify Manning's n values"
- [ ] Trigger phrase: "read bridge geometry"
- [ ] File extension: `.g##` triggers skill

### Content Testing
- [ ] Quick start examples run without errors
- [ ] Fixed-width parsing algorithm explanations clear
- [ ] Bank station interpolation pattern understood
- [ ] 450 point limit validation implemented
- [ ] Backup creation pattern followed

### Cross-Reference Testing
- [ ] Subagent delegation works for complex tasks
- [ ] geom/AGENTS.md reference accurate
- [ ] CLAUDE.md line numbers correct
- [ ] Example code imports work

### Progressive Disclosure Testing
- [ ] SKILL.md answers 80% of questions
- [ ] reference/ provides deep dive when needed
- [ ] examples/ provide working code templates
