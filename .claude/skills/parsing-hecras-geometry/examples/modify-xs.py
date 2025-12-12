"""
Modify HEC-RAS Cross Section Geometry Example

Demonstrates safe modification of cross section station-elevation data,
including validation, backup creation, and bank station handling.
"""

from pathlib import Path
import sys
import pandas as pd
import numpy as np

# Flexible imports for development vs installed package
try:
    from ras_commander.geom.GeomCrossSection import GeomCrossSection
    from ras_commander.geom.GeomParser import GeomParser
except ImportError:
    current_file = Path(__file__).resolve()
    parent_directory = current_file.parent.parent.parent.parent
    sys.path.append(str(parent_directory))
    from ras_commander.geom.GeomCrossSection import GeomCrossSection
    from ras_commander.geom.GeomParser import GeomParser


def lower_channel_invert(geom_file, river, reach, rs, depth_feet):
    """
    Lower channel invert between bank stations.

    Parameters:
        geom_file: Path to geometry file
        river: River name
        reach: Reach name
        rs: River station
        depth_feet: Amount to lower invert (feet)
    """
    print(f"\n=== Lowering Channel Invert ===")
    print(f"Cross Section: {river} - {reach} - {rs}")
    print(f"Depth: {depth_feet} feet")

    # Read current geometry
    df = GeomCrossSection.get_station_elevation(geom_file, river, reach, rs)
    banks = GeomCrossSection.get_bank_stations(geom_file, river, reach, rs)

    print(f"\nOriginal geometry:")
    print(f"  Points: {len(df)}")
    print(f"  Bank Left: {banks['BankLeft']:.2f}")
    print(f"  Bank Right: {banks['BankRight']:.2f}")

    # Modify channel (between bank stations)
    channel_mask = (
        (df['Station'] >= banks['BankLeft']) &
        (df['Station'] <= banks['BankRight'])
    )

    original_min = df.loc[channel_mask, 'Elevation'].min()
    df.loc[channel_mask, 'Elevation'] -= depth_feet
    new_min = df.loc[channel_mask, 'Elevation'].min()

    print(f"\nChannel invert:")
    print(f"  Original: {original_min:.2f}")
    print(f"  Modified: {new_min:.2f}")
    print(f"  Change: {new_min - original_min:.2f}")

    # Validate before writing
    validate_cross_section(df, river, reach, rs)

    # Write back (creates .bak backup automatically)
    GeomCrossSection.set_station_elevation(
        geom_file,
        river,
        reach,
        rs,
        df,
        bank_left=banks['BankLeft'],
        bank_right=banks['BankRight']
    )

    print(f"\nModification complete!")
    print(f"Backup created: {geom_file}.bak")

    return df


def raise_overbanks(geom_file, river, reach, rs, elevation_change):
    """
    Raise overbank elevations (outside bank stations).

    Parameters:
        geom_file: Path to geometry file
        river: River name
        reach: Reach name
        rs: River station
        elevation_change: Amount to raise overbanks (feet)
    """
    print(f"\n=== Raising Overbanks ===")
    print(f"Cross Section: {river} - {reach} - {rs}")
    print(f"Elevation change: {elevation_change} feet")

    # Read current geometry
    df = GeomCrossSection.get_station_elevation(geom_file, river, reach, rs)
    banks = GeomCrossSection.get_bank_stations(geom_file, river, reach, rs)

    # Modify overbanks (outside bank stations)
    left_overbank = df['Station'] < banks['BankLeft']
    right_overbank = df['Station'] > banks['BankRight']
    overbank_mask = left_overbank | right_overbank

    df.loc[overbank_mask, 'Elevation'] += elevation_change

    print(f"\nModified {overbank_mask.sum()} overbank points")

    # Validate before writing
    validate_cross_section(df, river, reach, rs)

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

    print(f"Modification complete!")

    return df


