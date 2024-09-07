"""
Operations for handling unsteady flow files in HEC-RAS projects.
"""
from pathlib import Path
from .project_config import ProjectConfig
import re

class UnsteadyOperations:
    """
    Class for all operations related to HEC-RAS unsteady flow files.
    """
    @staticmethod
    def copy_unsteady_files(dst_folder, template_unsteady):
        """
        Copy unsteady flow files from a template to the next available unsteady number
        and update the destination folder accordingly.

        Parameters:
        dst_folder (str): Destination folder path
        template_unsteady (str): Template unsteady flow number (e.g., 'u01')

        Returns:
        str: New unsteady flow number (e.g., 'u03')
        """
        config = ProjectConfig()
        config.check_initialized()

        src_folder = config.project_folder
        dst_folder = Path(dst_folder)
        dst_folder.mkdir(parents=True, exist_ok=True)

        # Determine the next available unsteady number
        existing_numbers = []
        unsteady_file_pattern = re.compile(r'^Flow File=u(\d+)', re.IGNORECASE)

        for plan_file in src_folder.glob("*.p[0-9][0-9]"):
            with open(plan_file, 'r') as file:
                lines = file.readlines()
                for line in lines:
                    match = unsteady_file_pattern.match(line.strip())
                    if match:
                        existing_numbers.append(int(match.group(1)))

        if existing_numbers:
            existing_numbers.sort()
            next_number = 1
            for num in existing_numbers:
                if num == next_number:
                    next_number += 1
                else:
                    break
        else:
            next_number = 1

        next_unsteady_number = f"{next_number:02d}"

        # Copy the template unsteady file to the new unsteady file
        template_unsteady_filename = f"{config.project_name}.u{template_unsteady}"
        src_u_file = src_folder / template_unsteady_filename
        if src_u_file.exists():
            new_unsteady_filename = f"{config.project_name}.u{next_unsteady_number}"
            dst_u_file = dst_folder / new_unsteady_filename
            dst_u_file.write_bytes(src_u_file.read_bytes())
            print(f"Copied {src_u_file} to {dst_u_file}")
        else:
            raise FileNotFoundError(f"Template unsteady file '{src_u_file}' does not exist.")

        # Copy the corresponding .hdf file
        src_hdf_file = src_folder / f"{template_unsteady_filename}.hdf"
        if src_hdf_file.exists():
            new_hdf_filename = f"{new_unsteady_filename}.hdf"
            dst_hdf_file = dst_folder / new_hdf_filename
            dst_hdf_file.write_bytes(src_hdf_file.read_bytes())
            print(f"Copied {src_hdf_file} to {dst_hdf_file}")
        else:
            print(f"No corresponding .hdf file found for '{template_unsteady_filename}'. Skipping '.hdf' copy.")
        config = ProjectConfig()
        return f"u{next_unsteady_number}"

    @staticmethod
    def rename_unsteady_files(old_number, new_number):
        """
        Rename unsteady flow files in the project folder.
        Parameters:
        old_number (str): Old unsteady flow number (e.g., 'u01')
        new_number (str): New unsteady flow number (e.g., 'u02')
        Returns:
        None
        """
        config = ProjectConfig()
        config.check_initialized()
        
        folder = config.project_folder
        old_u_file = next(folder.glob(f"*.{old_number}"), None)
        if old_u_file:
            new_u_file = folder / old_u_file.name.replace(old_number, new_number)
            old_u_file.rename(new_u_file)
            print(f"Renamed {old_u_file} to {new_u_file}")
        else:
            print(f"No .{old_number} file found in {folder}")
        
        old_hdf_file = next(folder.glob(f"*.{old_number}.hdf"), None)
        if old_hdf_file:
            new_hdf_file = folder / old_hdf_file.name.replace(old_number, new_number)
            old_hdf_file.rename(new_hdf_file)
            print(f"Renamed {old_hdf_file} to {new_hdf_file}")
        else:
            print(f"No .{old_number}.hdf file found in {folder}")

    @staticmethod
    def update_unsteady_reference_in_plan(plan_file, new_unsteady_number):
        """
        Update the unsteady flow reference in a plan file.
        
        Parameters:
        plan_file (str): Full path to the plan file
        new_unsteady_number (str): New unsteady flow number (e.g., 'u02')
        
        Returns:
        None
        """
        config = ProjectConfig()
        config.check_initialized()
        
        plan_path = Path(plan_file)
        if not plan_path.is_file():
            raise FileNotFoundError(f"Plan file '{plan_path}' not found. Check that the file exists.")
        
        with open(plan_path, 'r') as f:
            lines = f.readlines()
        updated = False
        for i, line in enumerate(lines):
            if line.startswith("Unsteady File=") or line.startswith("Flow File=u"):
                lines[i] = f"Unsteady File={new_unsteady_number}\n"
                updated = True
                break
        if updated:
            with open(plan_path, 'w') as f:
                f.writelines(lines)
            print(f"Updated unsteady flow reference in {plan_file} to {new_unsteady_number}")
        else:
            print(f"No unsteady flow reference found in {plan_file}")
            
    @staticmethod
    def modify_unsteady_flow_parameters(unsteady_file, modifications):
        """
        Modify parameters in an unsteady flow file.
        Parameters:
        unsteady_file (str): Full path to the unsteady flow file
        modifications (dict): Dictionary of modifications to apply, where keys are parameter names and values are new values
        Returns:
        None
        """
        config = ProjectConfig()
        config.check_initialized()
        
        unsteady_path = Path(unsteady_file)
        with open(unsteady_path, 'r') as f:
            lines = f.readlines()
        updated = False
        for i, line in enumerate(lines):
            for param, new_value in modifications.items():
                if line.startswith(f"{param}="):
                    lines[i] = f"{param}={new_value}\n"
                    updated = True
                    print(f"Updated {param} to {new_value}")
        if updated:
            with open(unsteady_path, 'w') as f:
                f.writelines(lines)
            print(f"Applied modifications to {unsteady_file}")
        else:
            print(f"No matching parameters found in {unsteady_file}")
