# RasMapperLib.Utilities Namespace Documentation

## Overview

The `RasMapperLib.Utilities` namespace provides a comprehensive collection of helper classes for common operations in RASMapper. These utilities support type conversion, geometry operations, drawing/rendering, data handling, file I/O, XML processing, and more. All classes in this namespace use static methods and serve as pure utility functions.

**Key Purpose:** Centralized helper functions used throughout RASMapper for tasks like:
- Type conversion between different geometry/raster representations
- Drawing primitives (arrows, text, labels)
- DataGridView operations (copy/paste, validation)
- Mathematical operations (matrix solving, interpolation)
- XML serialization/deserialization
- File path manipulation
- DSS date/time conversion
- Hash computation for caching

---

## Class Hierarchy

All classes in this namespace are **abstract** with **static methods only** - they cannot be instantiated.

```
RasMapperLib.Utilities
├── Converter          # Type conversions between geometry systems
├── Drawing            # Rendering primitives and color operations
├── DSS                # DSS date/time utilities
├── Form               # WinForms/DataGridView helpers
├── General            # Miscellaneous utilities
├── Hash               # Hash computation for data integrity
├── KnownLinkIDs       # Constants for HEC web links
├── Math               # Mathematical operations and solvers
├── Network            # HTTP/web communication
├── Path               # File path manipulation
├── Stats              # Statistics (empty placeholder)
├── Vector             # Geometric vector operations
└── XML                # XML parsing and serialization
```

---

## 1. Converter Class

**Purpose:** Convert between different geometry/raster representation systems (RASMapper internal types vs. Geospatial library types).

### Key Methods

#### Raster Conversions
```csharp
public static RasterDefinition Convert(RasterM raster)
public static RasterM Convert(RasterDefinition raster)
```
Convert between `RasterM` (RASMapper) and `RasterDefinition` (Geospatial library).

#### Point Conversions
```csharp
public static Geospatial.Vectors.Point Convert(PointM pt)
public static PointM ConvertPtM(Geospatial.Vectors.Point pt)
public static Geospatial.Vectors.Point Convert(Point2Double pt)
public static List<Geospatial.Vectors.Point> Convert(IList<PointM> pts)
public static List<PointM> Convert(IList<Geospatial.Vectors.Point> pts)
```

#### Polygon/Polyline Conversions
```csharp
public static Polygon Convert(Geospatial.Vectors.Polygon poly)
public static Geospatial.Vectors.Polygon Convert(Polygon poly)
public static Polygon Convert(ComplexPolygon poly)
```
- Handles point list conversions
- **Important:** Adds/removes last point for ring closure

#### TIN Conversions
```csharp
public static Geospatial.Vectors.Tin Convert(Tin tin)
public static Tin Convert(Geospatial.Vectors.Tin tin)
```
Convert TIN (Triangulated Irregular Network) structures between systems.

#### Extent Conversions
```csharp
public static Geospatial.Vectors.Extent Convert(Extent ext)
public static Extent Convert(Geospatial.Vectors.Extent ext)
```

### Python Implementation Notes

Python equivalent using shapely/geopandas:
```python
from shapely.geometry import Point, Polygon, LineString
import numpy as np

def convert_pointm_to_shapely(pt_dict):
    """Convert PointM to shapely Point"""
    return Point(pt_dict['X'], pt_dict['Y'])

def convert_polygon_to_shapely(ras_polygon):
    """Convert RASMapper polygon to shapely"""
    coords = [(pt['X'], pt['Y']) for pt in ras_polygon['points']]
    # shapely polygons don't need explicit closure
    return Polygon(coords)
```

**Key Difference:** RASMapper polygons explicitly close (last point = first point), Shapely assumes closure.

---

## 2. Drawing Class

**Purpose:** Rendering utilities for drawing graphics, managing colors, and handling pens/brushes in RASMapper visualizations.

### Nested Types

#### NameColor Struct
```csharp
public struct NameColor {
    public string Name;
    public Color Color;
}
```

