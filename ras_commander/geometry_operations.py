"""
Operations for handling geometry files in HEC-RAS projects.
"""
from pathlib import Path
from .plan_operations import PlanOperations
from .file_operations import FileOperations
from .project_config import ProjectConfig
import re

class GeometryOperations:
    """
    A class for operations on HEC-RAS geometry files.
    """
    @staticmethod
    def clear_geometry_preprocessor_files(plan_file):
        """
        Clear HEC-RAS geometry preprocessor files for a given plan file.
        
        Parameters:
        plan_file (str): Full path to the HEC-RAS plan file (.p*)
        
        Returns:
        None
        """
        config = ProjectConfig()
        config.check_initialized()
        
        plan_path = Path(plan_file)
        geom_preprocessor_file = plan_path.with_suffix('.c' + plan_path.suffix[2:])
        if geom_preprocessor_file.exists():
            print(f"Deleting geometry preprocessor file: {geom_preprocessor_file}")
            geom_preprocessor_file.unlink()
            print("File deletion completed successfully.")
        else:
            print(f"No geometry preprocessor file found for: {plan_file}")

    @staticmethod
    def clear_geometry_preprocessor_files_for_all_plans():
        """
        Clear HEC-RAS geometry preprocessor files for all plan files in the project directory.
        
        Returns:
        None
        """
        config = ProjectConfig()
        config.check_initialized()
        
        for plan_file in config.project_folder.glob("*.p[0-9][0-9]"):
            GeometryOperations.clear_geometry_preprocessor_files(plan_file)

    @staticmethod
    def copy_geometry_files(dst_folder, template_geom):
        """
        Copy geometry files from a template to the next available geometry number
        and update the destination folder accordingly.

        Parameters:
        dst_folder (str): Destination folder path
        template_geom (str): Template geometry number (e.g., 'g01')

        Returns:
        str: New geometry number (e.g., 'g03')
        """
        config = ProjectConfig()
        config.check_initialized()

        src_folder = config.project_folder
        dst_folder = Path(dst_folder)
        dst_folder.mkdir(parents=True, exist_ok=True)

        # Determine the next available geometry number
        existing_numbers = []
        geom_file_pattern = re.compile(r'^Geom File=g(\d+)', re.IGNORECASE)

        for plan_file in src_folder.glob("*.p[0-9][0-9]"):
            with open(plan_file, 'r') as file:
                lines = file.readlines()
                for line in lines:
                    match = geom_file_pattern.match(line.strip())
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

        next_geom_number = f"{next_number:02d}"

        # Copy the template geometry file to the new geometry file
        template_geom_filename = f"{config.project_name}.g{template_geom}"
        src_g_file = src_folder / template_geom_filename
        if src_g_file.exists():
            new_geom_filename = f"{config.project_name}.g{next_geom_number}"
            dst_g_file = dst_folder / new_geom_filename
            dst_g_file.write_bytes(src_g_file.read_bytes())
            print(f"Copied {src_g_file} to {dst_g_file}")
        else:
            raise FileNotFoundError(f"Template geometry file '{src_g_file}' does not exist.")

        # Copy the corresponding .hdf file
        src_hdf_file = src_folder / f"{template_geom_filename}.hdf"
        if src_hdf_file.exists():
            new_hdf_filename = f"{new_geom_filename}.hdf"
            dst_hdf_file = dst_folder / new_hdf_filename
            dst_hdf_file.write_bytes(src_hdf_file.read_bytes())
            print(f"Copied {src_hdf_file} to {dst_hdf_file}")
        else:
            raise FileNotFoundError(f"Template geometry .hdf file '{src_hdf_file}' does not exist.")
        config = ProjectConfig()
        return f"g{next_geom_number}"

    @staticmethod
    def rename_geometry_files(old_number, new_number):
        """
        Rename geometry files in the project folder.
        
        Parameters:
        old_number (str): Old geometry number (e.g., 'g01')
        new_number (str): New geometry number (e.g., 'g02')
        
        Returns:
        None
        """
        config = ProjectConfig()
        config.check_initialized()
        
        folder = config.project_folder
        old_g_file = next(folder.glob(f"*.{old_number}"), None)
        if old_g_file:
            new_g_file = folder / old_g_file.name.replace(old_number, new_number)
            old_g_file.rename(new_g_file)
            print(f"Renamed {old_g_file} to {new_g_file}")
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
    def update_geometry_reference_in_plan(plan_file, new_geometry_number):
        """
        Update the geometry reference in a plan file.
        
        Parameters:
        plan_file (str): Full path to the plan file
        new_geometry_number (str): New geometry number (e.g., 'g02')
        
        Returns:
        None
        """
        config = ProjectConfig()
        config.check_initialized()
        
        geometry_full_path = next(config.project_folder.glob(f"*.g{new_geometry_number}"), None)
        if not geometry_full_path:
            raise FileNotFoundError(f"Geometry file '*.g{new_geometry_number}' not found in the project folder.")
        
        plan_path = Path(plan_file)
        with open(plan_path, 'r') as file:
            lines = file.readlines()
        updated = False
        for index, line in enumerate(lines):
            if line.startswith("Geom File="):
                lines[index] = f"Geom File=g{new_geometry_number}\n"
                updated = True
                break
        if updated:
            with open(plan_path, 'w') as file:
                file.writelines(lines)
            print(f"Updated geometry reference in {plan_file} to {new_geometry_number}")
        else:
            print(f"No geometry reference found in {plan_file}")
