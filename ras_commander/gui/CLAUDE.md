# GUI Automation Subpackage

## Architecture

Three-layer architecture for HEC-RAS GUI automation:

```
Layer 3 — Workflows (workflows/)
    Orchestrated multi-step GUI sequences.
    Each workflow uses Layer 2 elements and handles retry/recovery.

Layer 2 — Element Finders
    hecras_elements.py: HEC-RAS VB6 main window, menus, dialogs
    rasmapper_elements.py: RASMapper .NET WinForms, TreeView, context menus

Layer 1 — Win32 Primitives
    win32_primitives.py: Generic window ops (zero HEC-RAS knowledge)
    constants.py: VB6 class names, Win32 message constants
```

## Key Patterns

- **Static classes only** — no instantiation, matches ras-commander convention
- **@log_call decorator** on all public methods
- **WIN32_AVAILABLE guard** — graceful degradation when pywin32 not installed
- **WorkflowStep + context dict** — steps communicate via shared mutable dict
- **Fallback chains** — menu path → keyboard shortcut → user instruction

## Adding New Workflows

1. Create `workflows/my_workflow.py` with a static class
2. Use `HecRasElements.launch_and_wait()` for HEC-RAS launch (don't duplicate)
3. Build steps as `List[WorkflowStep]` with retry and recovery
4. Add to `workflows/__init__.py` and `gui/__init__.py`
5. Add backward-compat method to `RasGuiAutomation.py` shim if needed

## RASMapper Automation Notes

- RASMapper is .NET WinForms — different class names from VB6
- TreeView navigation requires `TVM_*` Win32 messages
- Context menus appear as `#32768` class windows after right-click
- Use `is_window_responsive()` to detect load completion (not fixed sleeps)
- Mesh generation timing is highly variable — use idle detection

## References

- VB6 GUI map: `C:\GH\RASDecomp` (278 forms, 3,367 controls, 713 menus)
- .NET API surface: `C:\GH\RASDecomp\RASMapper\` (2,855 types, 228 RASMapperCom methods)
