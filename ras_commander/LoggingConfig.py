# logging_config.py

import logging
import logging.handlers
from pathlib import Path
import functools

# Define log levels
DEBUG = logging.DEBUG
INFO = logging.INFO
WARNING = logging.WARNING
ERROR = logging.ERROR
CRITICAL = logging.CRITICAL


_logging_setup_done = False

def setup_logging(log_file=None, log_level=logging.INFO):
    """Set up logging configuration for the ras-commander library."""
    global _logging_setup_done
    if _logging_setup_done:
        return
    
    # Define log format
    log_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Configure console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)

    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(console_handler)

    # Configure file handler if log_file is provided
    if log_file:
        log_dir = Path('logs')
        log_dir.mkdir(exist_ok=True)
        log_file_path = log_dir / log_file

        file_handler = logging.handlers.RotatingFileHandler(
            log_file_path, maxBytes=10*1024*1024, backupCount=5
        )
        file_handler.setFormatter(log_format)
        root_logger.addHandler(file_handler)
    
    _logging_setup_done = True

def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the specified name.
    
    Args:
        name: The name for the logger, typically __name__ or module path
        
    Returns:
        logging.Logger: Configured logger instance
    """
    logger = logging.getLogger(name)
    if not logger.handlers:  # Only add handler if none exists
        setup_logging()  # Ensure logging is configured
    return logger

def log_call(logger=None):
    """Decorator to log function calls."""
    def get_logger():
        # Check if logger is None or doesn't have a debug method
        if logger is None or not hasattr(logger, 'debug'):
            return logging.getLogger(__name__)
        return logger

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            log = get_logger()
            log.debug(f"Calling {func.__name__}")
            result = func(*args, **kwargs)
            log.debug(f"Finished {func.__name__}")
            return result
        return wrapper
    
    # Check if we're being called as @log_call or @log_call()
    if callable(logger):
        return decorator(logger)
    return decorator

# Set up logging when this module is imported
setup_logging()