def simplify_cross_section(geom_file, river, reach, rs, target_points=400):
    """
    Reduce cross section points while preserving shape.

    Parameters:
        geom_file: Path to geometry file
        river: River name
        reach: Reach name
        rs: River station
        target_points: Target number of points
    """
    print(f"\n=== Simplifying Cross Section ===")
    print(f"Cross Section: {river} - {reach} - {rs}")
    print(f"Target points: {target_points}")

    # Read current geometry
    df = GeomCrossSection.get_station_elevation(geom_file, river, reach, rs)
    banks = GeomCrossSection.get_bank_stations(geom_file, river, reach, rs)

    print(f"\nOriginal points: {len(df)}")

    if len(df) <= target_points:
        print("No simplification needed (already below target)")
        return df

    # Interpolate to target number of points
    from scipy.interpolate import interp1d

    f = interp1d(df['Station'], df['Elevation'], kind='linear')
    new_stations = np.linspace(df['Station'].min(), df['Station'].max(), target_points)
    new_elevations = f(new_stations)

    # Create simplified DataFrame
    simplified_df = pd.DataFrame({
        'Station': new_stations,
        'Elevation': new_elevations
    })

    print(f"Simplified points: {len(simplified_df)}")
    print(f"Reduction: {len(df) - len(simplified_df)} points ({(1 - len(simplified_df)/len(df))*100:.1f}%)")

    # Validate before writing
    validate_cross_section(simplified_df, river, reach, rs)

    # Write back
    GeomCrossSection.set_station_elevation(
        geom_file,
        river,
        reach,
        rs,
        simplified_df,
        bank_left=banks['BankLeft'],
        bank_right=banks['BankRight']
    )

    print(f"Simplification complete!")

    return simplified_df


def batch_modify_reach(geom_file, river, reach, modification_func):
    """
    Apply modification to all cross sections in a reach.

    Parameters:
        geom_file: Path to geometry file
        river: River name
        reach: Reach name
        modification_func: Function to modify each XS DataFrame
    """
    print(f"\n=== Batch Modifying Reach ===")
    print(f"River: {river}")
    print(f"Reach: {reach}")

    # Get all cross sections in reach
    xs_df = GeomCrossSection.get_cross_sections(geom_file, river=river, reach=reach)
    print(f"\nFound {len(xs_df)} cross sections")

    modified_count = 0
    for _, row in xs_df.iterrows():
        rs = row['RS']

        try:
            # Read geometry
            df = GeomCrossSection.get_station_elevation(geom_file, river, reach, rs)
            banks = GeomCrossSection.get_bank_stations(geom_file, river, reach, rs)

            # Apply modification
            modified_df = modification_func(df, banks)

            # Validate
            validate_cross_section(modified_df, river, reach, rs)

            # Write back
            GeomCrossSection.set_station_elevation(
                geom_file,
                river,
                reach,
                rs,
                modified_df,
                bank_left=banks['BankLeft'],
                bank_right=banks['BankRight']
            )

            modified_count += 1
            print(f"  Modified {rs}")

        except Exception as e:
            print(f"  Error modifying {rs}: {e}")
            continue

    print(f"\nModified {modified_count}/{len(xs_df)} cross sections")

    return modified_count


def validate_cross_section(df, river, reach, rs):
    """
    Validate cross section data before writing.

    Raises ValueError if validation fails.
    """
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

    # 5. Elevation reasonableness
    if (df['Elevation'] < -1000).any() or (df['Elevation'] > 10000).any():
        errors.append("Elevations outside reasonable range [-1000, 10000]")

    if errors:
        raise ValueError(f"Validation failed for {river}-{reach}-{rs}:\n" + "\n".join(errors))

    return True


def main():
    """Main function to demonstrate cross section modifications."""

    # Example geometry file path
    # Replace with actual path to your geometry file
    geom_file = Path("path/to/your/model.g01")

    if not geom_file.exists():
        print(f"Geometry file not found: {geom_file}")
        print("\nPlease update the geom_file path in this script.")
        return

    print(f"Modifying geometry file: {geom_file}")

    # Get first cross section for examples
    xs_df = GeomCrossSection.get_cross_sections(geom_file)
    if xs_df.empty:
        print("No cross sections found in geometry file")
        return

    row = xs_df.iloc[0]
    river = row['River']
    reach = row['Reach']
    rs = row['RS']

    # Example 1: Lower channel invert
    lower_channel_invert(geom_file, river, reach, rs, depth_feet=2.0)

    # Example 2: Raise overbanks
    # raise_overbanks(geom_file, river, reach, rs, elevation_change=1.0)

    # Example 3: Simplify cross section
    # simplify_cross_section(geom_file, river, reach, rs, target_points=400)

    # Example 4: Batch modification
    # Define custom modification function
    def raise_all_elevations(df, banks):
        """Raise all elevations by 1 foot."""
        df['Elevation'] += 1.0
        return df

    # Apply to all XS in reach
    # batch_modify_reach(geom_file, river, reach, raise_all_elevations)

    print("\n=== Modifications Complete ===")
    print(f"\nTo restore original file: mv {geom_file}.bak {geom_file}")


if __name__ == "__main__":
    main()
