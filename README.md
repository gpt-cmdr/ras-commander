# Start of Selection
# RAS Commander (ras-commander)

RAS Commander is a Python library for automating HEC-RAS operations, providing a set of tools to interact with HEC-RAS project files, execute simulations, and manage project data. This library is an evolution of the RASCommander 1.0 Python Notebook Application previously released under HEC-Commander tools.

Contributors:
William Katzenmeyer, P.E., C.F.M. - billk@fenstermaker.com
Sean Micek, P.E., C.F.M. - smicek@fenstermaker.com
Aaron Nichols, P.E., C.F.M. - anichols@fenstermaker.com

## Features

- Automate HEC-RAS project management and simulations
- Support for both single and multiple project instances
- Parallel execution of HEC-RAS plans
- Utilities for managing geometry, plan, and unsteady flow files
- Example project management for testing and development
- Two primary operation modes: "Run Missing" and "Build from DSS"

## Installation

Install ras-commander using pip:

```bash
pip install pandas requests pathlib # Only 3 requirements for ras-commander, needs to be added to the requirements.txt file so pip install works
pip install ras-commander
```

## Requirements

- Python 3.9+
- HEC-RAS 6.2 or later (other versions may work, all testing was done with version 6.2 and above)

For a full list of dependencies, see the `requirements.txt` file.

## Quick Start

```python
from ras_commander import init_ras_project, RasCmdr, RasPlan

# Initialize a project
init_ras_project(r"/path/to/project", "6.5")

# Execute a single plan
RasCmdr.compute_plan("01", dest_folder=r"/path/to/results", overwrite_dest=True)

# Execute plans in parallel
results = RasCmdr.compute_parallel(
    plan_numbers=["01", "02"],
    max_workers=2,
    cores_per_run=2,
    dest_folder=r"/path/to/results",
    overwrite_dest=True
)

# Modify a plan
RasPlan.set_geom("01", "02")
```

## Key Components

- `RasPrj`: Manages HEC-RAS projects
- `RasCmdr`: Handles execution of HEC-RAS simulations
- `RasPlan`: Provides functions for modifying and updating plan files
- `RasGeo`: Handles operations related to geometry files
- `RasUnsteady`: Manages unsteady flow file operations
- `RasUtils`: Contains utility functions for file operations and data management
- `RasExamples`: Manages and loads HEC-RAS example projects

## Documentation

For detailed usage instructions and API documentation, please refer to the [Comprehensive Library Guide](Comprehensive_Library_Guide.md).

## Examples

Check out the `examples/` directory for sample scripts demonstrating various features of ras-commander.

## Project Organization Diagram

```
ras_commander
├── .github
│   └── workflows
│       └── python-package.yml
├── ras_commander
│   ├── __init__.py
│   ├── RasCmdr.py
│   ├── RasExamples.py
│   ├── RasGeo.py
│   ├── RasPlan.py
│   ├── RasPrj.py
│   ├── RasUnsteady.py
│   └── RasUtils.py
├── examples
│   ├── 01_project_initialization.py
│   ├── 02_plan_operations.py
│   ├── 03_geometry_operations.py
│   ├── 04_unsteady_flow_operations.py
│   ├── 05_utility_functions.py
│   ├── 06_single_plan_execution.py
│   ├── 07_sequential_plan_execution.py
│   ├── 08_parallel_execution.py
│   ├── 09_specifying_plans.py
│   ├── 10_arguments_for_compute.py
│   ├── 11_Using_RasExamples.ipynb
│   ├── 12_plan_set_execution.py
│   └── 13_multiple_project_operations.py
├── tests
│   └── ... (test files)
├── .gitignore
├── LICENSE
├── README.md
├── STYLE_GUIDE.md
├── Comprehensive_Library_Guide.md
├── pyproject.toml
├── setup.cfg
├── setup.py
└── requirements.txt
```

## Inclusion of .cursorrules and ai_tools for AI-driven Coding Experience

Open the ras_commander folder in the Cursor IDE, and it will automatically include the .cursorrules file in your instructions.  Additionally, two other provided methods for interacting with the library through your current AI subscriptions: 

- ChatGPT:  ras_commander GPT Assistant (LINK HERE)
- Latest LLM summaries of the code base:
   - Entire code base: LINK HERE (TOKEN COUNT) (for Claude or Gemini)
   - Examples and Function Docstrings Only: LINK HERE (TOKEN COUNT) (for GPT-4o, o1 or Llama 3.1 405b)
