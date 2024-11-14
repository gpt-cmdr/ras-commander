"""
Configuration module for the Library Assistant.

This module provides functions for loading and updating settings,
as well as defining default settings for the application.

Functions:
- load_settings(): Loads the current settings from the database or initializes with defaults.
- update_settings(data): Updates the settings in the database with new values.

Constants:
- DEFAULT_SETTINGS: A dictionary containing the default settings for the application.
"""

import json
from sqlalchemy.orm import sessionmaker
from database.models import Settings, engine

# Create a SessionLocal class for database sessions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Default settings for the application
DEFAULT_SETTINGS = {
    "anthropic_api_key": "",
    "openai_api_key": "",
    "selected_model": "",
    "context_mode": "",
    "omit_folders": [
        "Bald Eagle Creek", 
        "__pycache__", 
        ".git", 
        ".github", 
        "tests", 
        "build", 
        "dist", 
        "ras_commander.egg-info", 
        "venv", 
        "example_projects", 
        "llm_summary", 
        "misc", 
        "future", 
        "ai_tools",
        "docs"
        "Example_Projects_6_6"
        "html"
        "data"
    ],
    "omit_extensions": [
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.svg', '.ico',
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.zip', '.rar', '.7z', '.tar', '.gz',
        '.exe', '.dll', '.so', '.dylib',
        '.pyc', '.pyo', '.pyd',
        '.class',
        '.log', '.tmp', '.bak', '.swp',
        '.bat', '.sh', '.html',
    ],
    "omit_files": [
        'FunctionList.md',
        'DS_Store',
        'Thumbs.db',
        'llmsummarize',
        'example_projects.zip',
        '11_accessing_example_projects.ipynb',
        'Example_Projects_6_5.zip',
        'github_code_assistant.ipynb',
        'example_projects.ipynb',
        '11_Using_RasExamples.ipynb',
        'example_projects.csv',
        'rascommander_code_assistant.ipynb',
        'RasExamples.py'
    ],
    "chunk_level": "function",
    "initial_chunk_size": 32000,
    "followup_chunk_size": 16000
}

def load_settings():
    """
    Loads the current settings from the database or initializes with defaults.

    This function queries the database for existing settings. If no settings are found,
    it initializes the database with the default settings. The settings are stored
    as a singleton record in the database.

    Returns:
        Settings: An instance of the Settings model containing the current settings.
    """
    db = SessionLocal()
    settings = db.query(Settings).filter(Settings.id == "singleton").first()
    if not settings:
        # Initialize with default settings
        settings = Settings(
            id="singleton",
            **{key: json.dumps(value) if isinstance(value, list) else value 
               for key, value in DEFAULT_SETTINGS.items()}
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    db.close()
    return settings

def update_settings(data):
    """
    Updates the settings in the database with new values.

    This function takes a dictionary of settings to update, queries the database
    for the existing settings, and updates the values accordingly. For list-type
    settings (omit_folders, omit_extensions, omit_files), the values are JSON-encoded
    before storage.

    Args:
        data (dict): A dictionary containing the settings to update.
                     Keys should match the attribute names in the Settings model.

    Note:
        This function does not return any value. It directly updates the database.
    """
    db = SessionLocal()
    settings = db.query(Settings).filter(Settings.id == "singleton").first()
    for key, value in data.items():
        if key in ["omit_folders", "omit_extensions", "omit_files"]:
            setattr(settings, key, json.dumps(value))
        else:
            setattr(settings, key, value)
    db.commit()
    db.close()
