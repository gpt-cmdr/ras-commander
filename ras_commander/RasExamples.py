"""
RasExamples - Manage and load HEC-RAS example projects for testing and development

This module is part of the ras-commander library and uses a centralized logging configuration.

Logging Configuration:
- The logging is set up in the logging_config.py file.
- A @log_call decorator is available to automatically log function calls.
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Logs are written to both console and a rotating file handler.
- The default log file is 'ras_commander.log' in the 'logs' directory.
- The default log level is INFO.

To use logging in this module:
1. Use the @log_call decorator for automatic function call logging.
2. For additional logging, use logger.[level]() calls (e.g., logger.info(), logger.debug()).
3. Obtain the logger using: logger = logging.getLogger(__name__)

Example:
    @log_call
    def my_function():
        logger = logging.getLogger(__name__)
        logger.debug("Additional debug information")
        # Function logic here
        
        
-----

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in RasExamples:   
- get_example_projects()
- list_categories()
- list_projects()
- extract_project()
- is_project_extracted()
- clean_projects_directory()
        
"""
import os
import requests
import zipfile
import pandas as pd
from pathlib import Path
import shutil
from typing import Union, List
import csv
from datetime import datetime
import logging
import re
from tqdm import tqdm
from ras_commander import get_logger
from ras_commander.LoggingConfig import log_call

logger = get_logger(__name__)

