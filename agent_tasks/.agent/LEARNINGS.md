# Learnings

## What Works
- **5-File Memory System**: Simple, predictable, easy to understand (STATE, CONSTITUTION, BACKLOG, PROGRESS, LEARNINGS)
- **Markdown Over JSON**: Human-readable, git-friendly, easier to maintain than structured data files
- **Archive .old/ Folder**: Clean way to preserve history without cluttering active workspace

## What Doesn't Work
- **Over-Engineered Systems**: 1500-line coordination plans with waves, verdicts, JSON schemas - too complex for starting out
- **Symlinks in ReadTheDocs**: They get stripped during rsync deployment (always use cp -r instead)
- **Planning Without Implementation**: Multiple planning docs scattered around, none actually executed

## Project-Specific
- **ras-commander Context**: Test-driven with HEC-RAS example projects instead of unit tests; notebooks serve as both docs and tests
- **Static Class Pattern**: Most ras-commander classes use static methods; don't instantiate them
- **Path Handling**: Always use pathlib.Path, support both string and Path objects in parameters
- **Protocol Pattern for Callbacks**: Using `@runtime_checkable` Protocol instead of ABC enables flexible partial implementation (lib-001)
- **Extract Before Extend**: When adding features, extract proven patterns from existing code (e.g., BcoMonitor from DockerWorker) rather than reinventing
- **hasattr() for Optional Methods**: Checking hasattr() before invoking Protocol methods enables graceful degradation without requiring all methods
- **Thread-Safe Callbacks**: Always use threading.Lock in callback implementations for compute_parallel() compatibility
- **Backward Compatibility Pattern**: New optional parameters with None default preserve 100% backward compatibility without versioning headaches
