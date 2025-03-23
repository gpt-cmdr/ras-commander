"""
Utility functions for file handling in the Library Assistant.

This module provides functions for reading API keys, system messages,
and processing various file types for the Library Assistant application.

Functions:
- read_api_key(file_path): Reads an API key from a file.
- read_system_message(): Reads the system message from .cursorrules file.
- set_context_folder(): Sets the context folder for file processing.
- strip_code_from_functions(content): Strips code from function bodies.
- handle_python_file(content, filepath, strip_code, chunk_level='function'): Processes Python files.
- handle_markdown_file(content, filepath): Processes Markdown files.
- combine_files(summarize_subfolder, omit_folders, omit_extensions, omit_files, strip_code=False, chunk_level='function', selected_files=None): Combines and processes multiple files.
"""

import os
import json
import re
import ast
import astor
from pathlib import Path
import tiktoken

def read_api_key(file_path):
    """
    Reads an API key from a file.

    Args:
        file_path (str): Path to the file containing the API key.

    Returns:
        str: The API key.

    Raises:
        FileNotFoundError: If the API key file is not found.
    """
    try:
        with open(file_path, 'r') as file:
            return file.read().strip()
    except FileNotFoundError:
        raise FileNotFoundError(f"API key file not found: {file_path}")

def read_system_message():
    """
    Reads the system message from .cursorrules file.
    
    Updated to handle the new folder structure where library_assistant
    is in ai_tools/library_assistant instead of the root folder.

    Returns:
        str: The system message.

    Raises:
        FileNotFoundError: If the .cursorrules file is not found.
        ValueError: If no system message is found in the file.
    """
    current_dir = Path.cwd()
    print(f"Current directory: {current_dir}")
    cursor_rules_path = current_dir.parent.parent / '.cursorrules'  # Changed from parent to parent.parent
    print(f"Cursor rules path: {cursor_rules_path}")

    if not cursor_rules_path.exists():
        raise FileNotFoundError("This script expects to be in a directory within the ras_commander repo which has a .cursorrules file in its parent.parent directory.")

    with open(cursor_rules_path, 'r') as f:
        system_message = f.read().strip()

    if not system_message:
        raise ValueError("No system message found in .cursorrules file.")

    return system_message

def set_context_folder():
    """
    Sets the context folder for file processing.
    
    Since the library_assistant is now located in ai_tools/library_assistant,
    we need to go up two directory levels to reach the root folder.
    
    If a preprocessed context folder exists, it will be used instead.

    Returns:
        Path: The path to the context folder.
    """
    # Check if we have a context_integration module and a preprocessed folder
    try:
        # Attempt to import dynamically to avoid circular imports
        import importlib
        context_integration_module = importlib.import_module('utils.context_integration')
        
        # If the module has a function to get the preprocessed folder, use it
        if hasattr(context_integration_module, 'set_context_folder_with_preprocessing'):
            return context_integration_module.set_context_folder_with_preprocessing()
    except (ImportError, AttributeError) as e:
        # If anything fails, just continue with original implementation
        print(f"Info: Using original context folder (no preprocessing available): {e}")
    
    # Original implementation
    context_folder = Path.cwd().parent.parent
    print(f"Setting context folder to: {context_folder}")
    return context_folder

class FunctionStripper(ast.NodeTransformer):
    """AST NodeTransformer to strip code from function bodies."""
    def visit_FunctionDef(self, node):
        new_node = ast.FunctionDef(
            name=node.name,
            args=node.args,
            body=[ast.Pass()],
            decorator_list=node.decorator_list,
            returns=node.returns
        )
        if (node.body and isinstance(node.body[0], ast.Expr) and
            isinstance(node.body[0].value, ast.Str)):
            new_node.body = [node.body[0], ast.Pass()]
        return new_node

def strip_code_from_functions(content):
    """
    Strips code from function bodies, leaving only function signatures and docstrings.

    Args:
        content (str): The Python code content.

    Returns:
        str: The code with function bodies stripped.
    """
    try:
        tree = ast.parse(content)
        stripped_tree = FunctionStripper().visit(tree)
        return astor.to_source(stripped_tree)
    except SyntaxError:
        return content

