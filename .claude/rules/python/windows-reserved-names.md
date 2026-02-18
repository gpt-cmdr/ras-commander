# Windows Reserved Device Names in File Operations

**Context**: Handling Windows virtual device names during file copy/iteration
**Priority**: High - causes runtime failures on Windows
**Auto-loads**: Yes (all file operation code)
**Discovered**: 2026-02-04 (copytree failures with `nul` in project directories)

## The Problem

Windows has 22 reserved device names that appear in directory listings (`os.listdir()`, `Path.iterdir()`) even though they are virtual devices, not real files:

```
CON, PRN, AUX, NUL
COM1-COM9, LPT1-LPT9
```

`shutil.copytree()` fails when encountering these because it tries to open them as regular files.

## The Fix

### For shutil.copytree()

Use `RasUtils.ignore_windows_reserved` as the `ignore=` parameter:

```python
shutil.copytree(src, dst, ignore=RasUtils.ignore_windows_reserved)
```

### For iterdir() loops

Filter with `RasUtils.is_windows_reserved_name()`:

```python
for item in folder.iterdir():
    if RasUtils.is_windows_reserved_name(item.name):
        continue
    # process item...
```

### Matching Behavior

The check uses `Path(name).stem.upper()` which catches:
- Bare names: `nul`, `CON`, `AUX`
- Names with extensions: `nul.txt`, `NUL.dat`, `com1.log`
- Does NOT match: `confile.txt` (stem is `confile`, not `CON`)

## When to Apply

Apply this filter to ANY `shutil.copytree()` or `iterdir()` + copy/move loop that operates on user-provided directories (HEC-RAS project folders). These directories may contain reserved names depending on the user's environment.

## Implementation

- `RasUtils._WINDOWS_RESERVED_NAMES` - frozenset of 22 names
- `RasUtils.ignore_windows_reserved(directory, contents)` - copytree ignore function
- `RasUtils.is_windows_reserved_name(name)` - boolean check

## See Also

- `ras_commander/RasUtils.py` - Implementation
- `.claude/outputs/2026-02-04-windows-reserved-names-fix-closeout.md` - Full task details
