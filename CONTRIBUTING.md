# Contributing to ras-commander

## Our Philosophy: Don't Ask Me, Ask a GPT!

ras-commander was **built by LLMs**, is **designed for LLM workflows**, and **welcomes contributions prepared with LLM agent assistance**.

We encourage ALL contributors to use an LLM coding agent when preparing pull requests. The repository contains comprehensive, machine-readable style rules in `.claude/rules/` that any LLM can read and follow. When your agent reads these rules before writing code, your PR becomes trivially easy to review.

**Why this works**: An LLM-reviewed PR that follows the style guide takes 5 minutes to review. A PR that ignores the style guide takes 50 minutes. Help us merge your code fast -- load the rules.

**Any agent works**: [Claude Code](https://claude.ai/code), [Codex CLI](https://github.com/openai/codex), [Aider](https://aider.chat), [Cursor](https://cursor.sh), [Gemini CLI](https://github.com/google-gemini/gemini-cli), or any other LLM coding tool. The rules are plain markdown -- every LLM can read them.

---

## Quick Start

```bash
# 1. Fork and clone
git clone https://github.com/YOUR_USERNAME/ras-commander.git
cd ras-commander

# 2. Set up environment
uv venv .venv && uv pip install -e .

# 3. Launch your preferred coding agent
claude          # Claude Code
codex           # OpenAI Codex CLI
aider           # Aider
cursor .        # Cursor IDE
```

Your agent will find `AGENTS.md` and `CLAUDE.md` files throughout the repo that provide codebase context. Have it read the style rules in `.claude/rules/` before writing code.

---

## The Self-Review Contract

This is what makes LLM contributions welcome rather than burdensome:

1. **Before writing code**: Your agent reads the relevant style rules
2. **Before submitting**: You run through the Self-Review Checklist below
3. **When opening the PR**: The PR template includes the checklist

If your agent followed the rules, your PR is easy to review and fast to merge. If it didn't, we'll ask you to re-run with the rules loaded. This isn't gatekeeping -- it's how we keep velocity high for everyone.

---

## LLM Self-Review Checklist

Have your agent confirm each item before opening a PR.

### Style Compliance

| Rule | File to Read | What It Means |
|------|-------------|---------------|
| Static class pattern | `.claude/rules/python/static-classes.md` | No `__init__` unless legitimately stateful. Call methods directly: `RasCmdr.compute_plan("01")` |
| Decorator stacking | `.claude/rules/python/decorators.md` | `@staticmethod` then `@log_call` on all public methods |
| Naming conventions | `.claude/rules/python/naming-conventions.md` | `snake_case` functions, `PascalCase` classes, approved abbreviations |
| Path handling | `.claude/rules/python/path-handling.md` | `pathlib.Path` internally, accept both `str` and `Path` in parameters |
| DataFrame-first | `.claude/rules/python/dataframe-first-principle.md` | Use `ras.plan_df` for file paths, never glob patterns |

### Code Quality

- [ ] All public functions have Google-style docstrings (Args, Returns, Raises)
- [ ] Tested with a real HEC-RAS project via `RasExamples.extract_project()` -- no mocks or synthetic data
- [ ] No hardcoded file paths -- parameters accept `Union[Path, str]`
- [ ] Uses `logging` (via `@log_call` or `logger`), not `print()`
- [ ] Error handling with appropriate exceptions and informative messages

### For API Changes

- [ ] `ras_object=None` parameter included for multi-project support
- [ ] Standard parameter names: `plan_number` (not `plan_num`), `geom_file` (not `geometry_path`)
- [ ] Path parameters use `@standardize_input` or manual `Path()` conversion
- [ ] Return types are consistent (DataFrames for tabular data, Path for file references)
- [ ] All 5 API consistency auditor rules followed (see below)

### For Example Notebooks

- [ ] First cell is markdown with H1 title (`# Descriptive Title`)
- [ ] Uses `RasExamples.extract_project()` for reproducible data
- [ ] Includes development mode toggle cell (`USE_LOCAL_SOURCE`)
- [ ] All cells execute without error

---

## API Changes: The Consistency Auditor

Any PR that adds or modifies public API methods must follow these 5 rules. See `.claude/agents/api-consistency-auditor.md` for the complete specification.

| # | Rule | Violation Example | Correct Pattern |
|---|------|-------------------|-----------------|
| 1 | **Static class pattern** | `class Foo:` with `__init__` | Static methods, no instantiation |
| 2 | **@log_call required** | Public method without decorator | `@log_call` on every public method |
| 3 | **@staticmethod required** | Method in static class without it | `@staticmethod` above `@log_call` |
| 4 | **Parameter naming** | `plan_num`, missing `ras_object` | `plan_number`, `ras_object=None` |
| 5 | **Path handling** | `filepath: Path` (rigid) | `filepath: Union[Path, str]` |

### Gold Standard Template

Copy this pattern for new classes:

```python
from ras_commander.logging_config import log_call
from pathlib import Path
from typing import Union

class MyNewAnalyzer:
    """Analyzer for [domain] data. Static class -- do not instantiate."""

    @staticmethod
    @log_call
    def analyze_data(
        file_path: Union[Path, str],
        plan_number: str = "01",
        ras_object=None
    ):
        """Analyze data from HEC-RAS output.

        Args:
            file_path: Path to input file (str or Path)
            plan_number: Plan identifier (e.g., "01")
            ras_object: Optional RasPrj context for multi-project support

        Returns:
            pd.DataFrame: Analysis results with columns [col1, col2, ...]

        Raises:
            FileNotFoundError: If file_path does not exist
            ValueError: If plan_number is invalid
        """
        file_path = Path(file_path)
        _ras = ras_object if ras_object is not None else ras
        # Implementation...
```

---

## What We Accept

- Bug fixes with test validation
- New HDF extraction methods (`ras_commander/hdf/`)
- Geometry parsing capabilities (`ras_commander/geom/`)
- USGS integration enhancements (`ras_commander/usgs/`)
- Precipitation and hydrology methods (`ras_commander/precip/`)
- Remote execution worker types (`ras_commander/remote/`)
- Example notebooks (`examples/`)
- Documentation improvements
- Performance optimizations

## What We Don't Accept

- Changes that break the static class pattern without prior discussion
- Mock-based tests (use real HEC-RAS projects via `RasExamples`)
- New dependencies without clear justification
- Changes that bypass professional review pathways (this is safety-critical flood modeling software)

---

## Development Setup

See [docs/development/contributing.md](docs/development/contributing.md) for detailed setup instructions, including:

- Environment management (uv, Anaconda)
- Running tests with example projects
- Notebook testing workflow
- Building documentation locally

---

## Commit Messages

Use conventional commit format with scope:

```
feat(HdfMesh): Add cell velocity extraction method
fix(GeomXS): Handle 500-point cross sections correctly
docs(examples): Add channel capacity analysis notebook
refactor(RasCmdr): Simplify smart skip logic
```

When your contribution was prepared with LLM assistance, include attribution:

```
feat(HdfMesh): Add cell velocity extraction method

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## Community Standards

### Respect for Maintainer Time

The entire point of LLM self-review is to reduce review burden. A well-prepared PR is a gift to the maintainer. A poorly prepared PR -- regardless of whether a human or LLM wrote it -- wastes everyone's time.

### Professional Context

ras-commander is used for **flood modeling and infrastructure design**. Professional engineers use this library to make decisions that affect public safety. All contributions are reviewed with this context in mind.

### LLM Forward Philosophy

This project follows the [LLM Forward](https://clbengineering.com/llm-forward) philosophy: professional responsibility first, LLMs positioned forward to accelerate engineering insight. See [docs/development/llm-development.md](docs/development/llm-development.md) for the complete framework.

### Conduct

- Be respectful and professional in all interactions
- Focus on engineering quality and code correctness
- Welcome contributors of all experience levels
- Judge contributions on merit, not on what tool was used to write them

---

## Getting Help

- **Open an issue** for questions, bug reports, or feature requests
- **Read `AGENTS.md` files** in each subpackage for codebase context
- **Check `examples/`** for working patterns and usage demonstrations
- **Your LLM agent can explore the codebase** -- that's exactly what it's designed for

---

*ras-commander is maintained by [CLB Engineering Corporation](https://clbengineering.com/). Licensed under MIT.*
