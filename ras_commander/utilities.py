"""
Utility functions for the ras_commander library.
"""
import shutil
import logging
import time
from pathlib import Path
from .project_config import ProjectConfig

class Utilities:
    """
    A class containing the utility functions for the ras_commander library.
    When integrating new functions that do not clearly fit into other classes, add them here.
    """
    @staticmethod
    def create_backup(file_path, backup_suffix="_backup"):
        """
        Create a backup of the specified file.
        Parameters:
        file_path (str): Path to the file to be backed up
        backup_suffix (str): Suffix to append to the backup file name
        Returns:
        str: Path to the created backup file
        """
        config = ProjectConfig()
        config.check_initialized()
        
        original_path = Path(file_path)
        backup_path = original_path.with_name(f"{original_path.stem}{backup_suffix}{original_path.suffix}")
        shutil.copy2(original_path, backup_path)
        print(f"Backup created: {backup_path}")
        return str(backup_path)

    @staticmethod
    def restore_from_backup(backup_path, remove_backup=True):
        """
        Restore a file from its backup.
        Parameters:
        backup_path (str): Path to the backup file
        remove_backup (bool): Whether to remove the backup file after restoration
        Returns:
        str: Path to the restored file
        """
        config = ProjectConfig()
        config.check_initialized()
        
        backup_path = Path(backup_path)
        original_path = backup_path.with_name(backup_path.stem.rsplit('_backup', 1)[0] + backup_path.suffix)
        shutil.copy2(backup_path, original_path)
        print(f"File restored: {original_path}")
        if remove_backup:
            backup_path.unlink()
            print(f"Backup removed: {backup_path}")
        return str(original_path)

    @staticmethod
    def safe_remove(file_path):
        """
        Safely remove a file if it exists.
        Parameters:
        file_path (str): Path to the file to be removed
        Returns:
        bool: True if the file was removed, False if it didn't exist
        """
        config = ProjectConfig()
        config.check_initialized()
        
        path = Path(file_path)
        if path.exists():
            path.unlink()
            print(f"File removed: {path}")
            return True
        else:
            print(f"File not found: {path}")
            return False

    @staticmethod
    def ensure_directory(directory_path):
        """
        Ensure that a directory exists, creating it if necessary.
        Parameters:
        directory_path (str): Path to the directory
        Returns:
        str: Path to the ensured directory
        """
        config = ProjectConfig()
        config.check_initialized()
        
        path = Path(directory_path)
        path.mkdir(parents=True, exist_ok=True)
        print(f"Directory ensured: {path}")
        return str(path)

    @staticmethod
    def list_files_with_extension(extension):
        """
        List all files in the project directory with a specific extension.
        Parameters:
        extension (str): File extension to filter (e.g., '.prj')
        Returns:
        list: List of file paths matching the extension
        """
        config = ProjectConfig()
        config.check_initialized()
        
        files = list(config.project_folder.glob(f"*{extension}"))
        return [str(file) for file in files]

    @staticmethod
    def get_file_size(file_path):
        """
        Get the size of a file in bytes.
        Parameters:
        file_path (str): Path to the file
        Returns:
        int: Size of the file in bytes
        """
        config = ProjectConfig()
        config.check_initialized()
        
        path = Path(file_path)
        if path.exists():
            size = path.stat().st_size
            print(f"File size: {size} bytes")
            return size
        else:
            print(f"File not found: {path}")
            return None

    @staticmethod
    def get_modification_time(file_path):
        """
        Get the last modification time of a file.
        Parameters:
        file_path (str): Path to the file
        Returns:
        float: Last modification time as a timestamp
        """
        config = ProjectConfig()
        config.check_initialized()
        
        path = Path(file_path)
        if path.exists():
            mtime = path.stat().st_mtime
            print(f"Last modified: {mtime}")
            return mtime
        else:
            print(f"File not found: {path}")
            return None

    @staticmethod
    def get_plan_path(current_plan_number):
        """
        Get the path for a plan file with a given plan number.
        Parameters:
        current_plan_number (str or int): The plan number (01 to 99)
        Returns:
        str: Full path to the plan file with the given plan number
        """
        config = ProjectConfig()
        config.check_initialized()
        
        current_plan_number = f"{int(current_plan_number):02d}"  # Ensure two-digit format
        plan_name = f"{config.project_name}.p{current_plan_number}"
        return str(config.project_folder / plan_name)

    @staticmethod
    def retry_remove_folder(folder_path: str, max_attempts: int = 5, initial_delay: float = 1.0) -> bool:
        """
        Attempts to remove a folder with retry logic and exponential backoff.
        Args:
            folder_path (str): Path to the folder to be removed.
            max_attempts (int): Maximum number of removal attempts.
            initial_delay (float): Initial delay between attempts in seconds.
        Returns:
            bool: True if the folder was successfully removed, False otherwise.
        """
        config = ProjectConfig()
        config.check_initialized()
        
        folder = Path(folder_path)
        for attempt in range(max_attempts):
            try:
                if folder.exists():
                    shutil.rmtree(folder)
                return True
            except PermissionError:
                if attempt < max_attempts - 1:
                    delay = initial_delay * (2 ** attempt)  # Exponential backoff
                    logging.warning(f"Failed to remove folder {folder}. Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    logging.error(f"Failed to remove folder {folder} after {max_attempts} attempts. Skipping.")
                    return False
        return False
