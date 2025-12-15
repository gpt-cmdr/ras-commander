# Precipitation Specialist Refactor Summary

## Before vs After

### Line Count Reduction
- **Before**: 1,174 lines total
  - `SUBAGENT.md`: 248 lines
  - `reference/aorc-api.md`: 437 lines
  - `reference/atlas14.md`: 490 lines

- **After**: 232 lines total
  - `SUBAGENT.md`: 232 lines
  - `reference/` folder: DELETED

- **Reduction**: 80.2% reduction (1,174 → 232 lines)

## What Changed

### Deleted Content
1. **`reference/aorc-api.md` (437 lines)**
   - Complete API reference with all method signatures
   - Workflow examples duplicating CLAUDE.md
   - Already exists in: `ras_commander/precip/CLAUDE.md` lines 92-156

2. **`reference/atlas14.md` (490 lines)**
   - Complete Atlas 14 API reference
   - Design storm workflows
   - Already exists in: `ras_commander/precip/CLAUDE.md` lines 158-280

### New Content
1. **Lightweight Navigator Pattern**
   - Direct pointers to primary sources
   - Line number references to CLAUDE.md sections
   - Notebook references for working examples
   - Minimal duplication of API surface

2. **Subagent Task Pattern** (new section)
   - Step-by-step guidance for subagent execution
   - Emphasizes "read primary source first"
   - Prevents workflow drift/hallucination

## Primary Sources (Single Source of Truth)

1. **`ras_commander/precip/CLAUDE.md`** (329 lines)
   - Complete AORC workflow (4 steps)
   - Complete Atlas 14 workflow (4 steps)
   - Multi-event workflows
   - ARF guidance
   - Module organization

2. **`examples/24_aorc_precipitation.ipynb`**
   - Working AORC demonstration
   - Project setup, bounds, catalog
   - Precipitation export and execution

3. **Code Implementation**
   - `PrecipAorc.py` (~38 KB)
   - `StormGenerator.py` (~27 KB)

## Benefits

1. **Single Source of Truth**: All workflows maintained in CLAUDE.md
2. **Reduced Maintenance**: No duplicate content to keep in sync
3. **Faster Navigation**: Subagent reads 232 lines vs 1,174 lines
4. **Better Accuracy**: Direct line references prevent interpretation errors
5. **User-Facing**: CLAUDE.md is what users actually see

## Usage Pattern

When user requests precipitation work:
1. Subagent reads `SUBAGENT.md` (232 lines)
2. Opens `ras_commander/precip/CLAUDE.md` at specified line numbers
3. Follows documented workflow exactly
4. References notebooks for examples
5. Only reads code if API clarification needed

## Verification

```bash
# Before
find .claude/agents/precipitation-specialist -name "*.md" | xargs wc -l
# Output: 1,174 lines

# After
wc -l .claude/agents/precipitation-specialist/SUBAGENT.md
# Output: 232 lines
```

## Next Steps

Consider applying this pattern to other agents:
- Remote execution specialist
- HDF specialist
- Geometry specialist

**Goal**: All agents become lightweight navigators (~200-400 lines) pointing to primary sources.
