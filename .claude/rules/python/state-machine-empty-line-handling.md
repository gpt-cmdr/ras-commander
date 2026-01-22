# State Machine Empty Line Handling Pattern

**Context**: Parsing text with state machines that process table sections
**Priority**: Medium - Prevents subtle parsing bugs
**Auto-loads**: When working with text parsers
**Discovered**: 2026-01-21 (results_df fallback implementation)

---

## The Pattern

### ✅ Correct: Separate Empty Line Checks

```python
for line in lines:
    line_stripped = line.strip()

    # Check 1: Skip empty lines (always)
    if not line_stripped:
        continue

    # Check 2: Skip specific header lines
    if line_stripped.startswith('Section Header'):
        continue

    # State machine logic processes remaining lines
    if in_table_state:
        process_line(line_stripped)
```

### ❌ Bug: Combined Empty Line Check

```python
for line in lines:
    line_stripped = line.strip()

    # BUGGY: Combines unrelated skip conditions
    if not line_stripped or line_stripped.startswith('Section Header'):
        continue

    # State machine never processes lines after empty line
    if in_table_state:
        process_line(line_stripped)  # Never reached after empty line!
```

---

## Why This Matters

### The Bug Mechanism

When checks are combined with `or`:
1. Empty line encountered → condition is True (from `not line_stripped`)
2. `continue` executes → skips to next line
3. **State remains active but no processing happens**
4. Next non-empty line may trigger different state transition
5. **Data lines in table are never processed**

### Real-World Example

**Computations Summary table** (HEC-RAS output):
```
Computation Task	Time(hh:mm:ss)
Completing Geometry	      27
Preprocessing Geometry	<1
                            <- Empty line here
Computation Speed	Simulation/Runtime
```

**With buggy combined check**:
- Line "Completing Geometry..." → Processed? **NO** (empty line skips it)
- Line "Preprocessing Geometry..." → Processed? **NO** (empty line skips it)
- Empty line → Skip due to combined check
- State transitions to speed table
- **Result**: No time data extracted

**With separated checks**:
- Line "Completing Geometry..." → Processed ✓
- Line "Preprocessing Geometry..." → Processed ✓
- Empty line → Skipped (state stays active)
- State transitions when "Computation Speed" found
- **Result**: All time data extracted correctly

---

## When to Separate Checks

### Always Separate When:

1. **Different skip reasons** - Empty vs specific content
2. **State machine parsing** - Table sections with intermittent empty lines
3. **Multi-section documents** - Need to stay in state across empty lines

### Example Scenarios:

**CSV-like tables with blank lines**:
```python
if not line_stripped:  # Skip empties
    continue
if line_stripped.startswith('#'):  # Skip comments
    continue
```

**Configuration file sections**:
```python
if not line_stripped:  # Skip empties
    continue
if line_stripped.startswith('['):  # New section header
    current_section = parse_header(line_stripped)
    continue
```

**Log file parsing**:
```python
if not line_stripped:  # Skip empties
    continue
if line_stripped.startswith('==='):  # Section divider
    reset_state()
    continue
```

---

## Testing Pattern

### Test With Empty Lines in Data

```python
def test_parser_with_empty_lines():
    """Verify parser handles empty lines correctly."""

    input_text = """
    Section Header

    Data Line 1
    Data Line 2

    Data Line 3
    """

    result = parse_with_state_machine(input_text)

    # Should extract all 3 data lines despite empty lines
    assert len(result) == 3
    assert 'Data Line 1' in result
    assert 'Data Line 2' in result
    assert 'Data Line 3' in result
```

---

## Anti-Pattern Detection

### Code Smell: Combined Skip Conditions

Look for patterns like:
```python
if not line or condition1 or condition2:
    continue
```

**Red flags**:
- Multiple unrelated conditions in single if statement
- `or` chaining skip conditions
- State machine with combined empty line check

**Refactor to**:
```python
if not line:
    continue
if condition1:
    continue
if condition2:
    continue
```

---

## Reference Implementation

**File**: `ras_commander/results/ResultsParser.py`
**Method**: `parse_compute_messages_runtime()`
**Lines**: 320-324

**Bug fix commit context**: Fixed parser returning all None values for runtime data

---

## See Also

- **Error Handling**: `.claude/rules/python/error-handling.md`
- **Testing Patterns**: `.claude/rules/testing/tdd-approach.md`
- **Implementation**: `ras_commander/results/ResultsParser.py` (working example)

---

**Key Takeaway**: Always separate empty line checks from content-based skip conditions in state machines. Combined checks with `or` cause state machines to skip data lines unintentionally.
