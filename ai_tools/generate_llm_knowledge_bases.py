"""
Knowledge Base Generation Script for ras-commander
===================================================

This script generates knowledge base files optimized for LLM consumption (Claude, GPT, Cursor, etc.).
All outputs are saved to the 'llm_knowledge_bases' directory.

GENERATED KNOWLEDGE BASES:
==========================

1. ras-commander_fullrepo.txt (~2-5 MB)
   Purpose: Complete codebase view for comprehensive RAG (Retrieval-Augmented Generation)
   Contents: All source files, examples, and documentation
   Excludes: Virtual environments, build artifacts, test data, ai_tools, library_assistant
   Use cases: RAG knowledge base, complete repository understanding, comprehensive searches

2. ras-commander_gpt.txt (~2-5 MB)
   Purpose: Similar to fullrepo but explicitly excludes ai_tools and library_assistant
   Contents: All source files, examples, and documentation (minus maintainer-only folders)
   Use cases: LLM context windows, general-purpose knowledge base

3. examples.txt (~2-3 MB)
   Purpose: Demonstrate library usage through practical examples
   Contents: All Jupyter notebooks from examples/ folder with outputs removed
   Use cases: Learning API patterns, understanding workflows, generating new examples

4. ras_commander_classes_and_functions_only.txt (~700 KB)
   Purpose: Core library implementation with full code
   Contents: Complete ras_commander/ folder source code
   Use cases: Understanding implementation details, debugging, extending library

5. ras_commander_documentation_only.txt (~800 KB)
   Purpose: Quick API reference and documentation review
   Contents: Docstrings + key markdown files (README.md, STYLE_GUIDE.md, etc.)
   Use cases: API documentation, quick reference, understanding function signatures

6. ras_commander_hdf_functions_only.txt (~350 KB)
   Purpose: Focus on HDF data processing subsystem
   Contents: All Hdf*.py files from ras_commander/ (HdfBase, HdfPlan, HdfResults, etc.)
   Use cases: Understanding HDF operations, data extraction workflows

7. ras_commander_ras_functions_only.txt (~350 KB)
   Purpose: Focus on HEC-RAS automation subsystem
   Contents: All Ras*.py files from ras_commander/ (RasPrj, RasPlan, RasGeo, etc.)
   Use cases: Understanding HEC-RAS file operations, plan execution workflows

NOTEBOOK PREPROCESSING:
=======================
- Images (PNG, JPEG, SVG) are removed from outputs
- DataFrame outputs truncated to headers + first 5 rows
- xarray outputs simplified to dimension info only
- Long text outputs truncated (>2000 chars)
- Stream outputs limited to 20 lines
- If cleaned notebook >100KB, all outputs removed

EXCLUDED CONTENT:
=================
See OMIT_FOLDERS and OMIT_FILES configuration below. Key exclusions:
- Virtual environments (.venv, venv, conda-env)
- Build artifacts (build/, dist/, *.egg-info)
- IDE folders (.vscode, .idea, .claude, .cursor)
- Test data and example projects
- Deprecated/maintainer-only tools (ai_tools/, library_assistant/)

USAGE:
======
Run this script from the ai_tools directory:
    python generate_llm_knowledge_bases.py

All knowledge bases will be regenerated in ai_tools/llm_knowledge_bases/
"""

import os
from pathlib import Path
import re
import json

