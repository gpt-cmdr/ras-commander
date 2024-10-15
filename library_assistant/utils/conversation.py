"""
Utility functions for conversation handling in the Library Assistant.

This module provides functions for managing conversation history,
including adding messages, retrieving the full conversation,
and saving the conversation to a file.

Functions:
- add_to_history(role, content): Adds a message to the conversation history.
- get_full_conversation(): Retrieves the full conversation history as a string.
- save_conversation(): Saves the current conversation history to a file.
"""

from datetime import datetime
import os

# Initialize conversation history
conversation_history = []

def add_to_history(role, content):
    """
    Adds a message to the conversation history.

    Args:
        role (str): The role of the message sender (e.g., 'user' or 'assistant').
        content (str): The content of the message.
    """
    conversation_history.append({"role": role, "content": content})

def get_full_conversation():
    """
    Retrieves the full conversation history as a formatted string.

    Returns:
        str: A string representation of the entire conversation history.
    """
    return "\n".join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in conversation_history])

def save_conversation():
    """
    Saves the current conversation history to a file.

    This function creates a text file with a timestamp in its name,
    containing the full conversation history.

    Returns:
        str: The file path of the saved conversation history.

    Raises:
        IOError: If there's an error writing to the file.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"conversation_history_{timestamp}.txt"
    file_path = os.path.join(os.getcwd(), file_name)
    
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            for message in conversation_history:
                f.write(f"{message['role'].capitalize()}: {message['content']}\n\n")
        return file_path
    except IOError as e:
        raise IOError(f"Error saving conversation history: {str(e)}")

def clear_conversation_history():
    """
    Clears the current conversation history.

    This function removes all messages from the conversation history,
    effectively resetting it to an empty state.
    """
    global conversation_history
    conversation_history = []

def get_conversation_length():
    """
    Returns the number of messages in the current conversation history.

    Returns:
        int: The number of messages in the conversation history.
    """
    return len(conversation_history)

def get_last_message():
    """
    Retrieves the last message from the conversation history.

    Returns:
        dict: A dictionary containing the role and content of the last message,
              or None if the conversation history is empty.
    """
    if conversation_history:
        return conversation_history[-1]
    return None
