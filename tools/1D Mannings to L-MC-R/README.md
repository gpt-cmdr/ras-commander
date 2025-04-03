# HEC-RAS Manning's n Editor

## Overview
The HEC-RAS Manning's n Editor is a utility tool designed to streamline the process of configuring Manning's roughness values in 1D HEC-RAS models. It specifically addresses the common issue where HEC-RAS defaults to horizontal Manning's values (`-9999`) for every cross section, making the setup of large dendritic river systems tedious and time-consuming.

This tool was developed in response to feedback from the hydraulic modeling community regarding workflow inefficiencies when building 1D models in newer versions of HEC-RAS.

## Problem Statement
When creating 1D models in recent versions of HEC-RAS, the software automatically assigns horizontal Manning's values (indicated by `-9999`) to every cross section. This requires modelers to manually convert each cross section to use the standard Left Overbank/Main Channel/Right Overbank (L/MC/R) format before they can assign appropriate roughness values through the Tables interface.

For models with numerous cross sections, this process becomes extremely time-consuming and error-prone.

## Solution
This tool automates the conversion process by:
1. Identifying all cross sections in a HEC-RAS geometry file that use the horizontal Manning's format (`#Mann= 1 ,-1,0`)
2. Converting them to use the standard L/MC/R format (`#Mann= 3 ,0,0`) with user-specified values
3. Preserving the original bank stations from each cross section
4. Automatically creating a backup of the original geometry file before making any changes

## Features
- Simple graphical user interface
- Drag-and-drop file selection (if tkinterdnd2 is installed)
- Custom Manning's n values for left overbank, main channel, and right overbank
- Progress tracking for large files
- Detailed results reporting
- Automatic backup creation with .bak extension

## Installation

### Option 1: Run the Python Script
1. Ensure Python 3.6+ is installed on your system
2. Install required dependencies:
   ```
   pip install tkinter
   pip install tkinterdnd2  # Optional, for drag-and-drop functionality
   ```
3. Download the `1D_Mannings_to_L-MC-R.py` script
4. Run it with Python:
   ```
   python 1D_Mannings_to_L-MC-R.py
   ```

### Option 2: Use the Executable
Download and run the pre-compiled executable (`1D_Mannings_to_L-MC-R.exe`) - no Python installation required.

## Usage Instructions
1. Launch the application
2. Select a HEC-RAS geometry file using the "Browse" button or drag-and-drop
3. Enter the desired Manning's n values for:
   - Left Overbank (default: 0.11)
   - Main Channel (default: 0.08)
   - Right Overbank (default: 0.12)
4. Click "Process File" to begin conversion
5. Review the results in the text area

## How It Works
For each cross section with format `#Mann= 1 ,-1,0` and `-9999` values, the tool:
1. Reads the bank stations
2. Replaces the format with `#Mann= 3 ,0,0`
3. Creates a line with the 3 specified Manning's values assigned to the appropriate stations

Before:
```
#Mann= 1 ,-1,0
       0   -9999       0
Bank Sta=2408.322,2509.271
```

After:
```
#Mann= 3 ,0,0
       0    .11       0 2408.322    .08       0 2509.271    .12       0
Bank Sta=2408.322,2509.271
```

## Compiling to Executable
If you wish to compile the script to an executable yourself:

1. Install PyInstaller:
   ```
   pip install pyinstaller
   ```

2. Navigate to the directory containing the script and run:
   ```
   pyinstaller --onefile --windowed 1D_Mannings_to_L-MC-R.py
   ```

3. Look for the executable in the `dist` folder that PyInstaller creates

For enhanced drag-and-drop functionality:
```
pyinstaller --onefile --windowed --add-data "C:\path\to\python\site-packages\tkinterdnd2;tkinterdnd2" 1D_Mannings_to_L-MC-R.py
```

## Notes and Limitations
- Always review results after processing to ensure proper conversion
- The tool will not affect cross sections that already use the standard L/MC/R format
- Creates a backup of the original file with .bak extension (or .bak1, .bak2, etc. if multiple backups exist)
- Modifies the original file in place after creating the backup

## Acknowledgments
This tool was created in response to discussions within the HEC-RAS user community about workflow improvements for 1D modeling. Special thanks to the hydraulic modelers who identified this common pain point.

## License
This tool is provided as-is under the MIT License.