#### StringPosition Enum
```csharp
public enum StringPosition {
    AboveLeft, Above, AboveRight,
    Left, Centered, Right,
    BelowLeft, Below, BelowRight
}
```

### Color Management

#### Static Collections
```csharp
public static List<NameColor> NameColors
public static Dictionary<Color, SolidBrush> ColorToSolidBrush
```
Pre-populated color lookup tables for performance.

#### Color Operations
```csharp
public static Color ChangeAlpha(byte alpha, Color color)
public static string ColorToCommaSeperated(Color color)
public static Color ColorFromCommaSeperated(string rgba)
public static Color ColorDefaultByLayer(int index)
```

**Color Matching Methods:**
```csharp
public static int ClosestColorHue(List<Color> colors, Color target)
public static int ClosestColorRGBDistance(List<Color> colors, Color target)
public static int ClosestColorHueSaturationBrightness(List<Color> colors, Color target)
```

### Drawing Primitives

#### Arrows
```csharp
public static void DrawArrow(RasterM raster, IGraphics g, Pen pen,
    PointM tailPoint, PointM headPoint)
public static void DrawArrowHead(IGraphics g, Pen pen,
    int headX, int headY, int tailX, int tailY, int normalizeLengthToPx)
```

#### Text Rendering with Overlap Detection
```csharp
public static void DrawStringCheckOverlap(RasterM raster, byte[] mask,
    IGraphics g, Font font, Brush brush, StringPosition sa,
    int x, int y, string label)
```
- Uses a `byte[]` mask to track already-labeled pixels
- Prevents label overlap
- Supports multi-line label tables

### Pen/Brush Serialization

#### Save to XML
```csharp
public static XmlElement PenSaveXML(Pen pen, XmlDocument doc, string elementName = "Pen")
public static XmlElement BrushSaveXML(Brush brush, XmlDocument doc, string elementName = "Brush")
```

#### Load from XML
```csharp
public static Pen PenLoadXML(XmlNode parentNode, Pen defaultPen = null, string elementName = "Pen")
public static Brush BrushLoadXML(XmlNode parentNode, Brush defaultBrush = null, string elementName = "Brush")
```

### Python Implementation Notes

For matplotlib-based Python rendering:
```python
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

def draw_arrow(ax, tail_xy, head_xy, **kwargs):
    """Draw arrow on matplotlib axes"""
    dx = head_xy[0] - tail_xy[0]
    dy = head_xy[1] - tail_xy[1]
    arrow = mpatches.FancyArrowPatch(
        tail_xy, head_xy,
        arrowstyle='->', mutation_scale=20, **kwargs
    )
    ax.add_patch(arrow)

def label_with_overlap_check(ax, x, y, text, placed_labels):
    """Prevent label overlap"""
    bbox = ax.text(x, y, text, ha='center').get_window_extent()
    for existing_bbox in placed_labels:
        if bbox.overlaps(existing_bbox):
            return False  # Skip overlapping label
    placed_labels.append(bbox)
    return True
```

---

## 3. DSS Class

**Purpose:** Handle HEC-DSS date/time format conversions.

### Date/Time Conversion

```csharp
public static DateTime ConvertFromDSSDateTime(string dateTime)
public static string ConvertToDSSDateTime(DateTime dt)
```

**DSS Date Format:** `DDMMMYYYYHHmmss` (e.g., `"01JAN2020 14:30:00"`)

**Special Case:** Midnight is represented as `24:00:00` of the previous day.

### Month Conversion
```csharp
public static string DSSMonth(DateTime dt)
```
Returns 3-letter month abbreviation (JAN, FEB, MAR, etc.).

### Date Searching
```csharp
public static int NearestDSSDateIndex(string[] dssDates, string dssDate)
```
Binary search through sorted DSS date array.

### Python Implementation

