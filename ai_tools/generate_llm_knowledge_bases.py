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
import json

# Configuration
OMIT_FOLDERS = [
    "Bald Eagle Creek", "__pycache__", ".git", ".github", "tests", "docs", "library_assistant", "__pycache__",
    "build", "dist", "ras_commander.egg-info", "venv", "ras_commander.egg-info", "log_folder", "logs",
    "example_projects", "llm_knowledge_bases", "misc", "ai_tools", "FEMA_BLE_Models", "hdf_example_data", "ras_example_categories", "html", "data", "apidocs", "build", "dist", "ras_commander.egg-info", "venv", "log_folder", "logs",
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
    
    Args:
        summarize_subfolder: Root folder to search for notebooks
        output_dir: Base output directory
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
                    # Process outputs
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
                    # For examples.txt, use for_examples=True to remove all notebook outputs
                    content = read_file_contents(filepath, for_examples=(folder_name == "examples"))
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

    # Update the path to reflect the new location of library_assistant within ai_tools
    library_assistant_folder = summarize_subfolder / "ai_tools" / "library_assistant"
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
    generate_full_docsonly_summary(summarize_subfolder, output_dir)
    generate_gpt_summary(summarize_subfolder, output_dir)
    generate_library_assistant_summary(summarize_subfolder, output_dir)

    print(f"All summaries, including GPT summary, have been generated in '{output_dir}'")

if __name__ == "__main__":
    main()
