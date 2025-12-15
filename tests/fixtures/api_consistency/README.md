# API Consistency Test Fixtures

This directory contains example files for testing the API Consistency Auditor.

## Purpose

These fixtures provide:
1. **Valid examples** - Demonstrate correct patterns for each rule
2. **Invalid examples** - Demonstrate violations for testing detection
3. **Reference documentation** - Show what compliance looks like

## File Organization

### Rule 1: Static Classes

**Valid**: `valid_static_class.py`
- Correct use of `@staticmethod` decorator
- All methods properly decorated with `@log_call`
- Clear documentation stating "do not instantiate"
- Backward compatibility aliases provided

**Invalid**: `invalid_static_class.py`
- Missing `@staticmethod` decorator
- Has `__init__` method (should not exist in static classes)
- Missing `@log_call` decorators
- No backward compatibility aliases

### Rule 2: @log_call Decorator

**Valid**: `valid_log_call.py`
- All public functions/methods use `@log_call`
- Private functions correctly omit `@log_call` (start with `_`)
- Dunder methods correctly omit `@log_call`
- Properties correctly omit `@log_call`
- Decorator functions correctly omit `@log_call`

**Invalid**: `invalid_log_call.py`
- Public functions missing `@log_call`
- Public methods missing `@log_call`

### Rule 3: @standardize_input Decorator

**Valid**: `valid_standardize_input.py`
- Functions with `Path` parameters use `@standardize_input`
- Correct decorator stacking order
- Different file_type variants shown (plan_hdf, geom_hdf, etc.)
- Functions without Path parameters correctly omit decorator

**Invalid**: `invalid_standardize_input.py`
- Functions with `Path` parameters missing `@standardize_input`
- Manual Path conversion instead of using decorator

### Rule 4: No Instantiation

**Valid**: `valid_no_instantiation.py`
- Clear documentation: "do not instantiate"
- Some examples raise TypeError on `__init__`
- Distinction between static classes and instantiable classes

**Invalid**: `invalid_no_instantiation.py`
- Ambiguous documentation (unclear if static or instantiable)
- Static class with real `__init__` that stores state
- Mixed static and instance methods without clear purpose

### Rule 5: Backward Compatibility

**Valid**: `valid_backward_compat.py`
- Static class methods provided
- Backward compatibility aliases at module level
- Aliases documented with reference to static method
- All functions listed in `__all__`

**Invalid**: `invalid_backward_compat.py`
- Static class without backward compatibility aliases
- Aliases with wrong signatures
- Incomplete aliases (some functions missing)
- Aliases not listed in `__all__`

## Using These Fixtures

### In Tests

```python
import ast
from pathlib import Path

def test_detect_missing_log_call():
    """Test that auditor detects missing @log_call decorator."""
    fixture = Path(__file__).parent / 'fixtures/api_consistency/invalid_log_call.py'
    violations = auditor.check_file(fixture)

    # Should detect violations
    assert len(violations) > 0
    assert any(v.rule == 'log_call' for v in violations)

def test_accept_valid_static_class():
    """Test that auditor accepts valid static class."""
    fixture = Path(__file__).parent / 'fixtures/api_consistency/valid_static_class.py'
    violations = auditor.check_file(fixture)

    # Should have no violations
    assert len(violations) == 0
```

### Manual Review

Each fixture file can be opened and reviewed to understand what
constitutes a violation vs valid pattern.

## Fixture Maintenance

When adding new rules or patterns:

1. Create `valid_{rule_name}.py` with correct examples
2. Create `invalid_{rule_name}.py` with violation examples
3. Document violations with clear comments in invalid files
4. Update this README with new fixtures
5. Add test cases that use the new fixtures

## Key Patterns Demonstrated

### Decorator Order

Correct order (outer to inner):
```python
@staticmethod        # Outer (applied second)
@log_call            # Middle
@standardize_input   # Inner (applied first)
def my_function():
    pass
```

### Backward Compatibility

Old API (standalone functions):
```python
def process_data(value):
    return value * 2
```

New API (static class):
```python
class NewClass:
    @staticmethod
    @log_call
    def process_data(value):
        return value * 2

# Backward compatibility alias
def process_data(value):
    return NewClass.process_data(value)
```

### Documentation Clarity

**Static class** (do NOT instantiate):
```python
class StaticClass:
    """
    All methods are static and designed to be used without instantiation.
    Do not create instances of this class.
    """
```

**Instantiable class** (DO instantiate):
```python
class Worker:
    """
    Worker class for executing tasks.

    Create instances with specific configuration:
        worker = Worker(config)
    """
```

## See Also

- `../../.auditor.yaml` - Configuration listing exception classes
- `../../../agent_tasks/api-consistency-auditor/BASELINE_AUDIT.md` - Current violations
- `../../../.claude/rules/python/static-classes.md` - Static class pattern documentation
