"""
This script generates summary knowledge bases for the ras-commander library.
It processes the project files and creates the following output files:

1. ras-commander_fullrepo.txt:
   A comprehensive summary of all relevant project files, including their content
   and structure. This file provides an overview of the entire codebase, including
   all files and folders except those specified in OMIT_FOLDERS and OMIT_FILES.

2. ras_commander_classes_and_functions_only.txt:
   Contains the complete code from the ras_commander folder, including all classes,
   functions, and their implementations. This file focuses on the core library code
   and includes all implementation details.

3. ras-commander_all_without_code.txt:
   Similar to ras_commander_classes_and_functions_only.txt but with function
   implementations stripped out. Only the function signatures and their docstrings
   are retained, omitting the actual code inside functions to provide a more concise
   overview of the library's structure and documentation.

4. ras_commander_documentation_only.txt:
   Contains only the docstrings extracted from the project files, specifically
   from the ras_commander folder. This file is useful for quickly reviewing the
   documentation and purpose of various components without any implementation details
   or examples.
   
   Notable Files:
   - All markdown files: Comprehensive_Library_Guide.md, STYLE_GUIDE.md, README.md, etc.    
   - logging_config.py

5. examples.txt:
   Includes the content of all files in the examples folder. This file helps in
   understanding the usage and implementation of the ras-commander library through
   practical examples.

6. ras-commander_gpt.txt:
   A summary of the project files, excluding certain files and folders that are
   not relevant for GPT processing (e.g., ai_tools, library_assistant).

7. library_assistant.txt:
   Contains all files and content from the library_assistant subfolder, providing
   a focused view of the library assistant functionality.

These output files are generated in the 'llm_knowledge_bases' directory and
serve different purposes for AI assistants or developers who need various levels
of detail about the project structure, documentation, and examples.
"""

import os
from pathlib import Path
import re

# Configuration
OMIT_FOLDERS = [
    "Bald Eagle Creek", "__pycache__", ".git", ".github", "tests", "docs", "library_assistant", "__pycache__",
    "build", "dist", "ras_commander.egg-info", "venv", "ras_commander.egg-info", "log_folder", "logs",
    "example_projects", "llm_knowledge_bases", "misc", "ai_tools", "FEMA_BLE_Models", "hdf_example_data", "ras_example_categories", "html", "data", "apidocs"
]
OMIT_FILES = [
    ".pyc", ".pyo", ".pyd", ".dll", ".so", ".dylib", ".exe",
    ".bat", ".sh", ".log", ".tmp", ".bak", ".swp",
    ".DS_Store", "Thumbs.db", "example_projects.zip",
    "Example_Projects_6_6.zip", "example_projects.ipynb", "11_Using_RasExamples.ipynb", 
    "future_dev_roadmap.ipynb", "structures_attributes.csv", "example_projects.csv",
]
SUMMARY_OUTPUT_DIR = "llm_knowledge_bases"
SCRIPT_NAME = Path(__file__).name

# Recursively delete all __pycache__ folders and their contents
for folder in Path(__file__).parent.parent.rglob("__pycache__"):
    if folder.is_dir():
        print(f"Deleting __pycache__ folder and contents: {folder}")
        try:
            # Recursively delete all subfolders and files
            for item in folder.rglob("*"):
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    item.rmdir()
            # Delete the empty __pycache__ folder itself
            folder.rmdir()
            print(f"Successfully deleted {folder} and all contents")
        except Exception as e:
            print(f"Error deleting {folder}: {e}")

def ensure_output_dir(base_path):
    output_dir = base_path / SUMMARY_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory ensured to exist: {output_dir}")
    return output_dir

def should_omit(filepath):
    if filepath.name == SCRIPT_NAME:
        return True
    if any(omit_folder in filepath.parts for omit_folder in OMIT_FOLDERS):
        return True
    if any(filepath.suffix == ext or filepath.name == ext for ext in OMIT_FILES):
        return True
    return False

def read_file_contents(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as infile:
            content = infile.read()
            print(f"Reading content of file: {filepath}")
    except UnicodeDecodeError:
        with open(filepath, 'rb') as infile:
            content = infile.read().decode('utf-8', errors='ignore')
            print(f"Reading and converting content of file: {filepath}")
    return content

def strip_code_from_functions(content):
    """
    Strips out the implementation code from functions, leaving only the function
    signature and its docstring. If a function does not have a docstring, a placeholder
    message is inserted.
    """
    # This regex matches a function definition, capturing the header and an optional docstring,
    # then it matches the function body (which will be removed).
    pattern = re.compile(
        r'^(def\s+\w+\(.*?\):\s*\n)'               # Group 1: function header
        r'((?:\s+("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')\s*\n)?)'  # Group 2: optional docstring block
        r'((?:\s+.+\n)+)',                         # Group 4: function body (one or more indented lines)
        re.MULTILINE
    )
    def replacer(match):
        header = match.group(1)
        docstring = match.group(2)
        if docstring.strip():
            return header + docstring
        else:
            return header + '    """Docs only, implementation omitted."""\n'
    stripped_content = pattern.sub(replacer, content)
    return stripped_content

