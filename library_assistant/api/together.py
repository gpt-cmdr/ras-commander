"""
Together.ai API integration for the Library Assistant.
Simple implementation focused on text completion with streaming support.
"""

import os
from together import Together, AsyncTogether
import logging
from typing import Dict, List, Any, Optional, AsyncGenerator, Union
import asyncio

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TogetherError(Exception):
    """Custom exception for Together.ai API errors"""
    pass

def together_chat_completion(
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None
) -> Dict[str, Any]:
    """
    Gets a completion from the Together.ai API using the specified model.

    Args:
        api_key: Together.ai API key
        model: The name of the model to use
        messages: A list of message dictionaries with 'role' and 'content'
        max_tokens: Optional maximum number of tokens to generate
        temperature: Optional temperature parameter for response randomness

    Returns:
        Dict[str, Any]: The API response

    Raises:
        TogetherError: If there's an error with the API call
    """
    try:
        # Validate model name
        supported_models = [
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "deepseek-ai/DeepSeek-V3",
            "deepseek-ai/DeepSeek-R1",
        ]
        if model not in supported_models:
            raise TogetherError(f"Unsupported model: {model}. Must be one of: {', '.join(supported_models)}")

        client = Together(api_key=api_key)
        
        # Format messages based on model requirements
        if model.startswith("deepseek-ai/"):
            # DeepSeek models expect a specific format
            formatted_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    formatted_messages.append({
                        "role": "user",
                        "content": f"Instructions: {msg['content']}"
                    })
                elif msg["role"] == "assistant":
                    formatted_messages.append({
                        "role": "assistant",
                        "content": msg["content"]
                    })
                else:  # user messages
                    formatted_messages.append({
                        "role": "user",
                        "content": msg["content"]
                    })
        else:
            # Other models can use the messages as-is
            formatted_messages = messages

        # Prepare API call parameters
        params = {
            "model": model,
            "messages": formatted_messages,
            "max_tokens": max_tokens if max_tokens is not None else 8192,
        }

        logger.info(f"Sending Together.ai API request with model: {model}")
        logger.info(f"Using API Key: {api_key}")
        logger.debug(f"Request parameters: {params}")
        
        # Make the API call
        response = client.chat.completions.create(**params)
        return response

    except Exception as e:
        logger.error(f"Error during Together.ai API call: {str(e)}")
        raise TogetherError(f"API error: {str(e)}")


def validate_together_api_key(api_key: str) -> bool:
    """
    Validates the Together.ai API key by making a test API call.

    Args:
        api_key: The Together.ai API key to validate

    Returns:
        bool: True if the API key is valid, False otherwise
    """
    try:
        test_messages = [{"role": "user", "content": "Test"}]
        together_chat_completion(
            api_key=api_key,
            model="meta-llama/Llama-3.3-70B-Instruct-Turbo",  # Use one of our supported models
            messages=test_messages,
            max_tokens=10
        )
        print("API key validation successful")
        return True
    except Exception as e:
        logger.error(f"API key validation failed: {str(e)}")
        return False

async def async_chat_completions(
    api_key: str,
    model: str,
    message_list: List[str]
) -> List[Dict[str, Any]]:
    """
    Performs multiple chat completions in parallel using async.

    Args:
        api_key: Together.ai API key
        model: The model to use
        message_list: List of messages to process in parallel

    Returns:
        List[Dict[str, Any]]: List of responses from the API
    """
    async_client = AsyncTogether(api_key=api_key)
    
    async def single_completion(message: str):
        return await async_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": message}]
        )
    
    tasks = [single_completion(message) for message in message_list]
    responses = await asyncio.gather(*tasks)
    return responses 