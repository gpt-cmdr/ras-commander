# Primitive Extraction and Notebook Development Workflow

**Purpose**: A systematic approach for extracting reusable primitives from production scripts into library modules and creating educational example notebooks.

---

## The Cycle: Production -> Primitives -> Notebooks

```
Production Scripts     ->     Library Primitives     ->     Example Notebooks
(task-specific code)         (commander libraries)         (published examples)
     |                              |                              |
     |------ Atomic Functions ------|                              |
     |                              |                              |
     |------ Full Workflows ----------------------------------------|
```

This cycle ensures that valuable patterns discovered in real projects become reusable library functions and educational examples. The key insight: **production scripts are a mine for general-purpose primitives**, but you must actively extract them or they stay buried in project-specific code.

---

## Phase 1: Identify Extraction Candidates

### Discovery Signals

Review production scripts for these indicators:

| Signal | What It Means |
|--------|---------------|
| Function called 3+ times across scripts | Duplication -- extract immediately |
| Generic parameters (no hardcoded paths) | Already close to primitive form |
| Complex logic solving a general problem | Deserves a library home |
| Copy-pasted between projects | Strong extraction candidate |

### Decision Framework: Extract or Leave?

**Extract** when the function:
- Solves a problem ANY user of the library might face
- Has clear inputs/outputs independent of the project
- Has been validated with real data in production
- Would reduce duplication if centralized

**Leave in the script** when the function:
- Contains project-specific business logic
- References domain knowledge not relevant to the library
- Is a thin wrapper around already-extracted primitives
- Would add complexity without broad reuse potential

```python
# EXTRACT: General pattern, reusable across any project
result = compare_hydrographs(flow_series_a, flow_series_b)

# LEAVE: Project-specific, not generalizable
def generate_project_title_page():  # Stays in script
```

### Agent Guidance for Discovery

Use **feature-dev:code-explorer** to scan production scripts and identify candidates. It excels at pattern recognition across files. Feed it the script directory and ask: "Which functions appear reusable beyond this project?"

Use **code-oracle-codex** only when you need deep analysis of whether a complex algorithm is truly general-purpose or subtly project-specific. The extended thinking helps for borderline cases.

---

## Phase 2: Extract Atomic Primitives

### Primitive Design Principles

**1. Pure Functions** -- No side effects, deterministic output.

```python
# GOOD: Pure function with clear contract
def compare_hydrographs(ts1: np.ndarray, ts2: np.ndarray,
                       truncate_to_shorter: bool = True) -> Dict[str, float]:
    """Compare two time series and return similarity metrics."""
    return {'correlation': r, 'nrmse_pct': nrmse, ...}

# BAD: Side effects, unclear output
def compare_and_log(ts1, ts2):
    result = compare(ts1, ts2)
    print(f"Correlation: {result}")  # Side effect
    self.results.append(result)      # State mutation
    return result
```

**2. Type Hints** -- Document expected inputs/outputs.

```python
def get_upstream_network(
    target: str,
    subbasins: pd.DataFrame,
    junctions: pd.DataFrame,
    diversions: pd.DataFrame
) -> Dict[str, List[str]]:
    """Build complete upstream network for a target element."""
```

**3. Comprehensive Docstrings** -- Args, Returns, Raises, Example.

```python
def compare_hydrographs(ts1, ts2, truncate_to_shorter=True):
    """
    Compare two hydrographs using correlation and NRMSE.

    Args:
        ts1: First time series (NumPy array or list)
        ts2: Second time series (NumPy array or list)
        truncate_to_shorter: If True, truncate both to shorter length.
                           If False, raise error on length mismatch.

    Returns:
        Dict with keys: correlation, nrmse_pct, peak_diff, peak_ratio

    Raises:
        ValueError: If lengths differ and truncate_to_shorter=False

    Example:
        >>> result = compare_hydrographs(np.array([0, 100, 0]), np.array([0, 102, 0]))
        >>> result['correlation']
        0.999987
    """
```

**4. Error Handling** -- Fail fast with informative messages.

```python
def get_xs_cut_lines(geom_file: Path) -> gpd.GeoDataFrame:
    """Extract cross-section cut lines from geometry file."""
    if not geom_file.exists():
        raise FileNotFoundError(f"Geometry file not found: {geom_file}")
    try:
        data = GeomParser._parse_geometry_file(geom_file)
    except Exception as e:
        raise ValueError(f"Failed to parse geometry: {e}")
    if not data['xs_lines']:
        raise ValueError("No cross-sections found in geometry file")
    return gpd.GeoDataFrame(data['xs_lines'], crs=None)
```

### Extraction Checklist

When moving a function from script to library:

- [ ] Remove hardcoded paths/project names (parameterize everything)
- [ ] Add type hints to all parameters and return value
- [ ] Write comprehensive docstring with Args/Returns/Raises/Example
- [ ] Add error handling for edge cases (empty data, type mismatches)
- [ ] Create unit test if logic is non-trivial
- [ ] Update module's `__all__` export list
- [ ] Commit: `feat(ModuleName): Add primitive_name`

### Agent Guidance for Extraction

Use **feature-dev:code-architect** to design the primitive's API. It helps with: Where should this live? What should the signature look like? How does it compose with existing primitives?

Use **feature-dev:code-explorer** to find all call sites of the function being extracted, ensuring you don't miss edge cases in how it's currently used.

---

## Phase 3: Create Example Notebooks

### The Two-Example Pattern

**Always include 2 examples** in each notebook. This is the single most important structural decision because it demonstrates:

1. **Generalizability**: The primitives work on different data, not just one lucky case
2. **Variation**: Different workflows, data sizes, or use cases
3. **Robustness**: Handles different data structures gracefully