```python
from datetime import datetime, timedelta

def dss_to_datetime(dss_str):
    """Convert DSS date string to datetime"""
    # Handle 24:00:00 special case
    if '24:00:00' in dss_str:
        dss_str = dss_str.replace('24:00:00', '00:00:00')
        dt = datetime.strptime(dss_str, '%d%b%Y %H:%M:%S')
        return dt + timedelta(days=1)
    return datetime.strptime(dss_str, '%d%b%Y %H:%M:%S')

def datetime_to_dss(dt):
    """Convert datetime to DSS format"""
    if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        # Midnight: use 24:00:00 of previous day
        prev_day = dt - timedelta(days=1)
        return prev_day.strftime('%d%b%Y') + ' 24:00:00'
    return dt.strftime('%d%b%Y %H:%M:%S')
```

---

## 4. Form Class

**Purpose:** Extensive WinForms utilities, especially for DataGridView operations (copy/paste, validation, cell editing).

### DataGridView Setup

```csharp
public static void DataGridViewSetup(DataGridView dgv, bool numberRows = false,
    bool includeKeyDownHandler = true, bool allowSorting = false,
    DGVKeydownRules dgvKeyDownRules = null, bool columnHeaderButton = false)

public static void DataGridViewSetupForEditing(DataGridView dgv, bool allowAddRow, ...)
```

### Copy/Paste Operations

```csharp
public static void dgv_KeyDown(object sender, KeyEventArgs e)
public static void dgv_KeyDown_CopyOnly(object sender, KeyEventArgs e)
```

**Supported Operations:**
- **Ctrl+C:** Copy selected cells/rows
- **Ctrl+V:** Paste tab-delimited data
- **Ctrl+X:** Cut (copy + delete)
- **Delete:** Clear cell contents or delete rows
- **Space:** Toggle boolean cells

### Cell Editing Utilities

```csharp
public static void DGVSetSelectedCellsPrompt(DataGridView dgv, CustomDataColumn dataColumn = null)
public static void DGVMultiplySelectedCellsPrompt(DataGridView dgv)
public static void DGVAddToSelectedCellsPrompt(DataGridView dgv)
public static void DGVRoundSelectedCellsPrompt(DataGridView dgv)
public static void DGVReplaceSelectedCellsPrompt(DataGridView dgv)
```

### Column Visibility

```csharp
public static void DGVSelectColumns(DataGridView dgv, FeatureLayer fLayer = null)
public static void TurnDGVColumnsOnOff(DataGridView dgv)
```

### Form Utilities

```csharp
public static void PositionDialog(Form parent, Form dialog)
public static void PositionForm(Form form, Point location, Size size)
public static void SuspendDrawing(Control parent)
public static void ResumeDrawing(Control parent)
```

### Data Conversion

```csharp
public static string ArrayToCSS<T>(T[] a)
public static double[] CSSToDoubleArray(string csbuffer)
public static int[] CSSToIntArray(string csbuffer)
public static Color[] CSSToColorArray(string csbuffer)
```
**CSS = Comma-Separated String**

### Python Notes

Python doesn't have direct WinForms equivalents, but Pandas DataFrames provide similar functionality:
```python
import pandas as pd

def copy_selection_to_clipboard(df, selected_indices):
    """Copy DataFrame selection to clipboard"""
    subset = df.iloc[selected_indices]
    subset.to_clipboard(index=False, sep='\t')

def paste_from_clipboard(df, start_row, start_col):
    """Paste tab-delimited clipboard data into DataFrame"""
    clipboard_data = pd.read_clipboard(sep='\t', header=None)
    for i, row in clipboard_data.iterrows():
        for j, value in enumerate(row):
            df.iloc[start_row + i, start_col + j] = value
```

---

## 5. General Class

**Purpose:** Miscellaneous utilities.

### Methods

```csharp
public static bool StringToBoolean(string value)
public static string BooleanToString(bool value)
public static void ConsoleWriteLineToStdErr(string errMessage)
public static bool EqualStringArrays(string[] a, string[] b)
public static void CopyStringArray(string[] a, ref string[] b)
public static void LaunchProcess(string exeFilename, string args)
```

