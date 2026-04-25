### Executive Summary
The new name/FID selector APIs in `GeomMesh.py` are close, but the spacing setters are still unsafe in the duplicate-name cases their docstrings call out. The main risks are silent multi-target edits when selecting by name, silent collapse of duplicate breakline spacings during text-to-HDF sync, and unsafe byte-level truncation for refinement-region names stored in fixed-width HDF fields.

This review was static. I inspected `GeomMesh.py`, the supporting helpers in the same file, and `tests/test_geom_mesh.py`; the current test coverage does not exercise the new name/FID/duplicate/HDF edge cases in the task scope.

### Severity-Ranked Findings
1. **Severity**: HIGH
**File**: `ras_commander/geom/GeomMesh.py:798`
**Issue**: `set_breakline_spacing(breakline_name=...)` updates every duplicate match, not the first match described by the docstring. In practice, `breakline_name=""` will edit every unnamed breakline block in the file.
**Evidence**:
```python
elif breakline_name is not None:
    in_target_block = name == breakline_name
    if in_target_block:
        found_target = True
```
The loop never records "already matched once", so every later `BreakLine Name=` header with the same name re-enters target mode and gets mutated.
**Fix**: Make name-based spacing follow the same ambiguity rule as `set_breakline_name()`: pre-scan for matches and raise on duplicates, or stop after the first match and update the docstring/tests to explicitly guarantee first-match semantics.

2. **Severity**: HIGH
**File**: `ras_commander/geom/GeomMesh.py:1845`
**Issue**: `set_refinement_region_spacing(region_name=...)` has the same ambiguity bug as the breakline spacing setter. Duplicate names, including empty names, cause every matching region to be edited even though the docstring says name targeting matches the first occurrence.
**Evidence**:
```python
if all_regions:
    target_match = True
elif region_fid is not None:
    target_match = i == region_fid
else:
    target_match = name == region_name
if not target_match:
    continue
found = True
```
There is no "already matched once" guard, so later duplicate-name rows are also updated.
**Fix**: Mirror `set_refinement_region_name()` and reject ambiguous `region_name` selectors, or explicitly stop after the first matched row and document that behavior consistently.

3. **Severity**: HIGH
**File**: `ras_commander/geom/GeomMesh.py:983`
**Issue**: Duplicate breakline names are collapsed during text-to-HDF sync, so a per-FID text edit is not preserved in the `generate()` workflow when names repeat or are empty. That undercuts the claim that `breakline_fid` is the reliable selector.
**Evidence**:
```python
hdf_names = [n.decode("utf-8", errors="replace").strip()
             for n in data["Name"]]
text_map = {name.strip(): (t_near, t_far, t_nr, t_pr)
            for _fid, name, t_near, t_far, t_nr, t_pr in bl_spacings}
for i, hdf_name in enumerate(hdf_names):
    if hdf_name in text_map:
        t_near, t_far, t_nr, t_pr = text_map[hdf_name]
```
`text_map` is keyed only by name, so the last duplicate wins and every HDF row with that name receives the same spacing.
**Fix**: Sync by stable row order/FID instead of by name, or detect duplicate/empty names and refuse the sync with a clear error so FID-targeted text edits are not silently overwritten.

4. **Severity**: MEDIUM
**File**: `ras_commander/geom/GeomMesh.py:1702`
**Issue**: `set_refinement_region_name()` truncates UTF-8 at an arbitrary byte boundary, which can write invalid byte sequences into the fixed-width HDF `Name` field. The rest of the API decodes with `errors="replace"`, so the stored name can no longer round-trip cleanly.
**Evidence**:
```python
encoded = new_name.encode("utf-8")
name_len = data.dtype["Name"].itemsize
if len(encoded) > name_len:
    encoded = encoded[:name_len]
data["Name"][found_idx] = encoded
```
This is safe for ASCII, but not for multibyte characters. In a fixed-width `S5` field, writing `"ééé"` stores `b"\xc3\xa9\xc3\xa9\xc3"`, which decodes as `éé�`.
**Fix**: Truncate by Unicode code point while preserving a valid UTF-8 prefix, then re-check the stored/truncated value for duplicate collisions before assignment. Shorter names do not need manual padding; NumPy/HDF fixed-width string assignment already handles that.