Choose example pairs that contrast meaningfully:
- Small dataset + large dataset
- Simple workflow + complex workflow
- One analysis type + another analysis type

### Notebook Structure

```markdown
# Title and Purpose
Brief description of what this notebook demonstrates.

## What You'll Learn
- 4-6 bullet points listing primitives covered

## Prerequisites
- Software/data requirements, estimated runtime

## Example 1: [Pattern Name]
Configuration -> Step-by-step workflow -> Visualization

## Example 2: [Alternative Pattern]
Different configuration -> Demonstrate variation -> Compare results

## Key Takeaways
Summary, common pitfalls, references

## Adapting for Your Project
Template configuration for users to modify
```

### Cell Organization

| Cell Type | Purpose | Count |
|-----------|---------|-------|
| Markdown intro | Title, purpose, what you'll learn | 1 |
| Setup imports | Library imports, path configuration | 1 |
| Example 1 config | Project paths, parameters | 1 |
| Example 1 workflow | One primitive per cell | 3-6 |
| Example 1 visualization | Plots with clear labels | 1-2 |
| Example 2 config + workflow | Alternative pattern | 3-5 |
| Comparison/summary | Side-by-side results | 1 |
| Key takeaways | Patterns, pitfalls, references | 1 |

### Testing Before Publication

1. **Clear all outputs**: `jupyter nbconvert --clear-output --inplace notebook.ipynb`
2. **Execute end-to-end**: `jupyter nbconvert --to notebook --execute notebook.ipynb`
3. **Check for errors**: Scan executed notebook for error cells
4. **Verify file sizes**: Executed notebook should be 300-500 KB
5. **Test on clean environment**: Verify imports work for installed package users

```python
# Quick error check script
import json
nb = json.load(open("executed_notebook.ipynb"))
code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
errors = [c for c in code_cells if any(
    o.get("output_type") == "error" for o in c.get("outputs", [])
)]
print(f"Code cells: {len(code_cells)}, Errors: {len(errors)}")
```

---

## Phase 4: Integration and Documentation

### Commit Strategy

**Primitives** (library commits):
```
feat(ModuleName): Add primitive_name

- What it does
- Key capabilities
- Extracted from [workflow type]
```

**Notebooks** (example commits):
```
docs(examples): Add [workflow] notebook

- Demonstrates [primitives used]
- Example 1: [pattern] ([key metric])
- Example 2: [pattern] ([key metric])
```

### Documentation Updates

Update these for each extraction:
1. **Module docstring** at top of file (what the module provides, quick example)
2. **README examples section** (3-5 line usage snippet)
3. **CHANGELOG** (Added section with primitives and notebooks)

---

## Phase 5: Publication Decision Gate

Before publishing notebooks with real project data:

- [ ] Verify data permissions (is it public or publishable?)
- [ ] Check for sensitive information (internal paths, credentials, metadata)
- [ ] Generalize where needed (replace specifics with template patterns)
- [ ] Notebooks tested on clean environment
- [ ] All outputs cleared from committed notebooks
- [ ] Documentation updated (README, CHANGELOG)

**Strategy**: Keep notebooks gitignored until approved, then remove exclusions and commit.

---

## Patterns and Anti-Patterns

### Good Patterns

**Function Composition** -- Build complex operations from atomic primitives:
```python
def analyze_matching(u_file, dss_file):
    bcs = RasUnsteady.get_inline_hydrograph_boundaries(u_file)
    catalog = RasDss.get_catalog(dss_file)
    for bc in bcs:
        result = RasHydroCompare.compare_hydrographs(bc['values'], dss_flow)
```

**DataFrame Returns** -- Structured data, easy to filter/join:
```python
def get_subbasins(basin_file: Path) -> pd.DataFrame:
    """Return DataFrame with name, area, downstream columns."""
```

**Optional Parameters** -- Sensible defaults, opt-in complexity:
```python
def compare_hydrographs(ts1, ts2,
                       truncate_to_shorter: bool = True,
                       return_diagnostics: bool = False):
```

### Anti-Patterns

| Anti-Pattern | Problem | Fix |
|-------------|---------|-----|
| God Functions (500+ lines, mixed concerns) | Hard to reuse or test | Decompose into atomic primitives |
| Hidden State (global variables) | Unpredictable behavior | Pass all inputs as parameters |
| Inconsistent Return Types | Caller must handle multiple types | Always return the same type |
| Notebook-Coupled Code | Can't use outside Jupyter | Make primitives context-independent |

---

## Quality Metrics

### When Is a Primitive "Ready"?

A primitive is ready for the library when it meets ALL of these:

- **Reusable**: You can describe a second use case beyond the original project
- **Clear**: A developer understands the docstring without reading the implementation
- **Robust**: Handles edge cases (empty data, mismatched lengths, missing values)
- **Tested**: Validated in production with real data, ideally with a unit test

If you can't articulate a second use case, the function probably belongs in the script, not the library.

### Notebook Quality

- **Educational**: Teaches primitives through realistic examples
- **Complete**: Both examples execute without errors
- **Reproducible**: Works in a clean environment with published data
- **Readable**: Clear narrative flow connecting code cells

---

## Workflow Summary

```
1. IDENTIFY candidates in production scripts
   Look for: reusable functions, duplication, complex general-purpose logic

2. EXTRACT atomic primitives to library
   Apply: pure functions, type hints, docstrings, error handling

3. CREATE example notebooks
   Include: 2 contrasting examples, step-by-step workflow, visualizations

4. INTEGRATE documentation
   Update: module docstrings, README examples, CHANGELOG

5. PUBLISH after data/permission review
   Ensure: clean outputs, tested execution, documentation complete
```
