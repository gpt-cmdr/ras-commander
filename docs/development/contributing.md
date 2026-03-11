# Contributing Guide

Thank you for your interest in contributing to ras-commander!

**Our philosophy: Don't Ask Me, Ask a GPT!** -- ras-commander was built with LLMs and welcomes contributions prepared with LLM agent assistance. See [CONTRIBUTING.md](../../CONTRIBUTING.md) at the repo root for the quick-start guide and self-review checklist, and [LLM-Driven Development](llm-development.md) for the full philosophy.

This page covers detailed development setup, coding patterns, and the complete style guide reference for LLM agents.

## Development Setup

### Clone and Install

```bash
# Fork and clone the repository
git clone https://github.com/YOUR_USERNAME/ras-commander.git
cd ras-commander

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# or: source venv/bin/activate  # Linux/Mac

# Install in editable mode
pip install -e .

# Install development dependencies
pip install pytest jupyter rasterio pyproj
```

### Using uv (Recommended)

```bash
uv venv .venv
.venv\Scripts\activate
uv pip install -e .
```

## Code Style

### Naming Conventions

| Element | Convention | Example |
|---------|------------|---------|
| Functions | snake_case | `compute_plan()` |
| Classes | PascalCase | `RasCmdr` |
| Constants | UPPER_CASE | `DEFAULT_VERSION` |
| Variables | snake_case | `plan_number` |

### Common Abbreviations

Use these consistently:

- `ras` - HEC-RAS
- `prj` - Project
- `geom` - Geometry
- `geompre` - Geometry Preprocessor
- `num` - Number
- `init` - Initialize
- `BC` - Boundary Condition
- `IC` - Initial Condition

### Function Naming

Start with verbs:
- `get_` - retrieve data
- `set_` - set values
- `compute_` - execute/calculate
- `clone_` - copy
- `clear_` - remove/reset
- `find_` - search
- `update_` - modify

### Docstrings

Use Google Python Style:

```python
def compute_plan(plan_number: str, num_cores: int = None) -> bool:
    """Execute a single HEC-RAS plan.

    Args:
        plan_number: Plan identifier (e.g., "01", "02")
        num_cores: Optional number of CPU cores

    Returns:
        True if execution succeeded, False otherwise

    Raises:
        FileNotFoundError: If plan file not found
        ValueError: If plan_number is invalid

    Examples:
        >>> success = RasCmdr.compute_plan("01")
        >>> print(f"Plan {'succeeded' if success else 'failed'}")
    """
```

### Decorators

Always use `@log_call` on public methods:

```python
from ras_commander.Decorators import log_call

class RasExample:
    @staticmethod
    @log_call
    def my_function(param: str) -> bool:
        """My function docstring."""
        pass
```

### Static Class Pattern

Use static methods (no instantiation):

```python
class RasExample:
    @staticmethod
    @log_call
    def do_something(param: str) -> bool:
        """Perform an operation."""
        return True

# Usage: RasExample.do_something("value")
# NOT: RasExample().do_something("value")
```

## Testing

### Test-Driven Development

RAS Commander uses HEC-RAS example projects for testing instead of mocks:

```python
from ras_commander import RasExamples, init_ras_project

# Extract example project
path = RasExamples.extract_project("Muncie")
init_ras_project(path, "6.5")

# Test your functionality
# ...
```

### Running Tests

```bash
# Run test scripts
python tests/test_ras_examples_initialization.py

# Run example notebooks (manual verification)
jupyter notebook examples/
```

## Pull Request Process

1. **Fork** the repository
2. **Create branch**: `git checkout -b feature/my-feature`
3. **Make changes** following style guide
4. **Test** with example notebooks
5. **Commit**: `git commit -m "Add feature X"`
6. **Push**: `git push origin feature/my-feature`
7. **Create PR** against `main` branch

### PR Checklist

- [ ] Code follows naming conventions
- [ ] Functions have docstrings with Args, Returns, Examples
- [ ] `@log_call` decorator on public methods
- [ ] Tested with HEC-RAS example project
- [ ] No hardcoded paths
- [ ] No new dependencies without justification

## Logging

Use logging, not print:

```python
from ras_commander import get_logger

logger = get_logger(__name__)

# In your function:
logger.info("Starting operation...")
logger.debug(f"Processing {count} items")
logger.warning("Unexpected condition")
logger.error(f"Operation failed: {error}")
```

## Error Handling

```python
def my_function(param: str) -> bool:
    """Function with proper error handling."""
    if not param:
        raise ValueError("param cannot be empty")

    try:
        # Operation that might fail
        result = risky_operation(param)
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return False

    return True
```

## LLM Agent Contributions: Step-by-Step

ras-commander encourages ALL contributions to be prepared with LLM agent assistance. The repository has machine-readable style rules that any LLM can consume.

### Step 1: Set Up and Launch Your Agent

```bash
# Clone and set up environment
git clone https://github.com/gpt-cmdr/ras-commander.git
cd ras-commander
uv venv .venv && uv pip install -e .

# Launch your preferred coding agent
claude          # Claude Code -- reads CLAUDE.md and .claude/rules/ automatically
codex           # OpenAI Codex CLI
aider           # Aider
cursor .        # Cursor IDE
gemini          # Google Gemini CLI
```

