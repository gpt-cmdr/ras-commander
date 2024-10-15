"""
OpenAI API integration for the Library Assistant.

This module provides functions for interacting with the OpenAI API,
specifically for GPT models.

Functions:
- get_openai_client(api_key): Creates and returns an OpenAI client.
- openai_stream_response(model, messages, max_tokens=16000): Streams a response from the OpenAI API.
- validate_openai_api_key(api_key): Validates the OpenAI API key.
- get_openai_models(): Returns a list of available OpenAI models.
"""

from openai import OpenAI
from openai.types.chat import ChatCompletionMessage

def get_openai_client(api_key):
    """
    Creates and returns an OpenAI client.

    Args:
        api_key (str): The OpenAI API key.

    Returns:
        OpenAI: An initialized OpenAI client.

    Raises:
        ValueError: If the API key is not provided.
    """
    if not api_key:
        raise ValueError("OpenAI API key not provided.")
    return OpenAI(api_key=api_key)

async def openai_stream_response(client, model, messages, max_tokens=16000):
    """
    Streams a response from the OpenAI API using the specified model.

    This function sends messages to the OpenAI API and yields chunks of the response.

    Args:
        client (OpenAI): An initialized OpenAI client.
        model (str): The name of the OpenAI model to use.
        messages (list): A list of message dictionaries to send to the API.
        max_tokens (int, optional): The maximum number of tokens to generate. Defaults to 16000.

    Yields:
        str: Chunks of the response from the API.

    Raises:
        openai.OpenAIError: If there's an error in the API call.
        Exception: For any other unexpected errors.
    """
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            stream=True
        )
        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content
    except openai.OpenAIError as e:
        raise openai.OpenAIError(f"OpenAI API error: {str(e)}")
    except Exception as e:
        raise Exception(f"Unexpected error in OpenAI API call: {str(e)}")

def validate_openai_api_key(api_key):
    """
    Validates the OpenAI API key by making a test API call.

    Args:
        api_key (str): The OpenAI API key to validate.

    Returns:
        bool: True if the API key is valid, False otherwise.
    """
    try:
        client = get_openai_client(api_key)
        # Make a minimal API call to test the key
        client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": "Test"}],
            max_tokens=1
        )
        return True
    except (openai.OpenAIError, ValueError):
        return False

def get_openai_models():
    """
    Returns a list of available OpenAI models.

    This function provides a static list of OpenAI models that are
    supported by the Library Assistant.

    Returns:
        list: A list of strings representing available OpenAI model names.
    """
    return ["gpt-4o-2024-08-06", "gpt-4o-mini", "o1-mini"]

def stream_response(client, model, messages, max_tokens=16000):
    """
    Streams a response from the OpenAI API.

    This function is a wrapper around openai_stream_response to provide
    a consistent interface across different API providers.

    Args:
        client (OpenAI): An initialized OpenAI client.
        model (str): The name of the OpenAI model to use.
        messages (list): A list of message dictionaries to send to the API.
        max_tokens (int, optional): The maximum number of tokens to generate. Defaults to 16000.

    Returns:
        str: The complete response from the API.
    """
    return openai_stream_response(client, model, messages, max_tokens)
