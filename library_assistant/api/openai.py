"""
OpenAI API integration for the Library Assistant.
"""

from openai import OpenAI, OpenAIError
from typing import AsyncGenerator, List, Optional, Dict, Any

async def openai_stream_response(
    client: OpenAI,
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: int = 16000
) -> AsyncGenerator[str, None]:
    """
    Streams a response from the OpenAI API using the specified model.

    Args:
        client: An initialized OpenAI client
        model: The name of the OpenAI model to use
        messages: A list of message dictionaries to send to the API
        max_tokens: The maximum number of tokens to generate (default: 16000)

    Yields:
        str: Chunks of the response text from the API

    Raises:
        OpenAIError: If there's an error with the API call
    """
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            stream=True
        )

        for chunk in stream:
            if chunk.choices[0].delta.content:
                # Clean and normalize the chunk text
                text = chunk.choices[0].delta.content.replace('\r', '')
                if text.strip():  # Only yield non-empty chunks
                    yield text

    except OpenAIError as e:
        raise OpenAIError(f"OpenAI API error: {str(e)}")
    except Exception as e:
        raise OpenAIError(f"Unexpected error in OpenAI API call: {str(e)}")

def get_openai_client(api_key: str) -> OpenAI:
    """
    Creates and returns an OpenAI client.

    Args:
        api_key: The OpenAI API key

    Returns:
        OpenAI: An initialized OpenAI client

    Raises:
        ValueError: If the API key is not provided
    """
    if not api_key:
        raise ValueError("OpenAI API key not provided")
    return OpenAI(api_key=api_key)

async def validate_openai_api_key(api_key: str) -> bool:
    """
    Validates the OpenAI API key by making a test API call.

    Args:
        api_key: The OpenAI API key to validate

    Returns:
        bool: True if the API key is valid, False otherwise
    """
    try:
        client = get_openai_client(api_key)
        # Make a minimal API call to test the key
        client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": "Test"}],
            max_tokens=1,
            stream=False
        )
        return True
    except (OpenAIError, ValueError):
        return False

def get_openai_models() -> List[str]:
    """
    Returns a list of available OpenAI models.

    Returns:
        List[str]: A list of strings representing available OpenAI model names
    """
    return ["gpt-4o-2024-08-06", "gpt-4o-mini", "o1-mini"]