### Process Launching
```csharp
public static void LaunchProcess(string exeFilename, string args)
```
- Redirects stdout/stderr
- Uses BackgroundWorker for async reading
- No shell execution (secure)

### Python Implementation

```python
import subprocess

def launch_process(exe_path, args):
    """Launch external process"""
    result = subprocess.run(
        [exe_path] + args.split(),
        capture_output=True,
        text=True
    )
    return result.stdout, result.stderr
```

---

## 6. Hash Class

**Purpose:** Compute SHA256 hashes for data integrity and caching.

### Constructor
```csharp
public Hash()
```

### Add Data
```csharp
public void Add<T>(T[] buf) where T : struct
public void Add(float val)
public void Add(int val)
public void Add(string str)
public void Add(IList<PointM> buf)
public void Add(Hash hash)  // Nested hashes
```

### Compute Hash
```csharp
public byte[] HashBytes()
public string HashString()
```

### Static Comparison
```csharp
public static bool HashEquals(byte[] hash1, byte[] hash2)
```

### Python Implementation

```python
import hashlib

class Hash:
    def __init__(self):
        self.hasher = hashlib.sha256()

    def add(self, data):
        if isinstance(data, str):
            self.hasher.update(data.encode('utf-8'))
        elif isinstance(data, (int, float)):
            self.hasher.update(str(data).encode('utf-8'))
        elif isinstance(data, (list, np.ndarray)):
            for item in data:
                self.add(item)

    def hash_bytes(self):
        return self.hasher.digest()

    def hash_string(self):
        return self.hasher.hexdigest()
```

---

## 7. KnownLinkIDs Class

**Purpose:** Constants for HEC web forward links.

```csharp
public const int NLD = 4;
```

**Usage:** For retrieving URLs from HEC's link forwarding service.

---

## 8. Math Class

**Purpose:** Mathematical utilities, matrix operations, interpolation, and geometric calculations.

### Constants
```csharp
public const float OneLessEpsilon = 0.9999999f;
```

### Range Operations

```csharp
public static float ConvertRange(float originalStart, float originalEnd,
    float newStart, float newEnd, float value)

public static bool IsInRange(double value, double min, double max)
public static double GetInRange(double value, double min, double max)
public static bool RangeOverlaps(float amin, float amax, float bmin, float bmax)
```

### Min/Max Operations

```csharp
public static double Max3(double d1, double d2, double d3)
public static double Min3(double d1, double d2, double d3)
public static double Mid3(double d1, double d2, double d3)
public static void MaxMin3(double d0, double d1, double d2, ref double max, ref double min)
public static int MinIndex(params double[] vals)
```

### Matrix Solving

```csharp
public static void Solve2x2(double a00, double a01, double a10, double a11,
    double b0, double b1, ref double x0, ref double x1)

public static void GaussJordan(double[,] a, double[,] b, bool makeInverse = false)
```

**Gauss-Jordan:** Solves systems of linear equations; optionally computes matrix inverse.

### Gaussian Quadrature

```csharp
public static double GaussianQuadraturePoint(int n1to5, int index)
public static double GaussianQuadratureWeight(int n1to5, int index)
```

Used for numerical integration (1 to 5 point quadrature).

### Byte Swapping

```csharp
public static double BitConverterSwapBytesToDouble(byte[] bytes, int startindex)
public static int BitConverterSwapBytesToInteger(byte[] Bytes, int startIndex)
public static byte[] BitConverterSwapBytesGetBytes(double value)
```

Handle big-endian/little-endian conversions.

### Point-in-Parallelogram Test

```csharp
public static bool PointInParallelogram(PointM p, PointM a, PointM b, PointM c)
```

### Array Comparison

```csharp
public static bool ArraysEqual<T>(T[] a, T[] b) where T : struct, IEquatable<T>
public static bool StringArraysEqual(string[] a, string[] b)
```

### Python Implementation

