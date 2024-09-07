"""
Project management operations for HEC-RAS projects.
"""
import os
import re
import shutil
from pathlib import Path
from .file_operations import FileOperations
from .project_config import ProjectConfig

class ProjectManager:
    """
    A class for functions that interface with the HEC-RAS project's project file.
    """
    @staticmethod
    def get_next_available_number(existing_numbers):
        """
        Determine the first available number for plan, unsteady, steady, or geometry files from 01 to 99.
        Parameters:
        existing_numbers (pandas.Series): Series of existing numbers as strings (e.g., ['01', '02', '03'])
        Returns:
        str: First available number as a two-digit string
        """
        existing_set = set(existing_numbers.astype(int))
        for num in range(1, 100):
            if num not in existing_set:
                return f"{num:02d}"
        return None

    @staticmethod
    def copy_plan_from_template(template_plan, new_plan_shortid=None):
        """
        Create a new plan file based on a template and update the project file.
        Parameters:
        template_plan (str): Plan file to use as template (e.g., 'p01')
        new_plan_shortid (str, optional): New short identifier for the plan file
        Returns:
        str: New plan number
        """
        config = ProjectConfig()
        config.check_initialized()

        new_plan_num = ProjectManager.get_next_available_number(config.ras_plan_entries['plan_number'])
        template_plan_path = config.project_folder / f"{config.project_name}.{template_plan}"
        new_plan_path = config.project_folder / f"{config.project_name}.p{new_plan_num}"
        shutil.copy(template_plan_path, new_plan_path)
        print(f"Copied {template_plan_path} to {new_plan_path}")

        with open(new_plan_path, 'r') as f:
            plan_lines = f.readlines()

        shortid_pattern = re.compile(r'^Short Identifier=(.*)$', re.IGNORECASE)
        for i, line in enumerate(plan_lines):
            match = shortid_pattern.match(line.strip())
            if match:
                current_shortid = match.group(1)
                if new_plan_shortid is None:
                    new_shortid = (current_shortid + "_copy")[:24]
                else:
                    new_shortid = new_plan_shortid[:24]
                plan_lines[i] = f"Short Identifier={new_shortid}\n"
                break

        with open(new_plan_path, 'w') as f:
            f.writelines(plan_lines)

        print(f"Updated short identifier in {new_plan_path}")

        with open(config.project_file, 'r') as f:
            lines = f.readlines()

        new_plan_line = f"Plan File=p{new_plan_num}\n"
        plan_file_pattern = re.compile(r'^Plan File=p(\d+)', re.IGNORECASE)
        insertion_index = None
        for i, line in enumerate(lines):
            match = plan_file_pattern.match(line.strip())
            if match:
                current_number = int(match.group(1))
                if current_number > int(new_plan_num):
                    insertion_index = i
                    break

        if insertion_index is not None:
            lines.insert(insertion_index, new_plan_line)
        else:
            last_plan_index = max([i for i, line in enumerate(lines) if plan_file_pattern.match(line.strip())], default=-1)
            if last_plan_index != -1:
                lines.insert(last_plan_index + 1, new_plan_line)
            else:
                lines.append(new_plan_line)

        with open(config.project_file, 'w') as f:
            f.writelines(lines)

        print(f"Updated {config.project_file} with new plan p{new_plan_num}")
        return f"p{new_plan_num}"

    @staticmethod
    def copy_geometry_from_template(template_geom):
        """
        Copy geometry files from a template, find the next geometry number,
        and update the project file accordingly.
        Parameters:
        template_geom (str): Geometry number to be used as a template (e.g., 'g01')
        Returns:
        str: New geometry number (e.g., 'g03')
        """
        config = ProjectConfig()
        config.check_initialized()

        template_geom_filename = f"{config.project_name}.{template_geom}"
        template_geom_path = config.project_folder / template_geom_filename

        if not template_geom_path.is_file():
            raise FileNotFoundError(f"Template geometry file '{template_geom_path}' does not exist.")

        template_hdf_path = template_geom_path.with_suffix('.hdf')
        if not template_hdf_path.is_file():
            raise FileNotFoundError(f"Template geometry .hdf file '{template_hdf_path}' does not exist.")

        next_geom_number = ProjectManager.get_next_available_number(config.ras_geom_entries['geom_number'])

        new_geom_filename = f"{config.project_name}.g{next_geom_number}"
        new_geom_path = config.project_folder / new_geom_filename

        shutil.copyfile(template_geom_path, new_geom_path)
        print(f"Copied '{template_geom_path}' to '{new_geom_path}'.")

        new_hdf_path = new_geom_path.with_suffix('.hdf')
        shutil.copyfile(template_hdf_path, new_hdf_path)
        print(f"Copied '{template_hdf_path}' to '{new_hdf_path}'.")

        with open(config.project_file, 'r') as file:
            lines = file.readlines()

        new_geom_line = f"Geom File=g{next_geom_number}\n"
        geom_file_pattern = re.compile(r'^Geom File=g(\d+)', re.IGNORECASE)
        insertion_index = None
        for i, line in enumerate(lines):
            match = geom_file_pattern.match(line.strip())
            if match:
                current_number = int(match.group(1))
                if current_number > int(next_geom_number):
                    insertion_index = i
                    break

        if insertion_index is not None:
            lines.insert(insertion_index, new_geom_line)
        else:
            header_pattern = re.compile(r'^(Proj Title|Current Plan|Default Exp/Contr|English Units)', re.IGNORECASE)
            header_indices = [i for i, line in enumerate(lines) if header_pattern.match(line.strip())]
            if header_indices:
                last_header_index = header_indices[-1]
                lines.insert(last_header_index + 2, new_geom_line)
            else:
                lines.insert(0, new_geom_line)

        with open(config.project_file, 'w') as file:
            file.writelines(lines)

        print(f"Inserted 'Geom File=g{next_geom_number}' into project file '{config.project_file}'.")
        return f"g{next_geom_number}"

    @staticmethod
    def copy_unsteady_from_template(template_unsteady):
        """
        Copy unsteady flow files from a template, find the next unsteady number,
        and update the project file accordingly.
        Parameters:
        template_unsteady (str): Unsteady flow number to be used as a template (e.g., 'u01')
        Returns:
        str: New unsteady flow number (e.g., 'u03')
        """
        config = ProjectConfig()
        config.check_initialized()

        template_unsteady_filename = f"{config.project_name}.{template_unsteady}"
        template_unsteady_path = config.project_folder / template_unsteady_filename

        if not template_unsteady_path.is_file():
            raise FileNotFoundError(f"Template unsteady flow file '{template_unsteady_path}' does not exist.")

        next_unsteady_number = ProjectManager.get_next_available_number(config.ras_unsteady_entries['unsteady_number'])

        new_unsteady_filename = f"{config.project_name}.u{next_unsteady_number}"
        new_unsteady_path = config.project_folder / new_unsteady_filename

        shutil.copyfile(template_unsteady_path, new_unsteady_path)
        print(f"Copied '{template_unsteady_path}' to '{new_unsteady_path}'.")

        template_hdf_path = template_unsteady_path.with_suffix('.hdf')
        new_hdf_path = new_unsteady_path.with_suffix('.hdf')

        if template_hdf_path.is_file():
            shutil.copyfile(template_hdf_path, new_hdf_path)
            print(f"Copied '{template_hdf_path}' to '{new_hdf_path}'.")
        else:
            print(f"No corresponding '.hdf' file found for '{template_unsteady_filename}'. Skipping '.hdf' copy.")

        with open(config.project_file, 'r') as file:
            lines = file.readlines()

        new_unsteady_line = f"Unsteady File=u{next_unsteady_number}\n"
        unsteady_file_pattern = re.compile(r'^Unsteady File=u(\d+)', re.IGNORECASE)
        insertion_index = None
        for i, line in enumerate(lines):
            match = unsteady_file_pattern.match(line.strip())
            if match:
                current_number = int(match.group(1))
                if current_number > int(next_unsteady_number):
                    insertion_index = i
                    break

        if insertion_index is not None:
            lines.insert(insertion_index, new_unsteady_line)
        else:
            last_unsteady_index = max([i for i, line in enumerate(lines) if unsteady_file_pattern.match(line.strip())], default=-1)
            if last_unsteady_index != -1:
                lines.insert(last_unsteady_index + 1, new_unsteady_line)
            else:
                lines.append(new_unsteady_line)

        with open(config.project_file, 'w') as file:
            file.writelines(lines)

        print(f"Inserted 'Unsteady File=u{next_unsteady_number}' into project file '{config.project_file}'.")
        return f"u{next_unsteady_number}"
