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

from sqlalchemy import create_engine, Column, String, Text, Integer
from sqlalchemy.orm import declarative_base

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
        selected_model (str): The currently selected AI model.
        context_mode (str): The context handling mode (e.g., 'full_context' or 'rag').
        omit_folders (str): JSON string of folders to omit from processing.
        omit_extensions (str): JSON string of file extensions to omit from processing.
        omit_files (str): JSON string of specific files to omit from processing.
        chunk_level (str): The level at which to chunk text (e.g., 'function').
        initial_chunk_size (int): The initial size of text chunks for processing.
        followup_chunk_size (int): The size of follow-up chunks for processing.
    """

    __tablename__ = "settings"

    id = Column(String, primary_key=True, index=True, default="singleton")
    anthropic_api_key = Column(Text, nullable=True)
    openai_api_key = Column(Text, nullable=True)
    selected_model = Column(String, nullable=True)
    context_mode = Column(String, nullable=True)
    omit_folders = Column(Text, nullable=True)
    omit_extensions = Column(Text, nullable=True)
    omit_files = Column(Text, nullable=True)
    chunk_level = Column(String, nullable=True)
    initial_chunk_size = Column(Integer, default=32000)
    followup_chunk_size = Column(Integer, default=16000)

# Create the database tables
Base.metadata.create_all(bind=engine)