class RasExamples:
    """
    A class for quickly loading HEC-RAS example projects for testing and development of ras-commander.
    All methods are class methods, so no initialization is required.
    """
    base_url = 'https://github.com/HydrologicEngineeringCenter/hec-downloads/releases/download/'
    valid_versions = [
            "6.6", "6.5", "6.4.1", "6.3.1", "6.3", "6.2", "6.1", "6.0",
            "5.0.7", "5.0.6", "5.0.5", "5.0.4", "5.0.3", "5.0.1", "5.0",
            "4.1", "4.0", "3.1.3", "3.1.2", "3.1.1", "3.0", "2.2"
        ]
    base_dir = Path.cwd()
    examples_dir = base_dir
    projects_dir = examples_dir / 'example_projects'
    csv_file_path = examples_dir / 'example_projects.csv'

    _folder_df = None
    _zip_file_path = None

    def __init__(self):
        """Initialize RasExamples and ensure data is loaded"""
        self._ensure_initialized()

    @property
    def folder_df(self):
        """Access the folder DataFrame"""
        self._ensure_initialized()
        return self._folder_df

    def _ensure_initialized(self):
        """Ensure the class is initialized with required data"""
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        if self._folder_df is None:
            self._load_project_data()

    def _load_project_data(self):
        """Load project data from CSV if up-to-date, otherwise extract from zip."""
        logger.debug("Loading project data")
        self._find_zip_file()
        
        if not self._zip_file_path:
            logger.info("No example projects zip file found. Downloading...")
            self.get_example_projects()
        
        try:
            zip_modified_time = os.path.getmtime(self._zip_file_path)
        except FileNotFoundError:
            logger.error(f"Zip file not found at {self._zip_file_path}.")
            return
        
        if self.csv_file_path.exists():
            csv_modified_time = os.path.getmtime(self.csv_file_path)
            
            if csv_modified_time >= zip_modified_time:
                logger.info("Loading project data from CSV...")
                try:
                    self._folder_df = pd.read_csv(self.csv_file_path)
                    logger.info(f"Loaded {len(self._folder_df)} projects from CSV.")
                    return
                except Exception as e:
                    logger.error(f"Failed to read CSV file: {e}")
                    self._folder_df = None

        logger.info("Extracting folder structure from zip file...")
        self._extract_folder_structure()
        self._save_to_csv()

    @classmethod
    def extract_project(cls, project_names: Union[str, List[str]]) -> Union[Path, List[Path]]:
        """Extract one or more specific HEC-RAS projects from the zip file.
        
        Args:
            project_names: Single project name as string or list of project names
            
        Returns:
            Path: Single Path object if one project extracted
            List[Path]: List of Path objects if multiple projects extracted
        """
        logger.debug(f"Extracting projects: {project_names}")
        
        # Initialize if needed
        if cls._folder_df is None:
            cls._find_zip_file()
            if not cls._zip_file_path:
                logger.info("No example projects zip file found. Downloading...")
                cls.get_example_projects()
            cls._load_project_data()
        
        if isinstance(project_names, str):
            project_names = [project_names]

        extracted_paths = []

        for project_name in project_names:
            logger.info("----- RasExamples Extracting Project -----")
            logger.info(f"Extracting project '{project_name}'")
            project_path = cls.projects_dir

            if (project_path / project_name).exists():
                logger.info(f"Project '{project_name}' already exists. Deleting existing folder...")
                try:
                    shutil.rmtree(project_path / project_name)
                    logger.info(f"Existing folder for project '{project_name}' has been deleted.")
                except Exception as e:
                    logger.error(f"Failed to delete existing project folder '{project_name}': {e}")
                    continue

            project_info = cls._folder_df[cls._folder_df['Project'] == project_name]
            if project_info.empty:
                error_msg = f"Project '{project_name}' not found in the zip file."
                logger.error(error_msg)
                raise ValueError(error_msg)

            try:
                with zipfile.ZipFile(cls._zip_file_path, 'r') as zip_ref:
                    for file in zip_ref.namelist():
                        parts = Path(file).parts
                        if len(parts) > 1 and parts[1] == project_name:
                            relative_path = Path(*parts[1:])
                            extract_path = project_path / relative_path
                            if file.endswith('/'):
                                extract_path.mkdir(parents=True, exist_ok=True)
                            else:
                                extract_path.parent.mkdir(parents=True, exist_ok=True)
                                with zip_ref.open(file) as source, open(extract_path, "wb") as target:
                                    shutil.copyfileobj(source, target)

                logger.info(f"Successfully extracted project '{project_name}' to {project_path / project_name}")
                extracted_paths.append(project_path / project_name)
            except Exception as e:
                logger.error(f"An error occurred while extracting project '{project_name}': {str(e)}")

        # Return single path if only one project was extracted, otherwise return list
        return extracted_paths[0] if len(project_names) == 1 else extracted_paths

    @classmethod
    def _find_zip_file(cls):
        """Locate the example projects zip file in the examples directory."""
        for version in cls.valid_versions:
            potential_zip = cls.examples_dir / f"Example_Projects_{version.replace('.', '_')}.zip"
            if potential_zip.exists():
                cls._zip_file_path = potential_zip
                logger.info(f"Found zip file: {cls._zip_file_path}")
                break
        else:
            logger.warning("No existing example projects zip file found.")

    @classmethod
    def get_example_projects(cls, version_number='6.6'):
        """
        Download and extract HEC-RAS example projects for a specified version.
        """
        logger.info(f"Getting example projects for version {version_number}")
        if version_number not in cls.valid_versions:
            error_msg = f"Invalid version number. Valid versions are: {', '.join(cls.valid_versions)}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        zip_url = f"{cls.base_url}1.0.33/Example_Projects_{version_number.replace('.', '_')}.zip"
        
        cls.examples_dir.mkdir(parents=True, exist_ok=True)
        
        cls._zip_file_path = cls.examples_dir / f"Example_Projects_{version_number.replace('.', '_')}.zip"

        if not cls._zip_file_path.exists():
            logger.info(f"Downloading HEC-RAS Example Projects from {zip_url}. \nThe file is over 400 MB, so it may take a few minutes to download....")
            try:
                response = requests.get(zip_url, stream=True)
                response.raise_for_status()
                with open(cls._zip_file_path, 'wb') as file:
                    shutil.copyfileobj(response.raw, file)
                logger.info(f"Downloaded to {cls._zip_file_path}")
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to download the zip file: {e}")
                raise
        else:
            logger.info("HEC-RAS Example Projects zip file already exists. Skipping download.")

        cls._load_project_data()
        return cls.projects_dir

    @classmethod
    def _load_project_data(cls):
        """Load project data from CSV if up-to-date, otherwise extract from zip."""
        logger.debug("Loading project data")
        
        try:
            zip_modified_time = os.path.getmtime(cls._zip_file_path)
        except FileNotFoundError:
            logger.error(f"Zip file not found at {cls._zip_file_path}.")
            return
        
        if cls.csv_file_path.exists():
            csv_modified_time = os.path.getmtime(cls.csv_file_path)
            
            if csv_modified_time >= zip_modified_time:
                logger.info("Loading project data from CSV...")
                try:
                    cls._folder_df = pd.read_csv(cls.csv_file_path)
                    logger.info(f"Loaded {len(cls._folder_df)} projects from CSV.")
                    return
                except Exception as e:
                    logger.error(f"Failed to read CSV file: {e}")
                    cls._folder_df = None

        logger.info("Extracting folder structure from zip file...")
        cls._extract_folder_structure()
        cls._save_to_csv()

    @classmethod
    def _extract_folder_structure(cls):
        """
        Extract folder structure from the zip file.

        Populates folder_df with category and project information.
        """
        folder_data = []
        try:
            with zipfile.ZipFile(cls._zip_file_path, 'r') as zip_ref:
                for file in zip_ref.namelist():
                    parts = Path(file).parts
                    if len(parts) > 1:
                        folder_data.append({
                            'Category': parts[0],
                            'Project': parts[1]
                        })
        
            cls._folder_df = pd.DataFrame(folder_data).drop_duplicates()
            logger.info(f"Extracted {len(cls._folder_df)} projects.")
            logger.debug(f"folder_df:\n{cls._folder_df}")
        except zipfile.BadZipFile:
            logger.error(f"The file {cls._zip_file_path} is not a valid zip file.")
            cls._folder_df = pd.DataFrame(columns=['Category', 'Project'])
        except Exception as e:
            logger.error(f"An error occurred while extracting the folder structure: {str(e)}")
            cls._folder_df = pd.DataFrame(columns=['Category', 'Project'])

    @classmethod
    def _save_to_csv(cls):
        """Save the extracted folder structure to CSV file."""
        if cls._folder_df is not None and not cls._folder_df.empty:
            try:
                cls._folder_df.to_csv(cls.csv_file_path, index=False)
                logger.info(f"Saved project data to {cls.csv_file_path}")
            except Exception as e:
                logger.error(f"Failed to save project data to CSV: {e}")
        else:
            logger.warning("No folder data to save to CSV.")

    @classmethod
    def list_categories(cls):
        """
        List all categories of example projects.
        """
        if cls._folder_df is None or 'Category' not in cls._folder_df.columns:
            logger.warning("No categories available. Make sure the zip file is properly loaded.")
            return []
        categories = cls._folder_df['Category'].unique()
        logger.info(f"Available categories: {', '.join(categories)}")
        return categories.tolist()

    @classmethod
    def list_projects(cls, category=None):
        """
        List all projects or projects in a specific category.
        """
        if cls._folder_df is None:
            logger.warning("No projects available. Make sure the zip file is properly loaded.")
            return []
        if category:
            projects = cls._folder_df[cls._folder_df['Category'] == category]['Project'].unique()
            logger.info(f"Projects in category '{category}': {', '.join(projects)}")
        else:
            projects = cls._folder_df['Project'].unique()
            logger.info(f"All available projects: {', '.join(projects)}")
        return projects.tolist()

    @classmethod
    def is_project_extracted(cls, project_name):
        """
        Check if a specific project is already extracted.
        """
        project_path = cls.projects_dir / project_name
        is_extracted = project_path.exists()
        logger.info(f"Project '{project_name}' extracted: {is_extracted}")
        return is_extracted

    @classmethod
    def clean_projects_directory(cls):
        """Remove all extracted projects from the example_projects directory."""
        logger.info(f"Cleaning projects directory: {cls.projects_dir}")
        if cls.projects_dir.exists():
            try:
                shutil.rmtree(cls.projects_dir)
                logger.info("All projects have been removed.")
            except Exception as e:
                logger.error(f"Failed to remove projects directory: {e}")
        else:
            logger.warning("Projects directory does not exist.")
        cls.projects_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Projects directory cleaned and recreated.")

    @classmethod
    def download_fema_ble_model(cls, huc8, output_dir=None):
        """
        Download a FEMA Base Level Engineering (BLE) model for a given HUC8.

        Args:
            huc8 (str): The 8-digit Hydrologic Unit Code (HUC) for the desired watershed.
            output_dir (str, optional): The directory to save the downloaded files. If None, uses the current working directory.

        Returns:
            str: The path to the downloaded and extracted model directory.

        Note:
            This method downloads the BLE model from the FEMA website and extracts it to the specified directory.
        """
        # Method implementation...

    @classmethod
    def _make_safe_folder_name(cls, name: str) -> str:
        """
        Convert a string to a safe folder name by replacing unsafe characters with underscores.
        """
        safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', name)
        logger.debug(f"Converted '{name}' to safe folder name '{safe_name}'")
        return safe_name

    @classmethod
    def _download_file_with_progress(cls, url: str, dest_folder: Path, file_size: int) -> Path:
        """
        Download a file from a URL to a specified destination folder with progress bar.
        """
        local_filename = dest_folder / url.split('/')[-1]
        try:
            with requests.get(url, stream=True) as r:
                r.raise_for_status()
                with open(local_filename, 'wb') as f, tqdm(
                    desc=local_filename.name,
                    total=file_size,
                    unit='iB',
                    unit_scale=True,
                    unit_divisor=1024,
                ) as progress_bar:
                    for chunk in r.iter_content(chunk_size=8192):
                        size = f.write(chunk)
                        progress_bar.update(size)
            logger.info(f"Successfully downloaded {url} to {local_filename}")
            return local_filename
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to write file {local_filename}: {e}")
            raise

    @classmethod
    def _convert_size_to_bytes(cls, size_str: str) -> int:
        """
        Convert a human-readable file size to bytes.
        """
        units = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
        size_str = size_str.upper().replace(' ', '')
        if not re.match(r'^\d+(\.\d+)?[BKMGT]B?$', size_str):
            raise ValueError(f"Invalid size string: {size_str}")
        
        number, unit = float(re.findall(r'[\d\.]+', size_str)[0]), re.findall(r'[BKMGT]B?', size_str)[0]
        return int(number * units[unit])