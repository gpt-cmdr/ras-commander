# Reading DSS Boundary Data Skill

Expert guidance for extracting boundary condition data from HEC-DSS files using ras-commander's RasDss class.

## Overview

This skill provides comprehensive guidance for working with HEC-DSS files (V6 and V7) in ras-commander. It covers JVM configuration, HEC Monolith auto-download, catalog reading, time series extraction, and boundary condition mapping.

## Contents

### SKILL.md (~440 lines)

Main skill documentation with:
- Quick start examples
- When to use this skill
- Technology overview (DSS format, pathname structure)
- Lazy loading architecture
- Core workflows (5 patterns)
- Common patterns
- Error handling
- Integration with HEC-RAS
- Cross-references

**Trigger Keywords**: DSS, HEC-DSS, boundary condition, time series, JVM, Java, catalog, pathname, HEC-HMS, Monolith, pyjnius

### reference/dss-api.md (~400 lines)

Complete API reference with:
- Class overview
- All methods with parameters, returns, examples
- DSS pathname format (7-part structure)
- DataFrame structure and metadata
- JVM configuration details
- Testing instructions

**Methods Documented**:
- `get_catalog()` - List all pathnames
- `read_timeseries()` - Read single time series
- `read_multiple_timeseries()` - Batch read
- `get_info()` - File summary
- `extract_boundary_timeseries()` - Auto-extract all BC data
- `shutdown_jvm()` - Placeholder

### reference/troubleshooting.md (~600 lines)

Comprehensive troubleshooting guide:

**Java/JVM Issues**:
- pyjnius not installed
- JAVA_HOME not set
- JVM already started
- Java class not found
- Native library not found
- OutOfMemoryError

**DSS File Issues**:
- DSS file not found
- Invalid pathname
- Empty time series
- Corrupted DSS file

**Performance Issues**:
- Slow catalog reading
- Slow time series extraction

**Integration Issues**:
- Boundaries not extracted
- Wrong project directory

**Debugging**:
- Enable debug logging
- Check versions
- Minimal test case
- Report issues

### examples/read-catalog.py

Complete working example for catalog exploration:
- Extract example project
- Get file info
- Read full catalog
- Analyze catalog contents (parameters, intervals)
- Find flow time series
- Find specific scenarios
- Export catalog to text and CSV

### examples/extract-boundaries.py

Complete working example for boundary extraction:
- Extract example project
- Initialize HEC-RAS project
- Extract all DSS boundary data
- Summary statistics (manual vs DSS)
- Export to CSV with metadata
- Export individual time series
- Create multi-panel plots
- Save visualizations

## Quick Start

```python
from ras_commander import init_ras_project, RasDss

# Initialize project
ras = init_ras_project("path/to/project", "6.6")

# Extract ALL boundary DSS data (one-call solution)
enhanced = RasDss.extract_boundary_timeseries(
    ras.boundaries_df,
    ras_object=ras
)

# Access extracted data
for idx, row in enhanced.iterrows():
    if row['Use DSS'] and row['dss_timeseries'] is not None:
        df = row['dss_timeseries']
        print(f"{row['bc_type']}: {len(df)} points")
```

## Technology Stack

- **HEC Monolith**: Java libraries (~20 MB, auto-downloaded)
- **pyjnius**: Python-Java bridge (must install: `pip install pyjnius`)
- **Java**: JRE/JDK 8+ required (set JAVA_HOME)

## Lazy Loading

Three-level lazy loading ensures zero overhead until first use:

1. **Import**: Lightweight, no Java
2. **First call**: Configures JVM, downloads Monolith
3. **Subsequent**: Uses cached JVM and libraries

## Cross-References

- **Developer Docs**: `ras_commander/dss/AGENTS.md`
- **Example Notebook**: `examples/22_dss_boundary_extraction.ipynb`
- **Source Code**: `ras_commander/dss/RasDss.py`

## Testing

Run example scripts:
```bash
# Test catalog reading
python .claude/skills/reading-dss-boundary-data/examples/read-catalog.py

# Test boundary extraction
python .claude/skills/reading-dss-boundary-data/examples/extract-boundaries.py
```

## Size Metrics

- **SKILL.md**: 438 lines (target: ~200, actual: 219% of target)
- **dss-api.md**: 397 lines (target: ~150, actual: 265% of target)
- **troubleshooting.md**: 596 lines (target: ~150, actual: 397% of target)
- **Total**: 1,431 lines

*Note: Files are larger than target to provide comprehensive coverage of complex DSS/Java integration.*

## Example Project

BaldEagleCrkMulti2D example contains DSS boundary conditions:
```python
from ras_commander import RasExamples
project_path = RasExamples.extract_project("BaldEagleCrkMulti2D")
```

## Key Features

1. **Unified API**: DSS and manual boundaries in same DataFrame
2. **One-Call Extraction**: `extract_boundary_timeseries()` handles all DSS data
3. **Metadata Preserved**: Units, pathname, interval in df.attrs
4. **V6 and V7 Support**: Both DSS versions supported
5. **Auto-Download**: HEC Monolith installed automatically
6. **Lazy Loading**: No overhead until first use
7. **Comprehensive Error Handling**: Graceful failures with detailed logging
