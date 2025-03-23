"""
Context folder preprocessing module for Library Assistant.

This module creates a clean copy of the context folder in a temporary directory,
processing Jupyter notebooks to remove images and truncate dataframe outputs
while preserving the original files.
"""

import os
import shutil
import tempfile
import json
import re
import copy
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Set

# Configure logging
logger = logging.getLogger("library_assistant.context_preprocessor")

class ContextPreprocessor:
    """
    Class to handle preprocessing of the context folder for Library Assistant.
    Creates a temporary copy with cleaned notebooks and respects filtering rules.
    """
    
    def __init__(self, 
                 source_folder: Path, 
                 omit_folders: List[str] = None, 
                 omit_extensions: List[str] = None, 
                 omit_files: List[str] = None):
        """
        Initialize the preprocessor with source folder and filtering rules.
        
        Args:
            source_folder: Path to the original context folder
            omit_folders: List of folder names to exclude
            omit_extensions: List of file extensions to exclude
            omit_files: List of specific filenames to exclude
        """
        self.source_folder = Path(source_folder)
        self.omit_folders = omit_folders or []
        self.omit_extensions = omit_extensions or []
        self.omit_files = omit_files or []
        self.temp_dir = None
        self.processed_folder = None
        
        # Initialize stats
        self.stats = {
            "total_files": 0,
            "notebooks_processed": 0,
            "files_copied": 0,
            "files_skipped": 0,
            "folders_skipped": 0,
            "errors": 0
        }
    
    def create_processed_context(self) -> Path:
        """
        Create a processed copy of the context folder in a temporary directory.
        
        Returns:
            Path to the processed context folder
        """
        # Create a temporary directory that will persist until explicitly deleted
        self.temp_dir = tempfile.mkdtemp(prefix="library_assistant_context_")
        logger.info(f"Created temporary directory: {self.temp_dir}")
        
        # Create the processed folder inside the temp directory
        self.processed_folder = Path(self.temp_dir) / self.source_folder.name
        self.processed_folder.mkdir(exist_ok=True)
        
        # Process the folder structure
        self._process_folder(self.source_folder, self.processed_folder)
        
        # Log statistics
        logger.info(f"Preprocessing complete: {self.stats}")
        
        return self.processed_folder
    
    def _process_folder(self, source: Path, target: Path):
        """
        Process a folder recursively, copying and cleaning files as needed.
        
        Args:
            source: Source folder to process
            target: Target folder to copy processed files to
        """
        # Create the target directory if it doesn't exist
        target.mkdir(exist_ok=True)
        
        # Iterate through items in the source directory
        for item in source.iterdir():
            # Check if folder should be skipped
            folder_name = item.name
            if item.is_dir():
                if any(omit_folder == folder_name for omit_folder in self.omit_folders):
                    logger.debug(f"Skipping folder (in omit list): {item}")
                    self.stats["folders_skipped"] += 1
                    continue
                
                # Recursively process subdirectories
                self._process_folder(item, target / folder_name)
            
            # Process files
            elif item.is_file():
                self.stats["total_files"] += 1
                
                # Check if file should be skipped
                if any(item.name == omit_file for omit_file in self.omit_files):
                    logger.debug(f"Skipping file (in omit list): {item}")
                    self.stats["files_skipped"] += 1
                    continue
                
                if any(item.suffix.lower() == ext.lower() for ext in self.omit_extensions):
                    logger.debug(f"Skipping file (extension in omit list): {item}")
                    self.stats["files_skipped"] += 1
                    continue
                
                # Process or copy the file based on type
                try:
                    if item.suffix.lower() == '.ipynb':
                        self._process_notebook(item, target / item.name)
                    else:
                        # Simple copy for non-notebook files
                        shutil.copy2(item, target / item.name)
                        self.stats["files_copied"] += 1
                except Exception as e:
                    logger.error(f"Error processing {item}: {str(e)}")
                    self.stats["errors"] += 1
                    # Copy the original file if processing fails
                    try:
                        shutil.copy2(item, target / item.name)
                        self.stats["files_copied"] += 1
                    except Exception as copy_err:
                        logger.error(f"Error copying {item} after processing failure: {str(copy_err)}")
    
    def _process_notebook(self, notebook_path: Path, output_path: Path):
        """
        Clean a Jupyter notebook by removing images and truncating dataframes.
        
        Args:
            notebook_path: Path to the input notebook file
            output_path: Path to save the cleaned notebook
        """
        logger.debug(f"Processing notebook: {notebook_path}")
        
        try:
            # Load the notebook
            with open(notebook_path, 'r', encoding='utf-8') as f:
                notebook = json.load(f)
            
            # Create a deep copy to avoid modifying the original
            cleaned_notebook = copy.deepcopy(notebook)
            
            # Process each cell
            for cell in cleaned_notebook.get('cells', []):
                if cell.get('cell_type') == 'code':
                    # Process outputs
                    if 'outputs' in cell:
                        cell['outputs'] = self._clean_outputs(cell['outputs'])
            
            # Save the cleaned notebook
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(cleaned_notebook, f, indent=1)
            
            self.stats["notebooks_processed"] += 1
            logger.debug(f"Notebook processed successfully: {output_path}")
        
        except Exception as e:
            logger.error(f"Error processing notebook {notebook_path}: {str(e)}")
            self.stats["errors"] += 1
            # Copy the original file if processing fails
            shutil.copy2(notebook_path, output_path)
            self.stats["files_copied"] += 1
    
    def _clean_outputs(self, outputs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
                new_output = copy.deepcopy(output)
                
                # Remove image data (png, jpeg, etc.)
                if 'data' in new_output:
                    # Remove all image formats
                    for img_format in ['image/png', 'image/jpeg', 'image/svg+xml']:
                        if img_format in new_output['data']:
                            del new_output['data'][img_format]
                    
                    # Check if this might be a DataFrame or other rich HTML display
                    if 'text/html' in new_output['data']:
                        html_content = new_output['data']['text/html']
                        new_output['data']['text/html'] = self._process_html_output(html_content)
                    
                    # If data dict is now empty or only has empty values, add a placeholder
                    if not new_output['data'] or all(not v for v in new_output['data'].values()):
                        new_output['data']['text/plain'] = '[Image or rich display removed during preprocessing]'
                
                cleaned_outputs.append(new_output)
                continue
            
            # Handle execute_result outputs (including dataframes, xarrays)
            elif output_type == 'execute_result':
                new_output = copy.deepcopy(output)
                
                if 'data' in new_output:
                    # Process HTML content (DataFrames, xarray objects)
                    if 'text/html' in new_output['data']:
                        html_content = new_output['data']['text/html']
                        new_output['data']['text/html'] = self._process_html_output(html_content)
                    
                    # Process plain text output
                    if 'text/plain' in new_output['data']:
                        text_content = new_output['data']['text/plain']
                        new_output['data']['text/plain'] = self._process_text_output(text_content)
                
                cleaned_outputs.append(new_output)
            
            # Handle stream outputs (stdout/stderr)
            elif output_type == 'stream':
                new_output = copy.deepcopy(output)
                
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
    
    def _process_html_output(self, html_content: str) -> str:
        """
        Process HTML output content to truncate and simplify it.
        
        Args:
            html_content: HTML content to process
            
        Returns:
            Processed HTML content
        """
        # Handle case where html_content is not a string (e.g., it's a list)
        if not isinstance(html_content, str):
            try:
                # Try to convert to string if possible
                html_content = str(html_content)
            except Exception:
                # If conversion fails, return a placeholder
                return "<div><pre>[Non-string HTML content removed during preprocessing]</pre></div>"
        
        # Check for DataFrame HTML pattern
        if '<table' in html_content and ('dataframe' in html_content or '<style' in html_content):
            return self._truncate_dataframe_html(html_content)
        
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
    
    def _process_text_output(self, text_content: str) -> str:
        """
        Process text output content to truncate and simplify it.
        
        Args:
            text_content: Text content to process
            
        Returns:
            Processed text content
        """
        # Handle case where text_content is not a string (e.g., it's a list)
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
    
    def _truncate_dataframe_html(self, html_content: str) -> str:
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
    
    def cleanup(self):
        """
        Remove the temporary directory and all its contents.
        """
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
                logger.info(f"Removed temporary directory: {self.temp_dir}")
                self.temp_dir = None
                self.processed_folder = None
            except Exception as e:
                logger.error(f"Error removing temporary directory: {str(e)}")

def preprocess_context_folder(
    source_folder: Path, 
    omit_folders: List[str] = None, 
    omit_extensions: List[str] = None, 
    omit_files: List[str] = None
) -> Path:
    """
    Create a processed copy of the context folder with cleaned notebooks.
    
    Args:
        source_folder: Path to the source context folder
        omit_folders: List of folder names to exclude
        omit_extensions: List of file extensions to exclude
        omit_files: List of specific filenames to exclude
    
    Returns:
        Path to the processed context folder
    """
    processor = ContextPreprocessor(
        source_folder=source_folder,
        omit_folders=omit_folders,
        omit_extensions=omit_extensions,
        omit_files=omit_files
    )
    
    processed_folder = processor.create_processed_context()
    
    # Note: We don't call cleanup() here because we want to keep the
    # temporary folder for the duration of the application's runtime
    
    return processed_folder 