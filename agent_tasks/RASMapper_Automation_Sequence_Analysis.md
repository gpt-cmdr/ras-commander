# RASMapper Automation - Proper Sequence and Timing Analysis

**Date**: 2024-12-12
**Context**: Fixing GUI automation failures for stored map generation in HEC-RAS 6.x
**Problem**: Current automation fails because RASMapper window detection and sequencing is incorrect

---

## Executive Summary

The current RASMapper automation fails due to:
1. **Wrong sequence**: Trying to run compute BEFORE RASMapper has been opened
2. **No wait logic**: Not waiting for RASMapper to fully open before proceeding
3. **Missing .rasmap upgrade**: For HEC-RAS 5.0.7 → 6.x projects, .rasmap MUST be upgraded FIRST

**Correct sequence** (as confirmed by user):
1. Open RASMapper from HEC-RAS
2. **WAIT** for RASMapper to open COMPLETELY (window appears AND is responsive)
3. Close RASMapper cleanly
4. **THEN** modify .rasmap XML to add results map entries
5. **THEN** run compute via "Run > Unsteady Flow Analysis"

---

## Analysis of Working Code (from 16_automating_ras_with_win32com.ipynb)

### Cell 16 - The Working RASMapper Open/Wait/Close Pattern

This cell demonstrates the **CORRECT** approach:

```python
# 1. OPEN HEC-RAS FIRST
ras_exe = ras.ras_exe_path
prj_path = f'"{str(ras.prj_file)}"'
command = f"{ras_exe} {prj_path}"

if sys.platform == "win32":
    hecras_process = subprocess.Popen(command)
else:
    hecras_process = subprocess.Popen([ras_exe, prj_path])

hecras_pid = hecras_process.pid

# 2. WAIT FOR HEC-RAS MAIN WINDOW (Critical first step)
windows = None
while True:
    windows = get_windows_by_pid(hecras_pid)
    if windows:
        hec_ras_hwnd, title = find_main_hecras_window(windows)
        if hec_ras_hwnd:
            print(f"\nUsing main window: {title}")
            break
        else:
            print("Main HEC-RAS window not ready yet, waiting 2 seconds...")
            time.sleep(2)
    else:
        print("No HEC-RAS windows found yet, waiting 2 seconds...")
        time.sleep(2)

# 3. OPEN RASMAPPER VIA MENU
# Try menu method first (most reliable)
if open_rasmapper_via_menu(hec_ras_hwnd):
    print("RAS Mapper opening via menu...")
else:
    # Fallback to keyboard method
    if open_rasmapper_keyboard(hec_ras_hwnd):
        print("RAS Mapper opening via keyboard...")

# 4. CRITICAL: WAIT FOR RASMAPPER WINDOW TO APPEAR
print("\nWaiting for RAS Mapper to open...")
rasmapper_windows = wait_for_window(find_rasmapper_window)

if rasmapper_windows:
    print(f"RAS Mapper is open: {rasmapper_windows[0][1]}")

    # 5. CRITICAL: ALLOW TIME FOR .rasmap UPDATE
    print("Allowing time for .rasmap update...")
    time.sleep(2)  # Give extra time for file updates

    # 6. CLOSE RASMAPPER
    print("Attempting to close RAS Mapper...")
    while True:
        if close_rasmapper():
            print("RAS Mapper closed successfully.")
            break
        print("Waiting 2 seconds before trying to close RAS Mapper again...")
        time.sleep(2)

    # 7. CRITICAL: WAIT UNTIL RASMAPPER FULLY CLOSED
    while find_rasmapper_window():
        print("Waiting for RAS Mapper to fully close...")
        time.sleep(2)

    # 8. FINALLY CLOSE HEC-RAS
    print("\nClosing HEC-RAS...")
    win32gui.PostMessage(hec_ras_hwnd, win32con.WM_CLOSE, 0, 0)
```

---

## Window Detection Logic

### Finding RASMapper Window

**Function**: `find_rasmapper_window()`

