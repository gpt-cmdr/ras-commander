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
- combine_files(summarize_subfolder, omit_folders, omit_extensions, omit_files, strip_code=False, chunk_level='function'): Combines and processes multiple files.
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

    Returns:
        str: The system message.

    Raises:
        FileNotFoundError: If the .cursorrules file is not found.
        ValueError: If no system message is found in the file.
    """
    current_dir = Path.cwd()
    cursor_rules_path = current_dir.parent / '.cursorrules'

    if not cursor_rules_path.exists():
        raise FileNotFoundError("This script expects to be in a directory within the ras_commander repo which has a .cursorrules file in its parent directory.")

    with open(cursor_rules_path, 'r') as f:
        system_message = f.read().strip()

    if not system_message:
        raise ValueError("No system message found in .cursorrules file.")

    return system_message

def set_context_folder():
    """
    Sets the context folder for file processing.

    Returns:
        Path: The path to the context folder.
    """
    return Path.cwd().parent

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
        content (str): The content of the Python file.
        filepath (Path): The path to the Python file.
        strip_code (bool): Whether to strip code from function bodies.
        chunk_level (str): The level at which to chunk the content ('function' or 'file').

    Returns:
        str: The processed content of the Python file.
    """
    header_end = content.find("class ") if "class " in content else len(content)
    header = content[:header_end]
    processed_content = f"\n\n----- {filepath.name} - header -----\n\n{header}\n\n----- End of header -----\n\n"
    
    if chunk_level == 'function':
        function_chunks = re.findall(r"(def .*?(?=\ndef |\Z))", content[header_end:], re.DOTALL)
        for chunk in function_chunks:
            if strip_code:
                chunk = strip_code_from_functions(chunk)
            processed_content += f"\n\n----- {filepath.name} - chunk -----\n\n{chunk}\n\n----- End of chunk -----\n\n"
    else:
        content = strip_code_from_functions(content[header_end:]) if strip_code else content[header_end:]
        processed_content += f"\n\n----- {filepath.name} - full_file -----\n\n{content}\n\n----- End of full_file -----\n\n"
    
    return processed_content

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

def combine_files(summarize_subfolder, omit_folders, omit_extensions, omit_files, strip_code=False, chunk_level='function'):
    """
    Combines and processes multiple files, respecting omission rules.

    Args:
        summarize_subfolder (Path): The root folder to process.
        omit_folders (list): List of folder names to omit.
        omit_extensions (list): List of file extensions to omit.
        omit_files (list): List of specific file names to omit.
        strip_code (bool): Whether to strip code from function bodies in Python files.
        chunk_level (str): The level at which to chunk content ('function' or 'file').

    Returns:
        tuple: A tuple containing the combined text, total token count, and a dictionary of file token counts.
    """
    combined_text = ""
    file_token_counts = {}
    total_token_count = 0
    
    this_script = Path(__file__).name
    summarize_subfolder = Path(summarize_subfolder)
    enc = tiktoken.encoding_for_model("gpt-3.5-turbo")

    for filepath in summarize_subfolder.rglob('*'):
        if (filepath.name != this_script and 
            not any(omit_folder in filepath.parts for omit_folder in omit_folders) and
            filepath.suffix.lower() not in omit_extensions and
            not any(omit_file in filepath.name for omit_file in omit_files)):
            
            if filepath.is_file():
                try:
                    with open(filepath, 'r', encoding='utf-8') as infile:
                        content = infile.read()
                except UnicodeDecodeError:
                    with open(filepath, 'rb') as infile:
                        content = infile.read().decode('utf-8', errors='ignore')
                
                if filepath.suffix.lower() == '.py':
                    content = handle_python_file(content, filepath, strip_code, chunk_level)
                elif filepath.suffix.lower() == '.md':
                    content = handle_markdown_file(content, filepath)
                else:
                    content = f"\n\n----- {filepath.name} - full_file -----\n\n{content}\n\n----- End of {filepath.name} -----\n\n"
                
                combined_text += content
                file_tokens = len(enc.encode(content))
                file_token_counts[str(filepath)] = file_tokens
                total_token_count += file_tokens

    return combined_text, total_token_count, file_token_counts
