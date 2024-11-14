from fastapi import APIRouter, Request
import logging
import os

router = APIRouter()

# Determine the path for the log folder relative to assistant.py
log_folder_path = os.path.join(os.path.dirname(__file__), '..', 'log_folder')
os.makedirs(log_folder_path, exist_ok=True)

# Configure logging
log_file_path = os.path.join(log_folder_path, 'client_logs.log')

# Create a logger
logger = logging.getLogger("clientLogger")
logger.setLevel(logging.INFO)

# Create handlers
file_handler = logging.FileHandler(log_file_path)
console_handler = logging.StreamHandler()

# Set level for handlers
file_handler.setLevel(logging.INFO)
console_handler.setLevel(logging.INFO)

# Create a logging format
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Add handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(console_handler)

@router.post("/log")
async def log_message(request: Request):
    data = await request.json()
    message = data.get("message", "")
    logger.info(message)
    return {"status": "success"} 