def handle_python_file(content, filepath, strip_code, chunk_level='function'):
    """
    Processes Python files, optionally stripping code and chunking content.

    Args:
        content (str): The content of the Python file
        filepath (Path): The path to the Python file
        strip_code (bool): Whether to strip code from function bodies
        chunk_level (str): The level at which to chunk the content ('function' or 'file')

    Returns:
        str: The processed content of the Python file
    """
    # Extract header (imports and module docstring)
    header_end = content.find("class ") if "class " in content else content.find("def ") if "def " in content else len(content)
    header = content[:header_end].strip()
    
    if not header:
        return ""
        
    processed_content = [f"\n\n----- {filepath.name} - header -----\n\n{header}\n\n----- End of header -----\n\n"]
    
    if chunk_level == 'function':
        # Improved regex to better handle nested functions and class methods
        function_pattern = r"(?:^|\n)(?:async\s+)?def\s+[^()]+\([^)]*\)\s*(?:->[^:]+)?:\s*(?:[^\n]*\n\s+[^\n]+)*"
        function_chunks = re.finditer(function_pattern, content[header_end:], re.MULTILINE)
        
        for match in function_chunks:
            chunk = match.group(0)
            if strip_code:
                chunk = strip_code_from_functions(chunk)
            processed_content.append(
                f"\n\n----- {filepath.name} - chunk -----\n\n{chunk.strip()}\n\n----- End of chunk -----\n\n"
            )
    else:
        remaining_content = strip_code_from_functions(content[header_end:]) if strip_code else content[header_end:]
        if remaining_content.strip():
            processed_content.append(
                f"\n\n----- {filepath.name} - full_file -----\n\n{remaining_content.strip()}\n\n----- End of full_file -----\n\n"
            )
    
    return "".join(processed_content)

def handle_markdown_file(content, filepath):
    """
    Processes Markdown files, splitting them into sections.

    Args:
        content (str): The content of the Markdown file.
        filepath (Path): The path to the Markdown file.

    Returns:
        str: The processed content of the Markdown file.
    """
    if filepath.name in ["Comprehensive_Library_Guide.md", "STYLE_GUIDE.md"]:
        return f"\n\n----- {filepath.name} - full_file -----\n\n{content}\n\n----- End of {filepath.name} -----\n\n"
    
    sections = re.split(r'\n#+ ', content)
    processed_content = ""
    for section in sections:
        processed_content += f"\n\n----- {filepath.name} - section -----\n\n# {section}\n\n----- End of section -----\n\n"
    return processed_content

def combine_files(summarize_subfolder, omit_folders, omit_extensions, omit_files, strip_code=False, chunk_level='function', selected_files=None):
    """
    Combines and processes multiple files, respecting omission rules and file selection.
    
    Args:
        summarize_subfolder (Path): The root folder to process
        omit_folders (list): List of folder names to omit
        omit_extensions (list): List of file extensions to omit
        omit_files (list): List of specific file names to omit
        strip_code (bool): Whether to strip code from function bodies
        chunk_level (str): The level at which to chunk content
        selected_files (list): Optional list of specific files to include
    
    Returns:
        tuple: (combined_text, total_token_count, file_token_counts)
    """
    combined_text = []
    file_token_counts = {}
    total_token_count = 0
    
    this_script = Path(__file__).name
    summarize_subfolder = Path(summarize_subfolder)
    enc = tiktoken.encoding_for_model("gpt-3.5-turbo")

    # Convert selected_files paths to relative paths for comparison
    selected_file_paths = None
    if selected_files:
        selected_file_paths = {Path(f).as_posix() for f in selected_files}

    for filepath in sorted(summarize_subfolder.rglob('*')):
        # Skip directories and filtered items
        if not filepath.is_file() or filepath.name == this_script:
            continue
            
        if (any(omit_folder in filepath.parts for omit_folder in omit_folders) or
            filepath.suffix.lower() in omit_extensions or
            any(omit_file in filepath.name for omit_file in omit_files)):
            continue

        # Check if file is in selected files list
        if selected_file_paths:
            relative_path = filepath.relative_to(summarize_subfolder).as_posix()
            if relative_path not in selected_file_paths:
                continue

        try:
            content = filepath.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            content = filepath.read_bytes().decode('utf-8', errors='ignore')
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
            continue

        processed_content = ""
        if filepath.suffix.lower() == '.py':
            processed_content = handle_python_file(content, filepath, strip_code, chunk_level)
        elif filepath.suffix.lower() == '.md':
            processed_content = handle_markdown_file(content, filepath)
        else:
            processed_content = f"\n\n----- {filepath.name} - full_file -----\n\n{content}\n\n----- End of {filepath.name} -----\n\n"
        
        if processed_content:
            combined_text.append(processed_content)
            file_tokens = len(enc.encode(processed_content))
            file_token_counts[str(filepath)] = file_tokens
            total_token_count += file_tokens

    return "".join(combined_text), total_token_count, file_token_counts
