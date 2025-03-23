"""
Utility functions for context processing in the Library Assistant.
"""

import tiktoken
from pathlib import Path
from config.config import load_settings
from utils.file_handling import combine_files, read_system_message, set_context_folder
import json

# Initialize global variables for context
preprocessed_context = ""
file_token_mapping = {}  # Add global variable definition here
conversation_context = {}  # Store context for each conversation

def initialize_context():
    """
    Initializes the full context processing.
    """
    global preprocessed_context
    global file_token_mapping  # Using global declaration here is fine since we already defined it above
    
    # Try to use the preprocessor version if available
    try:
        import importlib
        context_integration = importlib.import_module('utils.context_integration')
        if hasattr(context_integration, 'initialize_context_with_preprocessing'):
            # Use the enhanced version with notebook preprocessing
            if context_integration.initialize_context_with_preprocessing():
                # Copy over the processed context from the integration module
                preprocessed_context = context_integration.preprocessed_context
                
                # Copy over file token mapping
                file_token_mapping = context_integration.file_token_mapping
                
                return True
    except (ImportError, AttributeError) as e:
        print(f"Info: Using original context initialization (no preprocessing available): {e}")
    
    # If we get here, use the original implementation
    try:
        # Load settings
        settings = load_settings()
        context_folder = set_context_folder()
        
        # Get settings as Python objects
        omit_folders = json.loads(settings.omit_folders)
        omit_extensions = json.loads(settings.omit_extensions)
        omit_files = json.loads(settings.omit_files)
        
        # Combine files with current settings
        combined_text, total_token_count, file_token_counts = combine_files(
            summarize_subfolder=context_folder,
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
        print(f"Error initializing context: {str(e)}")
        raise

def prepare_full_prompt(user_query: str, selected_files=None, conversation_id=None) -> str:
    """
    Prepares the full prompt for the AI model, including context and conversation history.
    
    Args:
        user_query (str): The user's query
        selected_files (list): List of files to include in context
        conversation_id (str): Unique identifier for the conversation
    
    Returns:
        str: The complete prompt including system message, context, and conversation history
    """
    settings = load_settings()
    system_message = read_system_message()
    
    try:
        # Get or initialize conversation context
        if conversation_id not in conversation_context:
            conversation_context[conversation_id] = {
                'selected_files': selected_files,
                'history': []
            }
        
        conv_data = conversation_context[conversation_id]
        
        # Update selected files if they've changed
        if selected_files != conv_data['selected_files']:
            conv_data['selected_files'] = selected_files
        
        if selected_files:
            # Get content of selected files
            context_folder = set_context_folder()
            combined_text, _, _ = combine_files(
                summarize_subfolder=context_folder,
                omit_folders=[],
                omit_extensions=[],
                omit_files=[],
                strip_code=True,
                chunk_level='file',
                selected_files=selected_files
            )
            context = combined_text
        else:
            context = preprocessed_context
            
        # Format prompt with conversation history
        prompt = (f"{system_message}\n\n"
                 f"Files from RAS-Commander Repository for Context:\n{context}\n\n"
                 "Previous Conversation:\n")
        
        # Add conversation history
        for msg in conv_data['history']:
            prompt += f"{msg['role'].capitalize()}: {msg['content']}\n\n"
        
        # Add current query
        prompt += f"User Query: {user_query}"
        
        return prompt
            
    except Exception as e:
        print(f"Error preparing prompt: {str(e)}")
        return f"{system_message}\n\nUser Query: {user_query}"

def update_conversation_history(conversation_id: str, role: str, content: str):
    """
    Updates the conversation history for a given conversation.
    
    Args:
        conversation_id (str): Unique identifier for the conversation
        role (str): Role of the message sender ('user' or 'assistant')
        content (str): Content of the message
    """
    if conversation_id not in conversation_context:
        conversation_context[conversation_id] = {
            'selected_files': None,
            'history': []
        }
    
    conversation_context[conversation_id]['history'].append({
        'role': role,
        'content': content
    })

def clear_conversation_history(conversation_id: str):
    """
    Clears the conversation history for a given conversation.
    
    Args:
        conversation_id (str): Unique identifier for the conversation
    """
    if conversation_id in conversation_context:
        conversation_context[conversation_id]['history'] = []