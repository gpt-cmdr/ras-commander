# RAS Commander (ras-commander)

RAS Commander is a Python library for automating HEC-RAS operations, providing a set of tools to interact with HEC-RAS project files, execute simulations, and manage project data. This library is an evolution of the RASCommander 1.0 Python Notebook Application previously released under the [HEC-Commander tools repository](https://github.com/billk-FM/HEC-Commander).

## Contributors:
William Katzenmeyer, P.E., C.F.M. - billk@fenstermaker.com
Sean Micek, P.E., C.F.M. - smicek@fenstermaker.com
Aaron Nichols, P.E., C.F.M. - anichols@fenstermaker.com
(Your Name Here)

## Background
The ras-commander library emerged from the initial test-bed of AI-driven coding represented by the HEC-Commander tools Python notebooks. These notebooks served as a proof of concept, demonstrating the value proposition of automating HEC-RAS operations. The transition from notebooks to a structured library aims to provide a more robust, maintainable, and extensible solution for water resources engineers.

## Features

- Automate HEC-RAS project management and simulations
- Support for both single and multiple project instances
- Parallel execution of HEC-RAS plans
- Utilities for managing geometry, plan, and unsteady flow files
- Example project management for testing and development
- Two primary operation modes: "Run Missing" and "Build from DSS"

## Installation

Install ras-commander using pip:

pip install pandas requests pathlib
pip install ras-commander

## Requirements

- Python 3.9+
- HEC-RAS 6.2 or later (other versions may work, all testing was done with version 6.2 and above)

For a full list of dependencies, see the `requirements.txt` file.

## Quick Start

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

## Key Components

- `RasPrj`: Manages HEC-RAS projects
- `RasCmdr`: Handles execution of HEC-RAS simulations
- `RasPlan`: Provides functions for modifying and updating plan files
- `RasGeo`: Handles operations related to geometry files
- `RasUnsteady`: Manages unsteady flow file operations
- `RasUtils`: Contains utility functions for file operations and data management
- `RasExamples`: Manages and loads HEC-RAS example projects


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

## Accessing HEC Examples through RasExamples

The `RasExamples` class provides functionality for quickly loading and managing HEC-RAS example projects. This is particularly useful for testing and development purposes.

Key features:
- Download and extract HEC-RAS example projects
- List available project categories and projects
- Extract specific projects for use
- Manage example project data efficiently

Example usage:
from ras_commander import RasExamples

ras_examples = RasExamples()
ras_examples.get_example_projects()  # Downloads example projects if not already present
categories = ras_examples.list_categories()
projects = ras_examples.list_projects("Steady Flow")
extracted_paths = ras_examples.extract_project(["Bald Eagle Creek", "Muncie"])

## RasPrj

The `RasPrj` class is central to managing HEC-RAS projects within the ras-commander library. It handles project initialization, data loading, and provides access to project components.

Key features:
- Initialize HEC-RAS projects
- Load and manage project data (plans, geometries, flows, etc.)
- Provide easy access to project files and information

Note: While a global `ras` object is available for convenience, you can create multiple `RasPrj` instances to manage several projects simultaneously.

Example usage:
from ras_commander import RasPrj, init_ras_project

# Using the global ras object
init_ras_project("/path/to/project", "6.5")

# Creating a custom RasPrj instance
custom_project = RasPrj()
init_ras_project("/path/to/another_project", "6.5", ras_instance=custom_project)


## AI-Driven Coding Experience

ras-commander provides several AI-powered tools to enhance the coding experience:

1. ChatGPT Assistant: A specialized GPT model trained on the ras-commander codebase, available for answering queries and providing code suggestions.

2. LLM Summaries: Up-to-date summaries of the codebase for use with large language models like Claude or GPT-4.

3. Cursor IDE Integration: Custom rules for the Cursor IDE to provide context-aware suggestions and documentation.

4. Jupyter Notebook Assistant: A notebook for dynamic code summarization and API interaction.

These tools aim to streamline development and provide intelligent assistance when working with the ras-commander library.

## Documentation

For detailed usage instructions and API documentation, please refer to the [Comprehensive Library Guide](Comprehensive_Library_Guide.md).

## Examples

Check out the `examples/` directory for sample scripts demonstrating various features of ras-commander.

## Inclusion of .cursorrules and ai_tools for AI-driven Coding Experience

Open the ras_commander folder in the Cursor IDE, and it will automatically include the .cursorrules file in your instructions. Additionally, two other provided methods for interacting with the library through your current AI subscriptions:

- ChatGPT: ras_commander GPT Assistant (LINK HERE)
- Latest LLM summaries of the code base:
   - Entire code base: LINK HERE (TOKEN COUNT) (for Claude or Gemini)
   - Examples and Function Docstrings Only: LINK HERE (TOKEN COUNT) (for GPT-4o, o1 or Llama 3.1 405b)
- Cursor IDE through .cursorrules file
- 'rascommander_code_assistant.ipynb' notebook in the ras_commander folder, which allows for dynamic summarization of the code base and API chatting directly through the notebook.

There are a series of scripts provided in the "llm_summaries" folder that provide summaries of the code base, and the docstrings of the functions. They can be run in your local environment, or provided to ChatGPT's code interpreter for execution.

## RAS-Cmdr GPT Assistant

The RAS Commander GPT assistant has access to the entire code base, and can be a helpful tool for understanding the library and its capabilities.  However, it is subject to the same context window limitations and file retrieval limitations as I have covered in ADD BLOG LINK HERE.  For best results, use the llm summaries above to provide robust context to the model before asking to generate complex workflows. 

## Future Development

The ras-commander library is an ongoing project. Future plans include:
- Integration of more advanced AI-driven features
- Expansion of HMS and DSS functionalities
- Enhanced GPU support for computational tasks
- Community-driven development of new modules and features

## Related Resources

- [HEC-Commander Blog](https://github.com/billk-FM/HEC-Commander/tree/main/Blog)
- [GPT-Commander YouTube Channel](https://www.youtube.com/@GPT_Commander)
- [ChatGPT Examples for Water Resources Engineers](https://github.com/billk-FM/HEC-Commander/tree/main/ChatGPT%20Examples)


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