```python
def find_rasmapper_window():
    """Find any RAS Mapper window"""
    def callback(hwnd, windows):
        if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
            window_title = win32gui.GetWindowText(hwnd)
            if "RAS Mapper" in window_title:
                windows.append((hwnd, window_title))
        return True

    windows = []
    win32gui.EnumWindows(callback, windows)
    return windows
```

**Key checks**:
- `IsWindowVisible()` - Window must be visible
- `IsWindowEnabled()` - Window must be responsive (not disabled)
- Title contains "RAS Mapper" (case-sensitive)

### Waiting for Window to Appear

**Function**: `wait_for_window(find_window_func, timeout=60, check_interval=2)`

```python
def wait_for_window(find_window_func, timeout=60, check_interval=2):
    """Wait for a window to appear"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        windows = find_window_func()
        if windows:
            return windows
        print(f"Window not found, waiting {check_interval} seconds...")
        time.sleep(check_interval)
    return None
```

**Parameters**:
- `timeout=60` - Wait up to 60 seconds for RASMapper to open
- `check_interval=2` - Check every 2 seconds

**Why this works**: Polls continuously until window appears, with reasonable timeouts

---

## Timing Requirements

### 1. Initial HEC-RAS Launch Wait
**Wait time**: Variable (2-5 seconds typical)
**Method**: Polling `get_windows_by_pid()` until main window found
**Detection**: Window has title containing "HEC-RAS" AND has menu bar

```python
# From working code:
while True:
    windows = get_windows_by_pid(hecras_pid)
    if windows:
        hec_ras_hwnd, title = find_main_hecras_window(windows)
        if hec_ras_hwnd:
            break
    time.sleep(2)
```

### 2. RASMapper Launch Wait
**Wait time**: Up to 60 seconds (typical 5-10 seconds)
**Method**: `wait_for_window(find_rasmapper_window, timeout=60, check_interval=2)`
**Detection**: Window title contains "RAS Mapper", is visible AND enabled

```python
rasmapper_windows = wait_for_window(find_rasmapper_window, timeout=60)
```

### 3. .rasmap Update Wait
**Wait time**: 2 seconds AFTER RASMapper window detected
**Purpose**: Allow time for RASMapper to write .rasmap file updates
**Critical**: Must wait even after window appears

```python
if rasmapper_windows:
    time.sleep(2)  # Give extra time for file updates
```

### 4. RASMapper Close Wait
**Wait time**: Polling until window no longer found
**Method**: Continuous polling with 2-second intervals
**Critical**: Must verify window is FULLY closed before proceeding

```python
while find_rasmapper_window():
    print("Waiting for RAS Mapper to fully close...")
    time.sleep(2)
```

---

## Close Sequence

### Closing RASMapper

**Method**: Send `WM_CLOSE` message via `PostMessage()`

```python
def close_rasmapper():
    """Close RASMapper window"""
    windows = find_rasmapper_window()

    for hwnd, title in windows:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        print(f"Closed: {title}")
        return True
    return False
```

**Why `PostMessage` instead of `SendMessage`**:
- `PostMessage()` is asynchronous - doesn't block waiting for window to process
- Safer for closing operations - avoids deadlocks
- Window handles close message in its own message loop

### Retry Logic for Close

**Pattern from working code**:

```python
while True:
    if close_rasmapper():
        print("RAS Mapper closed successfully.")
        break
    print("Waiting 2 seconds before trying to close RAS Mapper again...")
    time.sleep(2)
```

**Why retry**: Window may not respond immediately, retry ensures clean close

### Verification Window is Closed

**Critical final check**:

```python
while find_rasmapper_window():
    print("Waiting for RAS Mapper to fully close...")
    time.sleep(2)
```

**Why necessary**:
- Window may still be in process of closing
- .rasmap file may still be locked
- Must ensure window completely gone before modifying .rasmap

---

## Why This Sequence is Required

### The .rasmap Upgrade Process

**For HEC-RAS 5.0.7 projects in 6.x**:

1. **Opening RASMapper triggers upgrade**: When RASMapper opens a 5.0.7 .rasmap file, it automatically upgrades the format
2. **Upgrade happens asynchronously**: File is written AFTER window appears
3. **Must allow upgrade to complete**: Hence the 2-second wait AFTER window detection
4. **Must close cleanly**: Ensures all file writes are flushed to disk