```python
import numpy as np
from scipy import linalg

def solve_2x2(a00, a01, a10, a11, b0, b1):
    """Solve 2x2 system"""
    A = np.array([[a00, a01], [a10, a11]])
    b = np.array([b0, b1])
    return linalg.solve(A, b)

def gauss_jordan(A, b, make_inverse=False):
    """Solve Ax=b using Gauss-Jordan elimination"""
    x = linalg.solve(A, b)
    if make_inverse:
        A_inv = linalg.inv(A)
        return x, A_inv
    return x

# Gaussian quadrature points/weights
from scipy.integrate import fixed_quad

def integrate_function(func, a, b, n=5):
    """Numerical integration using n-point Gaussian quadrature"""
    result, _ = fixed_quad(func, a, b, n=n)
    return result
```

---

## 9. Network Class

**Purpose:** HTTP communication with HEC servers.

### Constants
```csharp
public const string HECForwardLinkURL = "http://www.hec.usace.army.mil/fwlink/?";
```

### URL Retrieval
```csharp
public static string TryGetHecUrl(int linkId, ProgressReporter prog = null)
```

**Example Usage:**
```csharp
string url = Network.TryGetHecUrl(KnownLinkIDs.NLD, progressReporter);
```

### Python Implementation

```python
import requests

def try_get_hec_url(link_id, timeout=5):
    """Retrieve HEC forward link URL"""
    url = f"http://www.hec.usace.army.mil/fwlink/?linkid={link_id}&type=string"
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response.text.strip()
    except requests.RequestException as e:
        print(f"Error: {e}")
        return ""
```

---

## 10. Path Class

**Purpose:** File path manipulation and utilities.

### Directory Operations

```csharp
public static void EnsureDirectoryExists(string dirname)
public static string FolderName(string filename)
```

### File Operations

```csharp
public static string RenameFile(string currentFilename, string newfilename)
public static bool CreateOrUpdate(string olderFile, string newerFile)
public static string EnsureFileCharacters(string filename)
```

### World File Generation

```csharp
public static string CreateWorldFilename(string filename)
```
**Example:** `image.tif` → `image.tfw`

### Relative/Absolute Path Conversion

```csharp
public static string MakeRelative(string filename, string baseFilename)
public static string MakeAbsolute(string filename, string baseFilename)
```

**Critical for RASMapper:** All file paths in `.rasmap` files are stored relative to the project file.

### Python Implementation

```python
from pathlib import Path
import os

def make_relative(filename, base_filename):
    """Convert to relative path"""
    return os.path.relpath(filename, start=os.path.dirname(base_filename))

def make_absolute(filename, base_filename):
    """Convert to absolute path"""
    base_dir = os.path.dirname(base_filename)
    return os.path.abspath(os.path.join(base_dir, filename))

def create_world_filename(filename):
    """Generate world file name from raster"""
    # .tif -> .tfw, .jpg -> .jgw, etc.
    ext = Path(filename).suffix
    world_ext = ext[1] + ext[-1] + 'w'
    return filename.replace(ext, '.' + world_ext)
```

---

## 11. Stats Class

**Purpose:** Statistics utilities (currently empty placeholder).

```csharp
public abstract class Stats { }
```

No methods currently defined - reserved for future statistical operations.

---

## 12. Vector Class

**Purpose:** Geometric vector operations (dot product, cross product, angles, extent calculations).

### Extent Operations

```csharp
public static Extent MaximumExtent(Extent extent, Feature feature)
public static Extent MaximumExtent(Extent extent, SegmentM segment)
```

### Angle Calculations

```csharp
public static double AngleBetween(PointM a, PointM b, PointM c)
public static double AngleBetween(Point2Double a, Point2Double b, Point2Double c)
```

Returns angle in radians at point `a` formed by vectors `a→b` and `a→c`.

### Vector Products

```csharp
public static double DotProduct(PointM a, PointM b, PointM c)
public static double CrossProduct(PointM a, PointM b, PointM c)
public static double CrossProduct(Point2Double a, Point2Double b, Point2Double c)
```

**Cross Product:** Used to determine orientation (left/right turn).

### Python Implementation