def generate_full_summary(summarize_subfolder, output_dir):
    output_file_name = f"{summarize_subfolder.name}_fullrepo.txt"
    output_file_path = output_dir / output_file_name
    print(f"Generating Full Summary: {output_file_path}")

    with open(output_file_path, 'w', encoding='utf-8') as outfile:
        for filepath in summarize_subfolder.rglob('*'):
            if should_omit(filepath):
                continue
            if filepath.is_file():
                outfile.write(f"File: {filepath}\n")
                outfile.write("="*50 + "\n")
                content = read_file_contents(filepath)
                outfile.write(content)
                outfile.write("\n" + "="*50 + "\n\n")
                print(f"Added file to full summary: {filepath}")
            elif filepath.is_dir():
                outfile.write(f"Folder: {filepath}\n")
                outfile.write("="*50 + "\n\n")
                print(f"Added folder to full summary: {filepath}")

    print(f"Full summary created at '{output_file_path}'")



def generate_documentation_only_summary(summarize_subfolder, output_dir):
    """Generate documentation-only summary from the ras_commander folder."""
    target_folder = summarize_subfolder / "ras_commander"
    output_file_name = "ras_commander_documentation_only.txt"
    output_file_path = output_dir / output_file_name
    print(f"Generating Documentation-Only Summary: {output_file_path}")

    with open(output_file_path, 'w', encoding='utf-8') as outfile:
        # First add markdown files
        markdown_files = ["Comprehensive_Library_Guide.md", "STYLE_GUIDE.md", "README.md"]
        for md_file in markdown_files:
            filepath = summarize_subfolder / md_file
            if filepath.exists():
                outfile.write(f"File: {filepath}\n")
                outfile.write("="*50 + "\n")
                content = read_file_contents(filepath)
                outfile.write(content)
                outfile.write("\n" + "="*50 + "\n\n")
                print(f"Added markdown file: {filepath}")

        # Add logging_config.py
        logging_config = target_folder / "logging_config.py"
        if logging_config.exists():
            outfile.write(f"File: {logging_config}\n")
            outfile.write("="*50 + "\n")
            content = read_file_contents(logging_config)
            outfile.write(content)
            outfile.write("\n" + "="*50 + "\n\n")
            print(f"Added logging config file: {logging_config}")

        # Process Python files for docstrings
        for filepath in target_folder.rglob('*'):
            if should_omit(filepath):
                continue
            if filepath.is_file() and filepath.suffix == ".py":
                outfile.write(f"File: {filepath}\n")
                outfile.write("="*50 + "\n")
                content = read_file_contents(filepath)
                # Extract only docstrings and function signatures
                stripped_content = strip_code_from_functions(content)
                outfile.write(stripped_content)
                outfile.write("\n" + "="*50 + "\n\n")
                print(f"Added documentation-only file: {filepath}")

    print(f"Documentation-only summary created at '{output_file_path}'")


def generate_split_summary(summarize_subfolder, output_dir):
    """Generate separate summaries for examples, ras_commander, Ras files and Hdf files."""
    split_files_mapping = {
        "examples": "examples.txt",
        "ras_commander": "ras_commander_classes_and_functions_only.txt",
        "ras_files": "ras_commander_ras_functions_only.txt",
        "hdf_files": "ras_commander_hdf_functions_only.txt"
    }

    for folder_name, output_file in split_files_mapping.items():
        if folder_name in ["examples", "ras_commander"]:
            target_folder = summarize_subfolder / folder_name
            if not target_folder.exists():
                print(f"Warning: Folder '{folder_name}' does not exist in the repository.")
                continue
        else:
            target_folder = summarize_subfolder / "ras_commander"

        output_file_path = output_dir / output_file
        print(f"Generating Split Summary for '{folder_name}': {output_file_path}")

        with open(output_file_path, 'w', encoding='utf-8') as outfile:
            for filepath in target_folder.rglob('*'):
                if should_omit(filepath):
                    continue
                
                # Special handling for Ras and Hdf files
                if folder_name == "ras_files" and not (filepath.name.startswith("Ras") and filepath.suffix == ".py"):
                    continue
                if folder_name == "hdf_files" and not (filepath.name.startswith("Hdf") and filepath.suffix == ".py"):
                    continue
                    
                if filepath.is_file():
                    outfile.write(f"File: {filepath}\n")
                    outfile.write("="*50 + "\n")
                    content = read_file_contents(filepath)
                    outfile.write(content)
                    outfile.write("\n" + "="*50 + "\n\n")
                    print(f"Added file to split summary '{output_file}': {filepath}")
                elif filepath.is_dir() and folder_name not in ["ras_files", "hdf_files"]:
                    outfile.write(f"Folder: {filepath}\n")
                    outfile.write("="*50 + "\n\n")
                    print(f"Added folder to split summary '{output_file}': {filepath}")

        print(f"Split summary '{output_file}' created at '{output_file_path}'")



