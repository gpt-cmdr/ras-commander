"""
Integration of context preprocessing into the Library Assistant application.

This module provides integration functions to connect the context preprocessor
with the Library Assistant's existing workflow.
"""

import atexit
import logging
import json
import shutil
from pathlib import Path

from utils.context_preprocessor import preprocess_context_folder
from utils.file_handling import combine_files, set_context_folder as original_set_context_folder
from config.config import load_settings

# Configure logging
logger = logging.getLogger("library_assistant.context_integration")

# Global variables to keep track of context folders
_temp_context_folder = None
_original_context_folder = None

# Import these after initialization to avoid circular imports
preprocessed_context = ""
file_token_mapping = {}

def initialize_context_with_preprocessing():
    """
    Initialize context with preprocessing for the Library Assistant.
    This function replaces the original initialize_context function in utils/context_processing.py.
    """
    global _temp_context_folder, _original_context_folder
    global preprocessed_context, file_token_mapping
    
    try:
        # Load settings
        settings = load_settings()
        
        # Get the original context folder directly instead of using the function
        # to avoid circular imports
        original_context_folder = Path.cwd().parent.parent
        _original_context_folder = original_context_folder
        
        logger.info(f"Getting original context folder: {original_context_folder}")
        
        # Get settings as Python objects
        omit_folders = json.loads(settings.omit_folders)
        omit_extensions = json.loads(settings.omit_extensions)
        omit_files = json.loads(settings.omit_files)
        
        logger.info(f"Creating processed copy of context folder: {original_context_folder}")
        
        # Create a processed copy of the context folder
        _temp_context_folder = preprocess_context_folder(
            source_folder=original_context_folder,
            omit_folders=omit_folders,
            omit_extensions=omit_extensions,
            omit_files=omit_files
        )
        
        logger.info(f"Using processed context folder: {_temp_context_folder}")
        
        # Register cleanup function to execute on application exit
        atexit.register(cleanup_temp_context)
        
        # Use the temporary folder for subsequent processing
        # Combine files with current settings
        combined_text, total_token_count, file_token_counts = combine_files(
            summarize_subfolder=_temp_context_folder,
            omit_folders=omit_folders,
            omit_extensions=omit_extensions,
            omit_files=omit_files,
            strip_code=True,
            chunk_level='file'
        )
        
        # Store full context
        preprocessed_context = combined_text
        
        # Store token counts for files
        file_token_mapping = file_token_counts
        
        return True
    except Exception as e:
        logger.error(f"Error initializing context with preprocessing: {str(e)}")
        raise

def cleanup_temp_context():
    """
    Clean up the temporary context folder when the application exits.
    """
    global _temp_context_folder
    
    if _temp_context_folder and _temp_context_folder.exists():
        try:
            # Remove the entire temporary directory
            parent_temp_dir = _temp_context_folder.parent
            if parent_temp_dir.exists() and parent_temp_dir.name.startswith("library_assistant_context_"):
                logger.info(f"Cleaning up temporary context folder: {parent_temp_dir}")
                shutil.rmtree(parent_temp_dir)
                _temp_context_folder = None
        except Exception as e:
            logger.error(f"Error cleaning up temporary context folder: {str(e)}")

def set_context_folder_with_preprocessing():
    """
    Returns the temporary context folder path if it exists, otherwise falls back to the original.
    This function should replace or modify the existing set_context_folder function.
    """
    global _temp_context_folder, _original_context_folder
    
    if _temp_context_folder and _temp_context_folder.exists():
        logger.debug(f"Using preprocessed context folder: {_temp_context_folder}")
        return _temp_context_folder
    else:
        # INSTEAD OF calling original_set_context_folder(), we'll implement the
        # original functionality directly to avoid circular dependency
        context_folder = Path.cwd().parent.parent
        logger.debug(f"Using original context folder implementation: {context_folder}")
        return context_folder 