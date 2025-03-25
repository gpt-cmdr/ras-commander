# Configuration
OMIT_FOLDERS = [
    "Bald Eagle Creek", "__pycache__", ".git", ".github", "tests", "docs", "library_assistant", "__pycache__",
    "build", "dist", "ras_commander.egg-info", "venv", "ras_commander.egg-info", "log_folder", "logs",
    "example_projects", "llm_knowledge_bases", "misc", "ai_tools", "FEMA_BLE_Models", "hdf_example_data", "ras_example_categories", "html", "data", "apidocs"
]
OMIT_FILES = [
    ".pyc", ".pyo", ".pyd", ".dll", ".so", ".dylib", ".exe",
    ".bat", ".sh", ".log", ".tmp", ".bak", ".swp",
    ".DS_Store", "Thumbs.db", "example_projects.zip",
    "Example_Projects_6_6.zip", "example_projects.ipynb", "11_Using_RasExamples.ipynb", 
    "future_dev_roadmap.ipynb", "structures_attributes.csv", "example_projects.csv",
]
SUMMARY_OUTPUT_DIR = "llm_knowledge_bases"
SCRIPT_NAME = Path(__file__).name

def clean_output_directory(output_dir):
    """
    Clean the output directory by removing all files and subdirectories.
    
    Args:
        output_dir: Path to the output directory to clean
    """
    if output_dir.exists():
        print(f"Cleaning output directory: {output_dir}")
        try:
            # Recursively delete all files and subdirectories
            for item in output_dir.rglob("*"):
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    item.rmdir()
            print(f"Successfully cleaned output directory: {output_dir}")
        except Exception as e:
            print(f"Error cleaning output directory {output_dir}: {e}")
    else:
        print(f"Output directory does not exist: {output_dir}")

def ensure_output_dir(base_path):
    output_dir = base_path / SUMMARY_OUTPUT_DIR
    # Clean the output directory before creating new knowledge bases
    clean_output_directory(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory ensured to exist: {output_dir}")
    return output_dir 