def generate_full_docsonly_summary(summarize_subfolder, output_dir):
    """
    Generate a summary of the ras_commander folder with all function implementation code
    stripped out, leaving only the function headers and docstrings.
    """
    ras_commander_folder = summarize_subfolder / "ras_commander"
    output_file_name = "ras-commander_all_without_code.txt"
    output_file_path = output_dir / output_file_name
    print(f"Generating Full Documentation-Only Summary (code omitted): {output_file_path}")

    with open(output_file_path, 'w', encoding='utf-8') as outfile:
        for filepath in ras_commander_folder.rglob('*'):
            if should_omit(filepath):
                continue
            if filepath.is_file():
                outfile.write(f"File: {filepath}\n")
                outfile.write("="*50 + "\n")
                content = read_file_contents(filepath)
                if filepath.suffix == ".py":
                    # For Python files, strip out the function bodies while keeping headers and docstrings
                    stripped_content = strip_code_from_functions(content)
                    outfile.write(stripped_content)
                else:
                    # For non-Python files, include full content
                    outfile.write(content)
                outfile.write("\n" + "="*50 + "\n\n")
                print(f"Added file to all_without_code summary: {filepath}")
            elif filepath.is_dir():
                outfile.write(f"Folder: {filepath}\n")
                outfile.write("="*50 + "\n\n")
                print(f"Added folder to all_without_code summary: {filepath}")

    print(f"All_without_code summary created at '{output_file_path}'")

def generate_gpt_summary(summarize_subfolder, output_dir):
    output_file_name = "ras-commander_gpt.txt"
    output_file_path = output_dir / output_file_name
    print(f"Generating GPT Summary: {output_file_path}")

    excluded_files = [
        "Comprehensive_Library_Guide.md",
        "STYLE_GUIDE.md",
        "README.md",
        "future_dev_roadmap.ipynb"
    ]
    excluded_folders = ["ai_tools", "library_assistant"]

    with open(output_file_path, 'w', encoding='utf-8') as outfile:
        for filepath in summarize_subfolder.rglob('*'):
            if should_omit(filepath):
                continue
            if any(folder in filepath.parts for folder in excluded_folders):
                continue
            if filepath.name in excluded_files:
                continue
            if filepath.is_file():
                outfile.write(f"File: {filepath}\n")
                outfile.write("="*50 + "\n")
                content = read_file_contents(filepath)
                outfile.write(content)
                outfile.write("\n" + "="*50 + "\n\n")
                print(f"Added file to GPT summary: {filepath}")
            elif filepath.is_dir():
                outfile.write(f"Folder: {filepath}\n")
                outfile.write("="*50 + "\n\n")
                print(f"Added folder to GPT summary: {filepath}")

    print(f"GPT summary created at '{output_file_path}'")

def generate_library_assistant_summary(summarize_subfolder, output_dir):
    output_file_name = "library_assistant.txt"
    output_file_path = output_dir / output_file_name
    print(f"Generating Library Assistant Summary: {output_file_path}")

    library_assistant_folder = summarize_subfolder / "library_assistant"
    if not library_assistant_folder.exists():
        print(f"Warning: library_assistant folder not found at {library_assistant_folder}")
        return

    with open(output_file_path, 'w', encoding='utf-8') as outfile:
        for filepath in library_assistant_folder.rglob('*'):
            if filepath.is_file():
                outfile.write(f"File: {filepath}\n")
                outfile.write("="*50 + "\n")
                content = read_file_contents(filepath)
                outfile.write(content)
                outfile.write("\n" + "="*50 + "\n\n")
                print(f"Added file to library assistant summary: {filepath}")
            elif filepath.is_dir():
                outfile.write(f"Folder: {filepath}\n")
                outfile.write("="*50 + "\n\n")
                print(f"Added folder to library assistant summary: {filepath}")

    print(f"Library assistant summary created at '{output_file_path}'")

def main():
    # Get the name of this script
    this_script = SCRIPT_NAME
    print(f"Script name: {this_script}")

    # Define the subfolder to summarize (parent of the script's parent)
    summarize_subfolder = Path(__file__).parent.parent
    print(f"Subfolder to summarize: {summarize_subfolder}")

    # Ensure the output directory exists
    output_dir = ensure_output_dir(Path(__file__).parent)

    # Generate summaries
    generate_full_summary(summarize_subfolder, output_dir)
    generate_split_summary(summarize_subfolder, output_dir)
    generate_documentation_only_summary(summarize_subfolder, output_dir)
    generate_full_docsonly_summary(summarize_subfolder, output_dir)
    generate_gpt_summary(summarize_subfolder, output_dir)
    generate_library_assistant_summary(summarize_subfolder, output_dir)

    print(f"All summaries, including GPT summary, have been generated in '{output_dir}'")

if __name__ == "__main__":
    main()
