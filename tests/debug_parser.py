"""Debug GeomParser.get_xs_cut_lines() to understand why it's not working"""

import sys
from pathlib import Path

# Use local source
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

geom_file = Path("example_projects/Muncie_test_xs_coords/Muncie.g01")

print(f"Reading: {geom_file}")
print("=" * 80)

with open(geom_file, 'r') as f:
    lines = f.readlines()

current_river = None
current_reach = None
current_station = None

for i, line in enumerate(lines):
    stripped = line.strip()

    # Track river/reach
    if stripped.startswith("River Reach="):
        parts = stripped.split("=")[1].split(",")
        if len(parts) >= 2:
            current_river = parts[0].strip()
            current_reach = parts[1].strip()
            print(f"Line {i+1}: River Reach = {current_river} / {current_reach}")

    # Track station
    elif stripped.startswith("Type RM Length L Ch R ="):
        value_str = stripped.split("=")[1]
        values = [v.strip() for v in value_str.split(',')]
        if len(values) >= 2:
            current_station = values[1]
            print(f"Line {i+1}: Station = {current_station}")

    # Parse cut line
    elif stripped.startswith("XS GIS Cut Line="):
        print(f"\nLine {i+1}: XS GIS Cut Line found")
        print(f"  Current state: river={current_river}, reach={current_reach}, station={current_station}")

        if current_river is None or current_reach is None or current_station is None:
            print(f"  SKIPPED - missing river/reach/station")
            continue

        count_str = stripped.split("=")[1].strip()
        try:
            num_points = int(count_str)
            total_values = num_points * 2
            print(f"  Expecting {num_points} points ({total_values} values)")
        except ValueError:
            print(f"  ERROR: Could not parse num_points from '{count_str}'")
            continue

        coords = []
        j = i + 1
        values_read = 0

        while values_read < total_values and j < len(lines):
            data_line = lines[j].strip()
            print(f"    Line {j+1}: '{data_line[:50]}...'")

            if not data_line:
                print(f"      Empty line - stopping")
                break

            if data_line.startswith(('River', 'Type', 'Node', '#', 'XS', 'Levee', 'Bank')):
                print(f"      Starts with keyword - stopping")
                break

            parts = data_line.split()
            print(f"      Split into {len(parts)} parts")
            for part in parts:
                try:
                    coord = float(part)
                    coords.append(coord)
                    values_read += 1
                    if values_read <= 4:  # Print first few
                        print(f"        Value {values_read}: {coord}")
                except ValueError:
                    print(f"      ERROR: Could not parse '{part}' as float")
                    break
            j += 1

        print(f"  Total values read: {values_read} / {total_values}")
        print(f"  Coords: {len(coords)} values")

        if len(coords) >= 4:
            points = [(coords[k], coords[k+1]) for k in range(0, len(coords)-1, 2)]
            if len(points) >= 2:
                print(f"  SUCCESS: Created LineString with {len(points)} points")
                print(f"    First point: ({points[0][0]:.2f}, {points[0][1]:.2f})")
                print(f"    Last point: ({points[-1][0]:.2f}, {points[-1][1]:.2f})")
            else:
                print(f"  FAILED: Not enough points ({len(points)})")
        else:
            print(f"  FAILED: Not enough coords ({len(coords)})")

        # Only process first few for debugging
        if i > 200:
            break

print("\n" + "=" * 80)
print("Done")
