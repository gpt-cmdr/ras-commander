# RAS-Commander LLM Knowledge Base Generator

## Overview

This README explains the `generate_llm_knowledge_bases.py` script, which creates structured knowledge bases from the RAS-Commander codebase. These knowledge bases are designed to be used with Large Language Models (LLMs) like GPT-4 and Claude to provide context-aware assistance with RAS-Commander operations.

## Purpose

The script serves several key purposes:

1. **AI Context Creation**: Generates specialized text files that can be uploaded to LLMs as context, enabling more accurate and relevant responses about RAS-Commander.

2. **Documentation Extraction**: Automatically extracts and organizes documentation from the codebase in various formats and detail levels.

3. **Code Knowledge Summarization**: Creates filtered views of the codebase that focus on specific aspects (implementation details, function signatures, etc.).

4. **Size Optimization**: Produces knowledge bases that fit within LLM context windows by excluding unnecessary files and formatting appropriately.

## Generated Output Files

The script creates the following knowledge base files in the `llm_knowledge_bases` directory:

1. **`ras-commander_fullrepo.txt`**:
   - Comprehensive summary of all relevant project files
   - Includes content and structure of the entire codebase
   - Excludes files/folders specified in `OMIT_FOLDERS` and `OMIT_FILES`

2. **`ras_commander_classes_and_functions_only.txt`**:
   - Complete code from the `ras_commander` folder
   - Includes all classes, functions, and their implementations
   - Focuses on core library code with all implementation details

3. **`ras-commander_all_without_code.txt`**:
   - Function signatures and docstrings without implementations
   - Provides a concise overview of the library's structure
   - Maintains documentation while omitting actual code inside functions

4. **`ras_commander_documentation_only.txt`**:
   - Only docstrings extracted from project files
   - Includes important markdown files:
     - `Comprehensive_Library_Guide.md`
     - `STYLE_GUIDE.md`
     - `README.md`
   - Also includes `logging_config.py`
   - Useful for quickly reviewing documentation without implementation details

5. **`examples.txt`**:
   - Content of all files in the examples folder
   - Helps understand library usage through practical examples

6. **`ras-commander_gpt.txt`**:
   - Summary of project files excluding irrelevant content for GPT processing
   - Excludes specific folders like `ai_tools`

## Configuration

The script uses configuration variables to control which files and folders to include or exclude:

```python
# Folders to exclude from processing
OMIT_FOLDERS = [
    "Bald Eagle Creek", "__pycache__", ".git", ".github", "tests", "docs",
    "__pycache__", "build", "dist", "ras_commander.egg-info",
    "venv", "ras_commander.egg-info", "log_folder", "logs", "example_projects",
    "llm_knowledge_bases", "misc", "ai_tools", "FEMA_BLE_Models", "hdf_example_data",
    "ras_example_categories", "html", "data", "apidocs"
]

# File types to exclude from processing
OMIT_FILES = [
    ".pyc", ".pyo", ".pyd", ".dll", ".so", ".dylib", ".exe", ".bat", ".sh", 
    ".log", ".tmp", ".bak", ".swp", ".DS_Store", "Thumbs.db", "example_projects.zip",
    "Example_Projects_6_6.zip", "example_projects.ipynb", "11_Using_RasExamples.ipynb", 
    "future_dev_roadmap.ipynb", "structures_attributes.csv", "example_projects.csv",
]
```

## Usage

To use the script:

1. Navigate to the directory containing the script
2. Run the script using Python:

```bash
python generate_llm_knowledge_bases.py
```

The script will:
- Delete all `__pycache__` folders and their contents
- Create an output directory (`llm_knowledge_bases`) if it doesn't exist
- Process the repository files according to the defined rules
- Generate all knowledge base files
- Output progress information during execution

## Script Functionality

Key functions in the script include:

- **`ensure_output_dir(base_path)`**: Creates the output directory if it doesn't exist
- **`should_omit(filepath)`**: Determines if a file or folder should be excluded
- **`read_file_contents(filepath)`**: Reads file contents with error handling for encoding issues
- **`strip_code_from_functions(content)`**: Removes function implementations while preserving signatures and docstrings
- **`generate_full_summary()`**: Creates the comprehensive repository summary
- **`generate_documentation_only_summary()`**: Extracts documentation-only content
- **`generate_split_summary()`**: Creates separate summaries for different parts of the codebase
- **`generate_full_docsonly_summary()`**: Generates function headers and docstrings without code
- **`generate_gpt_summary()`**: Creates a summary excluding content irrelevant for GPT

## Integration with RAS-Commander

This script is a key component of RAS-Commander's AI integration strategy. As mentioned in the main README, RAS-Commander provides several methods for LLM interaction:

1. **RAS Commander Library Assistant GPT**: A specialized GPT model with access to the knowledge bases created by this script.

2. **Purpose-Built Knowledge Base Summaries**: The files generated by this script, curated to fit within context window limitations of frontier models.

3. **Cursor IDE Integration**: Works alongside the `.cursorrules` file to provide context-aware suggestions.

## Examples of Use Cases

The knowledge bases generated by this script enable several powerful use cases:

1. **Contextual Documentation**: Upload a knowledge base file to provide context when asking an LLM about RAS-Commander functions.

```
# Example prompt with knowledge base context
I've uploaded the ras_commander_documentation_only.txt file. 
How do I initialize a project with RAS-Commander and run a single plan?
```

2. **Code Understanding**: Use the implementation-focused knowledge bases to understand how specific functions work.

```
# Example prompt with code knowledge base
I've uploaded ras_commander_classes_and_functions_only.txt.
Can you explain how the parallel execution works in RasCmdr.compute_parallel()?
```

## Troubleshooting

If you encounter issues with the script:

1. **Memory Errors**: If processing large repositories causes memory issues, try increasing available memory or excluding additional large folders.

2. **Encoding Issues**: If the script encounters files with unusual encoding, they will be handled with the `errors='ignore'` parameter, but this may result in some character loss.

3. **Missing Output Files**: Check that the script has appropriate permissions to create and write files in the target directory.

4. **Knowledge Base Size Issues**: If the generated files are too large for your LLM's context window, you can modify the script to be more selective in what files it includes.

---

For more information about RAS-Commander and its AI integration features, please refer to the main [README.md](README.md) and [Comprehensive_Library_Guide.md](Comprehensive_Library_Guide.md).