# RAS Commander

<p align="center">
  <img src="assets/ras-commander_logo.svg" alt="RAS Commander Logo" width="70%">
</p>

**RAS Commander** is a Python library for automating HEC-RAS (Hydrologic Engineering Center's River Analysis System) operations. It provides a comprehensive API for interacting with HEC-RAS project files, executing simulations, and processing results through HDF data analysis.

## Key Features

<div class="grid cards" markdown>

- :material-play-circle: **Plan Execution**

    Execute single plans, run multiple plans in parallel, or queue sequential computations with full control over cores and resources.

- :material-file-document: **HDF Data Access**

    Extract and analyze 1D/2D results directly from HDF files - water surfaces, velocities, depths, and more.

- :material-vector-polygon: **Geometry Operations**

    Parse and modify geometry files including cross-sections, storage areas, connections, and inline structures.

- :material-network: **Infrastructure Analysis**

    Work with pipe networks, pump stations, dam breaches, and hydraulic structures.

- :material-clock-fast: **Legacy Support**

    COM interface support for HEC-RAS 3.x-6.x via the RasControl class.

- :material-cloud-sync: **Remote Execution**

    Distribute computations across multiple machines using PsExec, Docker, or SSH workers.

</div>

## Quick Install

```bash
pip install --upgrade ras-commander
```

## Quick Start

```python
from ras_commander import init_ras_project, RasCmdr, ras

# Initialize a project
init_ras_project("/path/to/project", "6.5")

# View available plans
print(ras.plan_df)

# Execute a plan
success = RasCmdr.compute_plan("01")
```

## Why RAS Commander?

- **Pythonic API**: Modern Python interface using pandas DataFrames, pathlib, and type hints
- **No COM Required**: Direct file and HDF access without Windows COM dependencies (for most operations)
- **AI-Friendly**: Extensive documentation and examples optimized for LLM-assisted development
- **Test-Driven**: All features demonstrated with real HEC-RAS example projects
- **Open Source**: MIT licensed, community contributions welcome

## Getting Help

- **[GitHub Issues](https://github.com/gpt-cmdr/ras-commander/issues)**: Report bugs and request features
- **[Example Notebooks](examples/index.md)**: 30+ working examples covering all major features
- **[API Reference](api/index.md)**: Complete function and class documentation
- **[ChatGPT Assistant](https://chatgpt.com/g/g-TZRPR3oAO-ras-commander-library-assistant)**: Interactive help with your RAS Commander questions

## Acknowledgments

RAS Commander builds on work from:

- [HEC-Commander Tools](https://github.com/gpt-cmdr/HEC-Commander)
- Sean Micek's [funkshuns](https://github.com/openSourcerer9000/funkshuns), [TXTure](https://github.com/openSourcerer9000/TXTure), and [RASmatazz](https://github.com/openSourcerer9000/RASmatazz)
- Xiaofeng Liu's [pyHMT2D](https://github.com/psu-efd/pyHMT2D/)
- FEMA-FFRD's [rashdf](https://github.com/fema-ffrd/rashdf)
- Michael Koohafkan's [dssrip2](https://github.com/mkoohafkan/dssrip2)
- Chris Goodell's "Breaking the HEC-RAS Code"
