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
- POST /refresh_context: Refreshes the context processing for both RAG and full context modes.
"""

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from config.config import load_settings, update_settings
from utils.conversation import add_to_history, get_full_conversation, save_conversation
from utils.context_processing import prepare_full_prompt, update_conversation_history, initialize_rag_context
from utils.cost_estimation import create_pricing_df, estimate_cost
from utils.file_handling import set_context_folder
from api.anthropic import anthropic_stream_response, get_anthropic_client
from api.openai import openai_stream_response, get_openai_client
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
    try:
        # Validate input
        user_message = message.get("message")
        if not user_message:
            raise HTTPException(status_code=400, detail="No message provided.")
            
        # Get selected files for context if provided
        selected_files = message.get("selectedFiles", [])
        
        # Add user message to history
        add_to_history("user", user_message)
        
        # Load settings and prepare context
        settings = load_settings()
        selected_model = settings.selected_model
        
        # Get or generate conversation ID
        conversation_id = message.get("conversation_id", str(uuid.uuid4()))
        
        # Prepare prompt with conversation history
        full_prompt = prepare_full_prompt(
            user_message,
            selected_files if settings.context_mode == 'full_context' else None,
            conversation_id
        )
        
        # Update conversation history
        update_conversation_history(conversation_id, "user", user_message)
        
        # Estimate token usage and cost
        enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
        input_tokens = len(enc.encode(full_prompt))
        output_tokens = 1000  # Assuming average response length
        
        # Get pricing info
        pricing_info = create_pricing_df(selected_model)
        pricing_df = pricing_info["pricing_df"]
        provider = pricing_info["provider"]
        
        estimated_cost = estimate_cost(input_tokens, output_tokens, pricing_df)

        async def stream_response():
            """Generator for streaming the AI response"""
            accumulated_response = []
            try:
                if provider == "anthropic":
                    client = get_anthropic_client(settings.anthropic_api_key)
                    async for chunk in anthropic_stream_response(client, full_prompt):
                        accumulated_response.append(chunk)
                        yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                        
                elif provider == "openai":
                    client = get_openai_client(settings.openai_api_key)
                    messages = [
                        {"role": "system", "content": "You are a helpful AI assistant."},
                        {"role": "user", "content": full_prompt}
                    ]
                    async for chunk in openai_stream_response(client, selected_model, messages):
                        accumulated_response.append(chunk)
                        yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                else:
                    raise HTTPException(status_code=400, detail="Unsupported provider selected.")
                
                # Add complete response to history
                complete_response = "".join(accumulated_response)
                add_to_history("assistant", complete_response)
                
                # Update history with assistant response
                update_conversation_history(conversation_id, "assistant", complete_response)
                
                # Send the cost estimate as a final message
                yield f"data: {json.dumps({'cost': estimated_cost, 'provider': provider})}\n\n"
                
            except Exception as e:
                error_msg = f"Error during streaming: {str(e)}"
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
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

@router.post("/submit")
async def handle_submit(
    request: Request,
    anthropic_api_key: str = Form(None),
    openai_api_key: str = Form(None),
    selected_model: str = Form(None),
    context_mode: str = Form(None),
    initial_chunk_size: int = Form(None),
    followup_chunk_size: int = Form(None),
):
    """
    Handles form submissions for updating settings.

    This function updates the application settings based on form data submitted by the user.

    Args:
        request (Request): The incoming request object.
        anthropic_api_key (str, optional): The Anthropic API key.
        openai_api_key (str, optional): The OpenAI API key.
        selected_model (str, optional): The selected AI model.
        context_mode (str, optional): The context handling mode.
        initial_chunk_size (int, optional): The initial chunk size for RAG mode.
        followup_chunk_size (int, optional): The followup chunk size for RAG mode.

    Returns:
        JSONResponse: A JSON object indicating the success status of the update.
    """
    updated_data = {}
    if anthropic_api_key is not None:
        updated_data["anthropic_api_key"] = anthropic_api_key
    if openai_api_key is not None:
        updated_data["openai_api_key"] = openai_api_key
    if selected_model is not None:
        updated_data["selected_model"] = selected_model
    if context_mode is not None:
        updated_data["context_mode"] = context_mode
    if initial_chunk_size is not None:
        updated_data["initial_chunk_size"] = initial_chunk_size
    if followup_chunk_size is not None:
        updated_data["followup_chunk_size"] = followup_chunk_size
    
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
                
                cursorrules = path / '.cursorrules'
                if cursorrules.exists():
                    cursorrules_item = build_tree(cursorrules)
                    if cursorrules_item:
                        children.append(cursorrules_item)
                        total_tokens += cursorrules_item.get("tokens", 0)
                
                for child in path.iterdir():
                    if child.name != '.cursorrules':
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

@router.post("/refresh_context")
async def refresh_context():
    """
    Refreshes the context processing for both RAG and full context modes.
    """
    try:
        await initialize_rag_context()
        return JSONResponse({
            "status": "success",
            "message": "Context refreshed successfully",
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to refresh context: {str(e)}"
        )