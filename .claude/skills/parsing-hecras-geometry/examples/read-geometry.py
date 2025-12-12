"""
Read HEC-RAS Geometry File Example

Demonstrates parsing cross sections, bridges, culverts, storage areas,
and 2D Manning's n land cover from HEC-RAS geometry files.
"""

from pathlib import Path
import sys

# Flexible imports for development vs installed package
try:
    from ras_commander.geom.GeomCrossSection import GeomCrossSection
    from ras_commander.geom.GeomBridge import GeomBridge
    from ras_commander.geom.GeomCulvert import GeomCulvert
    from ras_commander.geom.GeomStorage import GeomStorage
    from ras_commander.geom.GeomLandCover import GeomLandCover
except ImportError:
    current_file = Path(__file__).resolve()
    parent_directory = current_file.parent.parent.parent.parent
    sys.path.append(str(parent_directory))
    from ras_commander.geom.GeomCrossSection import GeomCrossSection
    from ras_commander.geom.GeomBridge import GeomBridge
    from ras_commander.geom.GeomCulvert import GeomCulvert
    from ras_commander.geom.GeomStorage import GeomStorage
    from ras_commander.geom.GeomLandCover import GeomLandCover


def read_cross_sections(geom_file):
    """Read all cross sections from geometry file."""
    print("\n=== Reading Cross Sections ===")

    # List all cross sections
    xs_df = GeomCrossSection.get_cross_sections(geom_file)
    print(f"\nFound {len(xs_df)} cross sections")
    print(xs_df[['River', 'Reach', 'RS', 'NodeName']].head())

    # Get geometry for first cross section
    if not xs_df.empty:
        row = xs_df.iloc[0]
        river = row['River']
        reach = row['Reach']
        rs = row['RS']

        print(f"\nReading {river} - {reach} - {rs}:")

        # Get station-elevation profile
        df = GeomCrossSection.get_station_elevation(geom_file, river, reach, rs)
        print(f"  Points: {len(df)}")
        print(f"  Station range: {df['Station'].min():.2f} to {df['Station'].max():.2f}")
        print(f"  Elevation range: {df['Elevation'].min():.2f} to {df['Elevation'].max():.2f}")

        # Get bank stations
        banks = GeomCrossSection.get_bank_stations(geom_file, river, reach, rs)
        print(f"  Bank Left: {banks['BankLeft']:.2f}")
        print(f"  Bank Right: {banks['BankRight']:.2f}")

        # Get Manning's n values
        n_data = GeomCrossSection.get_mannings_n(geom_file, river, reach, rs)
        print(f"  Manning's n: {n_data['Values']}")


def read_bridges(geom_file):
    """Read bridge structures from geometry file."""
    print("\n=== Reading Bridges ===")

    # List all bridges
    bridges_df = GeomBridge.get_bridges(geom_file)
    print(f"\nFound {len(bridges_df)} bridges")

    if not bridges_df.empty:
        print(bridges_df[['River', 'Reach', 'RS']].head())

        # Get deck geometry for first bridge
        row = bridges_df.iloc[0]
        river = row['River']
        reach = row['Reach']
        rs = row['RS']

        print(f"\nReading bridge {river} - {reach} - {rs}:")

        deck_df = GeomBridge.get_deck(geom_file, river, reach, rs)
        print(f"  Deck points: {len(deck_df)}")
        print(deck_df.head())

        # Get pier data
        piers_df = GeomBridge.get_piers(geom_file, river, reach, rs)
        if not piers_df.empty:
            print(f"\n  Piers: {len(piers_df)}")
            print(piers_df.head())


def read_culverts(geom_file):
    """Read culvert structures from geometry file."""
    print("\n=== Reading Culverts ===")

    # Get all culverts
    culverts_df = GeomCulvert.get_all(geom_file)
    print(f"\nFound {len(culverts_df)} culverts")

    if not culverts_df.empty:
        print(culverts_df[['River', 'Reach', 'RS', 'Shape']].head())

        # Interpret shape codes
        shape_map = {
            1: "Circular",
            2: "Box",
            3: "Pipe Arch",
            4: "Ellipse",
            5: "Arch",
            6: "Semi-Circle",
            7: "Low Profile Arch",
            8: "High Profile Arch",
            9: "Con Span"
        }

        print("\nCulvert Details:")
        for _, row in culverts_df.head().iterrows():
            shape_code = row['Shape']
            shape_name = shape_map.get(shape_code, "Unknown")
            print(f"  {row['River']} - {row['RS']}: {shape_name}")


def read_storage_areas(geom_file):
    """Read storage area elevation-volume curves."""
    print("\n=== Reading Storage Areas ===")

    # List storage areas (exclude 2D flow areas)
    storage_areas = GeomStorage.get_storage_areas(geom_file, exclude_2d=True)
    print(f"\nFound {len(storage_areas)} storage areas")

    if storage_areas:
        # Get elevation-volume curve for first storage area
        area_name = storage_areas[0]
        print(f"\nReading storage area: {area_name}")

        df = GeomStorage.get_elevation_volume(geom_file, area_name)
        print(f"  Elevation points: {len(df)}")
        print(df.head())


def read_land_cover(geom_file):
    """Read 2D Manning's n land cover table."""
    print("\n=== Reading 2D Land Cover ===")

    try:
        # Read base Manning's n table
        lc_df = GeomLandCover.get_base_mannings_n(geom_file)
        print(f"\nFound {len(lc_df)} land cover classes")
        print(lc_df.head(10))

    except Exception as e:
        print(f"No 2D land cover found (file may be 1D only): {e}")


def main():
    """Main function to demonstrate reading geometry files."""

    # Example geometry file path
    # Replace with actual path to your geometry file
    geom_file = Path("path/to/your/model.g01")

    if not geom_file.exists():
        print(f"Geometry file not found: {geom_file}")
        print("\nPlease update the geom_file path in this script.")
        return

    print(f"Reading geometry file: {geom_file}")

    # Read different geometry components
    read_cross_sections(geom_file)
    read_bridges(geom_file)
    read_culverts(geom_file)
    read_storage_areas(geom_file)
    read_land_cover(geom_file)

    print("\n=== Reading Complete ===")


if __name__ == "__main__":
    main()
