"""
Anthropic API integration for the Library Assistant.
"""

from anthropic import AsyncAnthropic, Anthropic, APIError, AuthenticationError
from typing import AsyncGenerator, List, Optional, Union

async def anthropic_stream_response(
    client: Union[AsyncAnthropic, Anthropic], 
    prompt: str, 
    max_tokens: int = 8000,
    model: Optional[str] = None
) -> AsyncGenerator[str, None]:
    """
    Streams a response from the Anthropic API using the Claude model.

    Args:
        client: An initialized Anthropic client (sync or async)
        prompt: The prompt to send to the API
        max_tokens: The maximum number of tokens to generate (default: 8000)
        model: The model to use (default: claude-3-5-sonnet-20240620)

    Yields:
        str: Chunks of the response text from the API

    Raises:
        APIError: If there's an error with the API call
        AuthenticationError: If authentication fails
    """
    try:
        model = model or "claude-3-5-sonnet-20240620"
        
        # Convert to async client if needed
        async_client = client if isinstance(client, AsyncAnthropic) else AsyncAnthropic(api_key=client.api_key)
        
        stream = await async_client.messages.create(
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            model=model,
            stream=True
        )
        
        # Process the stream events
        current_line = []
        
        async for message in stream:
            try:
                if message.type == "content_block_delta" and message.delta and message.delta.text:
                    # Clean and normalize the chunk text
                    chunk = message.delta.text.replace('\r', '')
                    
                    # Accumulate text until we get a natural break
                    current_line.append(chunk)
                    
                    # Check for natural breaks (end of sentence or paragraph)
                    if any(chunk.endswith(end) for end in ['.', '!', '?', '\n']):
                        complete_line = ''.join(current_line)
                        if complete_line.strip():
                            yield complete_line
                        current_line = []
                        
            except Exception as e:
                print(f"Error processing message chunk: {str(e)}")
                continue
        
        # Yield any remaining text
        if current_line:
            remaining = ''.join(current_line)
            if remaining.strip():
                yield remaining
                
    except Exception as e:
        raise APIError(f"Unexpected error in Anthropic API call: {str(e)}")

def get_anthropic_client(api_key: str, async_client: bool = False) -> Union[Anthropic, AsyncAnthropic]:
    """
    Creates and returns an Anthropic client.

    Args:
        api_key: The Anthropic API key
        async_client: Whether to return an async client (default: False)

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
        True if the API key is valid, False otherwise
    """
    try:
        client = get_anthropic_client(api_key, async_client=True)
        await client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=1,
            messages=[{"role": "user", "content": "Test"}],
            stream=False
        )
        return True
    except (anthropic.APIError, anthropic.AuthenticationError, ValueError):
        return False

def get_anthropic_models() -> List[str]:
    """
    Returns a list of available Anthropic models.

    Returns:
        List of strings representing available Anthropic model names
    """
    return ["claude-3-5-sonnet-20240620"]

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