5. **Severity**: MEDIUM
**File**: `ras_commander/geom/GeomMesh.py:1843`
**Issue**: `set_refinement_region_spacing()` unconditionally reads and decodes the `Name` column even when the caller is targeting by `region_fid` or `all_regions`. A malformed HDF missing `Name` will therefore fail on code paths that do not need names at all.
**Evidence**:
```python
for i in range(len(data)):
    name = data["Name"][i].decode("utf-8", errors="replace").strip()
    if all_regions:
        target_match = True
    elif region_fid is not None:
        target_match = i == region_fid
```
The same assumption appears in `get_refinement_region_names()` and `get_refinement_regions()`, which access `row["Name"]` without validating the dtype first.
**Fix**: Branch on `all_regions` / `region_fid` before touching `Name`, and explicitly validate `"Name" in data.dtype.names` only on name-dependent code paths. Raise a targeted `ValueError` instead of letting NumPy/HDF field lookup errors escape.

6. **Severity**: MEDIUM
**File**: `ras_commander/geom/GeomMesh.py:1476`
**Issue**: The public selector validation does not enforce exclusivity between `all_breaklines` and a specific selector, or between `all_regions` and a specific selector. Passing `all_* = True` with `breakline_name`, `breakline_fid`, `region_name`, or `region_fid` silently broadens the edit to all features.
**Evidence**:
```python
if not all_breaklines and breakline_name is None and breakline_fid is None:
    raise ValueError(...)
if breakline_name is not None and breakline_fid is not None:
    raise ValueError(...)
```
and later:
```python
if all_breaklines:
    in_target_block = True
```
The same pattern exists in `set_refinement_region_spacing()`.
**Fix**: Reject any specific selector when `all_breaklines=True` or `all_regions=True`, matching the helper comment that target selection should be "exactly one" mode.

### Agreement with Existing Code
The basic FID accounting is consistent. Breakline readers and writers use 0-based file order, and refinement-region readers and writers use 0-based HDF order, which is easy to understand and document.

The rename APIs already take the safer approach to ambiguous selectors. `set_breakline_name()` and `set_refinement_region_name()` both raise when `old_name` matches multiple features, and both defer writing until after the full scan, so they avoid partial edits on ambiguity.

The text-backed breakline editors also do the right thing operationally by creating `.bak` backups before writing. On the HDF side, fixed-width string assignment correctly null-pads shorter names, so the padding concern is fine; the remaining bug is the truncation boundary, not the storage width itself.

I did not find a meaningful path-traversal or HDF-injection issue beyond the normal local-file API surface. The main problems here are correctness and API consistency, not security.

### Recommended Test Cases
1. Add a duplicate-name breakline test with two `BreakLine Name=Road` blocks and assert that `set_breakline_spacing(breakline_name="Road")` either raises for ambiguity or updates only one documented target.
2. Add an unnamed-breakline test with two `BreakLine Name=` blocks and verify `set_breakline_spacing(breakline_name="")` does not silently update both.
3. Add the equivalent duplicate-name and unnamed-name tests for `set_refinement_region_spacing(region_name=...)`.
4. Add an end-to-end sync test where two breaklines share the same name but have different per-FID spacings in text, then call `_sync_breakline_spacing_text_to_hdf()` and assert the HDF rows retain distinct values.
5. Add a fixed-width HDF name test that renames a region with ASCII and multibyte Unicode values at, below, and above the field byte limit, and assert the stored bytes remain valid UTF-8 after truncation.
6. Add malformed-HDF tests where the refinement-region `Attributes` dataset is missing `Name`, `Spacing dx`, or `Spacing dy`, and assert the APIs raise targeted `ValueError`s with actionable messages.
7. Add selector-validation tests for `all_breaklines=True` plus `breakline_fid`/`breakline_name`, and `all_regions=True` plus `region_fid`/`region_name`.
8. Add negative and out-of-range FID tests for both breaklines and refinement regions so the desired error contract is explicit.

### Architecture Observations
Breakline APIs and refinement-region APIs look parallel on the surface, but they sit on different persistence models: breaklines edit `.g##` text and return a backup path, while refinement regions mutate compiled HDF in place and return `None`. That asymmetry is defensible, but the selector semantics should still be unified across both families.

Right now the rename APIs are safer than the spacing APIs because they reject ambiguous `old_name` selectors. Pulling selector resolution into a shared helper would likely fix most of the current inconsistencies in one place: duplicate detection, empty-name handling, `all_*` exclusivity, negative-FID validation, and consistent error messages.

The refinement-region methods also repeat the same HDF open/read/field-validation boilerplate. A small helper for "load attributes dataset, validate required fields, decode/encode names safely" would reduce drift and make future schema handling easier.

`tests/test_geom_mesh.py` does not currently exercise the new review focus area in any meaningful way. The file has basic coverage for `set_breakline_spacing(all_breaklines=True)`, but not for name-based targeting, per-FID targeting, duplicates, empty names, HDF name truncation, or malformed refinement-region attribute tables.
