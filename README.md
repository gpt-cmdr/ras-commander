# RAS Commander (ras-commander)

<p align="center">
  <img src="ras-commander_logo.svg" width=70%>
</p>

RAS Commander is a Python library for automating HEC-RAS operations, providing a set of tools to interact with HEC-RAS project files, execute simulations, and manage project data. This library was initially conceptualized in the Australian Water School course "AI Tools for Modelling Innovation", and subsequently expanded to cover much of the basic functionality of the HECRASController COM32 interface using open-source python libraries.  This library uses a Test Driven Development strategy, leveraging the publicly-available HEC-RAS Example projects to create repeatable demonstration examples.  The "Commmander" moniker is inspired by the "Command Line is All You Need" approach to HEC-RAS automation that was first implemented in the HEC-Commander Tools repository. 

*[Check out the ASFPM Presentation on RAS-Commander Here](https://drive.google.com/file/d/1kX0twae8NrpLwR0iQ0Dmd8zAXdq-pYXD/view)*

## Repository Author:
[William Katzenmeyer, P.E., C.F.M.](https://engineeringwithllms.info)
-----  

## Don't Ask Me, Ask a GPT!

This repository has several methods of interaction with Large Language Models and LLM-Assisted Coding built right in: 

1. **[Purpose-Built Knowledge Base Summaries](https://github.com/gpt-cmdr/ras-commander/tree/main/ai_tools/llm_knowledge_bases)**: Up-to-date compilations of the documentation and codebase for use with large language models like Claude, ChatGPT, Gemini or Grok. Look in 'ai_tools/assistant_knowledge_bases/' in the repo.  The repo's codebase (without documentation and examples) has been curated to stay within the current ~200k context window limitations of frontier models, and for tasks that do not need an understanding of the underlying code, the Comprehensive Library Guide and any relevant examples from the example folder should be adequate context for leveraging the ras-commander API to complete tasks. 

2. **[Cursor IDE Integration](https://github.com/gpt-cmdr/ras-commander/blob/main/.cursorrules)**: Custom rules(.cursor/rules) for the Cursor IDE to provide context-aware suggestions and documentation.  Just open the repository folder in Cursor to recognize these instructions.  You can create your own folders "/workspace/, "/projects/", or "my_projects/" as these are already in the .gitignore, and place your custom scripts there for your projects.  This will allow easy referencing of the ras-commander documents and individual repo files, the automatic loading of the .cursorrules file.  Alternatvely, download the github repo into your projects folder to easily load documents and use cursor rules files.

3. **[RAS-Commander library as indexed by Deepwiki](https://deepwiki.com/gpt-cmdr/ras-commander)** An LLM-generated summary of the repostiory with diagrams and analysis of the library, as well as an integrated chat assistant with deep research. 

4. **[RAS-Commander Library Assistant](https://github.com/gpt-cmdr/ras-commander/blob/main/ai_tools/library_assistant/REAME.md)**:

<img align="left" width="25%" hspace="40" src="ai_tools/library_assistant/ras-commander_library_assistant.svg">

The RAS-Commander library Assistant is a full-featured interface for multi-turn conversations, using your own API keys and the ras-commander library for context. The library assistant allows you to load your own scripts and chat with specific examples and/or function classes in the RAS-Commander library to effectively utilize the library's functions in your workflow. To reduce hallucinations, a file browser is included which adds full files to the conversation to ensure grounded responses. A dashboard shows you the total context and estimated cost of each request. **Now with support for Claude 3.7 with extended thinking, OpenAI's o1, o3 and o4-mini, and Deepseek V3 and R1 models using US-based Together.ai**

5. **[RAS Commander Library Assistant on ChatGPT](https://chatgpt.com/g/g-TZRPR3oAO-ras-commander-library-assistant)**: A specialized ChatGPT "GPT" with access to the ras-commander codebase and library, available for answering queries and providing code suggestions.   You can even upload your own plan, unsteady and HDF files to inspect and help determine how to automate your workflows or visualize your results.  _NOTE: GPT's are still quite limited by OpenAI's GPT frameworks and may not be useful for long conversations.  Code interpreter cannot run HEC-RAS but can [open and view smaller HDF files and projects for demonstration purposes](https://chatgpt.com/share/67e7cdb7-49e0-8010-bbac-61d2c54d473f)_


## Background
The ras-commander library emerged from the initial test-bed of AI-driven coding represented by the [HEC-Commander tools](https://github.com/gpt-cmdr/HEC-Commander) Python notebooks. These notebooks served as a proof of concept, demonstrating the value proposition of automating HEC-RAS operations. In 2024, I taught a series of progressively more complex webinars demonstrating how to use simple prompting, example projects and natural language instruction to effectively code HEC-RAS automation workflows, culminating in a 6 hour course.  The library published for utilization in that course, [awsrastools](https://github.com/gpt-cmdr/awsrastools) served as a foundation of examples which were iteratively extended into the full RAS-Commander library.  Unlike the original notebook by the same name, this library is not focused on parallel execution across multiple machines.  Instead, it is focused on providing a general-purpose python API for interacting with HEC-RAS projects, and building an AI-friendly library that will allow new users to quickly scaffold their own workflows into a python script. Example notebooks are provided, but the intention is to empower engineers, software developers, GIS personnel and data analysts to more easily access and interact with HEC-RAS data in a python environment.  Also, by publishing these examples publicly, with complete working code examples and LLM optimization, future users can readily rewrite they key functions of the library for inclusion in into their own preferred libraries, languages or return formats.

## Features

If you've ever read the book "Breaking the HEC-RAS Code" by Chris Goodell, this library is intended to be an AI-coded, pythonic library that provides a modern alternative to the HECRASController API.  By leveraginging modern python features libraries such as pandas, geopandas and H5Py (favoring HDF data sources wherever practicable) this library builds functionality around HEC-RAS 6.2+ while maintaining as much forward compatibilty as possible with HEC-RAS 2025.  

HEC-RAS Project Management & Execution
- Multi-project handling with parallel and sequential execution
- Command-line execution integration
- Project folder management and organization
- Multi-core processing optimization
- Progress tracking and logging
- Execution error handling and recovery

HDF Data Access & Analysis
- 2D mesh results processing (depths, velocities, WSE)
- Cross-section data extraction
- Boundary condition analysis
- Structure data (bridges, culverts, gates)
- Pipe network and pump station analysis
- Fluvial-pluvial boundary calculations
- Infiltration and precipitation data handling
- Infiltration and soil data handling
- Land cover and terrain data integration
- Weighted parameter calculations for hydrologic modeling

RASMapper Data Integration
- RASMapper configuration parsing (.rasmap files)
- Terrain, soil, and land cover HDF paths
- Profile line paths

Manning's n Coefficient Management
- Base Manning's n table extraction and modification
- Regional overrides for spatially-varied roughness
- Direct editing of geometry file Manning values

Infiltration & Soil Analysis
- Soil statistics calculation and analysis
- Infiltration parameter management and scaling
- Weighted average parameter calculation
- Raster-based soil data processing

RAS ASCII File Operations
- Plan file creation and modification
- Geometry file parsing examples 
- Unsteady flow file management
- Project file updates and validation  

Note about support for Pipe Networks:  As a relatively new feature, only read access to Pipe Network geometry and results data has been included.  Users will need to code their own methods to modify/add pipe network data, and pull requests are always welcome to incorporate this capability.  Please note that the library has not been tested with versions prior to HEC-RAS 6.2.

## Installation

First, create a virtual environment with conda or venv (ask ChatGPT if you need help).  

#### Install via Pip

In your virtual environment, install ras-commander using pip:
```
pip install --upgrade ras-commander
```
If you have dependency issues with pip (especially if you have errors with numpy), try clearing your local pip packages 'C:\Users\your_username\AppData\Roaming\Python\' and then creating a new virtual environment.  

Dependencies can also be manually installed: 
```
pip install h5py numpy pandas requests tqdm scipy xarray geopandas matplotlib shapely pathlib rasterstats rtree
```


#### Work in a Local Copy

If you want to make revisions and work actively in your local version of ras-commander, just skip the pip install rascommander step above and clone a fork of the repo to your local machine using Git (ask ChatGPT if you need help).  Most of the notebooks and examples in this repo have a code segment similar to the one below, that works as long as the script is located in a first-level subfolder of the ras-commander repository:
```
# Flexible imports to allow for development without installation
try:
    # Try to import from the installed package
    from ras_commander import init_ras_project, RasExamples, RasCmdr, RasPlan, RasGeo, RasUnsteady, RasUtils, ras
except ImportError:
    # If the import fails, add the parent directory to the Python path
    current_file = Path(__file__).resolve()
    parent_directory = current_file.parent.parent
    sys.path.append(str(parent_directory))
    # Alternately, you can just define a path sys.path.append(r"c:/path/to/rascommander/rascommander)")
    
    # Now try to import again
    from ras_commander import init_ras_project, RasExamples, RasCmdr, RasPlan, RasGeo, RasUnsteady, RasUtils, ras
```
It is highly suggested to fork this repository before going this route, and using Git to manage your changes!  This allows any revisions to the ras-commander classes and functions to be actively edited and developed by end users. The folders "/workspace/, "/projects/", or "my_projects/" are included in the .gitignore, so users can place you custom scripts there for any project data they don't want to be tracked by git.

## Quick Start Guide

```
from ras_commander import init_ras_project, RasCmdr, RasPlan
```

### Initialize a project (single project)
```python
# Basic initialization using default HEC-RAS location (on C: drive)
init_ras_project(r"/path/to/project", "6.5")

# Specifying a custom path to Ras.exe (useful if HEC-RAS is not installed on C: drive)
init_ras_project(r"/path/to/project", r"D:/Programs/HEC/HEC-RAS/6.5/Ras.exe")
```

### Initialize a project (multiple projects)
```python
your_ras_project = RasPrj()
init_ras_project(r"/path/to/project", "6.5", ras_object=your_ras_project)
```

## Accessing Plan, Unsteady and Boundary Conditions Dataframes
Using the default 'ras" object, othewise substitute your_ras_project for muli-project scripts
```
print("\nPlan Files DataFrame:")
ras.plan_df
```
```
print("\nFlow Files DataFrame:")
ras.flow_df
```
```
print("\nUnsteady Flow Files DataFrame:")
ras.unsteady_df
```
```
print("\nGeometry Files DataFrame:")
ras.geom_df
```
```
print("\nBoundary Conditions DataFrame:")
ras.boundaries_df
```
```
print("\nHDF Entries DataFrame:")
ras.get_hdf_entries()
```



### Execute a single plan
```
RasCmdr.compute_plan("01", dest_folder=r"/path/to/results", overwrite_dest=True)
```

### Execute plans in parallel
```
results = RasCmdr.compute_parallel(
    plan_number=["01", "02"],
    max_workers=2,
    num_cores=2,
    dest_folder=r"/path/to/results",
    overwrite_dest=True
)
```

### Modify a plan
```
RasPlan.set_geom("01", "02")
```

### Execution Modes

RAS Commander provides three methods for executing HEC-RAS plans:

#### Single Plan Execution
```python
# Execute a single plan
success = RasCmdr.compute_plan("01", dest_folder=r"/path/to/results")
print(f"Plan execution {'successful' if success else 'failed'}")
```

#### Sequential Execution of Multiple Plans
```python
# Execute multiple plans in sequence in a test folder
results = RasCmdr.compute_test_mode(
    plan_number=["01", "02", "03"],
    dest_folder_suffix="[Test]"
)
for plan, success in results.items():
    print(f"Plan {plan}: {'Successful' if success else 'Failed'}")
```

#### Parallel Execution of Multiple Plans
```python
# Execute multiple plans concurrently
results = RasCmdr.compute_parallel(
    plan_number=["01", "02", "03"],
    max_workers=3,
    num_cores=2
)
for plan, success in results.items():
    print(f"Plan {plan}: {'Successful' if success else 'Failed'}")
```

### Working with Multiple Projects

RAS Commander allows working with multiple HEC-RAS projects simultaneously:

```python
# Initialize multiple projects
project1 = RasPrj()
init_ras_project(path1, "6.6", ras_object=project1)
project2 = RasPrj()
init_ras_project(path2, "6.6", ras_object=project2)

# Perform operations on each project
RasCmdr.compute_plan("01", ras_object=project1, dest_folder=folder1)
RasCmdr.compute_plan("01", ras_object=project2, dest_folder=folder2)

# Compare results between projects
print(f"Project 1: {project1.project_name}")
print(f"Project 2: {project2.project_name}")

# Always specify the ras_object parameter when working with multiple projects
# to avoid confusion with the global 'ras' object
```

This is useful for comparing different river systems, running scenario analyses across multiple watersheds, or managing a suite of related models.

#### Core HEC-RAS Automation Classes

- `RasPrj`: Manages HEC-RAS projects, handling initialization and data loading
- `RasCmdr`: Handles execution of HEC-RAS simulations
- `RasPlan`: Provides functions for modifying and updating plan files
- `RasGeo`: Handles operations related to geometry files
- `RasUnsteady`: Manages unsteady flow file operations
- `RasUtils`: Contains utility functions for file operations and data management
- `RasMap`: Parses RASMapper configuration files and automates floodplain mapping
- `RasExamples`: Manages and loads HEC-RAS example projects

#### HDF Data Access Classes
- `HdfBase`: Core functionality for HDF file operations
- `HdfBndry`: Enhanced boundary condition handling
- `HdfMesh`: Comprehensive mesh data management
- `HdfPlan`: Plan data extraction and analysis
- `HdfResultsMesh`: Advanced mesh results processing
- `HdfResultsPlan`: Plan results analysis
- `HdfResultsXsec`: Cross-section results processing
- `HdfStruc`: Structure data management
- `HdfPipe`: Pipe network analysis tools
- `HdfPump`: Pump station analysis capabilities
- `HdfFluvialPluvial`: Fluvial-pluvial boundary analysis
- `HdfPlot` & `HdfResultsPlot`: Specialized plotting utilities

### Project Organization Diagram

```
ras_commander
├── ai_tools
│   ├── [AI Knowledge Bases](https://github.com/gpt-cmdr/ras-commander/tree/main/ai_tools/llm_knowledge_bases) 
│   └── [Library Assistant](https://github.com/gpt-cmdr/ras-commander/tree/main/ai_tools/library_asssistant)
├── examples
│   └── [Examples Notebooks](https://github.com/gpt-cmdr/ras-commander/tree/main/ras_commander)
├── ras_commander
│   ├── __init__.py
│   ├── _version.py
│   ├── Decorators.py
│   ├── LoggingConfig.py
│   ├── RasCmdr.py
│   ├── RasExamples.py
│   ├── RasGeo.py
│   ├── RasPlan.py
│   ├── RasPrj.py
│   ├── RasUnsteady.py
│   ├── RasUtils.py
│   ├── HdfBase.py
│   ├── HdfBndry.py
│   ├── HdfMesh.py
│   ├── HdfPlan.py
│   ├── HdfResultsMesh.py
│   ├── HdfResultsPlan.py
│   ├── HdfResultsXsec.py
│   ├── HdfStruc.py
│   ├── HdfPipe.py
│   ├── HdfPump.py
│   ├── HdfFluvialPluvial.py
│   ├── HdfPlot.py
│   └── HdfResultsPlot.py
├── .gitignore
├── LICENSE
├── README.md
├── STYLE_GUIDE.md
├── Comprehensive_Library_Guide.md
├── pyproject.toml
├── setup.py
```

### Accessing HEC Examples through RasExamples

The `RasExamples` class provides functionality for quickly loading and managing HEC-RAS example projects. This is particularly useful for testing and development purposes.  All examples in the ras-commander repository currently utilize HEC example projects to provide fully running scripts and notebooks for end user testing, demonstration and adaption. 

Key features:
- Download and extract HEC-RAS example projects
- List available project categories and projects
- Extract specific projects for use
- Manage example project data efficiently

Example usage:
from ras_commander import RasExamples

```
categories = ras_examples.list_categories()
projects = ras_examples.list_projects("Steady Flow")
extracted_paths = ras_examples.extract_project(["Bald Eagle Creek", "Muncie"])
```

The RasExamples class is used to provide an alternative to traditional unit testing, with example notebooks doubling as tests and in-context examples for the end user.  This increases interpretability by LLM's, reducing hallucinations.  

### RasPrj

The `RasPrj` class is central to managing HEC-RAS projects within the ras-commander library. It handles project initialization, data loading, and provides access to project components.

Key features:
- Initialize HEC-RAS projects
- Load and manage project data (plans, geometries, flows, etc.)
- Provide easy access to project files and information

Note: While a global `ras` object is available for convenience, you can create multiple `RasPrj` instances to manage several projects simultaneously.

Example usage:
```
from ras_commander import RasPrj, init_ras_project
```

#### Using the global ras object
```
init_ras_project("/path/to/project", "6.5")
```

#### Creating a custom RasPrj instance
```
custom_project = RasPrj()
init_ras_project("/path/to/another_project", "6.5", ras_instance=custom_project)
```

### RasHdf

The `RasHdf` class provides utilities for working with HDF files in HEC-RAS projects, enabling easy access to simulation results and model data.

Example usage:

```python
from ras_commander import RasHdf, init_ras_project, RasPrj

# Initialize project with a custom ras object
custom_ras = RasPrj()
init_ras_project("/path/to/project", "6.5", ras_instance=custom_ras)

# Get runtime data for a specific plan
plan_number = "01"
runtime_data = RasHdf.get_runtime_data(plan_number, ras_object=custom_ras)
print(runtime_data)
```
This class simplifies the process of extracting and analyzing data from HEC-RAS HDF output files, supporting tasks such as post-processing and result visualization.

#### Infrastructure Analysis
```python
from ras_commander import HdfPipe, HdfPump

# Analyze pipe network
pipe_network = HdfPipe.get_pipe_network(hdf_path)
conduits = HdfPipe.get_pipe_conduits(hdf_path)

# Analyze pump stations
pump_stations = HdfPump.get_pump_stations(hdf_path)
pump_performance = HdfPump.get_pump_station_summary(hdf_path)
```

#### Advanced Results Analysis
```python
from ras_commander import HdfResultsMesh

# Get maximum water surface and velocity
max_ws = HdfResultsMesh.get_mesh_max_ws(hdf_path)
max_vel = HdfResultsMesh.get_mesh_max_face_v(hdf_path)

# Visualize results
from ras_commander import HdfResultsPlot
HdfResultsPlot.plot_results_max_wsel(max_ws)
```

#### Fluvial-Pluvial Analysis
```python
from ras_commander import HdfFluvialPluvial

boundary = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(
    hdf_path,
    delta_t=12  # Time threshold in hours
)
```

## Examples

Check out the examples in the repository to learn how to use RAS Commander:

### Project Setup
- `00_Using_RasExamples.ipynb`: Download and extract HEC-RAS example projects
- `01_project_initialization.ipynb`: Initialize HEC-RAS projects and explore their components

### File Operations
- `02_plan_and_geometry_operations.ipynb`: Clone and modify plan and geometry files
- `03_unsteady_flow_operations.ipynb`: Extract and modify boundary conditions
- `09_plan_parameter_operations.ipynb`: Retrieve and update plan parameters

### Execution Modes
- `05_single_plan_execution.ipynb`: Execute a single plan with specific options
- `06_executing_plan_sets.ipynb`: Different ways to specify and execute plan sets
- `07_sequential_plan_execution.ipynb`: Run multiple plans in sequence
- `08_parallel_execution.ipynb`: Run multiple plans in parallel

### Advanced Operations
- `04_multiple_project_operations.ipynb`: Work with multiple HEC-RAS projects simultaneously

These examples demonstrate practical applications of RAS Commander for automating HEC-RAS workflows, from basic operations to advanced scenarios.

## Documentation

For detailed usage instructions and API documentation, please refer to the [Comprehensive Library Guide](Comprehensive_Library_Guide.md).

## Future Development

The ras-commander library is an ongoing project. Future plans include:
- Integration of more advanced AI-driven features
- Expansion of HMS and DSS functionalities
- Community-driven development of new modules and features

## Related Resources

- [HEC-Commander Blog](https://github.com/gpt-cmdr/HEC-Commander/tree/main/Blog)
- [GPT-Commander YouTube Channel](https://www.youtube.com/@GPT_Commander)
- [ChatGPT Examples for Water Resources Engineers](https://github.com/gpt-cmdr/HEC-Commander/tree/main/ChatGPT%20Examples)


## Style Guide

This project follows a specific style guide to maintain consistency across the codebase. Please refer to the [Style Guide](STYLE_GUIDE.md) for details on coding conventions, documentation standards, and best practices.

## Acknowledgments

RAS Commander is based on the HEC-Commander project's "Command Line is All You Need" approach, leveraging the HEC-RAS command-line interface for automation. The initial development of this library was presented in the HEC-Commander Tools repository. In a 2024 Australian Water School webinar, Bill demonstrated the derivation of basic HEC-RAS automation functions from plain language instructions. Leveraging the previously developed code and AI tools, the library was created. The primary tools used for this initial development were Anthropic's Claude, GPT-4, Google's Gemini Experimental models, and the Cursor AI Coding IDE.

Additionally, we would like to acknowledge the following notable contributions and attributions for open source projects which significantly influenced the development of RAS Commander:

1. Contributions: Sean Micek's [`funkshuns`](https://github.com/openSourcerer9000/funkshuns), [`TXTure`](https://github.com/openSourcerer9000/TXTure), and [`RASmatazz`](https://github.com/openSourcerer9000/RASmatazz) libraries provided inspiration, code examples and utility functions which were adapted with AI for use in RAS Commander. Sean has also contributed heavily to 

- Development of additional HDF functions for detailed analysis and mapping of HEC-RAS results within the RasHdf class.
- Development of the prototype `RasCmdr` class for executing HEC-RAS simulations.

2. Attribution: The [`pyHMT2D`](https://github.com/psu-efd/pyHMT2D/) project by Xiaofeng Liu, which provided insights into HDF file handling methods for HEC-RAS outputs.  Many of the functions in the [Ras_2D_Data.py](https://github.com/psu-efd/pyHMT2D/blob/main/pyHMT2D/Hydraulic_Models_Data/RAS_2D/RAS_2D_Data.py) file were adapted with AI for use in RAS Commander. 

   Xiaofeng Liu, Ph.D., P.E.,    Associate Professor, Department of Civil and Environmental Engineering
   Institute of Computational and Data Sciences, Penn State University

3. Attribution: The [ffrd\rashdf'](https://github.com/fema-ffrd/rashdf) project by FEMA-FFRD (FEMA Future of Flood Risk Data) was incorporated, revised, adapted and extended in rascommander's RasHDF libaries (where noted). 

These acknowledgments recognize the contributions and inspirations that have helped shape RAS Commander, ensuring proper attribution for the ideas and code that have influenced its development.

4. Chris Goodell, "Breaking the HEC-RAS Code" - Studied and used as a reference for understanding the inner workings of HEC-RAS, providing valuable insights into the software's functionality and structure.

5. [HEC-Commander Tools](https://github.com/gpt-cmdr/HEC-Commander) - Inspiration and initial code base for the development of RAS Commander.

## Official RAS Commander AI-Generated Songs:

[No More Wait and See (Bluegrass)](https://suno.com/song/16889f3e-50f1-4afe-b779-a41738d7617a)  
  
  
[No More Wait and See (Cajun Zydeco)](https://suno.com/song/4441c45d-f6cd-47b9-8fbc-1f7b277ee8ed)  
  
## Other Resources

Notebook version of RAS-Commander: [RAS-Commander Notebook in the HEC-Commander Tools Repository](https://github.com/gpt-cmdr/HEC-Commander/tree/main/RAS-Commander)  

Youtube Tutorials for HEC-Commander Tools and RAS-Commander: [GPT-Commander on YouTube](https://www.youtube.com/@GPT_Commander/videos)

## Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details on how to submit pull requests, report issues, and suggest improvements.

## LICENSE

This software is released under the MIT license.

## Contact

For questions, suggestions, or support, please contact:  
William Katzenmeyer, P.E., C.F.M. - heccommander@gmail.com
