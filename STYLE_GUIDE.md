# RAS Commander (ras-commander) Style Guide

## Table of Contents
1. [Naming Conventions](#1-naming-conventions)
2. [Code Structure and Organization](#2-code-structure-and-organization)
3. [Documentation and Comments](#3-documentation-and-comments)
4. [Code Style](#4-code-style)
5. [Error Handling](#5-error-handling)
6. [Testing](#6-testing)
7. [Version Control](#7-version-control)
8. [Type Hinting](#8-type-hinting)
9. [Project-Specific Conventions](#9-project-specific-conventions)
10. [Inheritance](#10-inheritance)

## 1. Naming Conventions

### 1.1 General Rules
- Use `snake_case` for all function and variable names
- Use `PascalCase` for class names
- Use `UPPER_CASE` for constants

### 1.2 Library-Specific Naming
- Informal Name: RAS Commander
- Package Name and GitHub Library Name: ras-commander (with a hyphen)
- Import Name: ras_commander (with an underscore)
- Main Class of functions for HEC-RAS Automation: RasCmdr

### 1.3 Function Naming
- Start function names with a verb describing the action
- Use clear, descriptive names
- Common verbs and their uses:
  - `get_`: retrieve data
  - `set_`: set values or properties
  - `compute_`: execute or calculate
  - `clone_`: copy
  - `clear_`: remove or reset data
  - `find_`: search
  - `update_`: modify existing data

### 1.4 Abbreviations
Use the following abbreviations consistently throughout the codebase:

- ras: HEC-RAS
- prj: Project
- geom: Geometry
- pre: Preprocessor
- geompre: Geometry Preprocessor
- num: Number
- init: Initialize
- XS: Cross Section
- DSS: Data Storage System
- GIS: Geographic Information System
- BC: Boundary Condition
- IC: Initial Condition
- TW: Tailwater

Use these abbreviations in lowercase for function and variable names (e.g., `geom`, not `Geom` or `GEOM`).

### 1.5 Class Naming
- Use `PascalCase` for class names (e.g., `FileOperations`, `PlanOperations`, `RasCmdr`)
- Class names should be nouns or noun phrases

### 1.6 Variable Naming
- Use descriptive names indicating purpose or content
- Prefix boolean variables with `is_`, `has_`, or similar

## 2. Code Structure and Organization

### 2.1 File Organization
- Group related functions into appropriate classes
- Keep each class in its own file, named after the class

### 2.2 Function Organization
- Order functions logically within a class
- Place common or important functions at the top of the class

### 2.3 Module Structure
- Use the following order for module contents:
  1. Module-level docstring
  2. Imports (grouped and ordered)
  3. Constants
  4. Classes
  5. Functions

## 3. Documentation and Comments

### 3.1 Docstrings
- Use docstrings for all modules, classes, methods, and functions
- Follow Google Python Style Guide format
- Include parameters, return values, and a brief description
- For complex functions, include examples in the docstring

### 3.2 Comments
- Use inline comments sparingly, only for complex logic
- Keep comments up-to-date with code changes
- Use TODO comments for future work, formatted as: `# TODO: description`

## 4. Code Style

### 4.1 Imports
- Order imports as follows:
  1. Standard library imports
  2. Third-party library imports
  3. Local application imports
- Use absolute imports
- Use `import ras_commander as ras` for shortening the library name in examples

### 4.2 Whitespace
- Follow PEP 8 guidelines
- Use 4 spaces for indentation (no tabs)
- Use blank lines to separate logical sections of code

### 4.3 Line Length
- Limit lines to 79 characters for code, 72 for comments and docstrings
- Use parentheses for line continuation in long expressions

## 5. Error Handling

- Use explicit exception handling with try/except blocks
- Raise custom exceptions when appropriate, with descriptive messages
- Use logging for error reporting and debugging information

## 6. Testing

- Write unit tests for all functions and methods
- Use the `unittest` framework
- Aim for high test coverage, especially for critical functionality
- Include tests for both single-project and multi-project scenarios

## 7. Version Control

- Use meaningful commit messages that clearly describe the changes made
- Create feature branches for new features or significant changes
- Submit pull requests for code review before merging into the main branch

## 8. Type Hinting

- Use type hints for function parameters and return values
- Use the `typing` module for complex types (e.g., `List`, `Dict`, `Optional`)
- Include type hints in function signatures and docstrings

## 9. Project-Specific Conventions

### 9.1 RAS Instance Handling
- Design functions to accept an optional `ras_object` parameter:
  ```python
  def some_function(param1, param2, ras_object=None):
      ras_obj = ras_object or ras
      ras_obj.check_initialized()
      # Function implementation
  ```

### 9.2 File Path Handling
- Use `pathlib.Path` for file and directory path manipulations
- Convert string paths to Path objects at the beginning of functions

### 9.3 DataFrame Handling
- Use pandas for data manipulation and storage where appropriate
- Prefer method chaining for pandas operations to improve readability

### 9.4 Parallel Execution
- Follow the guidelines in the "Benchmarking is All You Need" blog post for optimal core usage in parallel plan execution

### 9.5 Function Return Values
- Prefer returning meaningful values over modifying global state
- Use tuple returns for multiple values instead of modifying input parameters

Remember, consistency is key. When in doubt, prioritize readability and clarity in your code. Always consider the maintainability and extensibility of the codebase when making design decisions.

## 10. Inheritance

### 10.1 General Principles

- Prioritize composition over inheritance when appropriate.
- Design base classes for extension.
- Clearly document the public API and subclass API using docstrings.

### 10.2 Naming Conventions

- Public API: No leading underscores.
- Subclass API: Single leading underscore (e.g., `_prepare_for_execution`).
- Internal attributes and methods: Single leading underscore.
- Name mangling (double leading underscores): Use sparingly and document the decision clearly.

### 10.3 Template Method Pattern

Consider using the template method pattern in base classes to define a high-level algorithm structure. Subclasses can then override specific steps to customize behavior.

### 10.4 Dataframe Access Control

Use properties to control access and modification of dataframes, providing a controlled interface for subclasses.