```python
import numpy as np

def angle_between(a, b, c):
    """Compute angle at point a formed by vectors a->b and a->c"""
    ba = np.array(b) - np.array(a)
    ca = np.array(c) - np.array(a)

    cos_angle = np.dot(ba, ca) / (np.linalg.norm(ba) * np.linalg.norm(ca))
    angle = np.arccos(np.clip(cos_angle, -1.0, 1.0))
    return angle

def cross_product(a, b, c):
    """2D cross product (returns scalar)"""
    ba = np.array(b) - np.array(a)
    ca = np.array(c) - np.array(a)
    return ba[0] * ca[1] - ba[1] * ca[0]

def dot_product(a, b, c):
    """Dot product of vectors a->b and a->c"""
    ba = np.array(b) - np.array(a)
    ca = np.array(c) - np.array(a)
    return np.dot(ba, ca)
```

---

## 13. XML Class

**Purpose:** XML parsing, serialization, and attribute/element extraction utilities.

### Value Parsing

```csharp
public static double DoubleVal(string value)
public static float SingleVal(string value, float defaultValue = float.NaN)
public static int IntegerVal(string value)
public static bool BooleanVal(string value)
public static byte ByteVal(string value)
```

### Attribute Reading

```csharp
public static double DoubleAttribute(IXPathNavigable xmlNode, string attributeName)
public static float SingleAttribute(IXPathNavigable xmlNode, string attributeName, float defaultValue = float.NaN)
public static int IntegerAttribute(IXPathNavigable xmlNode, string attributeName, int defaultValue = int.MinValue)
public static string StringAttribute(IXPathNavigable xmlNode, string attributeName, string defaultValue = "")
public static bool BooleanAttribute(IXPathNavigable xmlNode, string attributeName, bool defaultValue = false)
```

### Element Reading

```csharp
public static double DoubleTextElement(XmlNode @base, string name, XmlNamespaceManager nsmgr = null)
public static int IntegerTextElement(XmlNode @base, string name, int defaultVal = int.MinValue)
public static bool BooleanTextElement(XmlNode @base, string name, bool notFoundValue = false)
public static string StringTextElement(XmlNode @base, string name)
```

### Element Creation

```csharp
public static XmlElement AddTextElement(XmlDocument doc, XmlNode @base, string name, string value)
public static XmlElement AddTextElementSanitized(XmlDocument doc, XmlNode @base, string name, string value)
```

### Sanitization

```csharp
public static string SanitizeName(string name)
public static string UnsanitizeName(string name)
public static string SanitizeValue(string text)
```

**Sanitization Rules:**
- Replace spaces with underscores
- Remove XML-invalid characters: `* ^ ( ) / ' "`
- Escape special XML characters in values

### Namespace Management

```csharp
public static XmlNamespaceManager MakeNameSpaceManager(XmlDocument doc, ref string dns)
```

### Formatting

```csharp
public static string FormattedXML(string xmlText)
public static string PrettyXML(ref string xmlText)
```

### Python Implementation

```python
import xml.etree.ElementTree as ET
from xml.dom import minidom

def double_attribute(element, attr_name, default=float('nan')):
    """Read double attribute from XML element"""
    try:
        return float(element.get(attr_name, default))
    except ValueError:
        return default

def add_text_element(parent, name, value):
    """Add text element to XML"""
    elem = ET.SubElement(parent, name)
    elem.text = str(value)
    return elem

def sanitize_name(name):
    """Sanitize XML element name"""
    name = name.replace(' ', '_')
    name = name.replace('*', '').replace('^', '')
    name = name.replace('(', '').replace(')', '')
    name = name.replace('/', '').replace("'", '').replace('"', '')
    return name

def pretty_xml(xml_string):
    """Format XML with indentation"""
    dom = minidom.parseString(xml_string)
    return dom.toprettyxml(indent="  ")
```

---

## Key Automation Opportunities

### 1. Batch Rendering
Use `Drawing` utilities to automate map generation:
```python
# Generate labeled flood maps programmatically
for plan in plans:
    render_map(plan, labels=True, arrows=True, colormap='WSE')
    export_to_pdf(f"FloodMap_{plan}.pdf")
```

