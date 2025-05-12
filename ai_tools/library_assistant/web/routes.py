"""
Web routes for the Library Assistant.

This module defines the FastAPI routes for the web interface of the Library Assistant.
It handles user interactions, API calls, and serves the HTML template.

Routes:
- GET /: Serves the main page of the application.
- POST /chat: Handles chat interactions with the AI model.
- POST /submit: Handles form submissions for updating settings.
- POST /save_conversation: Saves the current conversation history to a file.
- GET /get_file_tree: Returns the file tree structure with token counts.
- POST /calculate_tokens: Calculates token usage and cost for the current state.
- POST /add_root_folder: Adds a new root folder to the file tree.
"""

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from config.config import load_settings, update_settings
from utils.conversation import add_to_history, get_full_conversation, save_conversation
from utils.context_processing import prepare_full_prompt, update_conversation_history, initialize_context
from utils.cost_estimation import create_pricing_df, estimate_cost, calculate_usage_and_cost, MODEL_CONFIG
from utils.file_handling import set_context_folder
from api.anthropic import anthropic_stream_response, get_anthropic_client
from api.openai import openai_stream_response, get_openai_client
from api.together import together_chat_completion
from api.logging import logger, log_error, log_request_response
import json
import tiktoken
import os
from pathlib import Path
import uuid
from datetime import datetime

router = APIRouter()

# Set up Jinja2 templates
templates = Jinja2Templates(directory="web/templates")

# Set up static files
static_files = StaticFiles(directory="web/static")

class TokenCalcRequest(BaseModel):
    """Request model for token calculation endpoint."""
    model_name: str
    conversation_history: str
    user_input: str
    rag_context: str = ""
    system_message: str = ""
    output_length: Optional[int] = None
    selected_files: List[str] = []

@router.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """
    Serves the main page of the application.

    Args:
        request (Request): The incoming request object.

    Returns:
        TemplateResponse: The rendered HTML template with current settings.
    """
    settings = load_settings()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "settings": settings
    })

