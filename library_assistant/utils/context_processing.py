"""
Utility functions for context processing in the Library Assistant.

This module provides functions for ranking and chunking text,
preparing context for AI processing, and initializing the RAG context.

Functions:
- rank_chunks(chunks): Ranks chunks of text (placeholder function).
- chunk_and_rank(combined_text, chunk_size): Chunks and ranks the combined text.
- prepare_context(combined_text, mode='full_context', initial_chunk_size=32000, followup_chunk_size=16000): Prepares context based on the specified mode.
- reconstruct_context(ranked_chunks, max_tokens): Reconstructs context from ranked chunks.
- initialize_rag_context(): Initializes the RAG context for the application.
- prepare_full_prompt(user_query): Prepares the full prompt for the AI model, including context and user query.
"""

import tiktoken
from pathlib import Path
from config.config import load_settings
from utils.file_handling import combine_files, read_system_message, set_context_folder
import json

def rank_chunks(chunks):
    """
    Ranks chunks of text (placeholder function).

    This function is a placeholder for a more sophisticated ranking algorithm.
    Currently, it returns the chunks in their original order.

    Args:
        chunks (list): A list of text chunks to be ranked.

    Returns:
        list: The input chunks in their original order.
    """
    return chunks  # Implement your ranking algorithm here

def chunk_and_rank(combined_text, chunk_size):
    """
    Chunks the combined text and ranks the resulting chunks.

    This function splits the combined text into chunks based on file and function
    boundaries, then ranks these chunks.

    Args:
        combined_text (str): The combined text to be chunked and ranked.
        chunk_size (int): The maximum size (in tokens) for each chunk.

    Returns:
        list: A list of tuples, where each tuple contains (file_name, chunk_content).
    """
    enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
    chunks = []
    current_chunk = ""
    current_file = ""
    
    for line in combined_text.split('\n'):
        if line.startswith("----- ") and line.endswith(" -----"):
            if current_chunk:
                chunks.append((current_file, current_chunk))
                current_chunk = ""
            current_file = line.strip("-").strip()
        else:
            current_chunk += line + "\n"
            if len(enc.encode(current_chunk)) > chunk_size:
                chunks.append((current_file, current_chunk))
                current_chunk = ""
    
    if current_chunk:
        chunks.append((current_file, current_chunk))
    
    ranked_chunks = rank_chunks(chunks)
    return ranked_chunks

def prepare_context(context_mode='full_context', initial_chunk_size=32000, followup_chunk_size=16000):
    """
    Prepares context based on the specified mode.

    This function either returns the full context or uses RAG to prepare a
    more focused context.

    Args:
        context_mode (str): The context preparation mode ('full_context' or 'rag').
        initial_chunk_size (int): The initial chunk size for RAG mode.
        followup_chunk_size (int): The followup chunk size for RAG mode.

    Returns:
        str: The prepared context.

    Raises:
        ValueError: If an invalid mode is specified.
    """
    global preprocessed_context, preprocessed_rag_context

    if context_mode == 'full_context':
        return preprocessed_context
    elif context_mode == 'rag':
        return preprocessed_rag_context
    else:
        raise ValueError("Invalid mode. Choose 'full_context' or 'rag'.")

def reconstruct_context(ranked_chunks, max_tokens):
    """
    Reconstructs context from ranked chunks up to a maximum token limit.

    Args:
        ranked_chunks (list): A list of ranked text chunks.
        max_tokens (int): The maximum number of tokens to include in the context.

    Returns:
        str: The reconstructed context.
    """
    enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
    context = "Retrieval system has provided these chunks which may be helpful to the query:\n\n"
    current_tokens = len(enc.encode(context))
    
    for file, chunk in ranked_chunks:
        chunk_tokens = len(enc.encode(chunk))
        if current_tokens + chunk_tokens > max_tokens:
            break
        context += f"{chunk}\n\n"
        current_tokens += chunk_tokens
    
    return context

def initialize_rag_context():
    """
    Initializes the RAG context for the application.

    This function loads settings, combines files, and prepares the initial
    context for the RAG system.

    Note: This function modifies global variables `preprocessed_context`
    and `preprocessed_rag_context`.
    """
    global preprocessed_context, preprocessed_rag_context
    settings = load_settings()
    selected_model = settings.selected_model
    context_mode = settings.context_mode
    omit_folders = json.loads(settings.omit_folders)
    omit_extensions = json.loads(settings.omit_extensions)
    omit_files = json.loads(settings.omit_files)
    chunk_level = settings.chunk_level
    initial_chunk_size = settings.initial_chunk_size
    followup_chunk_size = settings.followup_chunk_size

    print("Setting context folder")
    context_folder = set_context_folder()
    print("Combining files")
    combined_text, total_token_count, _ = combine_files(
        summarize_subfolder=context_folder, 
        omit_folders=omit_folders, 
        omit_extensions=omit_extensions, 
        omit_files=omit_files, 
        strip_code=True, 
        chunk_level=chunk_level
    )

    print("Reading system message")
    system_message = read_system_message()

    if context_mode == 'full_context':
        print("Setting full context")
        preprocessed_context = combined_text
    else:  # RAG mode
        print("Preparing RAG Chunks (takes 10-20 seconds)")
        preprocessed_rag_context = prepare_context(
            combined_text=combined_text, 
            mode='rag', 
            initial_chunk_size=initial_chunk_size, 
            followup_chunk_size=followup_chunk_size
        )

# Initialize global variables for context
preprocessed_context = ""
preprocessed_rag_context = ""

def prepare_full_prompt(user_query):
    """
    Prepares the full prompt for the AI model, including context and user query.

    Args:
        user_query (str): The user's query.

    Returns:
        str: The full prompt including system message, context, and user query.
    """
    settings = load_settings()
    context_mode = settings.context_mode
    
    system_message = read_system_message()
    
    if context_mode == 'full_context':
        context = prepare_context(context_mode='full_context')
        full_prompt = f"{system_message}\n\nContext:\n{context}\n\nUser Query: {user_query}"
    else:  # RAG mode
        context = prepare_context(context_mode='rag')
        full_prompt = (
            f"{system_message}\n\n<context>Context Chunks:\n{context}\n\n</context>\n"
            "The context above is provided for your use in responding to the user's query:\n\n"
            f"User Query: {user_query}"
        )
    
    return full_prompt
