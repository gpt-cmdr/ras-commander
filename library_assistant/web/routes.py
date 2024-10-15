"""
Web routes for the Library Assistant.

This module defines the FastAPI routes for the web interface of the Library Assistant.
It handles user interactions, API calls, and serves the HTML template.

Routes:
- GET /: Serves the main page of the application.
- POST /chat: Handles chat interactions with the AI model.
- POST /submit: Handles form submissions for updating settings.
- POST /save_conversation: Saves the current conversation history to a file.
"""

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from config.config import load_settings, update_settings
from utils.conversation import add_to_history, get_full_conversation, save_conversation
from utils.context_processing import prepare_full_prompt
from utils.cost_estimation import create_pricing_df, estimate_cost
from api.anthropic import anthropic_stream_response, get_anthropic_client
from api.openai import openai_stream_response, get_openai_client
import json
import tiktoken
import os

router = APIRouter()

# Set up Jinja2 templates
templates = Jinja2Templates(directory="web/templates")

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
    Handles chat interactions with the AI model.

    This function processes user messages, prepares the context, sends the query to the
    appropriate AI model, and returns the response along with cost estimates.

    Args:
        request (Request): The incoming request object.
        message (dict): A dictionary containing the user's message.

    Returns:
        JSONResponse: A JSON object containing the AI's response and cost estimate.

    Raises:
        HTTPException: If there's an error processing the request.
    """
    user_message = message.get("message")
    if not user_message:
        raise HTTPException(status_code=400, detail="No message provided.")
    
    try:
        # Add user message to history
        add_to_history("user", user_message)
        
        # Load settings
        settings = load_settings()
        selected_model = settings.selected_model
        
        # Prepare the full prompt
        full_prompt = prepare_full_prompt(user_message)
        
        # Estimate cost (simplified for this example)
        enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
        input_tokens = len(enc.encode(full_prompt))
        output_tokens = 1000  # Assuming an average response length
        
        # Create pricing dataframe
        pricing_info = create_pricing_df(selected_model)
        pricing_df = pricing_info["pricing_df"]
        provider = pricing_info["provider"]
        
        estimated_cost = estimate_cost(input_tokens, output_tokens, pricing_df)

        # Prepare the streaming response
        async def response_generator():
            if provider == "anthropic":
                anthropic_api_key = settings.anthropic_api_key
                client = get_anthropic_client(anthropic_api_key)
                async for chunk in anthropic_stream_response(client, full_prompt):
                    yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            elif provider == "openai":
                openai_api_key = settings.openai_api_key
                client = get_openai_client(openai_api_key)
                messages = [
                    {"role": "system", "content": "You are a helpful AI assistant."},
                    {"role": "user", "content": full_prompt}
                ]
                async for chunk in openai_stream_response(client, selected_model, messages):
                    yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            else:
                raise HTTPException(status_code=400, detail="Unsupported provider selected.")

        return StreamingResponse(response_generator(), media_type="text/event-stream")
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
