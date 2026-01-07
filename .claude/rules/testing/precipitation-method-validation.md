# Precipitation Method Validation Pattern

**Context**: Validating HMS-equivalent precipitation methods
**Priority**: High - affects regulatory compliance
**Auto-loads**: Yes (precipitation testing)

---

## Critical Validation Requirements

### Atlas 14 Depth Verification

**Always verify against NOAA PFDS website**: https://hdsc.nws.noaa.gov/pfds/pfds_map_cont.html

**Include verification link in notebooks**:
```python
print(f"Verify at: https://hdsc.nws.noaa.gov/pfds/pfds_map_cont.html?lat={lat}&lon={lon}")
```

**Why**: Users will check NOAA website to verify depths used in analysis. Any mismatch breaks trust and regulatory compliance.

---

## HMS-Equivalent Methods Must Match Target Exactly

### Depth Conservation Requirements

| Method | Precision Requirement | Target Source |
|--------|----------------------|---------------|
| **Atlas14Storm** | < 10^-6 inches | User-specified (from NOAA PFDS) |
| **FrequencyStorm** | < 10^-6 inches | User-specified (from NOAA PFDS or TP-40) |
| **ScsTypeStorm** | < 10^-6 inches | User-specified (from NOAA PFDS) |
| **StormGenerator** | ~1% (interpolation) | DDF table interpolation |

### Validation Pattern

```python
# For HMS-equivalent methods
target_depth = 17.0  # From NOAA PFDS website
hyeto = Atlas14Storm.generate_hyetograph(total_depth_inches=target_depth, ...)

actual_depth = hyeto.sum()
error = abs(actual_depth - target_depth)

assert error < 1e-6, f"Depth conservation failed: {error} inches"
print(f"✓ HMS Equivalence verified: {error:.9f} inches (< 10^-6)")
```

---

## StormGenerator Specific Notes

### AMS vs PDS Series

**Default**: `series='ams'` (Annual Maximum Series)
- Standard for engineering design
- Matches Atlas 14 published tables
- Used for FEMA flood studies

**Alternative**: `series='pds'` (Partial Duration Series)
- Research applications
- NOT standard for design

### Known Behavior

**StormGenerator interpolates from DDF table**:
- Returns interpolated value (may differ slightly from rounded Atlas 14 tables)
- Example: Houston 100-yr, 24-hr returns 14.1 inches (interpolated) vs 14.0 inches (NOAA table)
- **This is expected** - ~1% variation is acceptable for StormGenerator

**For exact depths**: Use HMS-equivalent methods (Atlas14Storm, FrequencyStorm, ScsTypeStorm)

---

## Comparison Testing Pattern

### Fair Comparison Requirements

**Rule**: When comparing multiple methods, all must use the **same target depth**

**Get target from NOAA PFDS**:
```python
# Option 1: Use published Atlas 14 value
TOTAL_DEPTH_INCHES = 17.0  # From NOAA PFDS website for location

# Option 2: Use StormGenerator download as reference (interpolated)
gen = StormGenerator.download_from_coordinates(lat, lon)
# Note: Will be ~1% different from published values
```

**Apply to all methods**:
```python
# All methods use SAME target
hyeto_atlas14 = Atlas14Storm.generate_hyetograph(total_depth_inches=TOTAL_DEPTH_INCHES, ...)
hyeto_freq = FrequencyStorm.generate_hyetograph(total_depth=TOTAL_DEPTH_INCHES, ...)
hyeto_scs = ScsTypeStorm.generate_hyetograph(total_depth_inches=TOTAL_DEPTH_INCHES, ...)
```

**Validation**:
```python
# Check all methods converge to target
depths = [hyeto_atlas14.sum(), hyeto_freq.sum(), hyeto_scs.sum()]
for method, depth in zip(['Atlas14', 'Frequency', 'ScsType'], depths):
    error = abs(depth - TOTAL_DEPTH_INCHES)
    print(f"{method}: {depth:.6f} inches, error: {error:.9f}")

# HMS methods should all be < 10^-6
assert all(abs(d - TOTAL_DEPTH_INCHES) < 1e-6 for d in depths[1:])
```

---

## Common Pitfalls

### ❌ Using Different Depths for Each Method

**Wrong**:
```python
# Each method gets different depth - NOT comparable
hyeto_atlas14 = Atlas14Storm.generate_hyetograph(17.0, ...)
hyeto_freq = FrequencyStorm.generate_hyetograph(13.2, ...)  # TP-40 depth
hyeto_scs = ScsTypeStorm.generate_hyetograph(10.0, ...)
```

**Right**:
```python
# All use SAME depth - fair comparison
target = 17.0  # Atlas 14 from NOAA PFDS
hyeto_atlas14 = Atlas14Storm.generate_hyetograph(target, ...)
hyeto_freq = FrequencyStorm.generate_hyetograph(target, ...)
hyeto_scs = ScsTypeStorm.generate_hyetograph(target, ...)
```

### ❌ Not Verifying Against NOAA PFDS

**Always include PFDS link** for user verification:
```python
print(f"Verify at: https://hdsc.nws.noaa.gov/pfds/pfds_map_cont.html?lat={lat}&lon={lon}")
```

**Why**: Regulatory reviewers will check NOAA PFDS. Any mismatch is a red flag.

---

## See Also

- **Method comparison**: `examples/720_precipitation_methods_comprehensive.ipynb`
- **StormGenerator bug fix**: `feature_dev_notes/Atlas14_HMS_Integration/STORMGENERATOR_BUG_FIX.md`
- **HMS validation**: `hms-commander/examples/08_atlas14_hyetograph_generation.ipynb`

---

**Key Takeaway**: HMS-equivalent methods must conserve depth at 10^-6 precision. Always verify precipitation values against NOAA PFDS website. Use same target depth when comparing methods.
