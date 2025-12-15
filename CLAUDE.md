# CLAUDE.md

This file provides strategic guidance to Claude Code when working with ras-commander. **Detailed patterns are in `.claude/rules/`** (auto-loaded).

## AGENTS.md Standard

This repository uses the AGENTS.md standard alongside CLAUDE.md:
- `AGENTS.md` files provide scoped guidance (folder and subfolders)
- More deeply nested AGENTS.md files override parent guidance
- Always read both CLAUDE.md and AGENTS.md for working directory

**Key locations**:
- `/AGENTS.md` (root - library overview)
- `/ras_commander/AGENTS.md` (library API)
- `/ras_commander/remote/AGENTS.md` (remote execution)
- `/examples/AGENTS.md` (notebook index)

## Project Overview

**ras-commander** is a Python library for automating HEC-RAS (Hydrologic Engineering Center's River Analysis System) operations. Provides comprehensive API for project interaction, simulation execution, and HDF results processing.

**Core Capabilities**:
- Execute HEC-RAS plans (single, parallel, distributed remote)
- Parse and modify project files (geometry, plans, unsteady flow)
- Extract results from HDF files (steady and unsteady)
- Integrate USGS gauge data for validation and boundary conditions
- Automate geometry repair (RasFixit module)
- Real-time execution monitoring with callbacks

**Target Users**: Hydraulic engineers, researchers, automation developers

## Platform Context: You Are on a Windows Host

**CRITICAL ENVIRONMENT NOTICE**:

This repository is **almost always run on Windows hosts**. HEC-RAS is a **Windows-based modeling program** that requires Windows for execution.

**Key Implications**:
- **Default Platform**: Assume Windows unless explicitly stated otherwise
- **Path Handling**: Use `pathlib.Path` for cross-platform compatibility (supports both Windows `\` and Unix `/` separators)
- **HEC-RAS Availability**: HEC-RAS.exe only runs on Windows (no macOS/Linux native support)
- **Script Execution**: Bash scripts use Git Bash or WSL on Windows
- **File Paths**: Accept both forward slashes `/` and backslashes `\` in paths (Path handles both)

**Cross-Platform Compatibility**:
- ✅ **DO**: Use `pathlib.Path` for all file operations
- ✅ **DO**: Accept forward slashes in paths (works on Windows)
- ✅ **DO**: Test critical functionality on Linux/macOS where possible (library code should work)
- ❌ **DON'T**: Hardcode backslash separators (use Path composition with `/` operator)
- ❌ **DON'T**: Assume Unix-only commands (prefer cross-platform tools)
- ❌ **DON'T**: Require HEC-RAS for library-only functionality (separate concerns)

**Example Cross-Platform Path Handling**:
```python
from pathlib import Path

# ✅ CORRECT - works on all platforms
project_folder = Path("C:/Projects/MyModel")  # Windows with forward slashes
geom_file = project_folder / "geometry.g01"   # Path composition

# ❌ INCORRECT - Windows-specific
project_folder = "C:\\Projects\\MyModel"  # Hardcoded backslashes
geom_file = project_folder + "\\geometry.g01"  # String concatenation
```

**HEC-RAS Execution Context**:
- HEC-RAS installation: Typically `C:/Program Files/HEC/HEC-RAS/<version>/Ras.exe`
- Project files: Can be anywhere on Windows filesystem or network shares (UNC paths)
- Remote execution: Uses PsExec (Windows → Windows) or Docker (platform-agnostic)

## LLM Forward Development Philosophy

This repository embodies **LLM Forward** engineering principles:

**Core Tenets**:
1. **Professional Responsibility First**: Public safety, ethics, and professional licensure remain paramount
2. **LLMs Forward (Not First)**: Technology accelerates engineering insight without replacing professional judgment
3. **Multi-Level Verifiability**: HEC-RAS projects (GUI review) + visual outputs (plots/figures) + code audit trails
4. **Human-in-the-Loop**: Multiple review pathways - traditional engineering review, visual inspection, and code review
5. **Domain Expertise Accelerated**: H&H knowledge translated efficiently into working code
6. **Focus on LLMs Specifically**: Not general AI/ML - LLMs excel at code generation and documentation

**When contributing with AI assistance**:
- ✅ Test with real HEC-RAS projects using `RasExamples.extract_project()`
- ✅ Create reviewable HEC-RAS projects with descriptive plan titles/descriptions; models openable in GUI
- ✅ Generate visual outputs (plots/figures) at each calculation step for visual verification
- ✅ Maintain audit trails: @log_call decorators, comprehensive logging, self-documenting scripts
- ✅ Enable multiple review pathways: traditional engineering review + visual inspection + code review
- ✅ Follow static class patterns for predictable, reviewable code
- ❌ Don't use synthetic test data or mock objects
- ❌ Don't create black-box implementations that bypass professional review

**Framework Origin**: The LLM Forward approach was formalized by [CLB Engineering Corporation](https://clbengineering.com/).

**Learn More**: [Engineering with LLMs](https://engineeringwithllms.info)

## Development Guidance - Navigate to Rules

**For detailed patterns, see topic-specific rules** (auto-loaded from `.claude/rules/`):

### Python Coding Patterns

See `.claude/rules/python/`:
- **static-classes.md** - No instantiation pattern (RasCmdr, Hdf*, Ras*)
- **decorators.md** - @log_call, @staticmethod, @standardize_input
- **path-handling.md** - pathlib.Path for all operations
- **error-handling.md** - LoggingConfig, exception patterns
- **naming-conventions.md** - snake_case, PascalCase, approved abbreviations
- **import-patterns.md** - Flexible try/except for dev vs installed

### HEC-RAS Domain Knowledge

See `.claude/rules/hec-ras/`:
- **remote.md** - CRITICAL: session_id=2, Group Policy, Registry config
- **execution.md** - RasCmdr.compute_plan(), parallel modes
- More domain files to be added (hdf-files.md, geometry.md, etc.)

### Testing & Documentation

See `.claude/rules/testing/`:
- **tdd-approach.md** - Test with real HEC-RAS projects (RasExamples), not mocks

See `.claude/rules/documentation/`:
- **mkdocs-config.md** - CRITICAL: ReadTheDocs strips symlinks, use cp not ln -s
- **notebook-standards.md** - H1 title required, run before commit

## Architecture Overview

### Core Execution Classes

**Static classes** (call directly, no instantiation):
- `RasCmdr` - HEC-RAS plan execution (compute_plan, compute_parallel)
- `RasControl` - Legacy COM interface (HEC-RAS 3.x-5.x)
- `HdfResultsPlan` - Extract results from HDF files
- `RasGeometry` - Parse geometry files (cross sections, storage, structures)
- `RasUsgsCore` - USGS gauge data integration
- See **static-classes.md** for complete list and patterns

**Instantiated classes** (exceptions to static pattern):
- `RasPrj` - Project management (multiple projects)
- `ras` - Global project object
- Workers (PsexecWorker, LocalWorker, DockerWorker)
- Callbacks (ConsoleCallback, FileLoggerCallback, ProgressBarCallback)

### Execution Modes

1. **Single Plan**: `RasCmdr.compute_plan(plan_number, ...)`
2. **Parallel Local**: `RasCmdr.compute_parallel(plans_to_run, ...)`
3. **Sequential Test**: `RasCmdr.compute_test_mode(plans_to_run, ...)`
4. **Distributed Remote**: `compute_parallel_remote(plans_to_run, workers, ...)`

See **execution.md** for detailed parameters and examples.

### Critical Patterns

**Static Class Pattern**:
```python
# ✅ Correct - call directly
from ras_commander import RasCmdr
RasCmdr.compute_plan("01")

# ❌ Wrong - don't instantiate
cmdr = RasCmdr()  # Error!
```

**Remote Execution Pattern**:
```python
# ✅ Correct - session-based execution
worker = init_ras_worker(
    worker_type='psexec',
    session_id=2,  # CRITICAL for GUI apps
    ...
)

# ❌ Wrong - system account fails for HEC-RAS
worker = init_ras_worker(system_account=True)  # Silent failure!
```

See **remote.md** for complete remote configuration requirements.

## Development Environment

### Environment Management

**Agent Scripts and Tools**: Use `uv` and `python` for all agent scripts, development tools, and utilities.

**Jupyter Notebook Testing**: Use dedicated Anaconda environments:
- **`rascmdr_local`** - Test with local development version (when making code changes)
- **`RasCommander`** - Test with published pip package (user experience validation)

See **`.claude/rules/testing/environment-management.md`** for complete setup and usage instructions.

### Build and Install

```bash
# Build package
python setup.py sdist bdist_wheel

# Install for development (editable mode)
pip install -e .

# Install from PyPI
pip install ras-commander
```

### Testing Environments Setup

**For agent scripts (using uv)**:
```bash
# Create virtual environment
uv venv .venv

# Activate and install
.venv\Scripts\activate  # Windows
pip install -e .
```

**For Jupyter notebooks (using Anaconda)**:
```bash
# Local development testing
conda create -n rascmdr_local python=3.13
conda activate rascmdr_local
pip install -e .
pip install jupyter ipykernel
python -m ipykernel install --user --name rascmdr_local

# Published package testing (standard user environment)
conda create -n RasCommander python=3.13
conda activate RasCommander
pip install ras-commander
pip install jupyter ipykernel
python -m ipykernel install --user --name RasCommander
```

### Dependencies

**Python**: Requires 3.10+

**Core packages**: h5py, numpy, pandas, geopandas, matplotlib, shapely, scipy, xarray, tqdm, requests, rasterstats, rtree

**Optional**:
- `dataretrieval` - USGS gauge data integration
- `paramiko`, `docker` - Remote execution via SSH/Docker
- `tkinterdnd2` - GUI drag-and-drop

### Testing Strategy

Uses **Test Driven Development with real HEC-RAS projects** instead of mocks.

```python
from ras_commander import RasExamples, init_ras_project, RasCmdr

# Extract example project
path = RasExamples.extract_project("Muncie")

# Initialize and execute
init_ras_project(path, "6.5")
RasCmdr.compute_plan("01")
```

See **`.claude/rules/testing/tdd-approach.md`** for complete testing patterns and **`.claude/rules/testing/environment-management.md`** for environment details.

## Repository Structure

```
ras-commander/
├── ras_commander/          # Main library code
│   ├── AGENTS.md           # Library-specific guidance
│   ├── core.py             # Core execution
│   ├── hdf/                # HDF results processing
│   ├── remote/             # Remote execution workers
│   │   └── AGENTS.md       # Remote-specific guidance
│   ├── usgs/               # USGS gauge integration
│   └── ...
├── .claude/                # Claude Code framework
│   ├── rules/              # Auto-loaded topic rules
│   │   ├── python/         # Python patterns
│   │   ├── hec-ras/        # HEC-RAS domain knowledge
│   │   ├── testing/        # Testing approaches
│   │   └── documentation/  # Doc standards
│   ├── skills/             # Library workflow skills
│   └── agents/          # Specialist definitions
├── ras_agents/             # Production agent reference data (tracked)
│   ├── README.md           # Agent organization guidelines
│   └── decompilation-agent/# .NET assembly reverse engineering
├── ras_skills/             # Production domain skills
├── examples/               # Example notebooks
│   ├── AGENTS.md           # Notebook index
│   └── *.ipynb             # Jupyter notebooks
├── agent_tasks/            # Multi-session task coordination
│   ├── .agent/             # Memory system (STATE, BACKLOG, PROGRESS)
│   └── README.md           # Complete memory system docs
├── feature_dev_notes/      # Experimental space (gitignored, NOT for agent reference)
│   └── CLAUDE.md           # Feature dev guidance
├── docs/                   # Documentation source
├── tests/                  # Test scripts
└── CLAUDE.md               # This file (strategic guidance)
```

## Agent Coordination for Multi-Session Tasks

For complex tasks spanning multiple sessions, use **`agent_tasks/`** memory system:

**Every session start**: Read `agent_tasks/.agent/STATE.md`, PROGRESS.md, BACKLOG.md

**Every session end**: Update STATE.md, append to PROGRESS.md, update BACKLOG.md

See `agent_tasks/README.md` for complete documentation.

## Documentation

### Dual-Platform Deployment

- **GitHub Pages**: https://gpt-cmdr.github.io/ras-commander/
- **ReadTheDocs**: https://ras-commander.readthedocs.io

**CRITICAL**: ReadTheDocs strips symlinks during deployment. Always use `cp -r` instead of `ln -s` in `.readthedocs.yaml`.

See **mkdocs-config.md** for platform-specific configuration.

### Example Notebooks

All notebooks in `examples/` serve dual purpose:
1. User documentation (how to use library)
2. Functional tests (validate library works)

**Requirements**:
- First cell MUST be markdown with H1 title
- Use RasExamples for reproducible projects
- Run all cells before committing (if execute: false)

See **notebook-standards.md** for complete guidelines.

## Key Development Principles

1. **Use Real HEC-RAS Projects**: Test with RasExamples, not mocks
2. **Static Classes**: Most classes use static methods (no instantiation)
3. **pathlib.Path**: Use Path for all file operations, accept str or Path in parameters
4. **@log_call Decorator**: All public functions should use for automatic logging
5. **Session-Based Remote Execution**: HEC-RAS requires session_id, not system_account
6. **Progressive Disclosure**: Details in .claude/rules/, strategic content in CLAUDE.md

## Quick Reference

### Common Operations

```python
from ras_commander import init_ras_project, RasCmdr, RasExamples
from ras_commander.hdf import HdfResultsPlan

# Extract example project
path = RasExamples.extract_project("Muncie")

# Initialize
init_ras_project(path, "6.5")

# Execute plan
RasCmdr.compute_plan("01")

# Extract results
hdf = HdfResultsPlan(path / "Muncie.p01.hdf")
wse = hdf.get_wse(time_index=-1)
```

### Common Pitfalls

- ❌ Don't instantiate static classes: `RasCmdr()` is wrong
- ❌ Don't use system_account for remote HEC-RAS execution
- ❌ Don't use string concatenation for paths (use Path objects)
- ❌ Don't forget @log_call decorator on new functions
- ❌ Don't use mocks for HEC-RAS testing (use RasExamples)
- ❌ Don't use symlinks in ReadTheDocs builds (gets stripped)

## See Also

**For detailed guidance**:
- Python patterns: `.claude/rules/python/`
- HEC-RAS domain: `.claude/rules/hec-ras/`
- Testing: `.claude/rules/testing/`
- Documentation: `.claude/rules/documentation/`
- Multi-session coordination: `agent_tasks/README.md`
- Feature development: `feature_dev_notes/CLAUDE.md`
- Subpackage context: `ras_commander/*/AGENTS.md`

---

**Note**: This file provides strategic overview. Detailed patterns auto-load from `.claude/rules/`. For subpackage-specific guidance, see AGENTS.md files in relevant directories.
