# Modification Patterns

Safe geometry modification workflows for HEC-RAS geometry files (.g##).

## Core Principles

### 1. Always Create Backups

All write operations automatically create `.bak` backup files:

```python
from ras_commander.geom.GeomParser import GeomParser

# Automatic backup creation
GeomParser.create_backup("model.g01")
# Creates: model.g01.bak
```

**Backup is created BEFORE modification** to ensure original data is preserved.

### 2. Validate Before Writing

Always validate data before writing to geometry file:

```python
def validate_before_write(df, max_points=450):
    """Validate cross section data before writing."""
    # Check point count
    if len(df) > max_points:
        raise ValueError(f"Cross section has {len(df)} points (max {max_points})")

    # Check for NaN values
    if df.isnull().any().any():
        raise ValueError("Cross section contains NaN values")

    # Check station order (must be sorted)
    if not df['Station'].is_monotonic_increasing:
        raise ValueError("Stations must be in ascending order")

    # Check for duplicate stations
    if df['Station'].duplicated().any():
        raise ValueError("Cross section contains duplicate stations")

    return True
```

### 3. Preserve File Structure

Maintain original file structure during modifications:
- Don't remove metadata lines
- Keep section order unchanged
- Preserve formatting where possible

### 4. Handle Bank Stations Correctly

Use automatic bank station interpolation:

```python
from ras_commander.geom.GeomCrossSection import GeomCrossSection

# Read current geometry and bank stations
df = GeomCrossSection.get_station_elevation(geom_file, river, reach, rs)
banks = GeomCrossSection.get_bank_stations(geom_file, river, reach, rs)

# Modify geometry
df['Elevation'] += 1.0  # Raise 1 foot

# Write back (bank interpolation handled automatically)
GeomCrossSection.set_station_elevation(
    geom_file,
    river,
    reach,
    rs,
    df,
    bank_left=banks['BankLeft'],
    bank_right=banks['BankRight']
)
```

**Don't manually insert bank points** - method does it automatically.

## Common Modification Workflows

### Workflow 1: Modify Cross Section Elevations

**Pattern**: Read → Modify → Validate → Write

```python
from ras_commander.geom.GeomCrossSection import GeomCrossSection
import pandas as pd

def lower_channel_invert(geom_file, river, reach, rs, depth_feet):
    """Lower channel invert by specified depth."""

    # Read current geometry
    df = GeomCrossSection.get_station_elevation(geom_file, river, reach, rs)
    banks = GeomCrossSection.get_bank_stations(geom_file, river, reach, rs)

    # Modify channel (between bank stations)
    channel_mask = (
        (df['Station'] >= banks['BankLeft']) &
        (df['Station'] <= banks['BankRight'])
    )
    df.loc[channel_mask, 'Elevation'] -= depth_feet

    # Validate
    if len(df) > 450:
        raise ValueError(f"Cross section exceeds 450 points: {len(df)}")

    # Write back (creates .bak automatically)
    GeomCrossSection.set_station_elevation(
        geom_file,
        river,
        reach,
        rs,
        df,
        bank_left=banks['BankLeft'],
        bank_right=banks['BankRight']
    )

    return df
```

### Workflow 2: Update Manning's n Values

**Pattern**: Read → Modify → Validate → Write

```python
from ras_commander.geom.GeomCrossSection import GeomCrossSection

def update_roughness(geom_file, river, reach, rs, channel_n, overbank_n):
    """Update Manning's n values for cross section."""

    # Read current Manning's n data
    n_data = GeomCrossSection.get_mannings_n(geom_file, river, reach, rs)
    # Returns: {'NumN': 3, 'Values': [0.035, 0.025, 0.035], 'Stations': [0, 100, 300]}

    # Modify n values
    # First and last values are overbanks, middle is channel
    new_values = [overbank_n, channel_n, overbank_n]

    # Note: GeomCrossSection doesn't have set_mannings_n() yet
    # This would require direct file manipulation (advanced pattern)

    return n_data
```

### Workflow 3: Batch Update Multiple Cross Sections

**Pattern**: List → Filter → Iterate → Modify

```python
from ras_commander.geom.GeomCrossSection import GeomCrossSection

def raise_all_cross_sections(geom_file, river, reach, elevation_change):
    """Raise all cross sections in a reach by specified amount."""

    # Get list of all cross sections
    xs_df = GeomCrossSection.get_cross_sections(geom_file, river=river, reach=reach)

    modified_count = 0
    for _, row in xs_df.iterrows():
        rs = row['RS']

        try:
            # Read geometry and banks
            df = GeomCrossSection.get_station_elevation(geom_file, river, reach, rs)
            banks = GeomCrossSection.get_bank_stations(geom_file, river, reach, rs)

            # Modify elevations
            df['Elevation'] += elevation_change

            # Validate
            if len(df) > 450:
                print(f"Warning: {rs} exceeds 450 points, skipping")
                continue

            # Write back
            GeomCrossSection.set_station_elevation(
                geom_file,
                river,
                reach,
                rs,
                df,
                bank_left=banks['BankLeft'],
                bank_right=banks['BankRight']
            )

            modified_count += 1

        except Exception as e:
            print(f"Error modifying {rs}: {e}")
            continue

    return modified_count
```

### Workflow 4: Update 2D Manning's n Land Cover

**Pattern**: Read → Modify → Write

```python
from ras_commander.geom.GeomLandCover import GeomLandCover

def increase_forest_roughness(geom_file, forest_id, new_n):
    """Update Manning's n for forest land cover."""

    # Read current land cover table
    lc_df = GeomLandCover.get_base_mannings_n(geom_file)
    # Returns: DataFrame with LandCoverID, ManningsN

    # Modify specific land cover
    lc_df.loc[lc_df['LandCoverID'] == forest_id, 'ManningsN'] = new_n

    # Validate
    if (lc_df['ManningsN'] < 0).any() or (lc_df['ManningsN'] > 1.0).any():
        raise ValueError("Manning's n values must be between 0 and 1")

    # Write back (creates .bak automatically)
    GeomLandCover.set_base_mannings_n(geom_file, lc_df)

    return lc_df
```

## Advanced Modification Patterns

### Pattern 1: Conditional Modification

Modify geometry based on conditions:

```python
def conditional_channel_modification(geom_file, river, reach, rs, threshold_elev):
    """Lower elevations only if they exceed threshold."""

    df = GeomCrossSection.get_station_elevation(geom_file, river, reach, rs)
    banks = GeomCrossSection.get_bank_stations(geom_file, river, reach, rs)

    # Apply conditional modification
    channel_mask = (
        (df['Station'] >= banks['BankLeft']) &
        (df['Station'] <= banks['BankRight']) &
        (df['Elevation'] > threshold_elev)
    )
    df.loc[channel_mask, 'Elevation'] = threshold_elev

    # Write back
    GeomCrossSection.set_station_elevation(
        geom_file, river, reach, rs, df,
        bank_left=banks['BankLeft'],
        bank_right=banks['BankRight']
    )
```

### Pattern 2: Geometry Simplification

Reduce point count while preserving shape:

```python
from scipy.interpolate import interp1d
import numpy as np

def simplify_cross_section(geom_file, river, reach, rs, target_points=400):
    """Reduce cross section points while preserving shape."""

    df = GeomCrossSection.get_station_elevation(geom_file, river, reach, rs)
    banks = GeomCrossSection.get_bank_stations(geom_file, river, reach, rs)

    if len(df) <= target_points:
        return df  # No simplification needed

    # Interpolate to target number of points
    f = interp1d(df['Station'], df['Elevation'], kind='linear')
    new_stations = np.linspace(df['Station'].min(), df['Station'].max(), target_points)
    new_elevations = f(new_stations)

    # Create simplified DataFrame
    simplified_df = pd.DataFrame({
        'Station': new_stations,
        'Elevation': new_elevations
    })

    # Write back
    GeomCrossSection.set_station_elevation(
        geom_file, river, reach, rs, simplified_df,
        bank_left=banks['BankLeft'],
        bank_right=banks['BankRight']
    )

    return simplified_df
```

### Pattern 3: Merge Modifications from Multiple Sources

Combine modifications from different sources:

```python
def merge_cross_section_modifications(base_df, *modification_dfs):
    """
    Merge multiple modifications to cross section.

    Each modification_df should have 'Station' and 'Elevation' columns.
    Elevations are averaged at each station.
    """
    import pandas as pd
    import numpy as np

    # Combine all dataframes
    all_dfs = [base_df] + list(modification_dfs)
    combined = pd.concat(all_dfs, ignore_index=True)

    # Group by station and average elevations
    merged = combined.groupby('Station', as_index=False).agg({
        'Elevation': 'mean'
    })

    # Sort by station
    merged = merged.sort_values('Station').reset_index(drop=True)

    return merged
```

## Validation Patterns

### Pre-Write Validation Checklist

```python
def comprehensive_validation(df, river, reach, rs, banks):
    """Comprehensive validation before writing."""

    errors = []

    # 1. Point count
    if len(df) > 450:
        errors.append(f"Exceeds 450 points: {len(df)}")

    # 2. NaN values
    if df.isnull().any().any():
        errors.append("Contains NaN values")

    # 3. Station order
    if not df['Station'].is_monotonic_increasing:
        errors.append("Stations not in ascending order")

    # 4. Duplicate stations
    if df['Station'].duplicated().any():
        errors.append("Contains duplicate stations")

    # 5. Bank stations within range
    if banks:
        station_min = df['Station'].min()
        station_max = df['Station'].max()

        if banks['BankLeft'] < station_min or banks['BankLeft'] > station_max:
            errors.append(f"BankLeft {banks['BankLeft']} outside station range")

        if banks['BankRight'] < station_min or banks['BankRight'] > station_max:
            errors.append(f"BankRight {banks['BankRight']} outside station range")

    # 6. Elevation reasonableness
    if (df['Elevation'] < -1000).any() or (df['Elevation'] > 10000).any():
        errors.append("Elevations outside reasonable range [-1000, 10000]")

    if errors:
        raise ValueError(f"Validation failed for {river}-{reach}-{rs}:\n" + "\n".join(errors))

    return True
```

### Post-Write Verification

```python
def verify_modification(geom_file, river, reach, rs, expected_df):
    """Verify modification was written correctly."""

    # Read back modified geometry
    actual_df = GeomCrossSection.get_station_elevation(geom_file, river, reach, rs)

    # Compare
    if len(actual_df) != len(expected_df):
        raise ValueError(f"Point count mismatch: {len(actual_df)} vs {len(expected_df)}")

    # Check stations match (within tolerance)
    station_diff = abs(actual_df['Station'] - expected_df['Station']).max()
    if station_diff > 0.01:
        raise ValueError(f"Station mismatch: max diff {station_diff}")

    # Check elevations match (within tolerance)
    elev_diff = abs(actual_df['Elevation'] - expected_df['Elevation']).max()
    if elev_diff > 0.01:
        raise ValueError(f"Elevation mismatch: max diff {elev_diff}")

    return True
```

## Error Recovery

### Restore from Backup

```python
def restore_from_backup(geom_file):
    """Restore geometry file from .bak backup."""
    from pathlib import Path
    import shutil

    backup_file = Path(str(geom_file) + ".bak")

    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_file}")

    # Copy backup to original
    shutil.copy2(backup_file, geom_file)
    print(f"Restored {geom_file} from backup")

    return geom_file
```

### Create Multiple Backup Versions

```python
def create_timestamped_backup(geom_file):
    """Create backup with timestamp."""
    from pathlib import Path
    import shutil
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = Path(str(geom_file) + f".bak_{timestamp}")

    shutil.copy2(geom_file, backup_file)
    print(f"Created backup: {backup_file}")

    return backup_file
```

## Thread Safety

### Safe Parallel Modifications

```python
from concurrent.futures import ThreadPoolExecutor
import threading

# Thread-safe lock for file access
file_locks = {}
lock_manager = threading.Lock()

def get_file_lock(geom_file):
    """Get thread-safe lock for geometry file."""
    with lock_manager:
        if geom_file not in file_locks:
            file_locks[geom_file] = threading.Lock()
        return file_locks[geom_file]

def safe_modify_cross_section(geom_file, river, reach, rs, modification_func):
    """Thread-safe cross section modification."""

    # Acquire file lock
    file_lock = get_file_lock(geom_file)

    with file_lock:
        # Read geometry
        df = GeomCrossSection.get_station_elevation(geom_file, river, reach, rs)
        banks = GeomCrossSection.get_bank_stations(geom_file, river, reach, rs)

        # Apply modification
        modified_df = modification_func(df)

        # Write back
        GeomCrossSection.set_station_elevation(
            geom_file, river, reach, rs, modified_df,
            bank_left=banks['BankLeft'],
            bank_right=banks['BankRight']
        )

    return modified_df
```

## Best Practices Summary

1. **Always create backups** before modification (automatic with geom methods)
2. **Validate before writing** (point count, NaN, order, duplicates)
3. **Use exact casing** for River/Reach/RS identifiers
4. **Let methods handle bank interpolation** (don't manually insert points)
5. **Check 450 point limit** before writing
6. **Verify modifications** by reading back and comparing
7. **Handle errors gracefully** with try/except and meaningful messages
8. **Use thread locks** for parallel modifications
9. **Create timestamped backups** for critical modifications
10. **Test on small dataset** before batch modifications

## See Also

- [Parsing Algorithms](parsing.md) - Fixed-width format details
- SKILL.md - Main skill documentation
- `ras_commander/geom/GeomCrossSection.py` - Reference implementation
