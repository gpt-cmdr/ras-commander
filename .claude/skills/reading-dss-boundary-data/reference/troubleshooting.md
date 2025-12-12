# DSS Troubleshooting Guide

Solutions for common Java/JVM and DSS file issues.

## Java and JVM Issues

### Error: pyjnius Not Installed

**Symptom**:
```
ImportError: pyjnius is required for DSS file operations.
Install with: pip install pyjnius
```

**Cause**: pyjnius package not installed

**Solution**:
```bash
pip install pyjnius
```

**Verification**:
```python
import jnius
print("pyjnius installed successfully")
```

---

### Error: JAVA_HOME Not Set

**Symptom**:
```
RuntimeError: JAVA_HOME not set and Java not found automatically.
Please install Java JRE/JDK 8+ and set JAVA_HOME.
```

**Cause**: Java not installed or JAVA_HOME not set

**Solutions**:

**Windows**:
1. **Install Java** (if not installed):
   - Download from: https://adoptium.net/
   - Install JRE or JDK 8+

2. **Set JAVA_HOME**:
   ```batch
   # Temporary (current session)
   set JAVA_HOME=C:\Program Files\Java\jdk-11

   # Permanent (system-wide)
   # System Properties > Environment Variables > New
   # Variable: JAVA_HOME
   # Value: C:\Program Files\Java\jdk-11
   ```

**Linux/Mac**:
```bash
# Install Java (Ubuntu/Debian)
sudo apt-get install default-jdk

# Install Java (Mac)
brew install openjdk@11

# Set JAVA_HOME (add to ~/.bashrc or ~/.zshrc)
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64  # Linux
export JAVA_HOME=/opt/homebrew/opt/openjdk@11         # Mac

# Apply changes
source ~/.bashrc  # or source ~/.zshrc
```

**Verification**:
```bash
# Check JAVA_HOME
echo $JAVA_HOME          # Linux/Mac
echo %JAVA_HOME%         # Windows

# Check Java version
java -version
```

---

### Error: JVM Already Started

**Symptom**:
```
RuntimeError: JVM configuration already done. Cannot reconfigure.
```

**Cause**: JVM can only be configured once per Python process

**Solutions**:

**Jupyter Notebook**:
```python
# Restart kernel
# Kernel > Restart
```

**Python Script**:
```bash
# Exit and restart Python
exit()
python script.py
```

**Long-Running Process**:
- Design code to configure JVM once at startup
- Avoid reconfiguration in loops or multiple modules

**Workaround** (if absolutely needed):
```python
# Check if already configured
from ras_commander.dss.RasDss import RasDss
if not RasDss._jvm_configured:
    # Safe to call DSS methods
    catalog = RasDss.get_catalog("file.dss")
```

---

### Error: Java Class Not Found

**Symptom**:
```
jnius.JavaException: Class not found: hec.heclib.dss.HecDss
```

**Cause**: HEC Monolith not installed or classpath incorrect

**Solutions**:

1. **Check Monolith Installation**:
   ```python
   from ras_commander.dss._hec_monolith import HecMonolithDownloader

   downloader = HecMonolithDownloader()
   if not downloader.is_installed():
       print("Installing HEC Monolith...")
       downloader.install()
   ```

2. **Manual Reinstall**:
   ```python
   downloader = HecMonolithDownloader()
   downloader.install(force=True)  # Re-download and install
   ```

3. **Check Install Directory**:
   - Windows: `C:\Users\<user>\.ras-commander\dss\`
   - Linux/Mac: `~/.ras-commander/dss/`
   - Should contain: lib/ folder with 7 JARs

---

### Error: Native Library Not Found

**Symptom**:
```
java.lang.UnsatisfiedLinkError: no javaHeclib in java.library.path
```

**Cause**: Platform-specific native library missing or wrong platform

**Solutions**:

1. **Check Platform**:
   ```python
   import platform
   print(platform.system())  # Should be Windows, Linux, or Darwin
   ```

2. **Reinstall Monolith**:
   ```python
   from ras_commander.dss._hec_monolith import HecMonolithDownloader

   downloader = HecMonolithDownloader()
   downloader.install(force=True)
   ```

3. **Manual Check**:
   - Windows: `.ras-commander\dss\lib\` should have `javaHeclib.dll`
   - Linux: `.ras-commander/dss/lib/` should have `libjavaHeclib.so`
   - Mac: `.ras-commander/dss/lib/` should have `libjavaHeclib.dylib`

---

### Error: OutOfMemoryError

**Symptom**:
```
java.lang.OutOfMemoryError: Java heap space
```

**Cause**: JVM heap size too small for large DSS files

**Solution**:

Increase JVM heap before first DSS operation:

```python
# MUST be done before any jnius imports
import jnius_config