**From Cell 16 output**:
```
MANUAL STEP REQUIRED: Update .rasmap to Version 6.x
This project was created in HEC-RAS 5.0.7. To generate stored maps in HEC-RAS 6.x, you must:
1. HEC-RAS will now be opened with this project.
2. In HEC-RAS, open RAS Mapper (from the main toolbar).
3. When prompted, allow RAS Mapper to update the .rasmap file to the new version.
4. Once the update is complete, close RAS Mapper and exit HEC-RAS.
```

### Why Can't Modify .rasmap Before Opening RASMapper

**The .rasmap format changed between versions**:
- HEC-RAS 5.0.7 uses one XML schema
- HEC-RAS 6.x uses updated schema with new elements
- Adding 6.x elements to 5.0.7 schema causes validation errors
- RASMapper MUST upgrade first, then modifications can be made

**Sequence visualization**:
```
WRONG (Current):
1. Modify .rasmap (5.0.7 format) → Add 6.x elements → FAIL (schema mismatch)
2. Run compute → HEC-RAS can't read malformed .rasmap → FAIL

CORRECT (Required):
1. Open RASMapper → Upgrade .rasmap to 6.x format → Close
2. Modify .rasmap (6.x format) → Add elements → SUCCESS (schema compatible)
3. Run compute → HEC-RAS reads valid 6.x .rasmap → SUCCESS
```

---

## Current Implementation Issues in RasGuiAutomation.py

### Issue 1: No RASMapper Open/Wait/Close Logic

**File**: `C:\GH\ras-commander\ras_commander\RasGuiAutomation.py`
**Function**: `open_and_compute()`

**Current sequence** (WRONG):
```python
def open_and_compute(...):
    # 1. Set current plan in .prj file
    ras_obj.set_current_plan(plan_number)

    # 2. Open HEC-RAS
    hecras_process = subprocess.Popen(command)

    # 3. Wait for main window
    hec_ras_hwnd = wait_for_window(find_ras_window, timeout=30)

    # 4. Click "Run > Unsteady Flow Analysis" immediately ❌
    click_menu_item(hec_ras_hwnd, 47)

    # 5. Click Compute button ❌
    # ... no RASMapper logic anywhere
```

**Missing**:
- No RASMapper open step
- No wait for RASMapper to fully load
- No .rasmap upgrade verification
- No clean close of RASMapper

### Issue 2: Compute Button Not Found

**From notebook cell 19 log output**:
```
2025-11-17 21:31:16 - WARNING - Could not find Compute button - user must click manually
2025-11-17 21:31:16 - INFO - Trying keyboard shortcut as fallback...
2025-11-17 21:31:17 - INFO - Sent Enter key to dialog
```

**Why button not found**:

Looking at `find_button_by_text()`:
```python
def find_button_by_text(dialog_hwnd: int, button_text: str) -> Optional[int]:
    def callback(child_hwnd, buttons):
        try:
            text = win32gui.GetWindowText(child_hwnd)
            class_name = win32gui.GetClassName(child_hwnd)
            if button_text.lower() in text.lower() and class_name == "Button":
                buttons.append(child_hwnd)
        except:
            pass
        return True

    buttons = []
    win32gui.EnumChildWindows(dialog_hwnd, callback, buttons)
```

**Possible causes**:
1. **Button is owner-drawn**: Class name is "Button" but text is empty (rendered as image)
2. **Button in nested container**: `EnumChildWindows()` may not recurse deep enough
3. **Button text doesn't match**: Might be "Run" or "Execute" instead of "Compute"
4. **Dialog not fully loaded**: Button added after initial enumeration

**Evidence from logs**: Fallback to Enter key suggests dialog exists but button not enumerable

### Issue 3: No Window Responsive Check

**Current code** checks:
- `IsWindowVisible()` ✓
- `IsWindowEnabled()` ✓

**Missing check**:
- Window message queue responsive
- Window finished initialization
- All child controls loaded

