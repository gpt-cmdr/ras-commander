"""
This script generates summary knowledge bases for the ras-commander library.
It processes the project files and creates the following output files:

1. ras-commander_fullrepo.txt:
   A comprehensive summary of all relevant project files, including their content
   and structure. This file provides an overview of the entire codebase, including
   all files and folders except those specified in OMIT_FOLDERS and OMIT_FILES.

2. ras-commander_all_without_code.txt:
   Similar to the comprehensive summary, but with the actual code inside functions
   stripped out. This file focuses on the structure, documentation, and comments
   of the codebase without including implementation details. It includes content
   from all files, including examples and documentation files.

3. ras_commander_documentation_only.txt:
   Contains only the docstrings extracted from the project files, specifically
   from the ras_commander folder. This file is useful for quickly reviewing the
   documentation and purpose of various components without any implementation details
   or examples.
   
   Notable Files:
   - All markdown files: Comprehensive_Library_Guide.md, STYLE_GUIDE.md, Readme.md, etc.    
   - logging_config.py

4. examples.txt:
   Includes the content of all files in the examples folder. This file helps in
   understanding the usage and implementation of the ras-commander library through
   practical examples.

These output files are generated in the 'assistant_knowledge_bases' directory and
serve different purposes for AI assistants or developers who need various levels
of detail about the project structure, documentation, and examples.
"""


import os
from pathlib import Path
import re

# Configuration
OMIT_FOLDERS = [
    "Bald Eagle Creek", "__pycache__", ".git", ".github", "tests", "docs", "library_assistant",
    "build", "dist", "ras_commander.egg-info", "venv", "ras_commander.egg-info",
    "example_projects", "assistant_knowledge_bases", "misc", "ai_tools", "FEMA_BLE_Models","hdf_example_data", "ras_example_categories"
]
OMIT_FILES = [
    ".pyc", ".pyo", ".pyd", ".dll", ".so", ".dylib", ".exe",
    ".bat", ".sh", ".log", ".tmp", ".bak", ".swp",
    ".DS_Store", "Thumbs.db", "example_projects.zip",
    "Example_Projects_6_6.zip", "example_projects.ipynb", "11_Using_RasExamples.ipynb", 
    "future_dev_roadmap.ipynb", "structures_attributes.csv", "example_projects.csv",
]
SUMMARY_OUTPUT_DIR = "assistant_knowledge_bases"
SCRIPT_NAME = Path(__file__).name

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
    This function uses regex to strip out the code inside Python functions.
    It replaces the function body with a documentation placeholder.
    """
    def replacer(match):
        func_signature = match.group(1)
        func_name = match.group(2)
        return f"{func_signature}{func_name}:\n    \"\"\"Docs only, see '{func_name}.py' for full function code\"\"\"\n"

    # Regex to match Python function definitions
    pattern = re.compile(r'(def\s+)(\w+)\s*\(.*?\):\s*\n\s*(?:"""(?:.|\n)*?"""|#.*\n)?(?:\s+.+\n)+', re.MULTILINE)
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

def generate_split_summary(summarize_subfolder, output_dir):
    split_files_mapping = {
        "examples": "examples.txt",
        "ras_commander": "ras_commander_classes_and_functions_only.txt",
        # Add more mappings as needed
    }

    for folder_name, output_file in split_files_mapping.items():
        target_folder = summarize_subfolder / folder_name
        if not target_folder.exists():
            print(f"Warning: Folder '{folder_name}' does not exist in the repository.")
            continue
        output_file_path = output_dir / output_file
        print(f"Generating Split Summary for '{folder_name}': {output_file_path}")

        with open(output_file_path, 'w', encoding='utf-8') as outfile:
            for filepath in target_folder.rglob('*'):
                if should_omit(filepath):
                    continue
                if filepath.is_file():
                    outfile.write(f"File: {filepath}\n")
                    outfile.write("="*50 + "\n")
                    content = read_file_contents(filepath)
                    outfile.write(content)
                    outfile.write("\n" + "="*50 + "\n\n")
                    print(f"Added file to split summary '{output_file}': {filepath}")
                elif filepath.is_dir():
                    outfile.write(f"Folder: {filepath}\n")
                    outfile.write("="*50 + "\n\n")
                    print(f"Added folder to split summary '{output_file}': {filepath}")

        print(f"Split summary '{output_file}' created at '{output_file_path}'")

def generate_documentation_only_summary(summarize_subfolder, output_dir):
    # For example, processing 'ras_commander' folder
    target_folder = summarize_subfolder / "ras_commander"
    output_file_name = "ras_commander_documentation_only.txt"
    output_file_path = output_dir / output_file_name
    print(f"Generating Documentation-Only Summary: {output_file_path}")

    with open(output_file_path, 'w', encoding='utf-8') as outfile:
        for filepath in target_folder.rglob('*'):
            if should_omit(filepath):
                continue
            if filepath.is_file() and filepath.suffix == ".py":
                outfile.write(f"File: {filepath}\n")
                outfile.write("="*50 + "\n")
                content = read_file_contents(filepath)
                stripped_content = strip_code_from_functions(content)
                outfile.write(stripped_content)
                outfile.write("\n" + "="*50 + "\n\n")
                print(f"Added documentation-only file: {filepath}")
            elif filepath.is_dir():
                outfile.write(f"Folder: {filepath}\n")
                outfile.write("="*50 + "\n\n")
                print(f"Added folder to documentation-only summary: {filepath}")

    print(f"Documentation-only summary created at '{output_file_path}'")

def generate_full_docsonly_summary(summarize_subfolder, output_dir):
    output_file_name = f"{summarize_subfolder.name}_all_without_code.txt"
    output_file_path = output_dir / output_file_name
    print(f"Generating Full Documentation-Only Summary: {output_file_path}")

    with open(output_file_path, 'w', encoding='utf-8') as outfile:
        for filepath in summarize_subfolder.rglob('*'):
            if should_omit(filepath):
                continue
            if filepath.is_file():
                outfile.write(f"File: {filepath}\n")
                outfile.write("="*50 + "\n")
                if filepath.suffix == ".py":
                    content = read_file_contents(filepath)
                    stripped_content = strip_code_from_functions(content)
                    outfile.write(stripped_content)
                else:
                    content = read_file_contents(filepath)
                    outfile.write(content)
                outfile.write("\n" + "="*50 + "\n\n")
                print(f"Added file to full documentation-only summary: {filepath}")
            elif filepath.is_dir():
                outfile.write(f"Folder: {filepath}\n")
                outfile.write("="*50 + "\n\n")
                print(f"Added folder to full documentation-only summary: {filepath}")

    print(f"Full documentation-only summary created at '{output_file_path}'")

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

    print(f"All summaries have been generated in '{output_dir}'")

if __name__ == "__main__":
    main()
