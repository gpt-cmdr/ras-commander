"""
Operations for modifying and updating HEC-RAS plan files.
"""
import re
from pathlib import Path


from .project_config import ProjectConfig

class PlanOperations:
    """
    A class for operations on HEC-RAS plan files.
    """
    @staticmethod
    def apply_geometry_to_plan(plan_file, geometry_number):
        """
        Apply a geometry file to a plan file.
        
        Parameters:
        plan_file (str): Full path to the HEC-RAS plan file (.pXX)
        geometry_number (str): Geometry number to apply (e.g., '01')
        
        Returns:
        None

        Raises:
        ValueError: If the specified geometry number is not found in the project file
        """
        config = ProjectConfig()
        config.check_initialized()
        
        if f"g{geometry_number}" not in config.ras_geom_entries['geom_number'].values:
            raise ValueError(f"Geometry number g{geometry_number} not found in project file.")
        with open(plan_file, 'r') as f:
            lines = f.readlines()
        with open(plan_file, 'w') as f:
            for line in lines:
                if line.startswith("Geom File="):
                    f.write(f"Geom File=g{geometry_number}\n")
                    print(f"Updated Geom File in {plan_file} to g{geometry_number}")
                else:
                    f.write(line)

    @staticmethod
    def apply_flow_to_plan(plan_file, flow_number):
        """
        Apply a steady flow file to a plan file.
        
        Parameters:
        plan_file (str): Full path to the HEC-RAS plan file (.pXX)
        flow_number (str): Flow number to apply (e.g., '02')
        
        Returns:
        None

        Raises:
        ValueError: If the specified flow number is not found in the project file
        """
        config = ProjectConfig()
        config.check_initialized()
        
        if f"{flow_number}" not in config.ras_flow_entries['flow_number'].values:
            raise ValueError(f"Flow number f{flow_number} not found in project file.")
        with open(plan_file, 'r') as f:
            lines = f.readlines()
        with open(plan_file, 'w') as f:
            for line in lines:
                if line.startswith("Flow File="):
                    f.write(f"Flow File=f{flow_number}\n")
                    print(f"Updated Flow File in {plan_file} to f{flow_number}")
                else:
                    f.write(line)
                    
    @staticmethod
    def copy_plan_from_template(template_plan):
        """
        Create a new plan file based on a template and update the project file.
        
        Parameters:

        template_plan (str): Plan file to use as template (e.g., '01')
        project_folder, project_name, 
        Returns:
        str: New plan number
        """
        config = ProjectConfig()
        config.check_initialized()

        # Read existing plan numbers
        ras_plan_entries = config.ras_plan_entries

        # Get next available plan number
        new_plan_num = PlanOperations.get_next_available_number(ras_plan_entries['plan_number'])

        # Copy template plan file to new plan file
        template_plan_path = Path(config.project_folder) / f"{config.project_name}.p{template_plan}"
        new_plan_path = Path(config.project_folder) / f"{config.project_name}.p{new_plan_num}"
        new_plan_path.write_bytes(template_plan_path.read_bytes())
        print(f"Copied {template_plan_path} to {new_plan_path}")

        # Update project file with new plan
        project_file = config.project_file
        with open(project_file, 'a') as f:
            f.write(f"\nPlan File=p{new_plan_num}")
        print(f"Updated {project_file} with new plan p{new_plan_num}")
        config = ProjectConfig()
        return f"{new_plan_num}"

    @staticmethod
    def get_next_available_number(existing_numbers):
        """
        Determine the next available number from a list of existing numbers.
        
        Parameters:
        existing_numbers (list): List of existing numbers as strings
        
        Returns:
        str: Next available number as a zero-padded string
        """
        existing_numbers = sorted(int(num) for num in existing_numbers)
        next_number = 1
        for num in existing_numbers:
            if num == next_number:
                next_number += 1
            else:
                break
        return f"{next_number:02d}"



    @staticmethod
    def apply_unsteady_to_plan(plan_file, unsteady_number):
        """
        Apply an unsteady flow file to a plan file.
        
        Parameters:
        plan_file (str): Full path to the HEC-RAS plan file (.pXX)
        unsteady_number (str): Unsteady flow number to apply (e.g., '01')
        
        Returns:
        None

        Raises:
        ValueError: If the specified unsteady number is not found in the project file
        """
        config = ProjectConfig()
        config.check_initialized()
        
        if f"u{unsteady_number}" not in config.ras_unsteady_entries['unsteady_number'].values:
            raise ValueError(f"Unsteady number u{unsteady_number} not found in project file.")
        with open(plan_file, 'r') as f:
            lines = f.readlines()
        with open(plan_file, 'w') as f:
            for line in lines:
                if line.startswith("Unsteady File=") or line.startswith("Flow File=u"):
                    f.write(f"Unsteady File=u{unsteady_number}\n")
                    print(f"Updated Unsteady File in {plan_file} to u{unsteady_number}")
                else:
                    f.write(line)

    @staticmethod
    def set_num_cores(plan_file, num_cores):
        """
        Update the maximum number of cores to use in the HEC-RAS plan file.
        
        Parameters:
        plan_file (str): Full path to the plan file
        num_cores (int): Maximum number of cores to use
        
        Returns:
        None
        """
        config = ProjectConfig()
        config.check_initialized()
        
        cores_pattern = re.compile(r"(UNET D1 Cores= )\d+")
        with open(plan_file, 'r') as file:
            content = file.read()
        new_content = cores_pattern.sub(rf"\g<1>{num_cores}", content)
        with open(plan_file, 'w') as file:
            file.write(new_content)
        print(f"Updated {plan_file} with {num_cores} cores.")

    @staticmethod
    def update_geompre_flags(file_path, run_htab_value, use_ib_tables_value):
        """
        Update the simulation plan file to modify the `Run HTab` and `UNET Use Existing IB Tables` settings.
        
        Parameters:
        file_path (str): Path to the simulation plan file (.p06 or similar) that you want to modify.
        run_htab_value (int): Value for the `Run HTab` setting:
            - `0` : Do not run the geometry preprocessor, use existing geometry tables.
            - `-1` : Run the geometry preprocessor, forcing a recomputation of the geometry tables.
        use_ib_tables_value (int): Value for the `UNET Use Existing IB Tables` setting:
            - `0` : Use existing interpolation/boundary (IB) tables without recomputing them.
            - `-1` : Do not use existing IB tables, force a recomputation.
        
        Returns:
        None

        Raises:
        ValueError: If `run_htab_value` or `use_ib_tables_value` are not integers or not within the accepted values (`0` or `-1`).
        FileNotFoundError: If the specified file does not exist.
        IOError: If there is an error reading or writing the file.
        """
        config = ProjectConfig()
        config.check_initialized()
        
        if run_htab_value not in [-1, 0]:
            raise ValueError("Invalid value for `Run HTab`. Expected `0` or `-1`.")
        if use_ib_tables_value not in [-1, 0]:
            raise ValueError("Invalid value for `UNET Use Existing IB Tables`. Expected `0` or `-1`.")
        try:
            print(f"Reading the file: {file_path}")
            with open(file_path, 'r') as file:
                lines = file.readlines()
            print("Updating the file with new settings...")
            updated_lines = []
            for line in lines:
                if line.strip().startswith("Run HTab="):
                    updated_line = f"Run HTab= {run_htab_value} \n"
                    updated_lines.append(updated_line)
                    print(f"Updated 'Run HTab' to {run_htab_value}")
                elif line.strip().startswith("UNET Use Existing IB Tables="):
                    updated_line = f"UNET Use Existing IB Tables= {use_ib_tables_value} \n"
                    updated_lines.append(updated_line)
                    print(f"Updated 'UNET Use Existing IB Tables' to {use_ib_tables_value}")
                else:
                    updated_lines.append(line)
            print(f"Writing the updated settings back to the file: {file_path}")
            with open(file_path, 'w') as file:
                file.writelines(updated_lines)
            print("File update completed successfully.")
        except FileNotFoundError:
            raise FileNotFoundError(f"The file '{file_path}' does not exist.")
        except IOError as e:
            raise IOError(f"An error occurred while reading or writing the file: {e}")

    @staticmethod
    def get_plan_full_path(plan_number: str) -> str:
        """Return the full path for a given plan number."""
        config = ProjectConfig()
        config.check_initialized()
        
        plan_path = config.ras_plan_entries[config.ras_plan_entries['plan_number'] == plan_number]
        if not plan_path.empty:
            return plan_path['full_path'].iloc[0]
        else:
            raise ValueError(f"Plan number {plan_number} not found.")

    @staticmethod
    def get_results_full_path(plan_number: str) -> str:
        """Return the results path for a given plan number."""
        config = ProjectConfig()
        config.check_initialized()
        
        results_path = config.ras_plan_entries[config.ras_plan_entries['plan_number'] == plan_number]
        if not results_path.empty:
            results_file_path = Path(results_path['results_path'].iloc[0])
            if results_file_path.exists():
                print(f"Results file for Plan number {plan_number} exists at: {results_file_path}")
                return str(results_file_path)
            else:
                print(f"Error: Results file for Plan number {plan_number} does not exist at the expected location: {results_file_path}")
                return None
        else:
            print(f"Error: Results file for Plan number {plan_number} not found in the entries.")
            return None




    @staticmethod
    def get_flow_full_path(flow_number: str) -> str:
        """Return the full path for a given flow number."""
        config = ProjectConfig()
        config.check_initialized()
        
        flow_path = config.ras_flow_entries[config.ras_flow_entries['flow_number'] == flow_number]
        if not flow_path.empty:
            return flow_path['full_path'].iloc[0]
        else:
            raise ValueError(f"Flow number {flow_number} not found.")

    @staticmethod
    def get_unsteady_full_path(unsteady_number: str) -> str:
        """Return the full path for a given unsteady number."""
        config = ProjectConfig()
        config.check_initialized()
        
        unsteady_path = config.ras_unsteady_entries[config.ras_unsteady_entries['unsteady_number'] == unsteady_number]
        if not unsteady_path.empty:
            return unsteady_path['full_path'].iloc[0]
        else:
            raise ValueError(f"Unsteady number {unsteady_number} not found.")

    @staticmethod
    def get_geom_full_path(geometry_number: str) -> str:
        """Return the full path for a given geometry number."""
        config = ProjectConfig()
        config.check_initialized()
        
        geom_path = config.ras_geom_entries[config.ras_geom_entries['geom_number'] == geometry_number]
        if not geom_path.empty:
            return geom_path['full_path'].iloc[0]
        else:
            raise ValueError(f"Geometry number {geometry_number} not found.")