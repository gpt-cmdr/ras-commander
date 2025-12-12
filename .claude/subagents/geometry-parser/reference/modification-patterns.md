# Modification Patterns - Safe Geometry Updates

Best practices for modifying HEC-RAS geometry files while maintaining validity and preventing data loss.

## Table of Contents

1. [Backup File Creation](#backup-file-creation)
2. [Bank Station Requirements](#bank-station-requirements)
3. [450 Point Limit Validation](#450-point-limit-validation)
4. [Safe File Writing](#safe-file-writing)
5. [Common Modification Workflows](#common-modification-workflows)

---

## Backup File Creation

**Critical**: Always create backup before modifying geometry files.

### Automatic Backup Pattern

All write operations in `ras_commander.geom` automatically create `.bak` files:

```python
def create_backup(file_path):
    """Create .bak backup of file."""
    from pathlib import Path
    import shutil

    file_path = Path(file_path)
    backup_path = file_path.with_suffix(file_path.suffix + ".bak")

    if file_path.exists():
        shutil.copy2(file_path, backup_path)
        logger.info(f"Created backup: {backup_path}")

    return backup_path
```

**Result**:
```
Original: model.g01
Modified: model.g01
Backup:   model.g01.bak
```

### Restoration

Users can restore from backup by renaming:

```bash
# Windows
copy model.g01.bak model.g01

# Linux/Mac
cp model.g01.bak model.g01
```

### Timestamped Backups

For critical operations, use timestamped backups:

```python
from datetime import datetime

def create_timestamped_backup(file_path):
    """Create backup with timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{file_path}.{timestamp}.bak"
    shutil.copy2(file_path, backup_path)
    return backup_path
```

**Result**:
```
model.g01.20250112_143022.bak
```

---

## Bank Station Requirements

**Critical**: Bank stations MUST appear as exact points in station-elevation data.

### The Problem

HEC-RAS requires bank stations to exist in the cross section geometry:

**User Input**:
```python
# User provides XS data
df = pd.DataFrame({
    'Station': [0, 100, 200, 300],
    'Elevation': [100, 95, 95, 100]
})

# User specifies bank locations
bank_left = 50.0   # NOT in station array
bank_right = 250.0  # NOT in station array
```

**HEC-RAS Requirement**:
```
Bank stations must be present in station-elevation data.
If not, HEC-RAS will fail preprocessing or produce incorrect results.
```

### The Solution

`GeomCrossSection.set_station_elevation()` automatically handles this:

**Algorithm**:
1. Check if bank stations exist in user data
2. If missing, interpolate elevation at bank location
3. Insert bank point into sorted station array
4. Write complete dataset to file

**Implementation**:
```python
def insert_bank_stations(df, bank_left=None, bank_right=None):
    """Insert bank stations with interpolated elevations."""
    import numpy as np

    if bank_left is not None and bank_left not in df['Station'].values:
        # Interpolate elevation at bank_left
        elev_left = np.interp(bank_left, df['Station'], df['Elevation'])

        # Insert into dataframe
        new_row = pd.DataFrame({
            'Station': [bank_left],
            'Elevation': [elev_left]
        })
        df = pd.concat([df, new_row], ignore_index=True)

    if bank_right is not None and bank_right not in df['Station'].values:
        # Interpolate elevation at bank_right
        elev_right = np.interp(bank_right, df['Station'], df['Elevation'])

        # Insert into dataframe
        new_row = pd.DataFrame({
            'Station': [bank_right],
            'Elevation': [elev_right]
        })
        df = pd.concat([df, new_row], ignore_index=True)

    # Sort by station
    df = df.sort_values('Station').reset_index(drop=True)

    return df
```

### Example Workflow

**Before Bank Insertion**:
```
Station  Elevation
0        100.0
100      95.0
200      95.0
300      100.0

Bank Left: 50.0 (missing)
Bank Right: 250.0 (missing)
```

**After Bank Insertion**:
```
Station  Elevation
0        100.0
50       97.5      <- INSERTED (interpolated)
100      95.0
200      95.0
250      97.5      <- INSERTED (interpolated)
300      100.0
```

### User Experience

**Users don't need to handle this manually**:

```python
# User just calls set_station_elevation()
GeomCrossSection.set_station_elevation(
    geom_file,
    river,
    reach,
    rs,
    df,  # Original data (no bank points)
    bank_left=50.0,
    bank_right=250.0
)

# Method automatically:
# 1. Interpolates elevations at 50.0 and 250.0
# 2. Inserts bank points
# 3. Sorts by station
# 4. Writes to file
```

---

## 450 Point Limit Validation

**HEC-RAS Constraint**: Maximum 450 points per cross section.

### Validation Before Writing

Always validate point count:

```python
def validate_point_count(df, max_points=450):
    """Validate cross section point count."""
    num_points = len(df)

    if num_points > max_points:
        raise ValueError(
            f"Cross section has {num_points} points "
            f"(HEC-RAS maximum: {max_points})"
        )

    return True
```

### Simplification Strategies

If user data exceeds 450 points, simplify geometry:

**Option 1: Douglas-Peucker Algorithm**
```python
from shapely.geometry import LineString

def simplify_xs_geometry(df, max_points=450, tolerance=0.1):
    """Simplify XS geometry using Douglas-Peucker."""

    if len(df) <= max_points:
        return df  # No simplification needed

    # Create LineString
    line = LineString(zip(df['Station'], df['Elevation']))

    # Simplify with increasing tolerance until under limit
    current_tolerance = tolerance
    while True:
        simplified = line.simplify(current_tolerance)
        coords = list(simplified.coords)

        if len(coords) <= max_points:
            break

        current_tolerance *= 1.5  # Increase tolerance

    # Convert back to DataFrame
    stations, elevations = zip(*coords)
    return pd.DataFrame({
        'Station': stations,
        'Elevation': elevations
    })
```

**Option 2: Uniform Sampling**
```python
def downsample_xs_geometry(df, max_points=450):
    """Downsample XS geometry uniformly."""

    if len(df) <= max_points:
        return df

    # Keep every Nth point
    step = len(df) // max_points
    indices = list(range(0, len(df), step))

    # Always include first and last
    if indices[-1] != len(df) - 1:
        indices.append(len(df) - 1)

    return df.iloc[indices].reset_index(drop=True)
```

### Critical Points Preservation

When simplifying, preserve:
- First and last points (limits)
- Bank stations (hydraulic boundary)
- Low points (channel thalweg)
- High points (overbank crests)

```python
def simplify_preserve_critical(df, bank_left, bank_right, max_points=450):
    """Simplify while preserving critical points."""

    if len(df) <= max_points:
        return df

    # Identify critical indices
    critical_indices = set()

    # First and last
    critical_indices.add(0)
    critical_indices.add(len(df) - 1)

    # Bank stations
    bank_left_idx = (df['Station'] - bank_left).abs().idxmin()
    bank_right_idx = (df['Station'] - bank_right).abs().idxmin()
    critical_indices.add(bank_left_idx)
    critical_indices.add(bank_right_idx)

    # Low point (thalweg)
    min_elev_idx = df['Elevation'].idxmin()
    critical_indices.add(min_elev_idx)

    # Downsample non-critical points
    non_critical = [i for i in range(len(df)) if i not in critical_indices]
    remaining_points = max_points - len(critical_indices)
    step = len(non_critical) // remaining_points

    sampled_indices = sorted(
        list(critical_indices) + non_critical[::step]
    )

    return df.iloc[sampled_indices].reset_index(drop=True)
```

---

## Safe File Writing

### Atomic Write Pattern

Never write directly to original file - use temporary file:

```python
def safe_write_geometry(file_path, modified_lines):
    """Write geometry file atomically."""
    import tempfile
    from pathlib import Path

    file_path = Path(file_path)

    # Create backup
    create_backup(file_path)

    # Write to temporary file
    with tempfile.NamedTemporaryFile(
        mode='w',
        delete=False,
        dir=file_path.parent,
        suffix='.tmp'
    ) as tmp_file:
        tmp_path = Path(tmp_file.name)
        tmp_file.writelines(modified_lines)

    # Atomic replace
    tmp_path.replace(file_path)

    logger.info(f"Successfully wrote: {file_path}")
```

**Benefits**:
- Original file preserved if write fails
- No partial writes (atomic operation)
- Backup created before modification

### Line Ending Consistency

HEC-RAS expects Windows line endings (`\r\n`):

```python
def write_with_windows_endings(file_path, lines):
    """Write file with Windows line endings."""
    with open(file_path, 'w', newline='\r\n') as f:
        for line in lines:
            if not line.endswith('\n'):
                line += '\n'
            f.write(line)
```

### Encoding Handling

Geometry files are typically ASCII or UTF-8:

```python
def read_geometry_file(file_path):
    """Read geometry file with encoding fallback."""
    encodings = ['utf-8', 'latin-1', 'cp1252']

    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                return f.readlines()
        except UnicodeDecodeError:
            continue

    raise ValueError(f"Could not decode file: {file_path}")
```

---

## Common Modification Workflows

### Workflow 1: Modify Cross Section Elevations

**Scenario**: Lower channel by 2 feet.

```python
from ras_commander.geom.GeomCrossSection import GeomCrossSection

# Read current geometry
df = GeomCrossSection.get_station_elevation(
    "model.g01",
    "Ohio River",
    "Reach 1",
    "1000"
)

# Get bank stations
banks = GeomCrossSection.get_bank_stations(
    "model.g01",
    "Ohio River",
    "Reach 1",
    "1000"
)

# Modify channel (between banks)
channel_mask = (
    (df['Station'] >= banks['bank_left']) &
    (df['Station'] <= banks['bank_right'])
)
df.loc[channel_mask, 'Elevation'] -= 2.0

# Validate point count
if len(df) > 450:
    raise ValueError(f"Too many points: {len(df)}")

# Write back (bank stations auto-handled)
GeomCrossSection.set_station_elevation(
    "model.g01",
    "Ohio River",
    "Reach 1",
    "1000",
    df,
    bank_left=banks['bank_left'],
    bank_right=banks['bank_right']
)
```

### Workflow 2: Update All Manning's n Values

**Scenario**: Increase all channel roughness by 10%.

```python
from ras_commander.geom.GeomCrossSection import GeomCrossSection

# Get all cross sections
xs_df = GeomCrossSection.get_cross_sections("model.g01")

for _, row in xs_df.iterrows():
    # Get current Manning's n
    n_df = GeomCrossSection.get_mannings_n(
        "model.g01",
        row['River'],
        row['Reach'],
        row['RS']
    )

    # Increase channel n (index 1) by 10%
    n_df.loc[1, 'ManningsN'] *= 1.10

    # Write back
    GeomCrossSection.set_mannings_n(
        "model.g01",
        row['River'],
        row['Reach'],
        row['RS'],
        n_df
    )
```

### Workflow 3: Modify 2D Land Cover Roughness

**Scenario**: Update forest roughness values.

```python
from ras_commander.geom.GeomLandCover import GeomLandCover

# Read current land cover table
lc_df = GeomLandCover.get_base_mannings_n("model.g01")

# Update forest classifications (IDs 41-43)
forest_mask = lc_df['LandCoverID'].between(41, 43)
lc_df.loc[forest_mask, 'ManningsN'] = 0.15

# Validate
assert (lc_df['ManningsN'] >= 0.01).all(), "Manning's n too low"
assert (lc_df['ManningsN'] <= 1.0).all(), "Manning's n too high"

# Write back
GeomLandCover.set_base_mannings_n("model.g01", lc_df)
```

### Workflow 4: Batch Modify Multiple Cross Sections

**Scenario**: Apply elevation offset to all XS in a reach.

```python
from ras_commander.geom.GeomCrossSection import GeomCrossSection

# Get cross sections in reach
xs_df = GeomCrossSection.get_cross_sections(
    "model.g01",
    river="Ohio River",
    reach="Reach 1"
)

offset = 5.0  # Add 5 feet to all elevations

for _, row in xs_df.iterrows():
    # Read XS geometry
    df = GeomCrossSection.get_station_elevation(
        "model.g01",
        row['River'],
        row['Reach'],
        row['RS']
    )

    # Apply offset
    df['Elevation'] += offset

    # Validate
    assert len(df) <= 450, f"Too many points at RS {row['RS']}"

    # Write back
    GeomCrossSection.set_station_elevation(
        "model.g01",
        row['River'],
        row['Reach'],
        row['RS'],
        df,
        bank_left=row['Bank Left'],
        bank_right=row['Bank Right']
    )

    print(f"Modified RS {row['RS']}")
```

---

## Error Handling Best Practices

### Validation Before Modification

```python
def validate_before_write(df, bank_left, bank_right):
    """Validate data before writing."""

    # Check for NaN values
    if df.isnull().any().any():
        raise ValueError("DataFrame contains NaN values")

    # Check for duplicate stations
    if df['Station'].duplicated().any():
        raise ValueError("Duplicate stations found")

    # Check station ordering
    if not df['Station'].is_monotonic_increasing:
        raise ValueError("Stations must be monotonically increasing")

    # Check point count
    if len(df) > 450:
        raise ValueError(f"Too many points: {len(df)}")

    # Check bank stations
    if bank_left >= bank_right:
        raise ValueError("Bank left must be less than bank right")

    return True
```

### Rollback on Failure

```python
def modify_with_rollback(file_path, modify_func):
    """Modify file with automatic rollback on failure."""
    backup_path = create_backup(file_path)

    try:
        modify_func(file_path)
    except Exception as e:
        # Restore backup on failure
        shutil.copy2(backup_path, file_path)
        logger.error(f"Modification failed, restored backup: {e}")
        raise
    finally:
        # Optionally remove backup on success
        # backup_path.unlink()
        pass
```

### Logging and Audit Trail

```python
def log_modification(file_path, operation, details):
    """Log modification for audit trail."""
    from datetime import datetime

    log_entry = {
        'timestamp': datetime.now().isoformat(),
        'file': str(file_path),
        'operation': operation,
        'details': details
    }

    logger.info(f"Geometry modification: {log_entry}")

    # Optionally write to audit file
    audit_file = Path(file_path).parent / "geometry_modifications.log"
    with open(audit_file, 'a') as f:
        f.write(f"{log_entry}\n")
```

---

## Summary Checklist

Before modifying geometry files:

- [ ] Create backup (`.bak` file)
- [ ] Validate input data (no NaN, duplicates, ordering)
- [ ] Check point count (≤ 450 points)
- [ ] Handle bank station interpolation (automatic in `set_station_elevation()`)
- [ ] Use atomic write pattern (temp file → replace)
- [ ] Maintain Windows line endings (`\r\n`)
- [ ] Log modification for audit trail
- [ ] Test modified file in HEC-RAS (geometry check)
