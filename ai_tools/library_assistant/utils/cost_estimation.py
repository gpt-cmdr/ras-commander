"""
Utility functions for cost estimation in the Library Assistant.

This module provides functions for creating pricing dataframes and
estimating the cost of API calls based on token usage.

Functions:
- create_pricing_df(model): Creates a pricing dataframe for a given model.
- estimate_cost(input_tokens, output_tokens, pricing_df): Estimates the cost of an API call.
- calculate_usage_and_cost(): Calculates token usage and cost for the next request.
"""

import pandas as pd
import tiktoken
from typing import Dict, Optional
# Model configurations with token limits and pricing
MODEL_CONFIG = {
    # Anthropic Models
    "claude-3-7-sonnet-20250219": {
        "max_context_tokens": 200000,
        "prompt_cost_per_1m": 3.0,      # $3.00 per million tokens
        "completion_cost_per_1m": 15.0,  # $15.00 per million tokens
        "default_output_tokens": 8192
    },
    "claude-3-5-sonnet-20241022": {
        "max_context_tokens": 200000,
        "prompt_cost_per_1m": 3.0,      # $3.00 per million tokens
        "completion_cost_per_1m": 15.0,  # $15.00 per million tokens
        "default_output_tokens": 8192
    },
    # OpenAI Models (Existing)
    "gpt-4o-latest": { # Consider updating identifier if a specific version is known, e.g., gpt-4o-2024-08-06
        "max_context_tokens": 128000, # GPT-4o usually has 128k context
        "prompt_cost_per_1m": 5.0,   # Example pricing, update if known
        "completion_cost_per_1m": 15.0, # Example pricing, update if known
        "default_output_tokens": 16384 # Common output limit for GPT-4o
    },
    "gpt-4o-mini": {
        "max_context_tokens": 128000,
        "prompt_cost_per_1m": 0.15,     # $0.15 per million tokens
        "completion_cost_per_1m": 0.6,   # $0.60 per million tokens
        "default_output_tokens": 32768 # Matches gpt-4o standard output
    },
    "o1": {
        "max_context_tokens": 200000,
        "prompt_cost_per_1m": 15.0,     # $15.00 per million tokens
        "completion_cost_per_1m": 60.0,  # $60.00 per million tokens
        "default_output_tokens": 32768
    },
    "o1-mini": {
        "max_context_tokens": 128000, # Needs confirmation, using 128k based on o4-mini
        "prompt_cost_per_1m": 3.0,      # $3.00 per million tokens
        "completion_cost_per_1m": 12.0,  # $12.00 per million tokens
        "default_output_tokens": 32768 # Needs confirmation, using plausible value
    },
     "o3-mini-2025-01-31": { # Renamed from o4-mini based on user text
        "max_context_tokens": 200000,
        "prompt_cost_per_1m": 1.10,   # $1.10 per million tokens (From user text for o4-mini)
        "completion_cost_per_1m": 4.40, # $4.40 per million tokens (From user text for o4-mini)
        "default_output_tokens": 32768 # Max output tokens
    },
    # OpenAI Models (New)
    "o3": {
        "max_context_tokens": 200000,
        "prompt_cost_per_1m": 10.00,    # $10.00 per million tokens
        "completion_cost_per_1m": 40.00, # $40.00 per million tokens
        "default_output_tokens": 32768 # Max output tokens
    },
    "gpt-4.1": { # Using "gpt-4.1" as the identifier
        "max_context_tokens": 1047576, # Context window from user text
        "prompt_cost_per_1m": 2.00,     # $2.00 per million tokens
        "completion_cost_per_1m": 8.00,  # $8.00 per million tokens
        "default_output_tokens": 32768  # Max output tokens
    },
    # Together AI Models
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": {
        "max_context_tokens": 128000,
        "prompt_cost_per_1m": 0.88,     # $0.88 per million tokens
        "completion_cost_per_1m": 0.88,  # $0.88 per million tokens
        "default_output_tokens": 8192
    },
    "deepseek-ai/DeepSeek-V3": {
        "max_context_tokens": 128000,
        "prompt_cost_per_1m": 1.25,     # $1.25 per million tokens
        "completion_cost_per_1m": 1.25,  # $1.25 per million tokens
        "default_output_tokens": 8192
    },
    "deepseek-ai/DeepSeek-R1": {
        "max_context_tokens": 128000,
        "prompt_cost_per_1m": 7.0,      # $7.00 per million tokens
        "completion_cost_per_1m": 7.0,   # $7.00 per million tokens
        "default_output_tokens": 8192
    }
}


def count_tokens(text: str, model_name: str) -> int:
    """
    Count tokens in a string for the given model using tiktoken.
    
    Args:
        text (str): The text to count tokens for
        model_name (str): The name of the model to use for counting
        
    Returns:
        int: Number of tokens in the text
    """
    if not text:
        return 0
        
    try:
        if model_name.startswith("claude"):
            # Use cl100k_base for Claude models
            enc = tiktoken.get_encoding("cl100k_base")
        else:
            # Use gpt-3.5-turbo encoding for other models
            enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
        return len(enc.encode(text))
    except Exception as e:
        print(f"Error counting tokens: {e}")
        # Fallback to simple word count if encoding fails
        return len(text.split())

