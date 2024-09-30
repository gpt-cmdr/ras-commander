import os
from pathlib import Path
from typing import Optional
from ras_commander import get_logger, log_call

logger = get_logger(__name__)

class RasGpt:
    """
    A class containing helper functions for the RAS Commander GPT.
    """
    
    # READ Functions to allow GPT to read library files quickly 

    @classmethod
    @log_call
    def read_library_guide(cls) -> Optional[str]:
        """
        Reads and returns the contents of the Comprehensive_Library_Guide.md file.

        Returns:
            Optional[str]: The contents of the file, or None if the file is not found.
        """
        file_path = Path(__file__).parent.parent / "docs" / "Comprehensive_Library_Guide.md"
        return cls._read_file(file_path)


    # ADD FOR read_reaadme and read_function_list
    # Need to add a function list separate from the Library Guide
    
    # ADD for read_example_list which will read the example folder README.ModuleNotFoundError





    @classmethod
    @log_call
    def read_style_guide(cls) -> Optional[str]:
        """
        Reads and returns the contents of the STYLE_GUIDE.md file.

        Returns:
            Optional[str]: The contents of the file, or None if the file is not found.
        """
        file_path = Path(__file__).parent.parent / "docs" / "STYLE_GUIDE.md"
        return cls._read_file(file_path)
    
    
    # READ CLASS FILE FUNCTIONS: 

    @classmethod
    @log_call
    def read_class_rascmdr(cls) -> Optional[str]:
        """
        Reads and returns the contents of the RasCmdr.py file.

        Returns:
            Optional[str]: The contents of the file, or None if the file is not found.
        """
        file_path = Path(__file__).parent / "RasCmdr.py"
        return cls._read_file(file_path)
    
    # add one for each class file 
    
    
    
    
    
    # Public Helper Functions: 
    
    
    @classmethod
    @log_call
    def get_file_structure(cls, directory: Optional[str] = None) -> str:
        """
        Returns a string representation of the file structure of the ras_commander package.

        Args:
            directory (Optional[str]): The directory to start from. If None, uses the package root.

        Returns:
            str: A string representation of the file structure.
        """
        if directory is None:
            directory = Path(__file__).parent

        return cls._get_directory_structure(directory)
    
    
      
    
    # Private Helper Functions: 
    
    @staticmethod
    def _read_file(file_path: Path) -> Optional[str]:
        """
        Helper method to read the contents of a file.

        Args:
            file_path (Path): The path to the file to be read.

        Returns:
            Optional[str]: The contents of the file, or None if the file is not found.
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()
        except FileNotFoundError:
            logger.error(f"File not found: {file_path}")
            return None
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {str(e)}")
            return None


    @staticmethod
    def _get_directory_structure(directory: Path, prefix: str = "") -> str:
        """
        Helper method to recursively build the directory structure string.

        Args:
            directory (Path): The directory to process.
            prefix (str): The prefix to use for the current level.

        Returns:
            str: A string representation of the directory structure.
        """
        if not directory.is_dir():
            return ""

        output = []
        for item in sorted(directory.iterdir()):
            if item.name.startswith('.'):
                continue
            if item.is_dir():
                output.append(f"{prefix}{item.name}/")
                output.append(RasGpt._get_directory_structure(item, prefix + "  "))
            else:
                output.append(f"{prefix}{item.name}")

        return "\n".join(output)
