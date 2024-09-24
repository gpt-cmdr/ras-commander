import sys
from pathlib import Path

# Add the parent directory to the Python path
current_file = Path(__file__).resolve()
parent_directory = current_file.parent.parent
sys.path.append(str(parent_directory))

# Flexible imports to allow for development without installation
try:
    from ras_commander import init_ras_project, RasPrj, RasExamples
except ImportError:
    sys.path.append(str(parent_directory))
    from ras_commander import init_ras_project, RasPrj, RasExamples

import logging

def generate_category_summary(category_path):
    summary = []
    summary.append(f"RAS-Commander Example Projects Summary for Category: {category_path.name}\n")
    summary.append("=" * 80 + "\n\n")

    for project_path in category_path.iterdir():
        if project_path.is_dir():
            summary.append(f"Project Folder: {project_path.name}")
            summary.append(f"Full Path: {project_path.resolve()}\n")

            try:
                ras_project = init_ras_project(project_path, "6.5", ras_instance=RasPrj())
                
                summary.append(f"Project Name: {ras_project.get_project_name()}")
                summary.append(f"PRJ File: {ras_project.prj_file}")
                summary.append(f"RAS Executable: {ras_project.ras_exe_path}\n")

                summary.append("Plan Files:")
                summary.append(ras_project.plan_df.to_string())
                summary.append("\n")

                summary.append("Flow Files:")
                summary.append(ras_project.flow_df.to_string())
                summary.append("\n")

                summary.append("Geometry Files:")
                summary.append(ras_project.geom_df.to_string())
                summary.append("\n")

                summary.append("Unsteady Flow Files:")
                summary.append(ras_project.unsteady_df.to_string())
                summary.append("\n")

                summary.append("Boundary Conditions:")
                summary.append(ras_project.boundaries_df.to_string())
                summary.append("\n")

                # Add unparsed lines for each boundary condition
                summary.append("Unparsed Boundary Condition Lines:")
                for _, row in ras_project.boundaries_df.iterrows():
                    bc_number = row['boundary_condition_number']
                    unsteady_number = row['unsteady_number']
                    unparsed_lines = ras_project._parse_boundary_condition(
                        ras_project._get_boundary_condition_block(unsteady_number, bc_number),
                        unsteady_number,
                        bc_number
                    )[1]
                    if unparsed_lines:
                        summary.append(f"BC {bc_number} in Unsteady File {unsteady_number}:")
                        summary.append(unparsed_lines)
                        summary.append("\n")
                summary.append("\n")

            except Exception as e:
                summary.append(f"Error initializing RAS project: {str(e)}\n")

            summary.append("-" * 80 + "\n\n")

    return "\n".join(summary)

def main():
    # Set logging level to DEBUG to capture unparsed lines
    logging.getLogger().setLevel(logging.DEBUG)

    ras_examples = RasExamples()
    all_categories = ras_examples.list_categories()

    base_dir = Path.cwd() / "ras_example_categories"
    base_dir.mkdir(exist_ok=True)

    for category in all_categories:
        category_dir = base_dir / category
        category_dir.mkdir(exist_ok=True)

        projects = ras_examples.list_projects(category)
        extracted_paths = ras_examples.extract_project(projects)

        # Move extracted projects to the category directory
        for path in extracted_paths:
            new_path = category_dir / path.name
            path.rename(new_path)

        # Generate and save summary for this category
        summary_text = generate_category_summary(category_dir)
        output_file = base_dir / f"ras-commander {category} summary.txt"
        with open(output_file, "w") as f:
            f.write(summary_text)

        print(f"Summary for category '{category}' has been written to: {output_file}")

    print("All category summaries have been generated.")

    # Clean up extracted projects
    ras_examples.clean_projects_directory()
    print("Cleaned up original extracted example projects.")

if __name__ == "__main__":
    main()