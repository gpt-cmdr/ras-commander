# Learnings

Accumulated wisdom from working on this project. Update as you discover patterns.

## What Works

- **5-File Memory System**: Simple, predictable, easy to understand (STATE, CONSTITUTION, BACKLOG, PROGRESS, LEARNINGS)
- **Markdown Over JSON**: Human-readable, git-friendly, easier to maintain than structured data files
- **Archive .old/ Folder**: Clean way to preserve history without cluttering active workspace

## What Doesn't Work

- **Over-Engineered Systems**: Complex coordination plans are harder to maintain than simple files
- **Planning Without Implementation**: Plans without execution don't help users

## Project-Specific

<!-- Add learnings specific to ras-commander as you discover them -->

- **ras-commander Context**: Test-driven with HEC-RAS example projects instead of unit tests; notebooks serve as both docs and tests
- **Static Class Pattern**: Most ras-commander classes use static methods; don't instantiate them
- **Path Handling**: Always use pathlib.Path, support both string and Path objects in parameters

---

## How to Use This File

### When to Add Learnings

- Discovered a pattern that works well? Add to "What Works"
- Hit a wall with an approach? Add to "What Doesn't Work"
- Found something specific to this project? Add to "Project-Specific"

### Format

Keep entries brief but actionable. Include enough context that future readers understand why.

### Review Periodically

Before starting major tasks, scan this file for relevant learnings.