def calculate_usage_and_cost(
    model_name: str,
    conversation_history: str,
    user_input: str,
    rag_context: str = "",
    system_message: str = "",
    output_length: Optional[int] = None
) -> Dict[str, float]:
    """
    Calculates the token usage and cost for the next request.
    
    Args:
        model_name (str): Name of the selected model
        conversation_history (str): Current conversation history
        user_input (str): User's current input
        rag_context (str, optional): RAG context if used
        system_message (str, optional): System message if used
        output_length (int, optional): Desired output length in tokens
        
    Returns:
        dict: Usage data including token counts, costs, and color coding
    """
    config = MODEL_CONFIG.get(model_name)
    if not config:
        raise ValueError(f"Unsupported model: {model_name}")
        
    max_context_tokens = config["max_context_tokens"]
    default_output_tokens = config["default_output_tokens"]
    
    # Validate and set output length
    if output_length is None or output_length <= 0:
        output_length = default_output_tokens
    else:
        # Cap output length at model's default maximum
        output_length = min(output_length, default_output_tokens)
    
    # Count tokens for each component
    system_tokens = count_tokens(system_message, model_name)
    history_tokens = count_tokens(conversation_history, model_name)
    rag_tokens = count_tokens(rag_context, model_name)
    user_input_tokens = count_tokens(user_input, model_name)
    
    total_input_tokens = system_tokens + history_tokens + rag_tokens + user_input_tokens
    total_tokens_with_output = total_input_tokens + output_length
    
    # Calculate remaining tokens
    remaining_tokens = max_context_tokens - total_tokens_with_output
    
    # Calculate costs using per-million token rates
    prompt_cost = (total_input_tokens / 1_000_000) * config["prompt_cost_per_1m"]
    completion_cost = (output_length / 1_000_000) * config["completion_cost_per_1m"]
    total_cost = prompt_cost + completion_cost
    
    # Determine usage color based on thresholds
    usage_ratio = total_tokens_with_output / max_context_tokens
    if usage_ratio >= 0.8:
        usage_color = "danger"
    elif usage_ratio >= 0.5:
        usage_color = "warning"
    else:
        usage_color = "normal"
    
    return {
        "total_tokens_used": total_input_tokens,
        "total_tokens_with_output": total_tokens_with_output,
        "output_length": output_length,
        "max_tokens": max_context_tokens,
        "remaining_tokens": remaining_tokens,
        "cost_estimate": round(total_cost, 6),
        "usage_ratio": round(usage_ratio, 3),
        "usage_color": usage_color,
        "component_tokens": {
            "system": system_tokens,
            "history": history_tokens,
            "rag": rag_tokens,
            "user_input": user_input_tokens,
            "output": output_length
        },
        "prompt_cost_per_1m": config["prompt_cost_per_1m"],
        "completion_cost_per_1m": config["completion_cost_per_1m"]
    }

def create_pricing_df(model):
    """
    Creates a pricing dataframe for a given model.

    This function returns a dictionary containing a pandas DataFrame with pricing information
    and the provider (OpenAI, Anthropic, or Together) for the specified model.

    Args:
        model (str): The name of the model.

    Returns:
        dict: A dictionary containing:
            - 'pricing_df': A pandas DataFrame with columns 'Model', 'Input ($/1M Tokens)',
                            'Output ($/1M Tokens)', 'Context Window (Tokens)', and 'Response Max Tokens'.
            - 'provider': A string indicating the provider ('openai', 'anthropic', or 'together').

    Raises:
        ValueError: If an unsupported model is specified.
    """
    config = MODEL_CONFIG.get(model)
    if not config:
        # Try to find a close match (e.g., remove date suffix)
        base_model = model.rsplit('-', 1)[0] if '-' in model else model
        config = MODEL_CONFIG.get(base_model)
        if not config:
             raise ValueError(f"Unsupported model: {model}")

    pricing_data = {
        "Model": [model],
        "Input ($/1M Tokens)": [config["prompt_cost_per_1m"]],
        "Output ($/1M Tokens)": [config["completion_cost_per_1m"]],
        "Context Window (Tokens)": [config["max_context_tokens"]],
        "Response Max Tokens": [config["default_output_tokens"]]
    }

    pricing_df = pd.DataFrame(pricing_data)

    # Determine provider based on model name
    provider = "unknown"
    model_lower = model.lower()
    if model_lower.startswith("claude"):
        provider = "anthropic"
    elif model_lower.startswith(("gpt", "o1", "o3", "o4")): # Added o3, o4
        provider = "openai"
    elif any(prefix in model_lower for prefix in ["llama", "deepseek"]):
        provider = "together"

    return {"pricing_df": pricing_df, "provider": provider}

def estimate_cost(input_tokens, output_tokens, pricing_df):
    """
    Estimates the cost of an API call based on input and output tokens.

    Args:
        input_tokens (int): The number of input tokens used in the API call.
        output_tokens (int): The number of output tokens generated by the API call.
        pricing_df (pd.DataFrame): A pandas DataFrame containing pricing information.

    Returns:
        float: The estimated cost of the API call in dollars.
    """
    input_cost = (input_tokens / 1e6) * pricing_df['Input ($/1M Tokens)'].iloc[0]
    output_cost = (output_tokens / 1e6) * pricing_df['Output ($/1M Tokens)'].iloc[0]
    return input_cost + output_cost

def get_max_tokens(pricing_df):
    """
    Retrieves the maximum number of tokens allowed for a response.

    Args:
        pricing_df (pd.DataFrame): A pandas DataFrame containing pricing information.

    Returns:
        int: The maximum number of tokens allowed for a response.
    """
    return pricing_df['Response Max Tokens'].iloc[0]

def get_context_window(pricing_df):
    """
    Retrieves the context window size in tokens.

    Args:
        pricing_df (pd.DataFrame): A pandas DataFrame containing pricing information.

    Returns:
        int: The context window size in tokens.
    """
    return pricing_df['Context Window (Tokens)'].iloc[0]
