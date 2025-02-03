"""
Logging configuration for the Library Assistant.

This module provides centralized logging configuration for the entire application.
It sets up both file and console logging with proper formatting and log levels.
"""

from fastapi import APIRouter, Request
import logging
import os
from datetime import datetime
import traceback
import sys

router = APIRouter()

# Determine the path for the log folder relative to assistant.py
log_folder_path = os.path.join(os.path.dirname(__file__), '..', 'log_folder')
os.makedirs(log_folder_path, exist_ok=True)

# Configure logging
log_file_path = os.path.join(log_folder_path, 'library_assistant.log')

# Create a logger
logger = logging.getLogger("library_assistant")
logger.setLevel(logging.DEBUG)  # Set to DEBUG to capture all levels

# Create handlers
file_handler = logging.FileHandler(log_file_path)
console_handler = logging.StreamHandler(sys.stdout)  # Explicitly use stdout

# Set levels for handlers
file_handler.setLevel(logging.DEBUG)  # Debug and above for file
console_handler.setLevel(logging.INFO)  # Info and above for console

# Create formatters
file_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s'
)
console_formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s'
)

# Apply formatters
file_handler.setFormatter(file_formatter)
console_handler.setFormatter(console_formatter)

# Add handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Prevent log propagation to avoid duplicate logs
logger.propagate = False

def log_error(error: Exception, context: str = ""):
    """
    Log an error with full traceback and context.
    
    Args:
        error: The exception to log
        context: Additional context about where/when the error occurred
    """
    error_msg = f"{context} - {str(error)}" if context else str(error)
    logger.error(f"Error: {error_msg}")
    logger.debug(f"Traceback:\n{''.join(traceback.format_tb(error.__traceback__))}")

def log_request_response(request_data: dict, response_data: dict, endpoint: str):
    """
    Log request and response data for API calls.
    
    Args:
        request_data: The data sent in the request
        response_data: The data received in the response
        endpoint: The API endpoint being called
    """
    logger.debug(f"API Call to {endpoint}")
    logger.debug(f"Request: {request_data}")
    logger.debug(f"Response: {response_data}")

@router.post("/log")
async def log_message(request: Request):
    """
    Endpoint for client-side logging.
    
    Args:
        request: The incoming request object containing the log message
    """
    try:
        data = await request.json()
        message = data.get("message", "")
        level = data.get("level", "info").lower()
        
        # Map string level to logging level
        level_map = {
            "debug": logger.debug,
            "info": logger.info,
            "warning": logger.warning,
            "error": logger.error,
            "critical": logger.critical
        }
        
        log_func = level_map.get(level, logger.info)
        log_func(f"Client Log: {message}")
        
        return {"status": "success", "timestamp": datetime.now().isoformat()}
    except Exception as e:
        log_error(e, "Error processing client log message")
        return {"status": "error", "message": str(e)} 