# Set heap size (before JVM starts)
jnius_config.add_options('-Xmx2g')  # 2 GB heap

# Now safe to use RasDss
from ras_commander import RasDss
```

**Notes**:
- Must be done BEFORE first RasDss call
- Cannot change after JVM started
- Common values: 1g, 2g, 4g

---

## DSS File Issues

### Error: DSS File Not Found

**Symptom**:
```
FileNotFoundError: DSS file not found: file.dss
```

**Cause**: File doesn't exist or path incorrect

**Solutions**:

1. **Use Absolute Paths**:
   ```python
   from pathlib import Path

   dss_file = Path("path/to/file.dss").resolve()
   if not dss_file.exists():
       raise FileNotFoundError(f"Not found: {dss_file}")

   catalog = RasDss.get_catalog(dss_file)
   ```

2. **Resolve Relative to Project**:
   ```python
   from ras_commander import init_ras_project

   ras = init_ras_project("project_path", "6.6")
   dss_file = ras.project_dir / "Boundary_Data.dss"

   if dss_file.exists():
       catalog = RasDss.get_catalog(dss_file)
   ```

3. **Check Boundaries DataFrame**:
   ```python
   # DSS files listed in boundaries_df
   dss_files = boundaries_df['DSS File'].dropna().unique()
   for dss in dss_files:
       full_path = ras.project_dir / dss
       print(f"{dss}: {'EXISTS' if full_path.exists() else 'MISSING'}")
   ```

---

### Error: Invalid Pathname

**Symptom**:
```
ValueError: Pathname not found in DSS file
```

**Cause**: Pathname doesn't exist in file or formatting incorrect

**Solutions**:

1. **List Available Paths**:
   ```python
   catalog = RasDss.get_catalog("file.dss")
   print(f"Total paths: {len(catalog)}")

   # Search for specific parameter
   flow_paths = [p for p in catalog if '/FLOW/' in p]
   print(f"Flow paths: {len(flow_paths)}")
   for path in flow_paths[:10]:
       print(f"  {path}")
   ```

2. **Check Pathname Format**:
   ```python
   # Correct format (7 parts, leading/trailing slashes)
   pathname = "//LOCATION/FLOW/01JAN2000/15MIN/RUN:SCENARIO/"

   # Common errors:
   # - Missing leading slash: /LOCATION/FLOW/...
   # - Missing trailing slash: //LOCATION/FLOW/.../RUN
   # - Wrong date format: 2000-01-01 instead of 01JAN2000
   ```

3. **Case Sensitivity**:
   ```python
   # DSS pathnames are case-insensitive, but must match exactly
   # Check actual casing in catalog
   catalog = RasDss.get_catalog("file.dss")
   actual_path = [p for p in catalog if 'LOCATION' in p.upper()][0]
   print(f"Actual pathname: {actual_path}")
   ```

---

### Error: Empty Time Series

**Symptom**:
```python
df = RasDss.read_timeseries("file.dss", pathname)
print(len(df))  # 0
```

**Cause**: Pathname exists but contains no data

**Solutions**:

1. **Check Data Type**:
   ```python
   # Some paths are paired data, not time series
   # Look for empty D/E parts: //NAME/ELEVATION-STORAGE///TABLE/
   ```

2. **Verify in HEC-DSSVue**:
   - Open file in HEC-DSSVue
   - Navigate to pathname
   - Check if data exists and format

3. **Check File Info**:
   ```python
   info = RasDss.get_info("file.dss")
   print(f"Total paths: {info['total_paths']}")

   # If 0, file may be corrupted
   ```

---

### Error: Corrupted DSS File

**Symptom**:
- Random Java exceptions
- Incomplete catalog
- Garbled data

**Solutions**:

1. **Compact/Squeeze in HEC-DSSVue**:
   - Open file in HEC-DSSVue
   - Tools > Squeeze
   - This removes fragmentation

2. **Repair with HEC-DSSVue**:
   - Tools > Catalog
   - Check for errors
   - Repair if prompted

3. **Extract Known-Good Data**:
   ```python
   # Read catalog first
   catalog = RasDss.get_catalog("file.dss")

   # Try each path individually
   for pathname in catalog:
       try:
           df = RasDss.read_timeseries("file.dss", pathname)
           print(f"OK: {pathname}")
       except Exception as e:
           print(f"FAIL: {pathname} - {e}")
   ```

---

## Performance Issues

### Slow Catalog Reading

**Symptom**: `get_catalog()` takes minutes for large files

**Solutions**:

1. **Use get_info() Instead**:
   ```python
   # Faster - reads only first 50 paths
   info = RasDss.get_info("large_file.dss")
   print(f"Total: {info['total_paths']}")
   print(f"Sample: {info['sample_paths'][:10]}")
   ```

2. **Cache Catalog**:
   ```python
   # Save catalog for reuse
   catalog = RasDss.get_catalog("large_file.dss")

   import json
   with open("catalog.json", 'w') as f:
       json.dump(catalog, f)

   # Load from cache
   with open("catalog.json") as f:
       catalog = json.load(f)
   ```

3. **Filter During Read**:
   ```python
   # Read catalog once
   catalog = RasDss.get_catalog("file.dss")

   # Filter in Python (fast)
   flow_paths = [p for p in catalog if '/FLOW/' in p]
   stage_paths = [p for p in catalog if '/STAGE/' in p]
   ```

---

### Slow Time Series Extraction

**Symptom**: `read_timeseries()` slow for many paths

**Solutions**:

1. **Use Batch Extraction**:
   ```python
   # Slow - opens file multiple times
   for pathname in pathnames:
       df = RasDss.read_timeseries("file.dss", pathname)

   # Fast - opens file once
   results = RasDss.read_multiple_timeseries("file.dss", pathnames)
   ```

2. **Use extract_boundary_timeseries()**:
   ```python
   # Optimized for boundary conditions
   enhanced = RasDss.extract_boundary_timeseries(
       boundaries_df,
       ras_object=ras
   )
   ```

---

## Integration Issues

### Boundaries Not Extracted

**Symptom**: `extract_boundary_timeseries()` returns 0 DSS boundaries

**Solutions**:

1. **Check 'Use DSS' Column**:
   ```python
   dss_count = (boundaries_df['Use DSS'] == True).sum()
   print(f"DSS boundaries: {dss_count}")

   if dss_count == 0:
       print("No DSS-defined boundaries in this plan")
   ```

2. **Check DSS File Paths**:
   ```python
   # List DSS files referenced
   dss_files = boundaries_df['DSS File'].dropna().unique()
   for dss_file in dss_files:
       full_path = project_dir / dss_file
       print(f"{dss_file}: {full_path.exists()}")
   ```

3. **Check DSS Pathnames**:
   ```python
   dss_bc = boundaries_df[boundaries_df['Use DSS'] == True]
   for idx, row in dss_bc.iterrows():
       print(f"{row['bc_type']}")
       print(f"  File: {row['DSS File']}")
       print(f"  Path: {row['DSS Path']}")
   ```

---

### Wrong Project Directory

**Symptom**: DSS files not found even though they exist

**Solutions**:

1. **Pass ras_object**:
   ```python
   # Preferred - auto-detects project directory
   enhanced = RasDss.extract_boundary_timeseries(
       boundaries_df,
       ras_object=ras
   )
   ```

2. **Or Pass project_dir Explicitly**:
   ```python
   enhanced = RasDss.extract_boundary_timeseries(
       boundaries_df,
       project_dir=Path("path/to/project")
   )
   ```

3. **Verify Project Dir**:
   ```python
   print(f"Project dir: {ras.project_dir}")
   dss_file = ras.project_dir / "Boundary_Data.dss"
   print(f"DSS exists: {dss_file.exists()}")
   ```

---

## Getting Help

### Enable Debug Logging

```python
import logging