@router.post("/chat")
async def chat(request: Request, message: dict):
    """
    Handles chat interactions with the AI model, supporting streaming responses
    and extended output for specific models.
    """
    conversation_id = message.get("conversation_id", str(uuid.uuid4()))
    logger.info(f"Starting chat interaction - Conversation ID: {conversation_id}")

    try:
        user_message = message.get("message")
        if not user_message:
            logger.warning("Empty message received")
            raise HTTPException(status_code=400, detail="No message provided.")

        selected_files = message.get("selectedFiles", [])
        logger.debug(f"Selected files for context: {selected_files}")

        add_to_history("user", user_message)
        logger.debug(f"Added user message to history: {user_message[:100]}...")

        settings = load_settings()
        selected_model = settings.selected_model
        if not selected_model:
             raise HTTPException(status_code=400, detail="No model selected in settings.")
        logger.info(f"Using model: {selected_model}")

        # --- Start Model Specific Adjustments ---
        output_length = int(message.get("output_length", 0)) # Get user desired length if provided
        model_config = MODEL_CONFIG.get(selected_model, {})
        max_possible_output = model_config.get("default_output_tokens", 8192)
        anthropic_headers = None

        # Adjust for Claude 3.7 Sonnet extended output
        if selected_model == "claude-3-7-sonnet-20250219":
             # Use user specified length up to 128k, otherwise default to 128k
            output_length = min(output_length if output_length > 0 else 128000, 128000)
            anthropic_headers = {"anthropic-beta": "output-128k-2025-02-19"}
            logger.info(f"Claude 3.7 Sonnet selected. Enabling extended output up to {output_length} tokens.")
        elif output_length <= 0:
             # Use model default if user didn't specify
             output_length = max_possible_output
        else:
             # Use user specified length, capped by model max
             output_length = min(output_length, max_possible_output)
        # --- End Model Specific Adjustments ---

        full_prompt = prepare_full_prompt(
            user_message,
            selected_files,
            conversation_id
        )
        logger.debug(f"Prepared prompt length: {len(full_prompt)} characters")

        update_conversation_history(conversation_id, "user", user_message)

        usage_data = calculate_usage_and_cost(
            model_name=selected_model,
            conversation_history=get_full_conversation(),
            user_input=user_message,
            rag_context="".join(selected_files), # This might not be the best way to represent context tokens
            system_message=settings.system_message or "",
            output_length=output_length # Use the calculated/adjusted output length
        )

        if usage_data["remaining_tokens"] < 0:
            raise HTTPException(
                status_code=400,
                detail=f"Request exceeds maximum token limit ({usage_data['max_tokens']} tokens). Current estimate: {usage_data['total_tokens_with_output']}. Please reduce context or message length."
            )

        logger.info(f"Token usage - Input: {usage_data['total_tokens_used']}, Output: {usage_data['output_length']}")
        logger.info(f"Estimated cost: ${usage_data['cost_estimate']:.6f}")

        pricing_info = create_pricing_df(selected_model)
        provider = pricing_info["provider"]
        logger.info(f"Using provider: {provider}")

        async def stream_response():
            accumulated_response = []
            try:
                if provider == "anthropic":
                    logger.info("Using Anthropic API")
                    client = get_anthropic_client(settings.anthropic_api_key)
                    logger.info(f"Sending Anthropic API request with model: {selected_model}, max_tokens: {output_length}")
                    async for chunk in anthropic_stream_response(
                        client,
                        full_prompt,
                        system_message=settings.system_message,
                        max_tokens=output_length, # Pass adjusted max_tokens
                        model=selected_model,      # Explicitly pass model
                        extra_headers=anthropic_headers # Pass beta header if applicable
                    ):
                        accumulated_response.append(chunk)
                        yield f"data: {json.dumps({'chunk': chunk})}\n\n"

                elif provider == "openai":
                    logger.info("Using OpenAI API")
                    client = get_openai_client(settings.openai_api_key)
                    messages = [
                        {"role": "system", "content": settings.system_message or "You are a helpful AI assistant."},
                        {"role": "user", "content": full_prompt} # Consider structuring messages differently if needed
                    ]
                    logger.info(f"Sending OpenAI API request with model: {selected_model}, max_tokens: {output_length}")
                    async for chunk in openai_stream_response(
                        client,
                        selected_model,
                        messages,
                        max_tokens=output_length # Pass adjusted max_tokens
                    ):
                        accumulated_response.append(chunk)
                        yield f"data: {json.dumps({'chunk': chunk})}\n\n"

                elif provider == "together":
                    logger.info("Using Together.ai API")
                    messages = [
                        {"role": "system", "content": settings.system_message or "You are a helpful AI assistant."},
                        {"role": "user", "content": full_prompt}
                    ]
                    logger.info(f"Sending Together.ai API request with model: {selected_model}, max_tokens: {output_length}")
                    # Note: Together.ai API might not support streaming this way.
                    # Assuming non-streaming response for simplicity based on existing code.
                    response = together_chat_completion(
                        settings.together_api_key,
                        selected_model,
                        messages,
                        max_tokens=output_length # Pass adjusted max_tokens
                    )

                    if response and response.choices and response.choices[0].message:
                        response_text = response.choices[0].message.content
                        accumulated_response.append(response_text)
                        yield f"data: {json.dumps({'chunk': response_text})}\n\n"
                    else:
                        error_msg = "No response content received from Together.ai API"
                        logger.error(error_msg)
                        yield f"data: {json.dumps({'error': error_msg})}\n\n"
                else:
                    logger.error(f"Unsupported provider: {provider}")
                    raise HTTPException(status_code=400, detail="Unsupported provider selected.")

                complete_response = "".join(accumulated_response)
                logger.debug(f"Complete response length: {len(complete_response)} characters")
                add_to_history("assistant", complete_response)
                update_conversation_history(conversation_id, "assistant", complete_response)

                # Recalculate final cost based on actual tokens if possible (hard with streaming)
                # For now, send the initial estimate
                final_usage_data = calculate_usage_and_cost( # Recalculate with actual response? Hard for streaming.
                    model_name=selected_model,
                    conversation_history=get_full_conversation()[:-len(complete_response)], # History before response
                    user_input=user_message,
                    rag_context="".join(selected_files),
                    system_message=settings.system_message or "",
                    output_length=tiktoken.encoding_for_model("gpt-3.5-turbo").encode(complete_response) # Estimate actual output tokens
                 )

                yield f"data: {json.dumps({'cost': final_usage_data['cost_estimate'], 'provider': provider})}\n\n"
                logger.info(f"Chat interaction completed successfully - Conversation ID: {conversation_id}")

            except Exception as e:
                # Extract detailed API error information
                error_details = str(e)
                
                # Handle provider-specific API errors
                if provider == "anthropic":
                    # For Anthropic errors, try to extract the message from the error object
                    if hasattr(e, 'body') and e.body:
                        try:
                            error_body = e.body
                            if isinstance(error_body, dict) and 'error' in error_body:
                                if isinstance(error_body['error'], dict) and 'message' in error_body['error']:
                                    error_details = f"Anthropic API Error: {error_body['error']['message']}"
                                else:
                                    error_details = f"Anthropic API Error: {error_body['error']}"
                        except Exception:
                            pass
                    # Fallback for API error parsing
                    elif "rate_limit_error" in error_details:
                        error_details = "Rate limit exceeded. The API is receiving too many requests. Please try again later or reduce your token usage."
                
                elif provider == "openai":
                    # For OpenAI errors, try to extract the message
                    if hasattr(e, 'message'):
                        error_details = f"OpenAI API Error: {e.message}"
                    elif hasattr(e, 'response') and hasattr(e.response, 'json'):
                        try:
                            error_json = e.response.json()
                            if 'error' in error_json and 'message' in error_json['error']:
                                error_details = f"OpenAI API Error: {error_json['error']['message']}"
                        except Exception:
                            pass
                
                error_msg = f"Error during streaming: {error_details}"
                logger.error(error_msg, exc_info=True) # Log traceback
                log_error(e, "Streaming error")
                yield f"data: {json.dumps({'error': error_details})}\n\n"

        return StreamingResponse(
            stream_response(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    except HTTPException as http_exc:
        logger.error(f"HTTP Exception in /chat: {http_exc.detail}", exc_info=True)
        raise http_exc
    except Exception as e:
        log_error(e, f"Chat endpoint error - Conversation ID: {conversation_id}")
        logger.error(f"Unexpected error in /chat: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.post("/submit")
async def handle_submit(
    request: Request,
    anthropic_api_key: str = Form(None),
    openai_api_key: str = Form(None),
    together_api_key: str = Form(None),
    selected_model: str = Form(None),
    context_mode: str = Form(None),
    initial_chunk_size: int = Form(None),
    followup_chunk_size: int = Form(None),
    system_message: str = Form(None),
):
    """
    Handles form submissions for updating settings.

    This function updates the application settings based on form data submitted by the user.

    Args:
        request (Request): The incoming request object.
        anthropic_api_key (str, optional): The Anthropic API key.
        openai_api_key (str, optional): The OpenAI API key.
        together_api_key (str, optional): The Together.ai API key.
        selected_model (str, optional): The selected AI model.
        context_mode (str, optional): The context handling mode.
        initial_chunk_size (int, optional): The initial chunk size for RAG mode.
        followup_chunk_size (int, optional): The followup chunk size for RAG mode.
        system_message (str, optional): The system message for AI model interactions.

    Returns:
        JSONResponse: A JSON object indicating the success status of the update.
    """
    updated_data = {}
    if anthropic_api_key is not None:
        updated_data["anthropic_api_key"] = anthropic_api_key
    if openai_api_key is not None:
        updated_data["openai_api_key"] = openai_api_key
    if together_api_key is not None:
        updated_data["together_api_key"] = together_api_key
    if selected_model is not None:
        updated_data["selected_model"] = selected_model
    if context_mode is not None:
        updated_data["context_mode"] = context_mode
    if initial_chunk_size is not None:
        updated_data["initial_chunk_size"] = initial_chunk_size
    if followup_chunk_size is not None:
        updated_data["followup_chunk_size"] = followup_chunk_size
    if system_message is not None:
        updated_data["system_message"] = system_message
    
    update_settings(updated_data)
    return JSONResponse({"status": "success"})

@router.post("/save_conversation")
async def save_conversation_endpoint():
    """
    Saves the current conversation history to a file.

    This function triggers the saving of the conversation history and returns the file
    for download.

    Returns:
        FileResponse: The saved conversation history file for download.

    Raises:
        HTTPException: If there's an error saving the conversation.
    """
    try:
        file_path = save_conversation()
        return FileResponse(file_path, filename=os.path.basename(file_path))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save conversation: {str(e)}")

@router.get("/get_file_tree")
async def get_file_tree():
    """Get the file tree structure for the project."""
    try:
        # Use the set_context_folder function instead of hardcoding the path
        root_dir = set_context_folder()
        enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
        
        def count_tokens(content):
            return len(enc.encode(content))
            
        def build_tree(path):
            """Recursively build the file tree structure."""
            if path.name == '__pycache__':
                return None
                
            item = {
                "name": path.name,
                "path": str(path.relative_to(root_dir)),
                "type": "directory" if path.is_dir() else "file"
            }
            
            if path.is_dir():
                children = []
                total_tokens = 0
                
                for child in path.iterdir():
                    child_item = build_tree(child)
                    if child_item:
                        children.append(child_item)
                        total_tokens += child_item.get("tokens", 0)
                
                item["children"] = sorted(children, key=lambda x: (x["type"] == "file", x["name"]))
                item["tokens"] = total_tokens
            else:
                try:
                    content = path.read_text(encoding='utf-8')
                    item["tokens"] = count_tokens(content)
                except (UnicodeDecodeError, OSError):
                    item["tokens"] = 0
            
            return item
            
        tree = build_tree(root_dir)
        return {"fileTree": tree}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error building file tree: {str(e)}")

@router.get("/get_file_content")
async def get_file_content(path: str):
    """Get the content of a specific file."""
    try:
        # Use the set_context_folder function to get the root directory
        root_dir = set_context_folder()
        file_path = root_dir / path
        
        # Validate the path is within the project directory
        if not str(file_path.resolve()).startswith(str(root_dir.resolve())):
            raise HTTPException(status_code=403, detail="Access denied")
            
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found")
            
        # Read and return the file content
        try:
            content = file_path.read_text(encoding='utf-8')
            return {"content": content}
        except UnicodeDecodeError:
            return {"content": "Binary file - cannot display content"}
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")

@router.post("/calculate_tokens")
async def calculate_tokens(request: TokenCalcRequest):
    """
    Calculate token usage, cost, and color coding for the next request.
    Adjusts output length based on the selected model's capabilities.
    """
    try:
        model_name = request.model_name
        if not model_name:
            raise ValueError("Model name is required for token calculation.")

        system_message = request.system_message
        if not system_message:
            settings = load_settings()
            system_message = settings.system_message or ""

        # Determine the output length based on user input and model defaults
        output_length = request.output_length
        model_config = MODEL_CONFIG.get(model_name, {})
        max_possible_output = model_config.get("default_output_tokens", 8192)

        if output_length is None or output_length <= 0:
            # If user didn't specify, use the model's max potential output
            output_length = max_possible_output
        else:
            # Use user-specified length, but cap it at the model's max potential
            output_length = min(output_length, max_possible_output)

        logger.debug(f"Calculating tokens for model: {model_name} with output_length: {output_length}")

        # Calculate usage data using the determined output_length
        usage_data = calculate_usage_and_cost(
            model_name=model_name,
            conversation_history=request.conversation_history,
            user_input=request.user_input,
            rag_context=request.rag_context, # Note: RAG context token calculation might need refinement
            system_message=system_message,
            output_length=output_length # Pass the adjusted output length
        )

        # Add the actual max output token value to the response for the frontend
        usage_data["max_output_tokens"] = max_possible_output

        return usage_data

    except ValueError as ve:
         logger.warning(f"Value error calculating tokens: {str(ve)}")
         raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error calculating tokens: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error calculating tokens: {str(e)}")

"""
TODO: Future Implementation - Add Root Folder Feature

This endpoint will be responsible for handling the addition of new folders to the file tree.
Requirements:
1. Validate folder path and contents
2. Process files for token counting
3. Update file tree structure
4. Handle large folders and file type filtering
5. Integrate with context processing system
6. Provide progress feedback
7. Implement proper error handling
8. Consider security implications
"""
@router.post("/add_root_folder")
async def add_root_folder(request: Request):
    """
    [FUTURE IMPLEMENTATION]
    Adds a new root folder to the file tree.
    
    Args:
        request (Request): The incoming request object containing the folder path.
        
    Returns:
        JSONResponse: A JSON object indicating the success status of the operation.
        
    Raises:
        HTTPException: If there's an error adding the folder.
    """
    raise HTTPException(
        status_code=501,
        detail="This feature is not yet implemented."
    )