**Better detection** (from working code):
```python
# After finding window, give it time to fully load
if rasmapper_windows:
    print(f"RAS Mapper is open: {rasmapper_windows[0][1]}")
    time.sleep(2)  # Critical: allow window to fully initialize
```

---

## Alternative Methods for Button Discovery

### Method 1: Control ID instead of Text

HEC-RAS dialogs may use fixed control IDs:

```python
def find_button_by_id(dialog_hwnd: int, control_id: int) -> Optional[int]:
    """Find button by control ID (more reliable than text)"""
    def callback(child_hwnd, buttons):
        try:
            this_id = win32gui.GetDlgCtrlID(child_hwnd)
            if this_id == control_id:
                buttons.append(child_hwnd)
        except:
            pass
        return True

    buttons = []
    win32gui.EnumChildWindows(dialog_hwnd, callback, buttons)
    return buttons[0] if buttons else None

# Usage: Try common OK/Compute button IDs
for button_id in [1, 2, 100, 101, 1000, 1001]:  # IDOK=1, IDCANCEL=2, etc.
    button_hwnd = find_button_by_id(dialog_hwnd, button_id)
    if button_hwnd:
        break
```

### Method 2: Keyboard Shortcuts (Current Fallback)

**Current code** already implements this:
```python
shell = win32com.client.Dispatch("WScript.Shell")
shell.SendKeys("{ENTER}")
```

**Why this works**:
- Default button responds to Enter key
- Doesn't require finding specific button handle
- More reliable for owner-drawn buttons

**Downside**:
- Less precise (might activate wrong button)
- Requires dialog to have focus

### Method 3: Accessible Interface (Advanced)

Use UI Automation API instead of win32gui:

```python
import uiautomation as auto

# Find dialog
dialog = auto.WindowControl(searchDepth=1, Name="Unsteady Flow Analysis")

# Find button by name OR by automation ID
compute_button = dialog.ButtonControl(Name="Compute")
# OR
compute_button = dialog.ButtonControl(AutomationId="btnCompute")

# Click
compute_button.Click()
```

**Advantages**:
- Works with owner-drawn controls
- Handles nested containers
- More robust than text matching

**Disadvantages**:
- Requires `uiautomation` package
- Slower than win32gui
- More complex setup

### Method 4: Menu Shortcut Instead of Dialog

**Alternative approach** - bypass dialog entirely:

Some HEC-RAS operations have direct menu shortcuts:
```python
# Instead of opening dialog and clicking Compute:
# 1. Set current plan in .prj file
# 2. Use menu command that runs plan directly (if exists)
# 3. Avoid dialog interaction entirely
```

**Would need to research**: HEC-RAS menu IDs for direct compute commands

---

## Recommended Implementation

### New Function: `ensure_rasmapper_upgraded()`

Add to `RasGuiAutomation.py`:

