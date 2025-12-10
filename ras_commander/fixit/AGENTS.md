# AGENTS.md - fixit Subpackage

This file provides guidance for AI agents working with the fixit subpackage.

## Purpose

The fixit subpackage provides automated geometry repair capabilities for HEC-RAS models. It complements the `check/` subpackage by providing repair functionality for detected issues.

## Module Organization

```
fixit/
├── __init__.py         # Exports RasFixit, FixResults, FixMessage, FixAction, BlockedObstruction
├── RasFixit.py         # Main static class with fix methods
├── obstructions.py     # BlockedObstruction dataclass and elevation envelope algorithm
├── results.py          # FixAction enum, FixMessage, FixResults dataclasses
├── visualization.py    # Lazy-loaded matplotlib PNG generation
├── log_parser.py       # HEC-RAS compute log parsing for error detection
└── AGENTS.md           # This file
```

## Key Patterns

### Static Class Pattern
- `RasFixit` uses `@staticmethod` for all public methods
- All methods use `@log_call` decorator for automatic logging
- No instantiation required: `RasFixit.fix_blocked_obstructions()` not `RasFixit().fix_blocked_obstructions()`

### Lazy Loading
- `visualization.py` imports matplotlib only when `visualize=True`
- This keeps matplotlib truly optional for users who don't need visualizations

### Result Containers
- `FixResults` contains aggregate statistics and list of `FixMessage` objects
- Use `results.to_dataframe()` for pandas DataFrame output
- All results include original and fixed data for audit trail

## Critical Algorithm Details

### Elevation Envelope (obstructions.py)

The `create_elevation_envelope()` function is the core algorithm. These details MUST be preserved:

1. **0.02-unit Gap Insertion** (line ~110 in obstructions.py)
   - HEC-RAS requires minimum 0.02-unit separation between adjacent obstructions
   - Gap is inserted when segments have different elevations and touch
   - `GAP_SIZE = 0.02` constant must not be changed

2. **Max Elevation Wins**
   - In overlap zones, the maximum elevation is used (most restrictive)
   - This is hydraulically conservative

3. **Fixed-Width Parsing** (8 characters)
   - HEC-RAS geometry files use FORTRAN-style 8-character columns
   - `FIELD_WIDTH = 8` constant must not be changed
   - Overflow handled with asterisks (`********`)

4. **Section Terminators**
   - Data block ends at: `Bank Sta=`, `#XS Ineff=`, `#Mann=`, `XS Rating Curve=`, `XS HTab`, `Exp/Cntr=`

## Adding New Fix Types

To add a new fix type (e.g., `fix_ineffective_flow()`):

1. Create algorithm module (e.g., `ineffective.py`) with:
   - Dataclass for the element type
   - Parse function from geometry file
   - Fix algorithm
   - Format function back to geometry file

2. Add new `FixAction` enum value in `results.py`

3. Add new static method to `RasFixit.py`:
   ```python
   @staticmethod
   @log_call
   def fix_ineffective_flow(geom_path, backup=True, ...) -> FixResults:
       ...
   ```

4. Update `__init__.py` exports if needed

5. Add visualization support in `visualization.py` if applicable

## Testing

Test data is available at:
- `C:\GH\ras-obstruction-fixer\testdata\A100_00_00.g04` (104 overlaps)

Example test:
```python
from ras_commander import RasFixit

# Test detection
results = RasFixit.detect_obstruction_overlaps("A100_00_00.g04")
assert results.total_xs_fixed > 0

# Test fix (on copy of file)
import shutil
shutil.copy("A100_00_00.g04", "test_copy.g04")
results = RasFixit.fix_blocked_obstructions("test_copy.g04", visualize=True)
assert results.total_xs_fixed > 0
```

## Engineering Review Requirements

All fix operations MUST:
1. Create timestamped backups (default `backup=True`)
2. Generate verification outputs when `visualize=True`
3. Preserve original and fixed data in `FixMessage` for audit trail
4. Include clear documentation that results require PE review

## Relationship to Check Module

- `check/RasCheck.py` has XS_BO_01 and XS_BO_02 checks that DETECT obstruction issues
- `fixit/RasFixit.py` provides `fix_blocked_obstructions()` to REPAIR those issues
- Check operates on HDF files; Fixit operates on plain text geometry files
- No code sharing, but message IDs follow similar convention (XS_BO vs FX_BO)
