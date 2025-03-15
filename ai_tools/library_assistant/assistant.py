"""
Main entry point for the Library Assistant application.

This module initializes the FastAPI application, sets up the necessary routes,
and provides functions to open the browser and run the application.

Functions:
- open_browser(): Opens the default web browser to the application URL.
- run_app(): Starts the FastAPI application using uvicorn.
"""

import os
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from web.routes import router
import webbrowser
from utils.context_processing import initialize_context
from api.logging import logger

# Initialize FastAPI application
print("Initializing FastAPI")
app = FastAPI(
    title="Library Assistant",
    description="An AI-powered assistant for managing and querying library content.",
    version="1.0.0"
)

# Create necessary directories if they don't exist
os.makedirs("web/templates", exist_ok=True)
os.makedirs("web/static", exist_ok=True)

# Mount the static files directory
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# Include the router from web/routes.py
app.include_router(router)

def open_browser():
    """
    Opens the default web browser to the application URL.
    
    This function is called when the application starts to provide
    easy access to the web interface.
    """
    webbrowser.open("http://127.0.0.1:8000")

def run_app():
    """
    Starts the FastAPI application using uvicorn.
    
    This function configures and runs the uvicorn server with the
    FastAPI application.
    """
    logger.info("Starting Library Assistant application")
    uvicorn.run(app, host="127.0.0.1", port=8000)

if __name__ == "__main__":
    # Initialize context at startup
    try:
        logger.info("Initializing context...")
        initialize_context()
        logger.info("Context initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize context: {str(e)}")
        raise

    # Open the browser
    logger.info("Opening web browser")
    open_browser()

    # Run the app
    logger.info("Starting application server")
    run_app()