```python
@staticmethod
@log_call
def ensure_rasmapper_upgraded(ras_object=None, timeout=90) -> bool:
    """
    Open RASMapper to ensure .rasmap file is upgraded to 6.x format.

    This is required for HEC-RAS 5.0.7 projects before floodplain mapping.

    Workflow:
    1. Open HEC-RAS with project
    2. Wait for main window
    3. Open RASMapper via menu/keyboard
    4. Wait for RASMapper window to appear and be responsive
    5. Wait 2 seconds for .rasmap file write
    6. Close RASMapper cleanly
    7. Verify RASMapper fully closed
    8. Close HEC-RAS

    Args:
        ras_object: RAS project object
        timeout: Maximum time to wait for RASMapper (default 90 seconds)

    Returns:
        bool: True if successful, False otherwise
    """
    ras_obj = ras_object or ras
    ras_obj.check_initialized()

    # Step 1: Open HEC-RAS
    logger.info("Opening HEC-RAS for .rasmap upgrade...")
    ras_exe = ras_obj.ras_exe_path
    prj_path = f'"{str(ras_obj.prj_file)}"'
    command = f"{ras_exe} {prj_path}"

    try:
        if sys.platform == "win32":
            hecras_process = subprocess.Popen(command)
        else:
            hecras_process = subprocess.Popen([str(ras_exe), str(ras_obj.prj_file)])

        logger.info(f"HEC-RAS opened with Process ID: {hecras_process.pid}")
    except Exception as e:
        logger.error(f"Failed to open HEC-RAS: {e}")
        return False

    # Step 2: Wait for main window (with timeout)
    logger.info("Waiting for HEC-RAS main window...")

    def find_ras_window():
        windows = RasGuiAutomation.get_windows_by_pid(hecras_process.pid)
        hwnd, title = RasGuiAutomation.find_main_hecras_window(windows)
        return hwnd

    hec_ras_hwnd = RasGuiAutomation.wait_for_window(find_ras_window, timeout=30)

    if not hec_ras_hwnd:
        logger.error("Could not find main HEC-RAS window")
        try:
            hecras_process.kill()
        except:
            pass
        return False

    logger.info(f"Found HEC-RAS main window: {win32gui.GetWindowText(hec_ras_hwnd)}")
    time.sleep(1)  # Let window fully stabilize

    # Step 3: Open RASMapper
    logger.info("Opening RASMapper...")

    # Try menu method first
    menus = RasGuiAutomation.enumerate_all_menus(hec_ras_hwnd)
    rasmapper_menu_id = None

    # Look for RASMapper in GIS Tools menu
    for menu_name, items in menus.items():
        if "gis" in menu_name.lower() or "tools" in menu_name.lower():
            for item_text, item_id in items:
                if "ras mapper" in item_text.lower():
                    rasmapper_menu_id = item_id
                    logger.info(f"Found RASMapper menu item: ID {item_id}")
                    break

    if rasmapper_menu_id:
        RasGuiAutomation.click_menu_item(hec_ras_hwnd, rasmapper_menu_id)
    else:
        # Fallback to keyboard shortcut
        logger.info("Menu method failed, trying keyboard shortcut...")
        try:
            win32gui.SetForegroundWindow(hec_ras_hwnd)
            time.sleep(0.5)
            shell = win32com.client.Dispatch("WScript.Shell")
            shell.SendKeys("%g")  # Alt+G for GIS Tools
            time.sleep(0.2)
            shell.SendKeys("r")  # R for RAS Mapper
        except Exception as e:
            logger.error(f"Failed to open RASMapper: {e}")
            RasGuiAutomation.close_window(hec_ras_hwnd)
            return False

    # Step 4: Wait for RASMapper window
    logger.info("Waiting for RASMapper window to appear...")

    def find_rasmapper():
        def callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if "RAS Mapper" in title:
                    windows.append(hwnd)
            return True

        windows = []
        win32gui.EnumWindows(callback, windows)
        return windows[0] if windows else None

    rasmapper_hwnd = RasGuiAutomation.wait_for_window(find_rasmapper, timeout=timeout)

    if not rasmapper_hwnd:
        logger.error(f"RASMapper did not open within {timeout} seconds")
        RasGuiAutomation.close_window(hec_ras_hwnd)
        return False

    logger.info(f"RASMapper opened: {win32gui.GetWindowText(rasmapper_hwnd)}")

    # Step 5: CRITICAL - Wait for .rasmap file write
    logger.info("Waiting for .rasmap upgrade to complete...")
    time.sleep(2)  # Allow time for file updates

    # Step 6: Close RASMapper
    logger.info("Closing RASMapper...")
    max_close_attempts = 5
    for attempt in range(max_close_attempts):
        try:
            win32gui.PostMessage(rasmapper_hwnd, win32con.WM_CLOSE, 0, 0)
            logger.info(f"Sent close message to RASMapper (attempt {attempt+1})")
            time.sleep(2)

            # Check if still exists
            if not find_rasmapper():
                logger.info("RASMapper closed successfully")
                break
        except Exception as e:
            logger.warning(f"Close attempt {attempt+1} failed: {e}")
    else:
        logger.warning(f"RASMapper may not have closed cleanly after {max_close_attempts} attempts")

    # Step 7: Verify RASMapper fully closed
    logger.info("Verifying RASMapper is fully closed...")
    for i in range(10):  # Wait up to 20 seconds
        if not find_rasmapper():
            logger.info("RASMapper window no longer detected")
            break
        logger.info(f"RASMapper still closing... waiting ({i+1}/10)")
        time.sleep(2)
    else:
        logger.warning("RASMapper window may still be open")

    # Step 8: Close HEC-RAS
    logger.info("Closing HEC-RAS...")
    RasGuiAutomation.close_window(hec_ras_hwnd)

    # Wait for HEC-RAS to close
    try:
        hecras_process.wait(timeout=30)
        logger.info("HEC-RAS closed successfully")
    except subprocess.TimeoutExpired:
        logger.warning("HEC-RAS did not close within timeout, forcing termination")
        hecras_process.kill()

    return True
```

