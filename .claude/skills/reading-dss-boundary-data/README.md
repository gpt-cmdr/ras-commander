# Reading DSS Boundary Data - Skill

**Type**: Lightweight Primary Source Navigator
**Version**: 1.0.0
**Lines**: ~320 (SKILL.md only)

## Purpose

This skill provides a **concise entry point** to DSS (Data Storage System) file operations in ras-commander. It does NOT duplicate documentation - instead it directs you to authoritative primary sources.

## Primary Sources (Read These)

1. **Module Architecture**: `C:\GH\ras-commander\ras_commander\dss\AGENTS.md`
   - Lazy loading architecture
   - Public API reference
   - Developer guidance

2. **Complete Workflow**: `C:\GH\ras-commander\examples\22_dss_boundary_extraction.ipynb`
   - Step-by-step extraction examples
   - Real project (BaldEagleCrkMulti2D)
   - Plotting and analysis

3. **Source Code**: `C:\GH\ras-commander\ras_commander\dss\RasDss.py`
   - Method signatures and docstrings
   - Implementation details

## What This Skill Provides

- Quick reference code snippets
- Overview of DSS pathname format
- Overview of lazy loading architecture
- Common workflows (catalog reading, extraction, plotting)
- Error handling patterns
- **Explicit pointers to primary sources**

## What This Skill Does NOT Provide

- Complete API documentation (see dss/AGENTS.md)
- Detailed examples (see notebook 22)
- Troubleshooting guides (see dss/AGENTS.md)
- Method implementation details (see RasDss.py)

## Design Philosophy

**Lightweight Navigator Pattern**:
- Skills should be ~300-400 lines TOTAL
- Provide enough context to orient the user
- **Point to primary sources for complete information**
- Avoid duplicating content that exists elsewhere
- Primary sources are maintained, skills are stable

## Version History

- **v1.0.0** (2025-12-11): Refactored from 1,821 lines to 320 lines
  - Deleted `reference/` folder (duplicated AGENTS.md content)
  - Deleted `examples/` folder (notebook 22 already exists)
  - Rewrote SKILL.md as primary source navigator
  - Added explicit warnings NOT to read deleted folders

- **v0.1.0** (Initial): 1,821 lines with extensive duplication
  - `SKILL.md`: 439 lines
  - `reference/dss-api.md`: 498 lines (duplicated AGENTS.md)
  - `reference/troubleshooting.md`: 379 lines (duplicated AGENTS.md)
  - `examples/`: 505 lines (duplicated notebook 22)

## File Structure

```
reading-dss-boundary-data/
├── SKILL.md                      # ~320 lines - Primary source navigator
├── README.md                     # This file
└── COMPLETION_SUMMARY.md         # Refactoring notes
```

**Deleted** (v1.0.0):
- `reference/` - Duplicated dss/AGENTS.md content
- `examples/` - Duplicated notebook 22 content

## Usage

When Claude Code reads this skill, it will:
1. Read SKILL.md for quick reference
2. Be directed to read `dss/AGENTS.md` for architecture
3. Be directed to read `examples/310_dss_boundary_extraction.ipynb` for workflow
4. Have immediate access to code snippets for common operations

This keeps the skill lightweight while providing access to complete, authoritative documentation.
