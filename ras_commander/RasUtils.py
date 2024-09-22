"""
Utility functions for the ras-commander library.
"""
import os
import shutil
import logging
import time
from pathlib import Path
from .RasPrj import ras
from typing import Union, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class RasUtils:
    """
    A class containing utility functions for the ras-commander library.
    When integrating new functions that do not clearly fit into other classes, add them here.
    """

    @staticmethod
    def create_backup(file_path: Path, backup_suffix: str = "_backup", ras_object=None) -> Path:
        """
        Create a backup of the specified file.

        Parameters:
        file_path (Path): Path to the file to be backed up
        backup_suffix (str): Suffix to append to the backup file name
        ras_object (RasPrj, optional): RAS object to use. If None, uses the default ras object.

        Returns:
        Path: Path to the created backup file

        Example:
        >>> backup_path = RasUtils.create_backup(Path("project.prj"))
        >>> print(f"Backup created at: {backup_path}")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        original_path = Path(file_path)
        backup_path = original_path.with_name(f"{original_path.stem}{backup_suffix}{original_path.suffix}")
        try:
            shutil.copy2(original_path, backup_path)
            logging.info(f"Backup created: {backup_path}")
        except Exception as e:
            logging.error(f"Failed to create backup for {original_path}: {e}")
            raise
        return backup_path

    @staticmethod
    def restore_from_backup(backup_path: Path, remove_backup: bool = True, ras_object=None) -> Path:
        """
        Restore a file from its backup.

        Parameters:
        backup_path (Path): Path to the backup file
        remove_backup (bool): Whether to remove the backup file after restoration
        ras_object (RasPrj, optional): RAS object to use. If None, uses the default ras object.

        Returns:
        Path: Path to the restored file

        Example:
        >>> restored_path = RasUtils.restore_from_backup(Path("project_backup.prj"))
        >>> print(f"File restored to: {restored_path}")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        backup_path = Path(backup_path)
        if '_backup' not in backup_path.stem:
            logging.error(f"Backup suffix '_backup' not found in {backup_path.name}")
            raise ValueError(f"Backup suffix '_backup' not found in {backup_path.name}")
        
        original_stem = backup_path.stem.rsplit('_backup', 1)[0]
        original_path = backup_path.with_name(f"{original_stem}{backup_path.suffix}")
        try:
            shutil.copy2(backup_path, original_path)
            logging.info(f"File restored: {original_path}")
            if remove_backup:
                backup_path.unlink()
                logging.info(f"Backup removed: {backup_path}")
        except Exception as e:
            logging.error(f"Failed to restore from backup {backup_path}: {e}")
            raise
        return original_path

    @staticmethod
    def create_directory(directory_path: Path, ras_object=None) -> Path:
        """
        Ensure that a directory exists, creating it if necessary.

        Parameters:
        directory_path (Path): Path to the directory
        ras_object (RasPrj, optional): RAS object to use. If None, uses the default ras object.

        Returns:
        Path: Path to the ensured directory

        Example:
        >>> ensured_dir = RasUtils.create_directory(Path("output"))
        >>> print(f"Directory ensured: {ensured_dir}")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        path = Path(directory_path)
        try:
            path.mkdir(parents=True, exist_ok=True)
            logging.info(f"Directory ensured: {path}")
        except Exception as e:
            logging.error(f"Failed to create directory {path}: {e}")
            raise
        return path

    @staticmethod
    def find_files_by_extension(extension: str, ras_object=None) -> list:
        """
        List all files in the project directory with a specific extension.

        Parameters:
        extension (str): File extension to filter (e.g., '.prj')
        ras_object (RasPrj, optional): RAS object to use. If None, uses the default ras object.

        Returns:
        list: List of file paths matching the extension

        Example:
        >>> prj_files = RasUtils.find_files_by_extension('.prj')
        >>> print(f"Found {len(prj_files)} .prj files")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        try:
            files = list(ras_obj.project_folder.glob(f"*{extension}"))
            file_list = [str(file) for file in files]
            logging.info(f"Found {len(file_list)} files with extension '{extension}' in {ras_obj.project_folder}")
            return file_list
        except Exception as e:
            logging.error(f"Failed to find files with extension '{extension}': {e}")
            raise

    @staticmethod
    def get_file_size(file_path: Path, ras_object=None) -> Optional[int]:
        """
        Get the size of a file in bytes.

        Parameters:
        file_path (Path): Path to the file
        ras_object (RasPrj, optional): RAS object to use. If None, uses the default ras object.

        Returns:
        Optional[int]: Size of the file in bytes, or None if the file does not exist

        Example:
        >>> size = RasUtils.get_file_size(Path("project.prj"))
        >>> print(f"File size: {size} bytes")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        path = Path(file_path)
        if path.exists():
            try:
                size = path.stat().st_size
                logging.info(f"Size of {path}: {size} bytes")
                return size
            except Exception as e:
                logging.error(f"Failed to get size for {path}: {e}")
                raise
        else:
            logging.warning(f"File not found: {path}")
            return None

    @staticmethod
    def get_file_modification_time(file_path: Path, ras_object=None) -> Optional[float]:
        """
        Get the last modification time of a file.

        Parameters:
        file_path (Path): Path to the file
        ras_object (RasPrj, optional): RAS object to use. If None, uses the default ras object.

        Returns:
        Optional[float]: Last modification time as a timestamp, or None if the file does not exist

        Example:
        >>> mtime = RasUtils.get_file_modification_time(Path("project.prj"))
        >>> print(f"Last modified: {mtime}")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        path = Path(file_path)
        if path.exists():
            try:
                mtime = path.stat().st_mtime
                logging.info(f"Last modification time of {path}: {mtime}")
                return mtime
            except Exception as e:
                logging.error(f"Failed to get modification time for {path}: {e}")
                raise
        else:
            logging.warning(f"File not found: {path}")
            return None

    @staticmethod
    def get_plan_path(current_plan_number_or_path: Union[str, Path], ras_object=None) -> Path:
        """
        Get the path for a plan file with a given plan number or path.

        Parameters:
        current_plan_number_or_path (Union[str, Path]): The plan number (1 to 99) or full path to the plan file
        ras_object (RasPrj, optional): RAS object to use. If None, uses the default ras object.

        Returns:
        Path: Full path to the plan file

        Example:
        >>> plan_path = RasUtils.get_plan_path(1)
        >>> print(f"Plan file path: {plan_path}")
        >>> plan_path = RasUtils.get_plan_path("path/to/plan.p01")
        >>> print(f"Plan file path: {plan_path}")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        plan_path = Path(current_plan_number_or_path)
        if plan_path.is_file():
            logging.info(f"Using provided plan file path: {plan_path}")
            return plan_path
        
        try:
            current_plan_number = f"{int(current_plan_number_or_path):02d}"  # Ensure two-digit format
            logging.info(f"Converted plan number to two-digit format: {current_plan_number}")
        except ValueError:
            logging.error(f"Invalid plan number: {current_plan_number_or_path}. Expected a number from 1 to 99.")
            raise ValueError(f"Invalid plan number: {current_plan_number_or_path}. Expected a number from 1 to 99.")
        
        plan_name = f"{ras_obj.project_name}.p{current_plan_number}"
        full_plan_path = ras_obj.project_folder / plan_name
        logging.info(f"Constructed plan file path: {full_plan_path}")
        return full_plan_path

    @staticmethod
    def remove_with_retry(
        path: Path,
        max_attempts: int = 5,
        initial_delay: float = 1.0,
        is_folder: bool = True,
        ras_object=None
    ) -> bool:
        """
        Attempts to remove a file or folder with retry logic and exponential backoff.

        Parameters:
        path (Path): Path to the file or folder to be removed.
        max_attempts (int): Maximum number of removal attempts.
        initial_delay (float): Initial delay between attempts in seconds.
        is_folder (bool): If True, the path is treated as a folder; if False, it's treated as a file.
        ras_object (RasPrj, optional): RAS object to use. If None, uses the default ras object.

        Returns:
        bool: True if the file or folder was successfully removed, False otherwise.

        Example:
        >>> success = RasUtils.remove_with_retry(Path("temp_folder"), is_folder=True)
        >>> print(f"Removal successful: {success}")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        path = Path(path)
        for attempt in range(1, max_attempts + 1):
            try:
                if path.exists():
                    if is_folder:
                        shutil.rmtree(path)
                        logging.info(f"Folder removed: {path}")
                    else:
                        path.unlink()
                        logging.info(f"File removed: {path}")
                else:
                    logging.info(f"Path does not exist, nothing to remove: {path}")
                return True
            except PermissionError as pe:
                if attempt < max_attempts:
                    delay = initial_delay * (2 ** (attempt - 1))  # Exponential backoff
                    logging.warning(
                        f"PermissionError on attempt {attempt} to remove {path}: {pe}. "
                        f"Retrying in {delay} seconds..."
                    )
                    time.sleep(delay)
                else:
                    logging.error(
                        f"Failed to remove {path} after {max_attempts} attempts due to PermissionError: {pe}. Skipping."
                    )
                    return False
            except Exception as e:
                logging.error(f"Failed to remove {path} on attempt {attempt}: {e}")
                return False
        return False

    @staticmethod
    def update_plan_file(
        plan_number_or_path: Union[str, Path],
        file_type: str,
        entry_number: int,
        ras_object=None
    ) -> None:
        """
        Update a plan file with a new file reference.

        Parameters:
        plan_number_or_path (Union[str, Path]): The plan number (1 to 99) or full path to the plan file
        file_type (str): Type of file to update ('Geom', 'Flow', or 'Unsteady')
        entry_number (int): Number (from 1 to 99) to set
        ras_object (RasPrj, optional): RAS object to use. If None, uses the default ras object.

        Raises:
        ValueError: If an invalid file_type is provided
        FileNotFoundError: If the plan file doesn't exist

        Example:
        >>> RasUtils.update_plan_file(1, "Geom", 2)
        >>> RasUtils.update_plan_file("path/to/plan.p01", "Geom", 2)
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        valid_file_types = {'Geom': 'g', 'Flow': 'f', 'Unsteady': 'u'}
        if file_type not in valid_file_types:
            logging.error(
                f"Invalid file_type '{file_type}'. Expected one of: {', '.join(valid_file_types.keys())}"
            )
            raise ValueError(
                f"Invalid file_type. Expected one of: {', '.join(valid_file_types.keys())}"
            )

        plan_file_path = Path(plan_number_or_path)
        if not plan_file_path.is_file():
            plan_file_path = RasUtils.get_plan_path(plan_number_or_path, ras_object)
            if not plan_file_path.exists():
                logging.error(f"Plan file not found: {plan_file_path}")
                raise FileNotFoundError(f"Plan file not found: {plan_file_path}")
        
        file_prefix = valid_file_types[file_type]
        search_pattern = f"{file_type} File="
        formatted_entry_number = f"{int(entry_number):02d}"  # Ensure two-digit format

        try:
            RasUtils.check_file_access(plan_file_path, 'r')
            with plan_file_path.open('r') as file:
                lines = file.readlines()
        except Exception as e:
            logging.error(f"Failed to read plan file {plan_file_path}: {e}")
            raise

        updated = False
        for i, line in enumerate(lines):
            if line.startswith(search_pattern):
                lines[i] = f"{search_pattern}{file_prefix}{formatted_entry_number}\n"
                logging.info(
                    f"Updated {file_type} File in {plan_file_path} to {file_prefix}{formatted_entry_number}"
                )
                updated = True
                break

        if not updated:
            logging.warning(
                f"Search pattern '{search_pattern}' not found in {plan_file_path}. No update performed."
            )

        try:
            with plan_file_path.open('w') as file:
                file.writelines(lines)
            logging.info(f"Successfully updated plan file: {plan_file_path}")
        except Exception as e:
            logging.error(f"Failed to write updates to plan file {plan_file_path}: {e}")
            raise

        # Refresh RasPrj dataframes
        try:
            ras_obj.plan_df = ras_obj.get_plan_entries()
            ras_obj.geom_df = ras_obj.get_geom_entries()
            ras_obj.flow_df = ras_obj.get_flow_entries()
            ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
            logging.info("RAS object dataframes have been refreshed.")
        except Exception as e:
            logging.error(f"Failed to refresh RasPrj dataframes: {e}")
            raise

    @staticmethod
    def check_file_access(file_path: Path, mode: str = 'r') -> None:
        """
        Check if the file can be accessed with the specified mode.

        Parameters:
        file_path (Path): Path to the file
        mode (str): Mode to check ('r' for read, 'w' for write, etc.)

        Raises:
        FileNotFoundError: If the file does not exist
        PermissionError: If the required permissions are not met
        """
        path = Path(file_path)
        if not path.exists():
            logging.error(f"File not found: {file_path}")
            raise FileNotFoundError(f"File not found: {file_path}")
        
        if mode in ('r', 'rb'):
            if not os.access(path, os.R_OK):
                logging.error(f"Read permission denied for file: {file_path}")
                raise PermissionError(f"Read permission denied for file: {file_path}")
            else:
                logging.debug(f"Read access granted for file: {file_path}")
        
        if mode in ('w', 'wb', 'a', 'ab'):
            parent_dir = path.parent
            if not os.access(parent_dir, os.W_OK):
                logging.error(f"Write permission denied for directory: {parent_dir}")
                raise PermissionError(f"Write permission denied for directory: {parent_dir}")
            else:
                logging.debug(f"Write access granted for directory: {parent_dir}")