### Modified `open_and_compute()` Sequence

**Update existing function**:

```python
@staticmethod
@log_call
def open_and_compute(
    plan_number: str,
    ras_object=None,
    auto_click_compute: bool = True,
    wait_for_user: bool = True,
    ensure_rasmap_upgraded: bool = True  # NEW PARAMETER
) -> bool:
    """
    Open HEC-RAS, set plan, and run computation.

    Args:
        plan_number: Plan to run
        ras_object: RAS project object
        auto_click_compute: Auto-click Compute button
        wait_for_user: Wait for HEC-RAS to close
        ensure_rasmap_upgraded: Open/close RASMapper first to upgrade .rasmap (NEW)
    """
    ras_obj = ras_object or ras
    ras_obj.check_initialized()

    # NEW: Step 0 - Upgrade .rasmap if needed
    if ensure_rasmap_upgraded:
        logger.info("Checking .rasmap compatibility...")
        # Check if .rasmap needs upgrade (5.0.7 → 6.x)
        # This would call RasMap.ensure_rasmap_compatible()
        # If upgrade needed, call ensure_rasmapper_upgraded()
        pass  # Implementation from RasMap module

    # Step 1: Set current plan in .prj file
    logger.info(f"Setting current plan to {plan_number} in project file...")
    try:
        ras_obj.set_current_plan(plan_number)
        logger.info(f"Current plan set to {plan_number} in {ras_obj.prj_file}")
    except Exception as e:
        logger.error(f"Failed to set current plan: {e}")
        return False

    # ... rest of existing implementation
```

---

## Code Snippets for Each Step

### 1. Open HEC-RAS and Wait for Main Window

```python
# Open HEC-RAS
ras_exe = ras.ras_exe_path
prj_path = f'"{str(ras.prj_file)}"'
command = f"{ras_exe} {prj_path}"

hecras_process = subprocess.Popen(command)
logger.info(f"HEC-RAS opened with PID: {hecras_process.pid}")

# Wait for main window (with timeout and polling)
def find_ras_window():
    windows = RasGuiAutomation.get_windows_by_pid(hecras_process.pid)
    hwnd, title = RasGuiAutomation.find_main_hecras_window(windows)
    return hwnd

hec_ras_hwnd = RasGuiAutomation.wait_for_window(find_ras_window, timeout=30)

if not hec_ras_hwnd:
    raise RuntimeError("HEC-RAS main window did not appear")

logger.info(f"Found main window: {win32gui.GetWindowText(hec_ras_hwnd)}")
time.sleep(1)  # Stabilization pause
```

### 2. Open RASMapper via Menu

```python
# Enumerate menus to find RASMapper
menus = RasGuiAutomation.enumerate_all_menus(hec_ras_hwnd)

rasmapper_menu_id = None
for menu_name, items in menus.items():
    if "gis" in menu_name.lower():
        for item_text, item_id in items:
            if "ras mapper" in item_text.lower():
                rasmapper_menu_id = item_id
                break

if rasmapper_menu_id:
    logger.info(f"Clicking RASMapper menu item (ID: {rasmapper_menu_id})")
    RasGuiAutomation.click_menu_item(hec_ras_hwnd, rasmapper_menu_id)
else:
    raise RuntimeError("Could not find RASMapper menu item")
```

