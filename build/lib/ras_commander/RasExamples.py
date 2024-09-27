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
    Additionally, it includes functionality to download FEMA's Base Level Engineering (BLE) models
    from CSV files provided by the FEMA Estimated Base Flood Elevation (BFE) Viewer.

    [Documentation as previously provided]
    """

    def __init__(self):
        """
        Initialize the RasExamples class.
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
        Extract one or more specific HEC-RAS projects from the zip file.
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
        
    def download_fema_ble_model(self, csv_file: Union[str, Path], output_base_dir: Union[str, Path] = None):
        """
        Download a single FEMA Base Level Engineering (BLE) model from a CSV file and organize it into folders.

        This function performs the following steps:
        1. Reads the specified CSV file to get the download URLs.
        2. Creates a folder for the region (e.g., `LowerPearl`, `BogueChitto`, etc.).
        3. Downloads the zip files to the same folder as the CSV.
        4. Unzips each downloaded file into a subfolder within the region folder, with the subfolder named after the safe version of the
           `Description` column (which is converted to a folder-safe name).
        5. Leaves the zip files in place in the CSV folder.
        6. Does not download files again if they already exist in the CSV folder.

        **Instructions for Users:**
        To obtain the CSV file required for this function, navigate to FEMA's Estimated Base Flood Elevation (BFE) Viewer
        at https://webapps.usgs.gov/infrm/estBFE/. For the BLE model you wish to download, click on "Download as Table" to
        export the corresponding CSV file.

        Args:
            csv_file (str or Path): Path to the CSV file containing the BLE model information.
            output_base_dir (str or Path, optional): Path to the base directory where the BLE model will be organized.
                                                     Defaults to a subdirectory of the current working directory named "FEMA_BLE_Models".

        Raises:
            FileNotFoundError: If the specified CSV file does not exist.
            Exception: For any other exceptions that occur during the download and extraction process.
        """
        csv_file = Path(csv_file)
        if output_base_dir is None:
            output_base_dir = Path.cwd() / "FEMA_BLE_Models"
        else:
            output_base_dir = Path(output_base_dir)

        if not csv_file.exists() or not csv_file.is_file():
            logging.error(f"The specified CSV file does not exist: {csv_file}")
            raise FileNotFoundError(f"The specified CSV file does not exist: {csv_file}")

        output_base_dir.mkdir(parents=True, exist_ok=True)
        logging.info(f"BLE model will be organized in: {output_base_dir}")

        try:
            # Extract region name from the filename (assuming format <AnyCharacters>_<Region>_DownloadIndex.csv)
            match = re.match(r'.+?_(.+?)_DownloadIndex\.csv', csv_file.name)
            if not match:
                logging.warning(f"Filename does not match expected pattern and will be skipped: {csv_file.name}")
                return
            region = match.group(1)
            logging.info(f"Processing region: {region}")

            # Create folder for this region
            region_folder = output_base_dir / region
            region_folder.mkdir(parents=True, exist_ok=True)
            logging.info(f"Created/verified region folder: {region_folder}")

            # Read the CSV file
            try:
                df = pd.read_csv(csv_file, comment='#')
            except pd.errors.ParserError as e:
                logging.error(f"Error parsing CSV file {csv_file.name}: {e}")
                return

            # Verify required columns exist
            required_columns = {'URL', 'FileName', 'FileSize', 'Description', 'Details'}
            if not required_columns.issubset(df.columns):
                logging.warning(f"CSV file {csv_file.name} is missing required columns and will be skipped.")
                return

            # Process each row in the CSV
            for index, row in tqdm(df.iterrows(), total=len(df), desc="Downloading files", unit="file"):
                description = row['Description']
                download_url = row['URL']
                file_name = row['FileName']
                file_size_str = row['FileSize']

                # Convert file size to bytes
                try:
                    file_size = self._convert_size_to_bytes(file_size_str)
                except ValueError as e:
                    logging.error(f"Error converting file size '{file_size_str}' to bytes: {e}")
                    continue

                # Create a subfolder based on the safe description name
                safe_description = self._make_safe_folder_name(description)
                description_folder = region_folder / safe_description

                # Download the file to the CSV folder if it does not already exist
                csv_folder = csv_file.parent
                downloaded_file = csv_folder / file_name
                if not downloaded_file.exists():
                    try:
                        logging.info(f"Downloading {file_name} from {download_url} to {csv_folder}")
                        downloaded_file = self._download_file_with_progress(download_url, csv_folder, file_size)
                        logging.info(f"Downloaded file to: {downloaded_file}")
                    except Exception as e:
                        logging.error(f"Failed to download {download_url}: {e}")
                        continue
                else:
                    logging.info(f"File {file_name} already exists in {csv_folder}, skipping download.")

                # If it's a zip file, unzip it to the description folder
                if downloaded_file.suffix == '.zip':
                    # If the folder exists, delete it
                    if description_folder.exists():
                        logging.info(f"Folder {description_folder} already exists. Deleting it.")
                        shutil.rmtree(description_folder)

                    description_folder.mkdir(parents=True, exist_ok=True)
                    logging.info(f"Created/verified description folder: {description_folder}")

                    logging.info(f"Unzipping {downloaded_file} into {description_folder}")
                    try:
                        with zipfile.ZipFile(downloaded_file, 'r') as zip_ref:
                            zip_ref.extractall(description_folder)
                        logging.info(f"Unzipped {downloaded_file} successfully.")
                    except Exception as e:
                        logging.error(f"Failed to extract {downloaded_file}: {e}")
        except Exception as e:
            logging.error(f"An error occurred while processing {csv_file.name}: {e}")

    def _make_safe_folder_name(self, name: str) -> str:
        """
        Convert a string to a safe folder name by replacing unsafe characters with underscores.
        """
        safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', name)
        logging.debug(f"Converted '{name}' to safe folder name '{safe_name}'")
        return safe_name

    def _download_file_with_progress(self, url: str, dest_folder: Path, file_size: int) -> Path:
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
            logging.info(f"Successfully downloaded {url} to {local_filename}")
            return local_filename
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed for {url}: {e}")
            raise
        except Exception as e:
            logging.error(f"Failed to write file {local_filename}: {e}")
            raise

    def _convert_size_to_bytes(self, size_str: str) -> int:
        """
        Convert a human-readable file size to bytes.
        """
        units = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
        size_str = size_str.upper().replace(' ', '')
        if not re.match(r'^\d+(\.\d+)?[BKMGT]B?$', size_str):
            raise ValueError(f"Invalid size string: {size_str}")
        
        number, unit = float(re.findall(r'[\d\.]+', size_str)[0]), re.findall(r'[BKMGT]B?', size_str)[0]
        return int(number * units[unit])

    # Example usage:
    # ras_examples = RasExamples()
    # ras_examples.download_fema_ble_models('/path/to/csv/files', '/path/to/output/folder')
    # extracted_paths = ras_examples.extract_project(["Bald Eagle Creek", "BaldEagleCrkMulti2D", "Muncie"])
    # for path in extracted_paths:
    #     logging.info(f"Extracted to: {path}")


