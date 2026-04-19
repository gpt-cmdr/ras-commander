---
name: hecras_screenshot
description: Capture screenshots of HEC-RAS GUI for documentation and debugging.
---

# HEC-RAS Screenshot Skill

[Content to be populated - see RASDecomp project for current implementation]

## Trigger

Use when: capturing HEC-RAS GUI state for documentation, debugging, or QAQC reports.

## Status

Stub - implementation pending. The screenshot capability exists in the RASDecomp project at G:/GH/RASDecomp/screenshot/ras_screenshot.py, which provides:

- Window capture via Win32 PrintWindow + GDI (works even when obscured)
- Click control by name/best-match
- Menu navigation via menu_select
- Window detection by polling for new windows after interaction
- Change detection via pixel-diff monitoring (>0.5% threshold)

## Usage (from RASDecomp implementation)

See G:/GH/RASDecomp/screenshot/ras_screenshot.py for full implementation (~900 lines).

Common flags:
  --list --json         List available windows
  --output-dir DIR      Capture all windows to directory
  --title PATTERN       Capture specific window by title
  --click CONTROL       Click named control and capture
  --menu PATH           Navigate menu and capture
  --watch               Auto-capture on change detection

## Cross-References

**Related agents**:
- win32com-automation-expert -- .claude/agents/win32com-automation-expert.md
- hecras-code-archaeologist -- .claude/agents/hecras-code-archaeologist.md

**External implementation**:
- G:/GH/RASDecomp/screenshot/ras_screenshot.py -- Full screenshot tool (~900 lines)
