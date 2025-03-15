"""
Database models for the Library Assistant.

This module defines the SQLAlchemy ORM models used for storing application settings.

Classes:
- Base: The declarative base class for SQLAlchemy models.
- Settings: The model representing application settings.

Constants:
- DATABASE_URL: The URL for the SQLite database.
- engine: The SQLAlchemy engine instance.
"""

from sqlalchemy import create_engine, Column, String, Text, Integer, inspect, text
from sqlalchemy.orm import declarative_base
import logging

# Define the database URL
DATABASE_URL = "sqlite:///./settings.db"

# Create the SQLAlchemy engine
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# Create the declarative base class
Base = declarative_base()

class Settings(Base):
    """
    SQLAlchemy ORM model for storing application settings.

    This class represents a single row in the settings table, which stores
    all configuration options for the Library Assistant application.

    Attributes:
        id (str): Primary key, set to "singleton" as there's only one settings record.
        anthropic_api_key (str): API key for Anthropic services.
        openai_api_key (str): API key for OpenAI services.
        together_api_key (str): API key for Together.ai services.
        selected_model (str): The currently selected AI model.
        omit_folders (str): JSON string of folders to omit from processing.
        omit_extensions (str): JSON string of file extensions to omit from processing.
        omit_files (str): JSON string of specific files to omit from processing.
        system_message (str): The system message used for AI model interactions.
    """

    __tablename__ = "settings"

    id = Column(String, primary_key=True, index=True, default="singleton")
    anthropic_api_key = Column(Text, nullable=True)
    openai_api_key = Column(Text, nullable=True)
    together_api_key = Column(Text, nullable=True)
    selected_model = Column(String, nullable=True)
    omit_folders = Column(Text, nullable=True)
    omit_extensions = Column(Text, nullable=True)
    omit_files = Column(Text, nullable=True)
    system_message = Column(Text, nullable=True, default="")

def migrate_database():
    """
    Handles database migrations for new columns.
    This function checks for missing columns and adds them if necessary.
    """
    inspector = inspect(engine)
    existing_columns = [col['name'] for col in inspector.get_columns('settings')]
    
    # Check if system_message column exists
    if 'system_message' not in existing_columns:
        logging.info("Adding system_message column to settings table")
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE settings ADD COLUMN system_message TEXT DEFAULT 'You are a helpful AI assistant.'"
            ))
            conn.commit()
    
    # Add together_api_key column if it doesn't exist
    if 'together_api_key' not in existing_columns:
        logging.info("Adding together_api_key column to settings table")
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE settings ADD COLUMN together_api_key TEXT"
            ))
            conn.commit()

# Create the database tables and handle migrations
Base.metadata.create_all(bind=engine)
migrate_database()