"""
### How to Use the Revised `RasExamples` Class

1. **Instantiate the Class:**
   ```python
   ras_examples = RasExamples()
   ```

2. **Download FEMA BLE Models:**
   - Ensure you have the required CSV files by visiting [FEMA's Estimated Base Flood Elevation (BFE) Viewer](https://webapps.usgs.gov/infrm/estBFE/) and using the "Download as Table" option for each BLE model you wish to access.
   - Call the `download_fema_ble_models` method with the appropriate paths:
     ```python
     ras_examples.download_fema_ble_models('/path/to/csv/files', '/path/to/output/folder')
     ```
     - Replace `'/path/to/csv/files'` with the directory containing your CSV files.
     - Replace `'/path/to/output/folder'` with the directory where you want the BLE models to be downloaded and organized.

3. **Extract Projects (If Needed):**
   - After downloading, you can extract specific projects using the existing `extract_project` method:
     ```python
     extracted_paths = ras_examples.extract_project(["Bald Eagle Creek", "BaldEagleCrkMulti2D", "Muncie"])
     for path in extracted_paths:
         logging.info(f"Extracted to: {path}")
     ```

4. **Explore Projects and Categories:**
   - List available categories:
     ```python
     categories = ras_examples.list_categories()
     ```
   - List projects within a specific category:
     ```python
     projects = ras_examples.list_projects(category='SomeCategory')
     ```

5. **Clean Projects Directory (If Needed):**
   - To remove all extracted projects:
     ```python
     ras_examples.clean_projects_directory()
     ```

### Dependencies

Ensure that the following Python packages are installed:

- `pandas`
- `requests`

You can install them using `pip`:

```bash
pip install pandas requests
```

### Notes

- The class uses Python's `logging` module to provide detailed information about its operations. Ensure that the logging level is set appropriately to capture the desired amount of detail.
- The `download_fema_ble_models` method handles large file downloads by streaming data in chunks, which is memory-efficient.
- All folder names are sanitized to prevent filesystem errors due to unsafe characters.
"""