- Cursor IDE through .cursorrules file
- 'rascommander_code_assistant.ipynb' notebook in the ras_commander folder, which allows for dynamic summarization of the code base and API chatting directly through the notebook. 

There are a series of scripts provided in the "llm_summaries" folder that provide summaries of the code base, and the docstrings of the functions.  They can be run in your local environment, or provided to ChatGPT's code interpreter for execution.  

## RAS-Cmdr GPT Assistant 

The RAS Commander GPT assistant has access to the entire code base, and can be a helpful tool for understanding the library and its capabilities.  However, it is subject to the same context window limitations and file retrieval limitations as I have covered in ADD BLOG LINK HERE.  For best results, use the llm summaries above to provide robust context to the model before asking to generate complex workflows. 

## Current Uses and Roadmap Items

### Potential Uses (Roadmap Items) of HEC-RAS Automation Functions

This set of functions provides a powerful foundation for automating various aspects of HEC-RAS modeling workflows. Here are some potential applications:

1. **Calibration and Sensitivity Analysis:**
    - **Automated Parameter Variation:** Users can create multiple simulation scenarios with varying parameters (e.g., Manning's n values, boundary conditions, initial conditions) to calibrate their model against observed data.
    - **Sensitivity Testing:** Evaluate the impact of different input parameters on model outputs by generating a range of scenarios and analyzing the results. This helps identify critical parameters that require more attention during calibration.

2. **Real-time Forecasting:**
    - **Dynamic Model Updates:** Integrate with external data sources (e.g., weather forecasts, streamflow observations) to automatically update boundary conditions and initial conditions in unsteady flow files before running the simulation.
    - **Ensemble Forecasting:** Generate multiple forecasts by incorporating uncertainty in input data and model parameters. This provides a more comprehensive understanding of potential future flow conditions.

3. **Scenario Analysis:**
    - **Land Use Change Impacts:** Evaluate the effects of land use changes on flood risk by modifying Manning's n values using `extract_2d_mannings_tables`, `modify_2d_mannings_table`, and `write_2d_mannings_tables` and running simulations with updated geometry files.
    - **Climate Change Impacts:** Analyze the potential impacts of projected climate changes on flood risk by adjusting precipitation patterns and other relevant parameters in unsteady flow files.

4. **Batch Processing and High-Performance Computing:**
    - **Large-scale Model Runs:** Utilize `run_plans_parallel` to execute multiple simulations concurrently on a multi-core system, significantly reducing processing time for large-scale models or complex scenarios.
    - **Automated Report Generation:** Integrate with Python libraries like matplotlib and bokeh to automatically generate customized reports summarizing simulation results, including tables, figures, and maps.

5. **Model Development and Testing:**
    - **Rapid Prototyping:** Quickly set up and run new model configurations using template files and automated workflows, facilitating rapid model development and testing.
    - **Regression Testing:** Ensure model integrity and consistency after code changes or updates by automatically running a predefined set of simulations and comparing results with expected outputs.

6. **User-Friendly Interfaces:**
    - **GUI Development:** Integrate with Python GUI libraries like Tkinter or PyQt to create user-friendly interfaces for automating HEC-RAS workflows, allowing non-programmers to access the power of automation.

## Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details on how to submit pull requests, report issues, and suggest improvements.

## Style Guide

This project follows a specific style guide to maintain consistency across the codebase. Please refer to the [Style Guide](STYLE_GUIDE.md) for details on coding conventions, documentation standards, and best practices.

## License

ras-commander is released under the MIT License. See the license file for details.

## Acknowledgments

RAS Commander is based on the HEC-Commander project's "Command Line is All You Need" approach, leveraging the HEC-RAS command-line interface for automation. The initial development of this library was presented in the HEC-Commander Tools repository.  In a 2024 Australian Water School webinar, Bill demonstrated the derivation of basic HEC-RAS automation functions from plain language instructions. Leveraging the previously developed code and AI tools, the library was created. The primary tools used for this initial development were Anthropic's Claude, GPT-4o, Google's Gemini Experimental models, and the Cursor AI Coding IDE.

## Contact

For questions, suggestions, or support, please contact:
William Katzenmeyer, P.E., C.F.M. - billk@fenstermaker.com
# End of Selection
```