### 3. Wait for RASMapper Window (Fully Loaded)

```python
# Define window finder function
def find_rasmapper():
    def callback(hwnd, windows):
        if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if "RAS Mapper" in title:
                windows.append(hwnd)
        return True

    windows = []
    win32gui.EnumWindows(callback, windows)
    return windows[0] if windows else None

# Wait for window to appear
logger.info("Waiting for RASMapper to open...")
rasmapper_hwnd = RasGuiAutomation.wait_for_window(
    find_rasmapper,
    timeout=90,  # Generous timeout for slow systems
    check_interval=2
)

if not rasmapper_hwnd:
    raise RuntimeError("RASMapper did not open within timeout")

logger.info(f"RASMapper opened: {win32gui.GetWindowText(rasmapper_hwnd)}")

# CRITICAL: Wait for window to fully initialize
logger.info("Allowing time for RASMapper initialization and .rasmap update...")
time.sleep(2)  # Minimum 2 seconds for file write
```

### 4. Close RASMapper Cleanly

```python
# Close RASMapper
logger.info("Closing RASMapper...")

max_attempts = 5
for attempt in range(max_attempts):
    try:
        # Send WM_CLOSE message
        win32gui.PostMessage(rasmapper_hwnd, win32con.WM_CLOSE, 0, 0)
        logger.info(f"Sent close message (attempt {attempt+1}/{max_attempts})")
        time.sleep(2)

        # Verify closed
        if not find_rasmapper():
            logger.info("RASMapper closed successfully")
            break
    except Exception as e:
        logger.warning(f"Close attempt {attempt+1} failed: {e}")
        if attempt < max_attempts - 1:
            time.sleep(2)  # Wait before retry
else:
    logger.error(f"Failed to close RASMapper after {max_attempts} attempts")
    # Could force-kill process here if needed
```

### 5. Verify RASMapper Fully Closed

```python
# Wait for complete closure (window handle invalid)
logger.info("Verifying RASMapper fully closed...")

max_wait = 10  # 10 checks × 2 seconds = 20 second max wait
for i in range(max_wait):
    if not find_rasmapper():
        logger.info(f"RASMapper confirmed closed after {i*2} seconds")
        break
    logger.info(f"RASMapper still closing... ({i+1}/{max_wait})")
    time.sleep(2)
else:
    logger.warning("RASMapper may still be running after maximum wait time")

# Additional check: .rasmap file not locked
import time
rasmap_path = ras.project_folder / f"{ras.project_name}.rasmap"
for i in range(5):
    try:
        # Try to open for writing (will fail if locked)
        with open(rasmap_path, 'a'):
            pass
        logger.info(".rasmap file is accessible (not locked)")
        break
    except IOError:
        logger.info(f".rasmap still locked, waiting... ({i+1}/5)")
        time.sleep(1)
else:
    logger.warning(".rasmap file may still be locked by RASMapper")
```

### 6. Modified .rasmap XML (After RASMapper Closed)

```python
# NOW safe to modify .rasmap
logger.info("Modifying .rasmap to add stored map entries...")

# Parse XML
import xml.etree.ElementTree as ET
tree = ET.parse(rasmap_path)
root = tree.getroot()

# Add results layers
results_layer = root.find(".//Results")
if results_layer is not None:
    # Add stored map elements
    # ... XML modification code

    # Write back to file
    tree.write(rasmap_path, encoding='utf-8', xml_declaration=True)
    logger.info("Successfully updated .rasmap file")
else:
    raise RuntimeError("Could not find Results layer in .rasmap")
```

### 7. Run Compute (After .rasmap Modified)

