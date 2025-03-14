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
from typing import Optional, List
from config.config import load_settings, update_settings
from utils.conversation import add_to_history, get_full_conversation, save_conversation
from utils.context_processing import prepare_full_prompt, update_conversation_history, initialize_context
from utils.cost_estimation import create_pricing_df, estimate_cost, calculate_usage_and_cost
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
    Handles chat interactions with the AI model, supporting streaming responses.
    """
    conversation_id = message.get("conversation_id", str(uuid.uuid4()))
    logger.info(f"Starting chat interaction - Conversation ID: {conversation_id}")
    
    try:
        # Validate input
        user_message = message.get("message")
        if not user_message:
            logger.warning("Empty message received")
            raise HTTPException(status_code=400, detail="No message provided.")
            
        # Get selected files for context if provided
        selected_files = message.get("selectedFiles", [])
        logger.debug(f"Selected files for context: {selected_files}")
        
        # Add user message to history
        add_to_history("user", user_message)
        logger.debug(f"Added user message to history: {user_message[:100]}...")
        
        # Load settings and prepare context
        settings = load_settings()
        selected_model = settings.selected_model
        logger.info(f"Using model: {selected_model}")
        
        # Set output length based on model
        output_length = None
        if selected_model == "claude-3-7-sonnet-20250219":
            output_length = 32000  # Support for extended output length (32k tokens)
        
        # Prepare prompt with conversation history
        full_prompt = prepare_full_prompt(
            user_message,
            selected_files,
            conversation_id
        )
        logger.debug(f"Prepared prompt length: {len(full_prompt)} characters")
        
        # Update conversation history
        update_conversation_history(conversation_id, "user", user_message)
        
        # Calculate token usage and validate against limits
        usage_data = calculate_usage_and_cost(
            model_name=selected_model,
            conversation_history=get_full_conversation(),
            user_input=user_message,
            rag_context="".join(selected_files),
            system_message=settings.system_message,
            output_length=output_length
        )
        
        # Check if we're exceeding token limits
        if usage_data["remaining_tokens"] < 0:
            raise HTTPException(
                status_code=400,
                detail="Request exceeds maximum token limit. Please reduce context or message length."
            )
            
        logger.info(f"Token usage - Input: {usage_data['total_tokens_used']}, Output: {usage_data['output_length']}")
        logger.info(f"Estimated cost: ${usage_data['cost_estimate']:.6f}")

        # Get provider info from pricing data
        pricing_info = create_pricing_df(selected_model)
        provider = pricing_info["provider"]
        logger.info(f"Using provider: {provider}")

        async def stream_response():
            """Generator for streaming the AI response"""
            accumulated_response = []
            try:
                if provider == "anthropic":
                    logger.info("Using Anthropic API")
                    client = get_anthropic_client(settings.anthropic_api_key)
                    logger.info(f"Sending Anthropic API request with model: {selected_model}")
                    async for chunk in anthropic_stream_response(
                        client, 
                        full_prompt,
                        system_message=settings.system_message,
                        max_tokens=usage_data["output_length"]
                    ):
                        accumulated_response.append(chunk)
                        yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                        
                elif provider == "openai":
                    logger.info("Using OpenAI API")
                    client = get_openai_client(settings.openai_api_key)
                    messages = [
                        {"role": "system", "content": settings.system_message or "You are a helpful AI assistant."},
                        {"role": "user", "content": full_prompt}
                    ]
                    logger.info(f"Sending OpenAI API request with model: {selected_model}")
                    async for chunk in openai_stream_response(
                        client, 
                        selected_model, 
                        messages,
                        max_tokens=usage_data["output_length"]
                    ):
                        accumulated_response.append(chunk)
                        yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                        
                elif provider == "together":
                    logger.info("Using Together.ai API")
                    messages = [
                        {"role": "system", "content": settings.system_message or "You are a helpful AI assistant."},
                        {"role": "user", "content": full_prompt}
                    ]
                    logger.info(f"Sending Together.ai API request with model: {selected_model}")
                    response = together_chat_completion(
                        settings.together_api_key,
                        selected_model,
                        messages,
                        max_tokens=usage_data["output_length"]
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
                
                # Add complete response to history
                complete_response = "".join(accumulated_response)
                logger.debug(f"Complete response length: {len(complete_response)} characters")
                add_to_history("assistant", complete_response)
                
                # Update history with assistant response
                update_conversation_history(conversation_id, "assistant", complete_response)
                
                # Send the cost estimate as a final message
                yield f"data: {json.dumps({'cost': usage_data['cost_estimate'], 'provider': provider})}\n\n"
                logger.info(f"Chat interaction completed successfully - Conversation ID: {conversation_id}")
                
            except Exception as e:
                error_msg = f"Error during streaming: {str(e)}"
                logger.error(error_msg)
                log_error(e, "Streaming error")
                yield f"data: {json.dumps({'error': error_msg})}\n\n"

        return StreamingResponse(
            stream_response(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    except Exception as e:
        log_error(e, f"Chat endpoint error - Conversation ID: {conversation_id}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

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
        # Get the parent directory of the current project
        root_dir = Path(__file__).parent.parent.parent
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
        # Get the project root directory
        root_dir = Path(__file__).parent.parent.parent
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
    
    Args:
        request (TokenCalcRequest): The request containing model and content information
        
    Returns:
        dict: Usage data including token counts, costs, and color coding
    """
    try:
        # Get settings for system message if not provided
        if not request.system_message:
            settings = load_settings()
            request.system_message = settings.system_message
            
        # Set default output length based on model if not specified
        if not request.output_length:
            if request.model_name == "claude-3-7-sonnet-20250219":
                request.output_length = 32000  # Support for extended output length (32k tokens)
            else:
                request.output_length = 8192  # Default for other models
            
        # Calculate usage data
        usage_data = calculate_usage_and_cost(
            model_name=request.model_name,
            conversation_history=request.conversation_history,
            user_input=request.user_input,
            rag_context=request.rag_context,
            system_message=request.system_message,
            output_length=request.output_length
        )
        
        return usage_data
        
    except Exception as e:
        logger.error(f"Error calculating tokens: {str(e)}")
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