# Configuration
# Folders to exclude from knowledge base generation
OMIT_FOLDERS = [
    # Version control and CI/CD
    ".git", ".github", "working", ".claude",
    # Python artifacts
    "__pycache__", ".pytest_cache", ".conda",
    # Build outputs
    "build", "dist", "ras_commander.egg-info",
    # Virtual environments (all variants)
    "venv", ".venv", "env", ".env", "conda-env",
    ".venv-py312", ".venv-py311", ".venv-py310",
    "site-packages", "Lib", "Scripts", "Include",
    # IDE and editor folders
    ".vscode", ".idea", ".cursor",
    # Logs and temporary files
    "logs", "log_folder", "temp", "tmp",
    # Deprecated/internal tooling
    "ai_tools", "library_assistant",
    # Generated outputs
    "llm_knowledge_bases",
    # Test and documentation build
    "tests", "tools", "docs", "html", "apidocs", "_build", "_static",
    # Project data folders
    "example_projects", "data", "FEMA_BLE_Models",
    "hdf_example_data", "ras_example_categories",
    # User workspace folders
    "workspace", "projects", "my_projects", "test_projects",
    # Specific project folders to exclude
    "Bald Eagle Creek", "misc",
    # Development and research folders
    "feature_dev_notes", "research",
    # Old/deprecated content
    ".old", "old", "deprecated",
    # Cache directories
    "cache", "usgs3dep",
    # Model/data folders
    "m3_models", "gauge_data", "hyetographs",
    # Terrain and GIS output folders
    "Terrain", "Output", "python_gis_plan_06",
    # Pip package metadata
    "dist-info",
]
OMIT_FILES = [
    # Compiled Python
    ".pyc", ".pyo", ".pyd", ".dll", ".so", ".dylib", ".exe",
    # Scripts and logs
    ".bat", ".sh", ".log", ".tmp", ".bak", ".swp",
    # OS files
    ".DS_Store", "Thumbs.db",
    # Large example data
    "example_projects.zip", "Example_Projects_6_6.zip", "Example_Projects_6_5.zip",
    "example_projects.ipynb", "11_Using_RasExamples.ipynb",
    "future_dev_roadmap.ipynb", "structures_attributes.csv", "example_projects.csv",
    # Images
    ".ico", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    # Video/audio
    ".mp4", ".avi", ".mov", ".mp3", ".wav", ".m4a", ".m4v", ".ogg", ".webm",
    # Binary/archive files
    ".zip", ".tar", ".gz", ".7z", ".rar",
    ".sqlite", ".db", ".sqlite3",
    ".hdf", ".hdf5", ".h5", ".nc",
    ".tif", ".tiff", ".geotiff",
    ".shp", ".shx", ".dbf", ".prj", ".cpg",
    ".gpkg", ".gdb", ".dss",
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

def process_notebook_content(filepath):
    """
    Process a Jupyter notebook to remove images and truncate dataframe outputs.
    
    Args:
        filepath: Path to the notebook file
        
    Returns:
        Processed notebook content as a string
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            notebook = json.load(f)
        
        # Process each cell
        for cell in notebook.get('cells', []):
            if cell.get('cell_type') == 'code':
                # Process outputs
                if 'outputs' in cell:
                    cell['outputs'] = clean_notebook_outputs(cell['outputs'])
        
        # Convert back to string with indentation for readability
        return json.dumps(notebook, indent=2)
    
    except Exception as e:
        print(f"Error processing notebook {filepath}: {e}")
        # Fall back to original content
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()

def process_notebook_no_outputs(filepath):
    """
    Process a Jupyter notebook to completely remove all outputs.
    
    Args:
        filepath: Path to the notebook file
        
    Returns:
        Processed notebook content as a string with all outputs removed
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            notebook = json.load(f)
        
        # Process each cell
        for cell in notebook.get('cells', []):
            if cell.get('cell_type') == 'code':
                # Remove all outputs
                cell['outputs'] = []
                # Reset execution count
                if 'execution_count' in cell:
                    cell['execution_count'] = None
        
        # Convert back to string with indentation for readability
        return json.dumps(notebook, indent=2)
    
    except Exception as e:
        print(f"Error processing notebook {filepath}: {e}")
        # Fall back to original content
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()

def save_cleaned_notebooks(summarize_subfolder, output_dir):
    """
    Save cleaned versions of all notebooks to a separate subfolder.
    All notebooks will be placed directly in the root of example_notebooks_cleaned.
    If the cleaned notebook is >100KB, remove all outputs.
    """
    cleaned_notebooks_dir = output_dir / "example_notebooks_cleaned"
    cleaned_notebooks_dir.mkdir(parents=True, exist_ok=True)
    print(f"Creating cleaned notebooks directory: {cleaned_notebooks_dir}")
    
    # Find all notebooks
    notebooks = list(summarize_subfolder.rglob('*.ipynb'))
    
    for notebook_path in notebooks:
        if should_omit(notebook_path):
            continue
        try:
            # Process the notebook to clean outputs
            with open(notebook_path, 'r', encoding='utf-8') as f:
                notebook = json.load(f)
            # Process each cell
            for cell in notebook.get('cells', []):
                if cell.get('cell_type') == 'code':
                    if 'outputs' in cell:
                        cell['outputs'] = clean_notebook_outputs(cell['outputs'])
            # Use only the filename for the target path (no subdirectories)
            target_path = cleaned_notebooks_dir / notebook_path.name
            # Overwrite any existing file with the same name
            if target_path.exists():
                target_path.unlink()
            # Save the cleaned notebook
            with open(target_path, 'w', encoding='utf-8') as f:
                json.dump(notebook, f, indent=2)
            # Check file size; if >100KB, remove all outputs and save again
            if target_path.stat().st_size > 100 * 1024:
                print(f"Notebook {notebook_path} cleaned version >100KB, removing all outputs.")
                no_output_content = process_notebook_no_outputs(notebook_path)
                with open(target_path, 'w', encoding='utf-8') as f:
                    f.write(no_output_content)
            print(f"Saved cleaned notebook: {target_path}")
        except Exception as e:
            print(f"Error processing notebook {notebook_path}: {e}")

def clean_notebook_outputs(outputs):
    """
    Clean cell outputs by removing images and truncating dataframes.
    
    Args:
        outputs: List of cell output dictionaries
        
    Returns:
        Cleaned outputs
    """
    cleaned_outputs = []
    
    for output in outputs:
        output_type = output.get('output_type', '')
        
        # Handle display_data outputs (images, HTML, etc.)
        if output_type == 'display_data':
            new_output = output.copy()
            
            # Remove image data (png, jpeg, etc.)
            if 'data' in new_output:
                # Remove all image formats
                for img_format in ['image/png', 'image/jpeg', 'image/svg+xml']:
                    if img_format in new_output['data']:
                        del new_output['data'][img_format]
                
                # Check if this might be a DataFrame or other rich HTML display
                if 'text/html' in new_output['data']:
                    html_content = new_output['data']['text/html']
                    new_output['data']['text/html'] = process_html_output(html_content)
                
                # If data dict is now empty or only has empty values, add a placeholder
                if not new_output['data'] or all(not v for v in new_output['data'].values()):
                    new_output['data']['text/plain'] = '[Image or rich display removed during preprocessing]'
            
            cleaned_outputs.append(new_output)
            continue
        
        # Handle execute_result outputs (including dataframes, xarrays)
        elif output_type == 'execute_result':
            new_output = output.copy()
            
            if 'data' in new_output:
                # Process HTML content (DataFrames, xarray objects)
                if 'text/html' in new_output['data']:
                    html_content = new_output['data']['text/html']
                    new_output['data']['text/html'] = process_html_output(html_content)
                
                # Process plain text output
                if 'text/plain' in new_output['data']:
                    text_content = new_output['data']['text/plain']
                    new_output['data']['text/plain'] = process_text_output(text_content)
            
            cleaned_outputs.append(new_output)
        
        # Handle stream outputs (stdout/stderr)
        elif output_type == 'stream':
            new_output = output.copy()
            
            # Truncate very long text outputs
            if 'text' in new_output and isinstance(new_output['text'], str):
                text = new_output['text']
                lines = text.splitlines()
                
                # Truncate if more than 20 lines
                if len(lines) > 20:
                    truncated_text = '\n'.join(lines[:10]) + '\n...\n' + '\n'.join(lines[-5:])
                    truncated_text += f"\n[Output truncated, {len(lines)} lines total]"
                    new_output['text'] = truncated_text
            
            cleaned_outputs.append(new_output)
        
        # Handle error outputs
        elif output_type == 'error':
            # Keep error outputs as they are (they're usually important)
            cleaned_outputs.append(output)
        
        else:
            # For other output types, include them as is
            cleaned_outputs.append(output)
    
    return cleaned_outputs

def process_html_output(html_content):
    """
    Process HTML output content to truncate and simplify it.
    
    Args:
        html_content: HTML content to process
        
    Returns:
        Processed HTML content
    """
    # Handle case where html_content is not a string
    if not isinstance(html_content, str):
        try:
            # Try to convert to string if possible
            html_content = str(html_content)
        except Exception:
            # If conversion fails, return a placeholder
            return "<div><pre>[Non-string HTML content removed during preprocessing]</pre></div>"
    
    # Check for DataFrame HTML pattern
    if '<table' in html_content and ('dataframe' in html_content or '<style' in html_content):
        return truncate_dataframe_html(html_content)
    
    # Check for xarray HTML pattern
    elif 'xarray' in html_content.lower() and ('<table' in html_content or '<div' in html_content):
        # Extract xarray type
        xarray_type = "xarray.Dataset" if "xarray.Dataset" in html_content else "xarray.DataArray"
        
        # Extract dimensions if possible
        dims_match = re.search(r'Dimensions:(.+?)<', html_content, re.DOTALL)
        dims_info = dims_match.group(1).strip() if dims_match else "Unknown dimensions"
        
        # Return simplified version
        return f"""<div><pre>{xarray_type} with {dims_info}
[Full xarray output truncated during preprocessing]</pre></div>"""
    
    # Check for other kinds of rich HTML content (plots, widgets, etc.)
    elif any(pattern in html_content.lower() for pattern in 
            ['<svg', 'matplotlib', 'bokeh', 'plotly', 'widget', 'vis']):
        return """<div><pre>[Visualization or interactive content removed during preprocessing]</pre></div>"""
    
    # Other HTML content - truncate if very long
    elif len(html_content) > 5000:
        return f"""<div><pre>[Long HTML output truncated: {len(html_content)} characters]</pre></div>"""
    
    # Otherwise, keep the HTML content as is
    return html_content

def process_text_output(text_content):
    """
    Process text output content to truncate and simplify it.
    
    Args:
        text_content: Text content to process
        
    Returns:
        Processed text content
    """
    # Handle case where text_content is not a string
    if not isinstance(text_content, str):
        try:
            # Try to convert to string if possible
            text_content = str(text_content)
        except Exception:
            # If conversion fails, return a placeholder
            return "[Non-string text content removed during preprocessing]"
    
    # Check for DataFrame text representation
    if ('DataFrame' in text_content and '\n' in text_content) or \
       ('[' in text_content and ']' in text_content and '\n' in text_content):
        
        # Count the number of lines
        lines = text_content.splitlines()
        if len(lines) > 10:
            # Simple truncation for DataFrames
            return "[DataFrame output truncated, showing preview only]\n" + '\n'.join(lines[:7]) + '\n...'
    
    # Check for xarray text representation
    elif 'xarray.Dataset' in text_content or 'xarray.DataArray' in text_content:
        # Extract xarray type
        xarray_type = "xarray.Dataset" if "xarray.Dataset" in text_content else "xarray.DataArray"
        
        # Extract dimensions if possible
        dims_match = re.search(r'Dimensions:(.+?)\n', text_content)
        dims_info = dims_match.group(1).strip() if dims_match else "Unknown dimensions"
        
        # Abbreviated description
        return f"{xarray_type} with {dims_info}\n[Full xarray output truncated during preprocessing]"
    
    # Truncate general long text outputs
    elif len(text_content) > 2000:
        lines = text_content.splitlines()
        if len(lines) > 20:
            return '\n'.join(lines[:10]) + '\n...\n' + '\n'.join(lines[-5:]) + \
                   f"\n[Output truncated, {len(lines)} lines total]"
        else:
            return text_content[:1000] + f"\n...\n[Output truncated, {len(text_content)} characters total]"
    
    # Otherwise, keep the text as is
    return text_content

def truncate_dataframe_html(html_content):
    """
    Truncate an HTML dataframe to show only the header and a few rows.
    
    Args:
        html_content: HTML content containing a dataframe
        
    Returns:
        Truncated HTML content
    """
    # Handle case where html_content is not a string
    if not isinstance(html_content, str):
        try:
            # Try to convert to string if possible
            html_content = str(html_content)
        except Exception:
            # If conversion fails, return a placeholder
            return "<div><pre>[Non-string HTML DataFrame content removed during preprocessing]</pre></div>"
    
    # Keep the styling information
    style_match = re.search(r'<style.*?</style>', html_content, re.DOTALL)
    style_section = style_match.group(0) if style_match else ""
    
    # Find the table
    table_match = re.search(r'<table.*?</table>', html_content, re.DOTALL)
    if not table_match:
        return html_content  # Not a table, return as is
    
    table_content = table_match.group(0)
    
    # Extract the header
    header_match = re.search(r'<thead.*?</thead>', table_content, re.DOTALL)
    header_section = header_match.group(0) if header_match else ""
    
    # Extract the first few data rows (up to 5)
    body_match = re.search(r'<tbody.*?</tbody>', table_content, re.DOTALL)
    if body_match:
        body_content = body_match.group(0)
        row_matches = re.findall(r'<tr>.*?</tr>', body_content, re.DOTALL)
        
        max_rows = min(5, len(row_matches))
        first_rows = ''.join(row_matches[:max_rows])
        
        # Construct a new tbody with limited rows plus truncation message
        truncated_body = f"<tbody>\n    {first_rows}\n    <tr><td colspan=\"100%\" style=\"text-align:center\">[... additional rows truncated ...]</td></tr>\n  </tbody>"
    else:
        truncated_body = "<tbody><tr><td>[No data rows]</td></tr></tbody>"
    
    # Reconstruct the table
    table_start_match = re.search(r'<table.*?>', table_content)
    table_start = table_start_match.group(0) if table_start_match else "<table>"
    
    truncated_table = f"{table_start}\n  {header_section}\n  {truncated_body}\n</table>"
    
    # Put it all together
    return f"<div>\n{style_section}\n{truncated_table}\n</div>"

def read_file_contents(filepath, for_examples=False):
    try:
        # Process Jupyter notebooks specially
        if filepath.suffix.lower() == '.ipynb':
            print(f"Processing notebook: {filepath}")
            if for_examples:
                # For examples.txt, remove all outputs
                return process_notebook_no_outputs(filepath)
            else:
                # For other summaries, truncate outputs
                return process_notebook_content(filepath)
        
        # Regular file reading for other files
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

def build_project_tree(filepaths, base_path):
    """
    Build a project structure tree as a string, given a list of filepaths.
    Only includes files actually included in the knowledge base.
    """
    from collections import defaultdict
    tree = lambda: defaultdict(tree)
    file_tree = tree()
    for path in filepaths:
        rel_parts = Path(path).relative_to(base_path).parts
        subtree = file_tree
        for part in rel_parts[:-1]:
            subtree = subtree[part]
        subtree[rel_parts[-1]] = None
    def render(subtree, prefix=""):
        lines = []
        for i, (name, child) in enumerate(sorted(subtree.items())):
            connector = "└── " if i == len(subtree)-1 else "├── "
            lines.append(f"{prefix}{connector}{name}")
            if child:
                extension = "    " if i == len(subtree)-1 else "│   "
                lines.extend(render(child, prefix + extension))
        return lines
    return '\n'.join(render(file_tree))

def write_project_tree_and_content(outfile, filepaths, base_path, cleaned_notebooks_dir):
    """
    Write the project structure tree and then the content for each file.
    """
    tree_str = build_project_tree(filepaths, base_path)
    outfile.write("Project Structure (files included):\n")
    outfile.write(tree_str + "\n\n")
    for filepath in filepaths:
        outfile.write(f"File: {filepath}\n")
        outfile.write("="*50 + "\n")
        if filepath.suffix.lower() == '.ipynb':
            # Use cleaned notebook if available
            cleaned_notebook_path = cleaned_notebooks_dir / filepath.name
            if cleaned_notebook_path.exists():
                with open(cleaned_notebook_path, 'r', encoding='utf-8') as cleanfile:
                    content = cleanfile.read()
                outfile.write(content)
                outfile.write("\n" + "="*50 + "\n\n")
                continue
        content = read_file_contents(filepath)
        outfile.write(content)
        outfile.write("\n" + "="*50 + "\n\n")

def generate_full_summary(summarize_subfolder, output_dir):
    output_file_name = f"{summarize_subfolder.name}_fullrepo.txt"
    output_file_path = output_dir / output_file_name
    print(f"Generating Full Summary: {output_file_path}")
    cleaned_notebooks_dir = output_dir / "example_notebooks_cleaned"
    filepaths = []
    for filepath in summarize_subfolder.rglob('*'):
        if should_omit(filepath):
            continue
        if filepath.is_file():
            filepaths.append(filepath)
    with open(output_file_path, 'w', encoding='utf-8') as outfile:
        write_project_tree_and_content(outfile, filepaths, summarize_subfolder, cleaned_notebooks_dir)
    print(f"Full summary created at '{output_file_path}'")

def generate_documentation_only_summary(summarize_subfolder, output_dir):
    target_folder = summarize_subfolder / "ras_commander"
    output_file_name = "ras_commander_documentation_only.txt"
    output_file_path = output_dir / output_file_name
    print(f"Generating Documentation-Only Summary: {output_file_path}")
    cleaned_notebooks_dir = output_dir / "example_notebooks_cleaned"
    filepaths = []
    # Add markdown files
    markdown_files = ["Comprehensive_Library_Guide.md", "STYLE_GUIDE.md", "README.md"]
    for md_file in markdown_files:
        filepath = summarize_subfolder / md_file
        if filepath.exists():
            filepaths.append(filepath)
    # Add logging_config.py
    logging_config = target_folder / "logging_config.py"
    if logging_config.exists():
        filepaths.append(logging_config)
    # Add all .py files
    for filepath in target_folder.rglob('*'):
        if should_omit(filepath):
            continue
        if filepath.is_file() and filepath.suffix == ".py":
            filepaths.append(filepath)
    with open(output_file_path, 'w', encoding='utf-8') as outfile:
        write_project_tree_and_content(outfile, filepaths, summarize_subfolder, cleaned_notebooks_dir)
    print(f"Documentation-only summary created at '{output_file_path}'")

def generate_split_summary(summarize_subfolder, output_dir):
    """Generate separate summaries for examples, ras_commander, Ras files and Hdf files."""
    split_files_mapping = {
        "examples": "examples.txt",
        "ras_commander": "ras_commander_classes_and_functions_only.txt",
        "ras_files": "ras_commander_ras_functions_only.txt",
        "hdf_files": "ras_commander_hdf_functions_only.txt"
    }
    cleaned_notebooks_dir = output_dir / "example_notebooks_cleaned"
    for folder_name, output_file in split_files_mapping.items():
        if folder_name in ["examples", "ras_commander"]:
            target_folder = summarize_subfolder / folder_name
            if not target_folder.exists():
                print(f"Warning: Folder '{folder_name}' does not exist in the repository.")
                continue
        else:
            target_folder = summarize_subfolder / "ras_commander"
        filepaths = []
        for filepath in target_folder.rglob('*'):
            if should_omit(filepath):
                continue
            if folder_name == "ras_files" and not (filepath.name.startswith("Ras") and filepath.suffix == ".py"):
                continue
            if folder_name == "hdf_files" and not (filepath.name.startswith("Hdf") and filepath.suffix == ".py"):
                continue
            if filepath.is_file():
                filepaths.append(filepath)
        output_file_path = output_dir / output_file
        print(f"Generating Split Summary for '{folder_name}': {output_file_path}")
        with open(output_file_path, 'w', encoding='utf-8') as outfile:
            write_project_tree_and_content(outfile, filepaths, target_folder, cleaned_notebooks_dir)
        print(f"Split summary '{output_file}' created at '{output_file_path}'")


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
    cleaned_notebooks_dir = output_dir / "example_notebooks_cleaned"
    filepaths = []
    for filepath in summarize_subfolder.rglob('*'):
        if should_omit(filepath):
            continue
        if any(folder in filepath.parts for folder in excluded_folders):
            continue
        if filepath.name in excluded_files:
            continue
        if filepath.is_file():
            filepaths.append(filepath)
    with open(output_file_path, 'w', encoding='utf-8') as outfile:
        write_project_tree_and_content(outfile, filepaths, summarize_subfolder, cleaned_notebooks_dir)
    print(f"GPT summary created at '{output_file_path}'")


def main():
    # Get the name of this script
    this_script = SCRIPT_NAME
    print(f"Script name: {this_script}")

    # Define the subfolder to summarize (parent of the script's parent)
    summarize_subfolder = Path(__file__).parent.parent
    print(f"Subfolder to summarize: {summarize_subfolder}")

    # Ensure the output directory exists
    output_dir = ensure_output_dir(Path(__file__).parent)

    # Delete all existing files in the output directory and its subfolders
    for file in output_dir.rglob('*'):
        if file.is_file():
            file.unlink()
    
    # Save cleaned notebooks to a separate subfolder
    save_cleaned_notebooks(summarize_subfolder, output_dir)

    # Generate summaries
    generate_full_summary(summarize_subfolder, output_dir)
    generate_split_summary(summarize_subfolder, output_dir)
    generate_documentation_only_summary(summarize_subfolder, output_dir)
    generate_gpt_summary(summarize_subfolder, output_dir)

    print(f"All knowledge bases have been generated in '{output_dir}'")

if __name__ == "__main__":
    main()
