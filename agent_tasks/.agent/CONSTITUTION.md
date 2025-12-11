# Project Constitution

## Identity
**Project**: ras-commander
**Purpose**: Python library for automating HEC-RAS hydraulic modeling operations
**Stack**: Python 3.10+, HDF5, NumPy, Pandas, GeoPandas

## Principles

### 1. Clean Repository Organization
**Statement**: Keep repository root clean; planning docs go in designated folders
**Rationale**: Cluttered repos reduce clarity and increase cognitive load
**Implications**: Use `planning_docs/` for temporary analysis, `agent_tasks/` for coordination, `feature_dev_notes/` for implementation notes

### 2. Incremental Progress Over Perfection
**Statement**: Complete working features > perfect incomplete features
**Rationale**: Users benefit from functional code; perfect plans without code help no one
**Implications**: Ship working code, iterate based on feedback, refactor as separate tasks

### 3. Memory Persistence
**Statement**: Every session starts with amnesia - only files persist
**Rationale**: Claude Code sessions don't retain context automatically
**Implications**: Update STATE.md and PROGRESS.md every session; write detailed handoff notes

### 4. One Task At A Time
**Statement**: Focus on single task until complete or blocked
**Rationale**: Context switching reduces quality and increases error rates
**Implications**: Mark one task in_progress; complete it before starting next; document blockers immediately

## Constraints

### Required Technologies
- Python 3.10+ (ras-commander minimum version)
- HDF5 libraries (h5py) for HEC-RAS results processing
- pathlib.Path for all path operations (not os.path)
- Static class pattern with @log_call decorators

### Forbidden Patterns
- Do NOT instantiate static classes (use `RasCmdr.compute_plan()` not `RasCmdr().compute_plan()`)
- Do NOT commit planning documents to repository root (use `planning_docs/`)
- Do NOT use symlinks in ReadTheDocs builds (they get stripped during deployment)
- Do NOT modify git config or run destructive git commands without explicit user request

### Preferred Approaches
- Test-driven development with HEC-RAS example projects (not unit tests)
- Jupyter notebooks as both documentation and functional tests
- Flexible imports pattern for development vs installed package
- Comprehensive docstrings with Args, Returns, Raises, Examples

## Quality Bar

### Code Quality
- All functions use @log_call decorator
- Docstrings required for public APIs
- Example usage in docstrings for major functions
- Follow snake_case (functions/variables), PascalCase (classes), UPPER_CASE (constants)

### Documentation Quality
- Example notebooks must execute successfully (they are tests)
- Notebook first cell must have H1 heading
- Documentation builds must succeed on both GitHub Pages and ReadTheDocs
- AGENTS.md files provide scoped guidance per directory

### Review Standards
- Changes that affect existing features require validation with example projects
- Breaking changes require documentation updates first
- All commits follow conventional commit messages (feat:, fix:, docs:, etc.)