### Step 2: Have Your Agent Read the Style Rules

The style guide is stored as plain markdown files that any LLM can read:

```
# Tell your agent:
"Read the files in .claude/rules/python/ to understand the coding conventions."
"Read AGENTS.md in the root directory for codebase context."
```

**Claude Code** reads these automatically via `CLAUDE.md`. Other agents need explicit instructions to read the rule files.

### Step 3: Write Code Following Patterns

Your agent should follow the patterns described in the style rules. The key patterns are summarized in the Style Guide Reference below.

### Step 4: Self-Review Before PR

Run through the [LLM Self-Review Checklist](../../CONTRIBUTING.md#llm-self-review-checklist) in `CONTRIBUTING.md`. Your agent can verify each item programmatically.

### Step 5: Submit PR Using Template

The [PR template](../../.github/pull_request_template.md) includes the self-review checklist. Fill it out honestly -- it helps the maintainer review your PR quickly.

---

## Style Guide Reference for LLM Agents

These files contain the complete style rules. Have your agent read the ones relevant to your contribution:

### Python Patterns

| Rule File | What It Covers |
|-----------|---------------|
| `.claude/rules/python/static-classes.md` | No instantiation pattern -- call methods directly on class |
| `.claude/rules/python/decorators.md` | `@staticmethod` then `@log_call` stacking order |
| `.claude/rules/python/naming-conventions.md` | `snake_case` functions, `PascalCase` classes, approved abbreviations |
| `.claude/rules/python/path-handling.md` | `pathlib.Path` internally, accept both `str` and `Path` |
| `.claude/rules/python/dataframe-first-principle.md` | Use `ras.plan_df` for file paths, never glob patterns |
| `.claude/rules/python/error-handling.md` | Logging, exceptions, `LoggingConfig` |
| `.claude/rules/python/import-patterns.md` | Flexible imports for dev vs installed package |
| `.claude/rules/python/ras-commander-patterns.md` | `ras_object` parameter discipline for multi-project support |

### HEC-RAS Domain

| Rule File | What It Covers |
|-----------|---------------|
| `.claude/rules/hec-ras/execution.md` | `RasCmdr.compute_plan()`, parallel modes, smart skip |
| `.claude/rules/hec-ras/hdf-files.md` | HDF results extraction, steady vs unsteady detection |
| `.claude/rules/hec-ras/geometry.md` | Fixed-width parsing, 500-point limit, bank stations |
| `.claude/rules/hec-ras/dss-files.md` | DSS pathname validation, lazy-loaded Java bridge |
| `.claude/rules/hec-ras/remote.md` | `session_id=2`, Group Policy, Registry configuration |
| `.claude/rules/hec-ras/usgs.md` | Gauge discovery, data retrieval, boundary generation |
| `.claude/rules/hec-ras/precipitation.md` | AORC historic data, Atlas 14 design storms |

### Testing

| Rule File | What It Covers |
|-----------|---------------|
| `.claude/rules/testing/tdd-approach.md` | Test with real HEC-RAS projects, not mocks |
| `.claude/rules/testing/environment-management.md` | uv for agents, Anaconda for notebooks |

### Documentation

| Rule File | What It Covers |
|-----------|---------------|
| `.claude/rules/documentation/notebook-standards.md` | H1 title required, run before commit |
| `.claude/rules/documentation/mkdocs-config.md` | ReadTheDocs strips symlinks, use `cp` not `ln -s` |

---

## Using the API Consistency Auditor

For PRs that add or modify public API methods, the API consistency auditor defines 5 critical rules. See `.claude/agents/api-consistency-auditor.md` for the complete specification.

### The 5 Critical Rules

**Rule 1: Static Class Pattern**

```python
# WRONG -- don't instantiate
class MyAnalyzer:
    def __init__(self):
        self.data = []

# RIGHT -- static methods
class MyAnalyzer:
    @staticmethod
    @log_call
    def analyze(file_path):
        ...
```

**Rule 2: @log_call on All Public Methods**

```python
# WRONG -- missing decorator
def get_results(plan_number):
    ...

# RIGHT -- decorated
@staticmethod
@log_call
def get_results(plan_number):
    ...
```

**Rule 3: @staticmethod on Static Class Methods**

```python
# WRONG -- missing @staticmethod
class RasExample:
    @log_call
    def my_method(param):  # Looks like instance method
        ...

# RIGHT -- both decorators, correct order
class RasExample:
    @staticmethod  # Outer
    @log_call      # Inner
    def my_method(param):
        ...
```

**Rule 4: Parameter Naming**

```python
# WRONG
def get_data(plan_num, geom_path, ras=None):
    ...

# RIGHT
def get_data(plan_number, geom_file, ras_object=None):
    ...
```

**Rule 5: Path Handling**

```python
# WRONG -- rigid typing
def read_file(filepath: Path):
    ...

# RIGHT -- flexible, converts internally
def read_file(filepath):
    filepath = Path(filepath)  # Accepts str or Path
    ...
```

---

## Questions?

- **Open an issue** for questions, bug reports, or feature requests
- **Read `AGENTS.md` files** in each subpackage for codebase context
- **Check `examples/`** for working patterns and usage demonstrations
- **Your LLM agent can explore the codebase** -- that's exactly what it's designed for
