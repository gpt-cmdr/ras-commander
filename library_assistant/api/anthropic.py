"""
Anthropic API integration for the Library Assistant.

This module provides functions for interacting with the Anthropic API,
specifically for the Claude model.

Functions:
- anthropic_stream_response(client, prompt, max_tokens=8000): Streams a response from the Anthropic API.
"""

import anthropic

async def anthropic_stream_response(client, prompt, max_tokens=8000):
    """
    Streams a response from the Anthropic API using the Claude model.

    This function sends a prompt to the Anthropic API and yields chunks of the response.

    Args:
        client (anthropic.Anthropic): An initialized Anthropic client.
        prompt (str): The prompt to send to the API.
        max_tokens (int, optional): The maximum number of tokens to generate. Defaults to 8000.

    Yields:
        str: Chunks of the response from the API.

    Raises:
        anthropic.APIError: If there's an error in the API call.
        Exception: For any other unexpected errors.
    """
    try:
        with client.messages.stream(
            max_tokens=max_tokens,
            messages=[
                {"role": "user", "content": prompt}
            ],
            model="claude-3-5-sonnet-20240620"
        ) as stream:
            async for text in stream.text_stream:
                yield text
    except anthropic.APIError as e:
        raise anthropic.APIError(f"Anthropic API error: {str(e)}")
    except Exception as e:
        raise Exception(f"Unexpected error in Anthropic API call: {str(e)}")

def get_anthropic_client(api_key):
    """
    Creates and returns an Anthropic client.

    Args:
        api_key (str): The Anthropic API key.

    Returns:
        anthropic.Anthropic: An initialized Anthropic client.

    Raises:
        ValueError: If the API key is not provided.
    """
    if not api_key:
        raise ValueError("Anthropic API key not provided.")
    return anthropic.Anthropic(api_key=api_key)

def validate_anthropic_api_key(api_key):
    """
    Validates the Anthropic API key by making a test API call.

    Args:
        api_key (str): The Anthropic API key to validate.

    Returns:
        bool: True if the API key is valid, False otherwise.
    """
    try:
        client = get_anthropic_client(api_key)
        # Make a minimal API call to test the key
        client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=1,
            messages=[
                {"role": "user", "content": "Test"}
            ]
        )
        return True
    except (anthropic.APIError, ValueError):
        return False

def get_anthropic_models():
    """
    Returns a list of available Anthropic models.

    This function provides a static list of Anthropic models that are
    supported by the Library Assistant.

    Returns:
        list: A list of strings representing available Anthropic model names.
    """
    return ["claude-3-5-sonnet-20240620"]

def stream_response(client, prompt, max_tokens=8000):
    """
    Streams a response from the Anthropic API.

    This function is a wrapper around anthropic_stream_response to provide
    a consistent interface across different API providers.

    Args:
        client (anthropic.Anthropic): An initialized Anthropic client.
        prompt (str): The prompt to send to the API.
        max_tokens (int, optional): The maximum number of tokens to generate. Defaults to 8000.

    Returns:
        str: The complete response from the API.
    """
    return anthropic_stream_response(client, prompt, max_tokens)
