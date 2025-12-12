# Parsing Algorithms - Fixed-Width Format

Technical details of HEC-RAS geometry file parsing using FORTRAN-era fixed-width format.

## Table of Contents

1. [Fixed-Width Column Format](#fixed-width-column-format)
2. [Count Interpretation](#count-interpretation)
3. [Section Terminators](#section-terminators)
4. [Keyword Extraction](#keyword-extraction)
5. [Common Parsing Patterns](#common-parsing-patterns)

---

## Fixed-Width Column Format

HEC-RAS geometry files use 1970s-era FORTRAN formatting conventions.

### Column Specification

**Standard Format**:
- **Column Width**: 8 characters per value
- **Values Per Line**: 10 values (80 characters total)
- **Alignment**: Right-aligned with leading spaces
- **Precision**: Typically 2 decimal places

### Example Data

```
#Sta/Elev= 40
    0.00   100.00    10.00    99.50    20.00    99.00    30.00    98.50    40.00    98.00
   50.00    97.50    60.00    97.00    70.00    96.50    80.00    96.00    90.00    95.50
  100.00    95.00   110.00    95.50   120.00    96.00   130.00    96.50   140.00    97.00
```

**Breakdown**:
```
    0.00   100.00    10.00    99.50    20.00    99.00    30.00    98.50    40.00    98.00
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Col 1-8  9-16    17-24   25-32   33-40   41-48   49-56   57-64   65-72   73-80
```

### Parsing Algorithm

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

**Key Features**:
- Split line into chunks of `column_width` characters
- Strip whitespace from each chunk
- Convert to float (skip non-numeric)
- Return list of numeric values

### Formatting Algorithm

```python
def format_fixed_width(values, column_width=8, values_per_line=10, precision=2):
    """Format numeric values as fixed-width strings."""
    lines = []
    for i in range(0, len(values), values_per_line):
        chunk = values[i:i+values_per_line]
        line_parts = []
        for val in chunk:
            # Right-align within column width
            formatted = f"{val:>{column_width}.{precision}f}"
            line_parts.append(formatted)
        lines.append("".join(line_parts))
    return lines
```

**Key Features**:
- Format each value with specified precision
- Right-align within column width
- Group values into lines (10 per line)
- Join formatted values without separators

---

## Count Interpretation

HEC-RAS uses count declarations to specify data quantity. Critical: some counts refer to PAIRS, others to individual VALUES.

### Pair-Based Counts

**Pattern**: `#Sta/Elev= N`

- Declares N **PAIRS** of values
- Total values = N × 2
- Used for: station-elevation data, weir profiles, elevation-volume curves

**Example**:
```
#Sta/Elev= 40
```
- 40 PAIRS declared
- 40 stations + 40 elevations = 80 values
- 80 values ÷ 10 per line = 8 lines of data

**Algorithm**:
```python
def interpret_count(keyword, count_value):
    """Interpret count based on keyword type."""
    pair_keywords = ["#Sta/Elev", "#Elev/Volume", "Sta/Elev"]

    if any(kw in keyword for kw in pair_keywords):
        # Pair-based count
        return count_value * 2
    else:
        # Value-based count
        return count_value
```

### Common Count Keywords

| Keyword | Type | Interpretation |
|---------|------|----------------|
| `#Sta/Elev=` | Pair | Count × 2 values |
| `#Elev/Volume=` | Pair | Count × 2 values |
| `Sta/Elev=` | Pair | Count × 2 values (bridge deck) |
| `#Mann=` | Value | Count values |
| `#Pier=` | Value | Count values |

### Calculation Examples

**Cross Section (40 points)**:
```
#Sta/Elev= 40
40 pairs × 2 = 80 values
80 values ÷ 10 per line = 8 lines
```

**Storage Area (25 points)**:
```
#Elev/Volume= 25
25 pairs × 2 = 50 values
50 values ÷ 10 per line = 5 lines
```

**Manning's n (3 values)**:
```
#Mann= 3
3 values (not pairs)
3 values ÷ 10 per line = 1 line
```

---

## Section Terminators

Sections in geometry files are delimited by blank lines or specific keywords.

### Termination Patterns

**1. Blank Line Terminator**:
```
Type RM Length L Ch R = 1 ,1000    ,500   ,100   ,300
#Sta/Elev= 40
    0.00   100.00    10.00    99.50    20.00    99.00
   ...

Type RM Length L Ch R = 1 ,2000    ,500   ,100   ,300
```

**2. Keyword Terminator**:
```
River Reach=Ohio River,Reach 1
Rch Text=
Type RM Length L Ch R = 1 ,1000    ,500   ,100   ,300
#Sta/Elev= 40
    0.00   100.00    10.00    99.50
   ...
Bank Sta=      50.00,     250.00
#Mann= 3
    0.04    0.03    0.04
Type RM Length L Ch R = 1 ,2000    ,500   ,100   ,300   <- NEW SECTION
```

### Section Identification Algorithm

```python
def identify_section(lines, keyword, start_index=0):
    """Find section boundaries using keyword markers."""
    start_line = None
    end_line = None

    # Find start
    for i in range(start_index, len(lines)):
        if keyword in lines[i]:
            start_line = i
            break

    if start_line is None:
        return None, None

    # Find end (next occurrence or blank line)
    for i in range(start_line + 1, len(lines)):
        if lines[i].strip() == "":
            end_line = i
            break
        if keyword in lines[i]:
            end_line = i
            break

    if end_line is None:
        end_line = len(lines)

    return start_line, end_line
```

### Nested Sections

Some sections contain subsections:

```
Type RM Length L Ch R = 1 ,1000    ,500   ,100   ,300
#Sta/Elev= 40
    0.00   100.00    10.00    99.50
   ...
Bank Sta=      50.00,     250.00      <- SUBSECTION
#Mann= 3                               <- SUBSECTION
    0.04    0.03    0.04
Exp/Cntr=0.3  ,0.1                    <- SUBSECTION
```

**Parsing Strategy**:
1. Identify main section (Type RM Length...)
2. Extract subsections by keyword within bounds
3. Use count declarations to determine data extent

---

## Keyword Extraction

Two formats: fixed-width and comma-separated.

### Fixed-Width Keywords

**Pattern**: `Keyword=` followed by fixed-width value

**Example**:
```
River Reach=Ohio River       ,Reach 1
```

**Algorithm**:
```python
def extract_keyword_value(line, keyword):
    """Extract value following a keyword."""
    if keyword not in line:
        return None

    idx = line.index(keyword) + len(keyword)
    value = line[idx:].strip()
    return value
```

### Comma-Separated Lists

**Pattern**: `Keyword=` followed by comma-separated values

**Example**:
```
Type RM Length L Ch R = 1 ,1000    ,500   ,100   ,300
Bank Sta=      50.00,     250.00
```

**Algorithm**:
```python
def extract_comma_list(line, keyword):
    """Extract comma-separated list after keyword."""
    if "=" not in line:
        return []

    # Get everything after '='
    value_part = line.split("=", 1)[1]

    # Split by comma and clean
    values = [v.strip() for v in value_part.split(",")]
    values = [v for v in values if v]  # Remove empty

    return values
```

**Example**:
```python
line = "Type RM Length L Ch R = 1 ,1000    ,500   ,100   ,300"
values = extract_comma_list(line, "Type RM Length")
# ['1', '1000', '500', '100', '300']
```

---

## Common Parsing Patterns

### Pattern 1: Cross Section Geometry

```
Type RM Length L Ch R = 1 ,1000    ,500   ,100   ,300
#Sta/Elev= 40
    0.00   100.00    10.00    99.50    20.00    99.00
   ...
Bank Sta=      50.00,     250.00
#Mann= 3
    0.04    0.03    0.04
```

**Steps**:
1. Find "Type RM Length" line
2. Extract river station from comma list
3. Find "#Sta/Elev=" line
4. Extract count (40 pairs = 80 values)
5. Read next 8 lines (80 ÷ 10 = 8)
6. Parse fixed-width values
7. Separate into stations and elevations

**Code**:
```python
# Find XS declaration
type_line = find_line_with("Type RM Length")
values = extract_comma_list(type_line, "Type RM Length")
rs = values[1]  # River station

# Get count
count_line = find_line_with("#Sta/Elev=")
count = int(extract_keyword_value(count_line, "#Sta/Elev="))
total_values = count * 2  # PAIRS

# Calculate lines needed
lines_needed = (total_values + 9) // 10  # Round up

# Parse data
data_values = []
for i in range(lines_needed):
    line = lines[count_line_index + 1 + i]
    data_values.extend(parse_fixed_width(line))

# Separate stations and elevations
stations = data_values[0::2]  # Even indices
elevations = data_values[1::2]  # Odd indices
```

### Pattern 2: Storage Area Elevation-Volume

```
Storage Area= Detention Basin 1
#Elev/Volume= 25
  100.00   0.00  101.00   5.50  102.00   12.00
   ...
```

**Steps**:
1. Find "Storage Area=" line
2. Extract area name
3. Find "#Elev/Volume=" line
4. Extract count (25 pairs = 50 values)
5. Read next 5 lines (50 ÷ 10 = 5)
6. Parse fixed-width values
7. Separate into elevations and volumes

### Pattern 3: Bridge Deck

```
Type RM Length L Ch R = 3 ,1000    ,500   ,100   ,300
US/DS=U
Deck/Roadway
Sta/Elev= 30
    0.00   105.00    20.00   105.00    40.00   105.00
   ...
Dist Deck=    0.00
Width Deck=    50.00
```

**Steps**:
1. Find "Type RM Length" line with type=3 (bridge)
2. Find "Sta/Elev=" line (no # prefix for bridges)
3. Extract count (30 pairs = 60 values)
4. Read deck profile data
5. Extract "Dist Deck" and "Width Deck" values

### Pattern 4: Inline Weir

```
Type RM Length L Ch R = 5 ,1000    ,500   ,100   ,300
Inline Weir
#Sta/Elev= 20
    0.00   103.00    10.00   103.00    20.00   103.00
   ...
Weir Coef=  2.6
```

**Steps**:
1. Find "Type RM Length" line with type=5 (inline weir)
2. Confirm "Inline Weir" keyword
3. Parse weir profile (similar to XS)
4. Extract weir coefficient

---

## Performance Considerations

### Large Files

Geometry files can be 50+ MB with thousands of cross sections.

**Optimization Strategies**:

1. **Line-by-Line Processing**: Don't load entire file into memory
   ```python
   with open(geom_file, 'r') as f:
       for line in f:
           if "Type RM Length" in line:
               process_section(f, line)
   ```

2. **Targeted Search**: Jump to specific sections
   ```python
   # Build index of section start lines
   section_index = {}
   with open(geom_file, 'r') as f:
       for i, line in enumerate(f):
           if "Type RM Length" in line:
               section_index[extract_rs(line)] = i
   ```

3. **Caching**: Store parsed results for repeated access
   ```python
   @lru_cache(maxsize=128)
   def get_cross_section(geom_file, river, reach, rs):
       ...
   ```

### Error Recovery

Geometry files may have malformed data.

**Robust Parsing**:
```python
def safe_parse_fixed_width(line, column_width=8, allow_partial=True):
    """Parse with error tolerance."""
    values = []
    for i in range(0, len(line), column_width):
        chunk = line[i:i+column_width].strip()
        if chunk:
            try:
                values.append(float(chunk))
            except ValueError:
                if not allow_partial:
                    raise
                # Log warning and continue
                logger.warning(f"Non-numeric value: {chunk}")
    return values
```

---

## Edge Cases

### Blank Lines in Data

Some files have blank lines within data sections:

```
#Sta/Elev= 40
    0.00   100.00    10.00    99.50

    20.00    99.00    30.00    98.50
```

**Solution**: Skip blank lines when accumulating values.

### Missing Count Declarations

Older files may omit count:

```
Type RM Length L Ch R = 1 ,1000    ,500   ,100   ,300
    0.00   100.00    10.00    99.50
   ...
Bank Sta=      50.00,     250.00
```

**Solution**: Read until next keyword or blank line.

### Non-Standard Precision

Some values use more decimal places:

```
    0.000000   100.123456    10.000000    99.876543
```

**Solution**: Allow variable column width or trim to expected precision.
