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

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Set the logging level to INFO
    format='%(asctime)s - %(levelname)s - %(message)s',  # Log message format
    handlers=[
        logging.StreamHandler()  # Log to stderr
    ]
)

class RasExamples:
    """
    A class for quickly loading HEC-RAS example projects for testing and development of ras-commander.

    This class provides functionality to download, extract, and manage HEC-RAS example projects.
    It supports both default HEC-RAS example projects and custom projects from user-provided URLs.

    Expected folder structure:              Notes:
    ras-commander/
    ├── examples/                           # This is examples_dir
    │   ├── example_projects/               # This is projects_dir
    │   │   ├── Balde Eagle Creek/          # Individual Projects from Zip file
    │   │   ├── Muncie/                 
    │   │   └── ...
    │   ├── Example_Projects_6_5.zip        # HEC-RAS Example Projects zip file will be downloaded here
    │   ├── example_projects.csv            # CSV file containing cached project metadata
    │   └── 01_project_initialization.py    # ras-commander library examples are also at this level
    │   └── ...
    └── ras_commander/                      # Code for the ras-commander library

    Attributes:
        base_url (str): Base URL for downloading HEC-RAS example projects.
        valid_versions (list): List of valid HEC-RAS versions for example projects.
        base_dir (Path): Base directory for storing example projects.
        examples_dir (Path): Directory for example projects and related files. (assumed to be parent )
        projects_dir (Path): Directory where example projects are extracted.
        zip_file_path (Path): Path to the downloaded zip file.
        folder_df (pd.DataFrame): DataFrame containing folder structure information.
        csv_file_path (Path): Path to the CSV file for caching project metadata.

    Future Improvements:
    - Implement the ability for user-provided example projects (provided as a zip file) for their own repeatable examples. 
    - If the zip file is in the same folder structure as the HEC-RAS example projects, simple replace Example_Projects_6_5.zip and the folder structure will be automatically extracted from the zip file.
    - The actual RAS example projects haven't been updated much, but there is the structure here to handle future versions. Although this version of the code is probably fine for a few years, until HEC-RAS 2025 comes out. 
    """
    
    def __init__(self):
        """
        Initialize the RasExamples class.

        This constructor sets up the necessary attributes and paths for managing HEC-RAS example projects.
        It initializes the base URL for downloads, valid versions, directory paths, and other essential
        attributes. It also creates the projects directory if it doesn't exist and loads the project data.

        The method also logs the location of the example projects folder and calls _load_project_data()
        to initialize the project data.
        """
        self.base_url = 'https://github.com/HydrologicEngineeringCenter/hec-downloads/releases/download/'
        self.valid_versions = [
            "6.5", "6.4.1", "6.3.1", "6.3", "6.2", "6.1", "6.0",
            "5.0.7", "5.0.6", "5.0.5", "5.0.4", "5.0.3", "5.0.1", "5.0",
            "4.1", "4.0", "3.1.3", "3.1.2", "3.1.1", "3.0", "2.2"
        ]
        self.base_dir = Path.cwd()
        self.examples_dir = self.base_dir
        self.projects_dir = self.examples_dir / 'example_projects'
        self.zip_file_path = None
        self.folder_df = None
        self.csv_file_path = self.examples_dir / 'example_projects.csv'

        self.projects_dir.mkdir(parents=True, exist_ok=True)
        logging.info(f"Example projects folder: {self.projects_dir}")
        self._load_project_data()

    def _load_project_data(self):
        """
        Load project data from CSV if up-to-date, otherwise extract from zip.

        Checks for existing CSV file and compares modification times with zip file.
        Extracts folder structure if necessary and saves to CSV.
        """
        self._find_zip_file()
        
        if not self.zip_file_path:
            logging.info("No example projects zip file found. Downloading...")
            self.get_example_projects()
        
        try:
            zip_modified_time = os.path.getmtime(self.zip_file_path)
        except FileNotFoundError:
            logging.error(f"Zip file not found at {self.zip_file_path}.")
            return
        
        if self.csv_file_path.exists():
            csv_modified_time = os.path.getmtime(self.csv_file_path)
            
            if csv_modified_time >= zip_modified_time:
                logging.info("Loading project data from CSV...")
                try:
                    self.folder_df = pd.read_csv(self.csv_file_path)
                    logging.info(f"Loaded {len(self.folder_df)} projects from CSV. Use list_categories() and list_projects() to explore them.")
                except Exception as e:
                    logging.error(f"Failed to read CSV file: {e}")
                    self.folder_df = None
                return

        logging.info("Extracting folder structure from zip file...")
        self._extract_folder_structure()
        self._save_to_csv()

    def _find_zip_file(self):
        """Locate the example projects zip file in the examples directory."""
        for version in self.valid_versions:
            potential_zip = self.examples_dir / f"Example_Projects_{version.replace('.', '_')}.zip"
            if potential_zip.exists():
                self.zip_file_path = potential_zip
                logging.info(f"Found zip file: {self.zip_file_path}")
                break
        else:
            logging.warning("No existing example projects zip file found.")

    def _extract_folder_structure(self):
        """
        Extract folder structure from the zip file.

        Populates folder_df with category and project information.
        """
        folder_data = []
        try:
            with zipfile.ZipFile(self.zip_file_path, 'r') as zip_ref:
                for file in zip_ref.namelist():
                    parts = Path(file).parts
                    if len(parts) > 2:
                        folder_data.append({
                            'Category': parts[1],
                            'Project': parts[2]
                        })
            
            self.folder_df = pd.DataFrame(folder_data).drop_duplicates()
            logging.info(f"Extracted {len(self.folder_df)} projects.")
            logging.debug(f"folder_df:\n{self.folder_df}")
        except zipfile.BadZipFile:
            logging.error(f"The file {self.zip_file_path} is not a valid zip file.")
            self.folder_df = pd.DataFrame(columns=['Category', 'Project'])
        except Exception as e:
            logging.error(f"An error occurred while extracting the folder structure: {str(e)}")
            self.folder_df = pd.DataFrame(columns=['Category', 'Project'])

    def _save_to_csv(self):
        """Save the extracted folder structure to CSV file."""
        if self.folder_df is not None and not self.folder_df.empty:
            try:
                self.folder_df.to_csv(self.csv_file_path, index=False)
                logging.info(f"Saved project data to {self.csv_file_path}")
            except Exception as e:
                logging.error(f"Failed to save project data to CSV: {e}")
        else:
            logging.warning("No folder data to save to CSV.")

    def get_example_projects(self, version_number='6.5'):
        """
        Download and extract HEC-RAS example projects for a specified version.

        Args:
            version_number (str): HEC-RAS version number. Defaults to '6.5'.

        Returns:
            Path: Path to the extracted example projects.

        Raises:
            ValueError: If an invalid version number is provided.
        """
        logging.info(f"Getting example projects for version {version_number}")
        if version_number not in self.valid_versions:
            error_msg = f"Invalid version number. Valid versions are: {', '.join(self.valid_versions)}"
            logging.error(error_msg)
            raise ValueError(error_msg)

        zip_url = f"{self.base_url}1.0.31/Example_Projects_{version_number.replace('.', '_')}.zip"
        
        self.examples_dir.mkdir(parents=True, exist_ok=True)
        
        self.zip_file_path = self.examples_dir / f"Example_Projects_{version_number.replace('.', '_')}.zip"

        if not self.zip_file_path.exists():
            logging.info(f"Downloading HEC-RAS Example Projects from {zip_url}. \nThe file is over 400 MB, so it may take a few minutes to download....")
            try:
                response = requests.get(zip_url, stream=True)
                response.raise_for_status()
                with open(self.zip_file_path, 'wb') as file:
                    shutil.copyfileobj(response.raw, file)
                logging.info(f"Downloaded to {self.zip_file_path}")
            except requests.exceptions.RequestException as e:
                logging.error(f"Failed to download the zip file: {e}")
                raise
        else:
            logging.info("HEC-RAS Example Projects zip file already exists. Skipping download.")

        self._load_project_data()
        return self.projects_dir

    def list_categories(self):
        """
        List all categories of example projects.

        Returns:
            list: Available categories.
        """
        if self.folder_df is None or 'Category' not in self.folder_df.columns:
            logging.warning("No categories available. Make sure the zip file is properly loaded.")
            return []
        categories = self.folder_df['Category'].unique()
        logging.info(f"Available categories: {', '.join(categories)}")
        return categories.tolist()

    def list_projects(self, category=None):
        """
        List all projects or projects in a specific category.

        Args:
            category (str, optional): Category to filter projects.

        Returns:
            list: List of project names.
        """
        if self.folder_df is None:
            logging.warning("No projects available. Make sure the zip file is properly loaded.")
            return []
        if category:
            projects = self.folder_df[self.folder_df['Category'] == category]['Project'].unique()
            logging.info(f"Projects in category '{category}': {', '.join(projects)}")
        else:
            projects = self.folder_df['Project'].unique()
            logging.info(f"All available projects: {', '.join(projects)}")
        return projects.tolist()

    def extract_project(self, project_names: Union[str, List[str]]):
        """
        Extract one or more specific projects from the zip file.

        Args:
            project_names (str or List[str]): Name(s) of the project(s) to extract.

        Returns:
            List[Path]: List of paths to the extracted project(s).

        Raises:
            ValueError: If any project is not found.
        """
        if isinstance(project_names, str):
            project_names = [project_names]

        extracted_paths = []

        for project_name in project_names:
            logging.info("----- RasExamples Extracting Project -----")
            logging.info(f"Extracting project '{project_name}'")
            project_path = self.projects_dir / project_name

            if project_path.exists():
                logging.info(f"Project '{project_name}' already exists. Deleting existing folder...")
                try:
                    shutil.rmtree(project_path)
                    logging.info(f"Existing folder for project '{project_name}' has been deleted.")
                except Exception as e:
                    logging.error(f"Failed to delete existing project folder '{project_name}': {e}")
                    continue

            if self.folder_df is None or self.folder_df.empty:
                error_msg = "No project information available. Make sure the zip file is properly loaded."
                logging.error(error_msg)
                raise ValueError(error_msg)

            project_info = self.folder_df[self.folder_df['Project'] == project_name]
            if project_info.empty:
                error_msg = f"Project '{project_name}' not found in the zip file."
                logging.error(error_msg)
                raise ValueError(error_msg)

            category = project_info['Category'].iloc[0]
            
            # Ensure the project directory exists
            project_path.mkdir(parents=True, exist_ok=True)

            try:
                with zipfile.ZipFile(self.zip_file_path, 'r') as zip_ref:
                    for file in zip_ref.namelist():
                        parts = Path(file).parts
                        if len(parts) > 2 and parts[2] == project_name:
                            # Remove the first two levels (category and project name)
                            relative_path = Path(*parts[3:])
                            extract_path = project_path / relative_path
                            if file.endswith('/'):
                                extract_path.mkdir(parents=True, exist_ok=True)
                            else:
                                extract_path.parent.mkdir(parents=True, exist_ok=True)
                                with zip_ref.open(file) as source, open(extract_path, "wb") as target:
                                    shutil.copyfileobj(source, target)

                logging.info(f"Successfully extracted project '{project_name}' to {project_path}")
                extracted_paths.append(project_path)
            except zipfile.BadZipFile:
                logging.error(f"Error: The file {self.zip_file_path} is not a valid zip file.")
            except FileNotFoundError:
                logging.error(f"Error: The file {self.zip_file_path} was not found.")
            except Exception as e:
                logging.error(f"An unexpected error occurred while extracting the project: {str(e)}")
            logging.info("----- RasExamples Extraction Complete -----")
        return extracted_paths

    def is_project_extracted(self, project_name):
        """
        Check if a specific project is already extracted.

        Args:
            project_name (str): Name of the project to check.

        Returns:
            bool: True if the project is extracted, False otherwise.
        """
        project_path = self.projects_dir / project_name
        is_extracted = project_path.exists()
        logging.info(f"Project '{project_name}' extracted: {is_extracted}")
        return is_extracted

    def clean_projects_directory(self):
        """Remove all extracted projects from the example_projects directory."""
        logging.info(f"Cleaning projects directory: {self.projects_dir}")
        if self.projects_dir.exists():
            try:
                shutil.rmtree(self.projects_dir)
                logging.info("All projects have been removed.")
            except Exception as e:
                logging.error(f"Failed to remove projects directory: {e}")
        else:
            logging.warning("Projects directory does not exist.")
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        logging.info("Projects directory cleaned and recreated.")

# Example usage:
# ras_examples = RasExamples()
# extracted_paths = ras_examples.extract_project(["Bald Eagle Creek", "BaldEagleCrkMulti2D", "Muncie"])
# for path in extracted_paths:
#     logging.info(f"Extracted to: {path}")
