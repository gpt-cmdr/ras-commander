"""
OpenAI API integration for the Library Assistant.
Revision 2024.03.14:
- Fixed duplicate stream parameter issue
- Improved parameter handling for o1 models
- Cleaned up completion parameter management
- Removed OpenRouter dependency
"""

from openai import OpenAI, OpenAIError
from typing import AsyncGenerator, List, Optional, Dict, Any
import logging
from pathlib import Path

# Configure logging
def setup_logger():
    """Configure logger with both file and console handlers"""
    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Create logger
    logger = logging.getLogger("library_assistant.openai")
    logger.setLevel(logging.DEBUG)
    
    # Prevent duplicate handlers
    if logger.handlers:
        return logger
    
    # Create formatters
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_formatter = logging.Formatter(
        '%(levelname)s - %(message)s'
    )
    
    # File handler
    file_handler = logging.FileHandler(log_dir / "openai_api.log")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(console_formatter)
    
    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# Initialize logger
logger = setup_logger()

def _get_model_family(model: str) -> str:
    """
    Determines the model family to handle role requirements.
    
    Args:
        model: The model name to check
        
    Returns:
        str: Model family identifier ('o3-mini', 'o1', 'gpt4o', or 'default')
    """
    model_family = 'default'
    if model.startswith('o3-mini'):
        model_family = 'o3-mini'
    elif model.startswith('o1'):
        model_family = 'o1'
    elif model.startswith('gpt-4o'):
        model_family = 'gpt4o'
    
    logger.debug(f"Model {model} identified as family: {model_family}")
    return model_family

def _get_completion_params(model: str, max_tokens: int) -> Dict[str, Any]:
    """
    Gets the appropriate completion parameters for the model family.
    
    Args:
        model: The model name
        max_tokens: The maximum number of tokens to generate
        
    Returns:
        Dict[str, Any]: Dictionary of completion parameters
    """
    model_family = _get_model_family(model)
    
    params = {
        'model': model,
    }
    
    # Handle o1 and o3-mini models with max_completion_tokens
    if model_family in ['o1', 'o3-mini']:
        params['max_completion_tokens'] = max_tokens
    else:
        params['max_tokens'] = max_tokens
    
    logger.debug(f"Generated completion parameters for {model}: {params}")
    return params

def _transform_messages_for_model(messages: List[Dict[str, str]], model: str) -> List[Dict[str, str]]:
    """
    Transforms message roles based on model requirements.
    
    Args:
        messages: Original message list
        model: Target model name
        
    Returns:
        List[Dict[str, str]]: Transformed message list
    """
    transformed_messages = []
    model_family = _get_model_family(model)
    
    logger.debug(f"Original messages: {messages}")
    
    for message in messages:
        new_message = message.copy()
        
        # Handle system messages based on model family
        if message['role'] == 'system':
            if model_family == 'o1':
                # TODO: Update to 'developer' role once API support is available
                # For now, convert system messages to user messages for o1 models
                new_message['role'] = 'user'
                logger.debug(f"Converting system message to user for O1 model (temporary until developer role support)")
            elif model_family == 'gpt4o':
                # For GPT-4O models, keep as system
                logger.debug(f"Keeping system message for GPT-4O model")
                pass
            else:
                # For other models, convert to user
                new_message['role'] = 'user'
                logger.debug(f"Converting system message to user for default model")
        
        transformed_messages.append(new_message)
    
    logger.debug(f"Transformed messages: {transformed_messages}")
    return transformed_messages

