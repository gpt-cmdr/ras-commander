---
name: hecras_screenshot
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
description: Capture HEC-RAS and standalone RASMapper windows through current ras-commander Win32 APIs for documentation, debugging, QA/QC evidence, galleries, and deterministic spatial review packages. Use for screenshot, visible-window capture, RASMapper snapshot, dialog capture, or model gallery requests on Windows.
---

# HEC-RAS Screenshot

Use ras-commander's maintained screenshot APIs. Do not use the obsolete RASDecomp path.

## APIs

```python
from ras_commander import RasMap
from ras_commander.gui.screenshots import RasScreenshot

# One project, with .rasmap backup/restore and PID-specific close.
image = RasMap.screenshot_model(
    r"C:\Models\Example\Example.prj",
    output_path=r"C:\Reviews\example.png",
    ras_version="7.0",
)

# Existing window or dialog.
image = RasScreenshot.capture_window(hwnd, r"C:\Reviews\window.png")
image = RasScreenshot.capture_dialog("Unsteady Flow Analysis")

# All HEC-RAS windows associated with a process.
images = RasScreenshot.capture_all_ras_windows(pid)
```

For RASMapper layer configuration, exact bounds, state JSON, and repeatable evidence, prefer
`RasMap.create_spatial_review_package()` or the `qa-rasmapper-web-parity` skill.

## Rules

- Run on Windows with a visible target window and `pywin32` available.
- Copy a project before changing `.rasmap` presentation state unless mutation was requested.
- Launch standalone RASMapper through `RasMap.open_rasmapper()` and close only its PID.
- Use `capture_rasmapper_snapshot(viewport_width=..., viewport_height=...)` for fixed dimensions.
- Keep render delay after the window appears; large terrain/result layers may need minutes.
- Record project, RAS version, PID, viewport, selected layers, bounds, and image path.
- Treat screenshots as visual evidence. Use HDF/raster APIs for engineering values.

Primary implementation:

- `ras_commander/gui/screenshots.py`
- `ras_commander/RasMap.py`
- `ras_commander/_rasmap_control_helper.py`
- `tests/test_gui_screenshots.py`
- `tests/test_rasmap_map_layers.py`