```python
# NOW safe to run compute
logger.info("Opening Unsteady Flow Analysis dialog...")

# Click menu
RasGuiAutomation.click_menu_item(hec_ras_hwnd, 47)  # Run > Unsteady Flow Analysis
time.sleep(2)

# Find dialog
def find_unsteady_dialog():
    return RasGuiAutomation.find_dialog_by_title("Unsteady Flow Analysis")

dialog_hwnd = RasGuiAutomation.wait_for_window(find_unsteady_dialog, timeout=15)

if dialog_hwnd:
    logger.info("Found Unsteady Flow Analysis dialog")

    # Try to find Compute button
    compute_button = RasGuiAutomation.find_button_by_text(dialog_hwnd, "Compute")

    if compute_button:
        logger.info("Clicking Compute button")
        RasGuiAutomation.click_button(compute_button)
    else:
        # Fallback to keyboard
        logger.info("Button not found, using Enter key")
        shell = win32com.client.Dispatch("WScript.Shell")
        shell.SendKeys("{ENTER}")
else:
    raise RuntimeError("Unsteady Flow Analysis dialog did not appear")
```

---

## Summary of Critical Changes Needed

### 1. In `RasMap.postprocess_stored_maps()`

**Current flow** (WRONG):
```
1. Modify .rasmap
2. Modify plan file
3. Call RasGuiAutomation.open_and_compute()
4. Restore files
```

**Required flow**:
```
1. Check if .rasmap needs upgrade (5.0.7 → 6.x)
2. IF needs upgrade:
   a. Call RasGuiAutomation.ensure_rasmapper_upgraded()
   b. Wait for completion
3. Modify .rasmap (now upgraded to 6.x)
4. Modify plan file
5. Call RasGuiAutomation.open_and_compute()
6. Restore files
```

### 2. In `RasGuiAutomation.py`

**Add new function**: `ensure_rasmapper_upgraded()` (see implementation above)

**Modify**: `open_and_compute()` to optionally call `ensure_rasmapper_upgraded()` first

**Improve**: Button detection with fallback methods (ID-based, keyboard shortcuts)

### 3. Timing Adjustments

**Current**:
- 3 second initial wait
- 2 second intervals for polling
- 15-30 second timeouts

**Recommended**:
- 1 second after main window found (stabilization)
- 2 seconds after RASMapper window detected (file write)
- 2 second intervals for close verification
- 60-90 second timeout for RASMapper open (can be slow on large projects)
- 20-30 second timeout for RASMapper close verification

---

## Testing Checklist

To verify the fix works:

- [ ] **Test 1**: Fresh 5.0.7 project in 6.x
  - Extract BaldEagleCrkMulti2D (5.0.7 project)
  - Run `postprocess_stored_maps()`
  - Verify RASMapper opens, upgrades .rasmap, closes
  - Verify compute runs successfully
  - Verify .tif files created

- [ ] **Test 2**: Already upgraded 6.x project
  - Use project with 6.x .rasmap
  - Run `postprocess_stored_maps()`
  - Verify RASMapper open/close skipped
  - Verify compute runs successfully

- [ ] **Test 3**: Slow system timing
  - Add artificial delays
  - Verify timeouts adequate
  - Verify polling doesn't give up too early

- [ ] **Test 4**: Button detection fallback
  - Verify Enter key fallback works if button not found
  - Verify keyboard shortcuts work if menu fails

- [ ] **Test 5**: Multiple plans
  - Run with `plan_numbers=["01", "02", "03"]`
  - Verify only opens RASMapper once
  - Verify all plans processed

---

## Conclusion

The key insight is that **RASMapper must be opened and closed BEFORE modifying .rasmap**, not after or during. This is because:

1. **5.0.7 → 6.x upgrade happens when RASMapper opens**
2. **Must wait for upgrade to complete** (file write happens asynchronously)
3. **Must ensure window fully closed** before modifying .rasmap (file lock)
4. **Only then safe to add stored map XML elements** (6.x schema now compatible)

The working code in `16_automating_ras_with_win32com.ipynb` Cell 16 demonstrates all these steps correctly. The current `RasGuiAutomation.py` implementation skips the RASMapper open/close cycle entirely, which is why it fails for 5.0.7 projects.

**Next steps**:
1. Implement `ensure_rasmapper_upgraded()` function
2. Integrate into `RasMap.postprocess_stored_maps()` workflow
3. Test with both 5.0.7 and 6.x projects
4. Document timing requirements for users with slow systems
