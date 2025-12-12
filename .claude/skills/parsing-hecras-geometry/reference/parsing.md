# Parsing Algorithms

Fixed-width FORTRAN format parsing algorithms used in HEC-RAS geometry files (.g##).

## Fixed-Width Format Structure

### Column Width: 8 Characters

Each numeric value occupies exactly 8 characters:

```
  12.34   56.78   90.12   34.56   78.90
  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  Col 1   Col 2   Col 3   Col 4   Col 5
  8 char  8 char  8 char  8 char  8 char
```

**Parsing Algorithm**:
```python
def parse_fixed_width(line, column_width=8):
    """Parse fixed-width numeric data from a line."""
    values = []
    for i in range(0, len(line), column_width):
        chunk = line[i:i+column_width].strip()
        if chunk:
            try:
                values.append(float(chunk))
            except ValueError:
                pass  # Skip non-numeric chunks
    return values
```

### Values Per Line: 10 (80 Characters Total)

Standard FORTRAN format: 10 values × 8 characters = 80 characters per line

**Example**:
```
#Sta/Elev= 40
    0.00   100.0    50.0    95.0   100.0    92.0   150.0    90.0   200.0    92.0
  250.0    95.0   300.0   100.0
```

**Line Count Calculation**:
- Count value: 40 (means 40 PAIRS)
- Total values: 80 (40 stations + 40 elevations)
- Lines required: 80 ÷ 10 = 8 lines

## Count Interpretation

### Keyword Patterns

Different keywords have different count interpretations:

| Keyword | Count Meaning | Total Values | Example |
|---------|---------------|--------------|---------|
| `#Sta/Elev=` | Number of PAIRS | count × 2 | 40 → 80 values |
| `#Mann=` | Number of VALUES | count | 3 → 3 values |
| `XS GIS Cut Line=` | Number of PAIRS | count × 2 | 5 → 10 values |
| `Pier Skew=` | Number of VALUES | count | 2 → 2 values |

### Algorithm: interpret_count()

```python
def interpret_count(keyword, count_value):
    """
    Interpret count value based on keyword.

    Pair keywords (return count × 2):
    - #Sta/Elev=
    - XS GIS Cut Line=
    - Skew Angle=

    Value keywords (return count):
    - #Mann=
    - Pier Skew=
    - Gate Opening=
    """
    pair_keywords = [
        "#Sta/Elev=",
        "XS GIS Cut Line=",
        "Skew Angle="
    ]

    if any(kw in keyword for kw in pair_keywords):
        return count_value * 2  # Pairs
    else:
        return count_value  # Single values
```

## Section Boundary Identification

### Section Terminators

HEC-RAS uses specific keywords to mark section boundaries:

**Cross Section Terminator**:
```
Type RM Length L Ch R = 1 ,1000   ,100    ,0.06   ,0.06
#Sta/Elev= 40
    0.00   100.0    50.0    95.0   ...
Node Last Edited Time=...
```

**Storage Area Terminator**:
```
Storage Area Elev=   123.45
#SA Elev=Area=Volume= 10
  100.0  1000.0  5000.0   101.0  1050.0  5500.0   ...
Storage Area= NewArea
```

### Algorithm: identify_section()

```python
def identify_section(lines, keyword, start_index=0):
    """
    Find section boundaries for a keyword.

    Returns:
        (start_line, end_line) tuple

    Termination conditions:
    1. Next occurrence of same keyword
    2. End of file
    3. Section-specific terminator keyword
    """
    terminators = {
        "Type RM Length L Ch R": ["Node Last Edited"],
        "#SA Elev=Area=Volume": ["Storage Area="],
        "Lat Struct": ["Lateral Weir="],
        "Inline Weir": ["Inline Structure="]
    }

    start_line = None
    for i in range(start_index, len(lines)):
        if keyword in lines[i]:
            start_line = i
            break

    if start_line is None:
        raise ValueError(f"Keyword '{keyword}' not found")

    # Find end line
    end_line = len(lines)  # Default: end of file
    terminator_keywords = terminators.get(keyword, [keyword])

    for i in range(start_line + 1, len(lines)):
        # Check for terminator
        if any(term in lines[i] for term in terminator_keywords):
            end_line = i
            break

    return (start_line, end_line)
```

## Keyword Extraction

### Fixed-Width Keywords

Extract numeric value following a keyword:

```
#Sta/Elev= 40
#Mann= 3 ,0.035  ,0.025  ,0.035
Bank Sta=   50.00  ,  250.00
```

**Algorithm**:
```python
def extract_keyword_value(line, keyword):
    """
    Extract numeric value following keyword.

    Handles:
    - Fixed-width: "Bank Sta=   50.00  ,  250.00"
    - Space-separated: "#Sta/Elev= 40"
    """
    if keyword not in line:
        raise ValueError(f"Keyword '{keyword}' not found in line")

    # Get text after keyword
    after_keyword = line.split(keyword)[1]

    # Extract first numeric value
    parts = after_keyword.split()
    for part in parts:
        # Remove commas
        part = part.replace(',', '').strip()
        try:
            return float(part)
        except ValueError:
            continue

    raise ValueError(f"No numeric value after '{keyword}'")
```

### Comma-Separated Keywords

Extract comma-separated list after keyword:

```
#Mann= 3 ,0.035  ,0.025  ,0.035
```

**Algorithm**:
```python
def extract_comma_list(line, keyword):
    """
    Extract comma-separated values after keyword.

    Example:
        "#Mann= 3 ,0.035  ,0.025  ,0.035"
        Returns: [3.0, 0.035, 0.025, 0.035]
    """
    if keyword not in line:
        raise ValueError(f"Keyword '{keyword}' not found")

    # Get text after keyword
    after_keyword = line.split(keyword)[1]

    # Split by comma
    parts = after_keyword.split(',')

    # Parse numeric values
    values = []
    for part in parts:
        part = part.strip()
        try:
            values.append(float(part))
        except ValueError:
            pass  # Skip non-numeric parts

    return values
```

## Writing Fixed-Width Data

### Formatting Algorithm

```python
def format_fixed_width(values, column_width=8, values_per_line=10, precision=2):
    """
    Format numeric values as fixed-width strings.

    Parameters:
        values: List of numeric values
        column_width: Width of each column (default: 8)
        values_per_line: Values per line (default: 10)
        precision: Decimal places (default: 2)

    Returns:
        List of formatted lines
    """
    lines = []
    for i in range(0, len(values), values_per_line):
        chunk = values[i:i+values_per_line]
        line_parts = []

        for value in chunk:
            # Format with precision
            formatted = f"{value:.{precision}f}"

            # Pad to column width
            if len(formatted) > column_width:
                # Use scientific notation if too long
                formatted = f"{value:.{precision}e}"

            # Right-align in column
            formatted = formatted.rjust(column_width)
            line_parts.append(formatted)

        lines.append(''.join(line_parts))

    return lines
```

**Example**:
```python
values = [0.0, 100.0, 50.0, 95.0, 100.0, 92.0, 150.0, 90.0, 200.0, 92.0, 250.0, 95.0]
lines = format_fixed_width(values, column_width=8, values_per_line=10, precision=1)

# Output:
# ['     0.0   100.0    50.0    95.0   100.0    92.0   150.0    90.0   200.0    92.0',
#  '   250.0    95.0']
```

## Validation Patterns

### Line Length Validation

```python
def validate_line_length(line):
    """Validate fixed-width line length."""
    if len(line) > 80:
        raise ValueError(f"Line exceeds 80 characters: {len(line)}")
    return True
```

### Value Count Validation

```python
def validate_value_count(values, expected_count):
    """Validate number of parsed values matches expected count."""
    if len(values) != expected_count:
        raise ValueError(
            f"Expected {expected_count} values, got {len(values)}"
        )
    return True
```

### Numeric Range Validation

```python
def validate_numeric_range(value, min_val, max_val, name):
    """Validate value is within acceptable range."""
    if not (min_val <= value <= max_val):
        raise ValueError(
            f"{name} value {value} outside range [{min_val}, {max_val}]"
        )
    return True
```

## Edge Cases

### Handling Empty Lines

```python
def skip_empty_lines(lines, start_index):
    """Skip empty or whitespace-only lines."""
    for i in range(start_index, len(lines)):
        if lines[i].strip():
            return i
    return len(lines)  # All remaining lines are empty
```

### Handling Comment Lines

HEC-RAS geometry files don't use traditional comment syntax, but some lines are metadata:

```python
def is_metadata_line(line):
    """Check if line is metadata (skip during parsing)."""
    metadata_keywords = [
        "Node Last Edited",
        "XS GIS",
        "BEGIN DESCRIPTION",
        "END DESCRIPTION"
    ]
    return any(kw in line for kw in metadata_keywords)
```

### Handling Precision Loss

```python
def handle_precision_loss(value, precision=2):
    """
    Handle precision loss during round-trip parsing.

    Original:  123.456
    Formatted: 123.46 (precision=2)
    Parsed:    123.46 (lost 0.004)
    """
    # Option 1: Warn user
    formatted = round(value, precision)
    if abs(value - formatted) > 0.01:
        print(f"Warning: Precision loss {value} → {formatted}")

    # Option 2: Use higher precision
    return round(value, precision + 1)
```

## Performance Considerations

### Batch Processing

Process multiple lines in single pass:
```python
def parse_multiple_lines(lines, start_index, num_values):
    """Parse multiple fixed-width lines efficiently."""
    values = []
    line_index = start_index

    while len(values) < num_values and line_index < len(lines):
        line_values = parse_fixed_width(lines[line_index])
        values.extend(line_values)
        line_index += 1

    return values[:num_values], line_index
```

### Memory Efficiency

Use generators for large files:
```python
def parse_cross_sections_generator(geom_file):
    """Generate cross sections without loading entire file."""
    with open(geom_file, 'r') as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        if "Type RM Length L Ch R" in lines[i]:
            # Parse this cross section
            xs_data = parse_single_xs(lines, i)
            yield xs_data

            # Skip to next section
            i = find_next_xs(lines, i + 1)
        else:
            i += 1
```

## See Also

- [Modification Patterns](modification.md) - Safe geometry modification workflows
- `ras_commander/geom/GeomParser.py` - Reference implementation
- SKILL.md - Main skill documentation
