"""
Anthropic API integration for the Library Assistant.

NOTE: The default model is set to claude-3-7-sonnet-20250219 for best performance.
For extended output length (up to 128k tokens), include the beta header output-128k-2025-02-19.
"""

from anthropic import AsyncAnthropic, Anthropic, APIError, AuthenticationError
from typing import AsyncGenerator, List, Optional, Union

async def anthropic_stream_response(
    client: Union[AsyncAnthropic, Anthropic], 
    prompt: str, 
    max_tokens: int = 8192,
    model: Optional[str] = None,
    system_message: Optional[str] = None
) -> AsyncGenerator[str, None]:
    """
    Streams a response from the Anthropic API using the Claude model.

    Args:
        client: An initialized Anthropic client (sync or async)
        prompt: The prompt to send to the API
        max_tokens: The maximum number of tokens to generate (default: 8192)
        model: The model to use (default: claude-3-7-sonnet-20250219)
        system_message: Optional system message to set the AI's behavior

    Yields:
        str: Chunks of the response text from the API

    Raises:
        APIError: If there's an error with the API call
        AuthenticationError: If authentication fails
    """
    try:
        model = model or "claude-3-7-sonnet-20250219"  # Use Claude 3.7 Sonnet by default
        
        # Convert to async client if needed
        async_client = client if isinstance(client, AsyncAnthropic) else AsyncAnthropic(api_key=client.api_key)
        
        # Create the streaming response with system message as top-level parameter
        stream = await async_client.messages.create(
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            model=model,
            system=system_message if system_message else None,
            stream=True
        )
        
        # Process the stream events
        async for chunk in stream:
            if chunk.type == "content_block_delta" and chunk.delta and chunk.delta.text:
                # Clean and normalize the chunk text
                text = chunk.delta.text.replace('\r', '')
                if text.strip():
                    yield text
                
    except Exception as e:
        error_msg = f"Unexpected error in Anthropic API call: {str(e)}"
        print(error_msg)  # Log the error
        raise APIError(error_msg, request=None)  # Include required request parameter

def get_anthropic_client(api_key: str, async_client: bool = True) -> Union[Anthropic, AsyncAnthropic]:
    """
    Creates and returns an Anthropic client.

    Args:
        api_key: The Anthropic API key
        async_client: Whether to return an async client (default: True)

    Returns:
        An initialized Anthropic client (sync or async)

    Raises:
        ValueError: If the API key is not provided or invalid
    """
    if not api_key or not isinstance(api_key, str):
        raise ValueError("Valid Anthropic API key must be provided")
    return AsyncAnthropic(api_key=api_key) if async_client else Anthropic(api_key=api_key)

async def validate_anthropic_api_key(api_key: str) -> bool:
    """
    Validates the Anthropic API key by making a test API call.

    Args:
        api_key: The Anthropic API key to validate

    Returns:
        bool: True if the API key is valid, False otherwise
    """
    try:
        client = get_anthropic_client(api_key)
        response = await client.messages.create(
            messages=[{"role": "user", "content": "Test"}],
            model="claude-3-7-sonnet-20250219",
            max_tokens=10
        )
        return True
    except (APIError, AuthenticationError):
        return False

def get_anthropic_models() -> List[str]:
    """
    Returns a list of available Anthropic models.

    Returns:
        List[str]: List of model identifiers
    """
    return [
        "claude-3-7-sonnet-20250219",  # Latest and most capable model
        "claude-3-5-sonnet-20241022"   # Previous generation model
    ]

async def stream_response(
    client: Union[AsyncAnthropic, Anthropic], 
    prompt: str, 
    max_tokens: int = 8000,
    model: Optional[str] = None
) -> AsyncGenerator[str, None]:
    """
    Streams a response from the Anthropic API.

    This function is a wrapper around anthropic_stream_response to provide
    a consistent interface across different API providers.

    Args:
        client: An initialized Anthropic client (sync or async)
        prompt: The prompt to send to the API
        max_tokens: The maximum number of tokens to generate (default: 8000)
        model: The model to use (optional)

    Returns:
        An async generator yielding response chunks
    """
    async for chunk in anthropic_stream_response(client, prompt, max_tokens, model):
        yield chunk
