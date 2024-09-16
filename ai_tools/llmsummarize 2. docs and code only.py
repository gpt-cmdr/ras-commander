from pathlib import Path

# Get the name of this script
this_script = Path(__file__).name
print(f"Script name: {this_script}")

# Define the subfolder to summarize
summarize_subfolder = Path(__file__).parent.parent
print(f"Subfolder to summarize: {summarize_subfolder}")

# Define the output file name based on the folder name
output_file_name = f"{summarize_subfolder.name}_code_only.txt"
output_file_path = Path(__file__).parent / "llm_summary" / output_file_name
print(f"Output file path: {output_file_path}")

# Ensure the output directory exists
output_file_path.parent.mkdir(parents=True, exist_ok=True)
print(f"Output directory ensured to exist: {output_file_path.parent}")

# Define folders to omit
omit_folders = ["Bald Eagle Creek", "__pycache__", ".git", ".github", "tests", "build", "dist", "ras_commander.egg-info", "venv", "example_projects", "llm_summary", "misc", "future", ".github"]
print(f"Folders to omit: {omit_folders}")

# Define files or extensions to omit
omit_files = [".pyc", ".pyo", ".pyd", ".dll", ".so", ".dylib", ".exe", ".bat", ".sh", ".log", ".tmp", ".bak", ".swp", ".DS_Store", "Thumbs.db", "example_projects.zip", "11_accessing_example_projects.ipynb", "Example_Projects_6_5.zip"]
print(f"Files or extensions to omit: {omit_files}")

# Open the output file
with open(output_file_path, 'w', encoding='utf-8') as outfile:
    print(f"Opened output file: {output_file_path}")
    # Iterate over all files and subfolders in the summarize_subfolder directory
    for filepath in summarize_subfolder.rglob('*'):
        # Check if the file is not this script, not in the omit_folders, and not in omit_files
        if (filepath.name != this_script and 
            not any(omit_folder in filepath.parts for omit_folder in omit_folders) and
            not any(filepath.suffix == ext or filepath.name == ext for ext in omit_files)):
            # Write the filename or folder name
            if filepath.is_file():
                outfile.write(f"File: {filepath}\n")
                print(f"Writing file: {filepath}")
            else:
                outfile.write(f"Folder: {filepath}\n")
                print(f"Writing folder: {filepath}")
            outfile.write("="*50 + "\n")  # Separator
            
            # If it's a file, open and read the contents of the file
            if filepath.is_file():
                try:
                    with open(filepath, 'r', encoding='utf-8') as infile:
                        content = infile.read()
                        print(f"Reading content of file: {filepath}")
                except UnicodeDecodeError:
                    with open(filepath, 'rb') as infile:
                        content = infile.read()
                        content = content.decode('utf-8', errors='ignore')
                        print(f"Reading and converting content of file: {filepath}")
                
                # Write the contents to the output file
                outfile.write(content)
                print(f"Written content of file: {filepath}")
            
            # Write a separator after the file contents or folder name
            outfile.write("\n" + "="*50 + "\n\n")
            print(f"Written separator for: {filepath}")

print(f"All files and folders have been combined into '{output_file_path}'")