# Set to DEBUG for detailed logs
logging.basicConfig(level=logging.DEBUG)

# Or just for ras_commander
logging.getLogger('ras_commander').setLevel(logging.DEBUG)

# Now run DSS operations
catalog = RasDss.get_catalog("file.dss")
```

### Check Versions

```python
import ras_commander
print(f"ras-commander: {ras_commander.__version__}")

import jnius
print(f"pyjnius: {jnius.__version__}")

import sys
print(f"Python: {sys.version}")

import platform
print(f"Platform: {platform.system()} {platform.release()}")
```

### Minimal Test Case

```python
from pathlib import Path
from ras_commander import RasDss

# Test with known-good DSS file
test_dss = Path("test.dss")

if test_dss.exists():
    try:
        print("Testing get_info...")
        info = RasDss.get_info(test_dss)
        print(f"  Total paths: {info['total_paths']}")

        print("Testing get_catalog...")
        catalog = RasDss.get_catalog(test_dss)
        print(f"  Catalog length: {len(catalog)}")

        if len(catalog) > 0:
            print("Testing read_timeseries...")
            df = RasDss.read_timeseries(test_dss, catalog[0])
            print(f"  Points: {len(df)}")

        print("All tests passed!")

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
else:
    print(f"Test file not found: {test_dss}")
```

### Report Issues

When reporting DSS issues, include:
1. ras-commander version
2. Python version
3. Platform (Windows/Linux/Mac)
4. Java version (`java -version`)
5. pyjnius version
6. Full error traceback
7. Minimal reproducible example
8. DSS file info (size, version if known)