async def openai_stream_response(
    client: OpenAI,
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: int = 16000
) -> AsyncGenerator[str, None]:
    """
    Streams a response from the OpenAI API using the specified model.
    For o1 models, returns the complete response as a single chunk due to API limitations.

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
        logger.debug(f"Starting response for model: {model}")
        
        if not client or not client.api_key:
            raise ValueError("OpenAI client not properly initialized")
        
        # Transform messages based on model requirements
        transformed_messages = _transform_messages_for_model(messages, model)
        
        # Get model-specific completion parameters
        completion_params = _get_completion_params(model, max_tokens)
        completion_params['messages'] = transformed_messages
        
        # Add more detailed logging
        logger.debug("=== API Call Details ===")
        logger.debug(f"Model: {model}")
        logger.debug(f"Parameters:")
        for key, value in completion_params.items():
            if key != 'messages':  # Don't log full messages for privacy
                logger.debug(f"  {key}: {value}")
        logger.debug("=====================")
        
        # Handle o1 models differently (no streaming)
        if model.startswith('o1'):
            response = client.chat.completions.create(
                **completion_params,
                stream=False
            )
            logger.debug(f"Non-streaming response received")
            yield response.choices[0].message.content
            return
            
        # For all other models, use streaming exactly as per OpenAI docs
        stream = client.chat.completions.create(
            **completion_params,
            stream=True
        )
        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                # Clean and normalize the chunk text
                text = chunk.choices[0].delta.content.replace('\r', '')
                if text.strip():  # Only yield non-empty chunks
                    yield text

    except ValueError as e:
        error_msg = str(e)
        logger.error(error_msg)
        raise OpenAIError(error_msg)
    except OpenAIError as e:
        error_msg = f"OpenAI API error: {str(e)}"
        logger.error("=== API Error Details ===")
        logger.error(error_msg)
        logger.error("Parameters:")
        for key, value in completion_params.items():
            if key != 'messages':  # Don't log full messages for privacy
                logger.error(f"  {key}: {value}")
        logger.error("=====================")
        raise OpenAIError(error_msg)
    except Exception as e:
        error_msg = f"Unexpected error in OpenAI API call: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Failed parameters: {completion_params}")
        raise OpenAIError(error_msg)

def get_openai_client(api_key: str) -> OpenAI:
    """
    Creates and returns an OpenAI client.

    Args:
        api_key: The OpenAI API key

    Returns:
        OpenAI: An initialized OpenAI client

    Raises:
        ValueError: If the API key is not provided or invalid
    """
    if not api_key or not isinstance(api_key, str) or not api_key.strip():
        logger.error("OpenAI API key not provided or invalid")
        raise ValueError("OpenAI API key not provided")
    
    try:
        client = OpenAI(api_key=api_key.strip())
        return client
    except Exception as e:
        logger.error(f"Error initializing OpenAI client: {str(e)}")
        raise ValueError(f"Failed to initialize OpenAI client: {str(e)}")

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
        response = client.chat.completions.create(
            model="gpt-4o-2024-08-06",
            messages=[{"role": "user", "content": "Test"}],
            max_tokens=10
        )
        return True
    except Exception as e:
        logger.error(f"API key validation failed: {str(e)}")
        return False

def get_openai_models() -> List[Dict[str, Any]]:
    """
    Returns a list of available OpenAI models.

    Returns:
        List[Dict[str, Any]]: A list of dictionaries containing model information
    """
    return [
        {
            "name": "gpt-4o-2024-08-06",
            "context_length": 16000,
            "description": "GPT-4 Optimized for fast inference"
        },
        {
            "name": "gpt-4o-mini",
            "context_length": 16000,
            "description": "GPT-4 Mini model for faster, more efficient processing"
        },
        {
            "name": "o1",
            "context_length": 200000,
            "description": "O1 model for general purpose use"
        },
        {
            "name": "o1-mini",
            "context_length": 200000,
            "description": "O1 Mini model for faster, more efficient processing"
        },
        {
            "name": "o3-mini-2025-01-31",
            "context_length": 200000,
            "description": "o3-mini – our most recent small reasoning model (knowledge cutoff: October 2023). Supports structured outputs, function calling, batch API, etc., with 200k context and 100k max output tokens."
        }
    ]
