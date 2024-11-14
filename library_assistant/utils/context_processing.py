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
preprocessed_rag_context = ""
conversation_context = {}  # Store context for each conversation

def initialize_rag_context():
    """
    Initializes both RAG and full context processing.
    """
    global preprocessed_context, preprocessed_rag_context
    
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
            chunk_level=settings.chunk_level
        )
        
        # Store full context
        preprocessed_context = combined_text
        
        # Process RAG context
        preprocessed_rag_context = prepare_context(
            text=combined_text,
            mode='rag',
            initial_chunk_size=settings.initial_chunk_size,
            followup_chunk_size=settings.followup_chunk_size
        )
        
        # Store token counts for files
        global file_token_mapping
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
    context_mode = settings.context_mode
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
        
        if context_mode == 'full_context':
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
            
        else:  # RAG mode
            prompt = (f"{system_message}\n\n"
                     "<context>\nFiles from RAS-Commander Repository for Context:\n"
                     f"{preprocessed_rag_context}\n</context>\n\n"
                     "Previous Conversation:\n")
            
            # Add conversation history
            for msg in conv_data['history']:
                prompt += f"{msg['role'].capitalize()}: {msg['content']}\n\n"
            
            prompt += f"Using the context above, please respond to this query:\n\n"
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

def prepare_context(text="", mode='full_context', selected_files=None, initial_chunk_size=32000, followup_chunk_size=16000):
    """
    Prepares context based on the specified mode.
    
    Args:
        text (str): The input text to process
        mode (str): Context preparation mode ('full_context' or 'rag')
        selected_files (list): List of files to include in context (for full_context mode)
        initial_chunk_size (int): Size for initial RAG chunks
        followup_chunk_size (int): Size for follow-up RAG chunks
    
    Returns:
        str: The prepared context
    """
    if mode == 'full_context':
        if selected_files:
            # Filter context to only include selected files
            filtered_text = ""
            current_file = None
            for line in text.split('\n'):
                if line.startswith("----- ") and " - " in line:
                    current_file = line.split(" - ")[0].replace("----- ", "")
                    if current_file in selected_files:
                        filtered_text += line + "\n"
                elif current_file in selected_files:
                    filtered_text += line + "\n"
            return filtered_text
        return text
    elif mode == 'rag':
        chunks = chunk_text(text, initial_chunk_size)
        ranked_chunks = rank_chunks(chunks)
        prepared_context = ""
        current_size = 0
        enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
        
        for chunk in ranked_chunks:
            chunk_size = len(enc.encode(chunk))
            if current_size + chunk_size <= followup_chunk_size:
                prepared_context += chunk + "\n\n"
                current_size += chunk_size
            else:
                break
        return prepared_context
    else:
        raise ValueError("Invalid mode. Choose 'full_context' or 'rag'")

def rank_chunks(chunks):
    """
    Ranks chunks of text based on potential relevance.
    Currently returns chunks in original order, but could be enhanced with
    more sophisticated ranking algorithms.

    Args:
        chunks (list): A list of text chunks to be ranked.

    Returns:
        list: The ranked chunks.
    """
    return chunks

def chunk_text(text, chunk_size):
    """
    Splits text into chunks while maintaining context boundaries.

    Args:
        text (str): The text to be chunked.
        chunk_size (int): Target size for each chunk in tokens.

    Returns:
        list: List of text chunks.
    """
    enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
    chunks = []
    current_chunk = ""
    current_tokens = 0

    for line in text.split('\n'):
        line_tokens = len(enc.encode(line))
        
        if current_tokens + line_tokens > chunk_size:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = line
            current_tokens = line_tokens
        else:
            current_chunk += '\n' + line if current_chunk else line
            current_tokens += line_tokens

    if current_chunk:
        chunks.append(current_chunk)

    return chunks