### 2. DataGridView Automation
Programmatically manipulate attribute tables:
```csharp
// Apply bulk edits to feature attributes
Form.DGVMultiplySelectedCellsPrompt(attributeTable);
Form.DGVSetSelectedCellsPrompt(attributeTable, customColumn);
```

### 3. File Path Management
Handle RASMapper project portability:
```python
# Convert all absolute paths to relative before sharing project
for layer in rasmapper_layers:
    layer.path = Path.make_relative(layer.path, project_file)
```

### 4. XML Parsing
Extract RASMapper settings programmatically:
```python
# Read all layer visibility settings
doc = ET.parse('Project.rasmap')
for layer in doc.findall('.//Layer'):
    name = XML.string_attribute(layer, 'Name')
    visible = XML.boolean_attribute(layer, 'Visible')
    print(f"{name}: {visible}")
```

### 5. Hash-Based Caching
Optimize repeated computations:
```python
# Cache expensive interpolation results
hash_obj = Hash()
hash_obj.add(mesh_points)
hash_obj.add(terrain_grid)
cache_key = hash_obj.hash_string()

if cache_key in cache:
    return cache[cache_key]
else:
    result = expensive_interpolation()
    cache[cache_key] = result
    return result
```

---

## Summary Table

| Class | Primary Use | Key Methods | Python Equivalent |
|-------|-------------|-------------|-------------------|
| **Converter** | Type conversion | `Convert(RasterM)`, `Convert(PointM)` | Custom conversion functions |
| **Drawing** | Rendering/graphics | `DrawArrow()`, `DrawStringCheckOverlap()` | matplotlib, PIL |
| **DSS** | Date/time | `ConvertFromDSSDateTime()` | datetime, custom parsers |
| **Form** | WinForms/DataGridView | `dgv_KeyDown()`, `DGVSetSelectedCells()` | pandas DataFrame operations |
| **General** | Misc utilities | `LaunchProcess()`, `EqualStringArrays()` | subprocess, numpy |
| **Hash** | Data integrity | `HashBytes()`, `Add()` | hashlib |
| **Math** | Mathematical ops | `GaussJordan()`, `Max3()`, `Solve2x2()` | numpy, scipy.linalg |
| **Network** | HTTP requests | `TryGetHecUrl()` | requests |
| **Path** | File operations | `MakeRelative()`, `MakeAbsolute()` | pathlib, os.path |
| **Vector** | Geometry | `AngleBetween()`, `CrossProduct()` | numpy vector operations |
| **XML** | XML parsing | `DoubleAttribute()`, `AddTextElement()` | xml.etree.ElementTree |

---

## Notes for Python Implementation

1. **No Direct WinForms Equivalent:** Use PyQt/Tkinter for UI, pandas for tabular data
2. **Geometry Libraries:** Use shapely/geopandas instead of RASMapper internal types
3. **Raster Operations:** Use rasterio/GDAL instead of RasterM
4. **XML:** ElementTree is sufficient for most operations
5. **Math:** scipy.linalg for matrix operations, numpy for arrays

---

## Calling RASMapper Utilities Directly

Most utilities are low-level and called internally by RASMapper. However, for automation:

### Read-Only Operations (Safe to Call)
- `XML.*` - Parse .rasmap files
- `Path.MakeRelative/Absolute` - Handle file paths
- `Drawing.ColorTo*/ColorFrom*` - Color conversions
- `DSS.ConvertFromDSSDateTime` - Parse DSS dates
- `Hash.HashBytes()` - Verify data integrity

### Modify-With-Caution Operations
- `Form.DGV*` - Require active WinForms DataGridView instance
- `Drawing.Draw*` - Require active Graphics context
- `Network.TryGetHecUrl` - Network calls to HEC servers

### Best Practice
Extract data via these utilities, manipulate in Python, then write back using RASMapper's save methods rather than direct XML manipulation.
