---
title: "ras-commander: A Python Library for Automating HEC-RAS Hydraulic Modeling Operations"
tags:
  - Python
  - hydraulic modeling
  - HEC-RAS
  - flood simulation
  - water resources engineering
  - hydrology
  - automation
authors:
  - name: William M. Katzenmeyer
    orcid: 0000-0000-0000-0000  # TODO: Replace with actual ORCID
    affiliation: 1
affiliations:
  - name: CLB Engineering Corporation, United States of America
    index: 1
date: 3 March 2026
bibliography: paper.bib
---

# Summary

`ras-commander` is a Python library that provides a comprehensive programmatic
interface for the Hydrologic Engineering Center's River Analysis System
(HEC-RAS), the most widely used river hydraulics software in the United States
[@hecras2024]. The library enables hydraulic engineers and researchers to
automate the full modeling lifecycle: project initialization, plan execution
(single, parallel, and distributed remote), geometry and boundary condition
manipulation, and extraction of simulation results from HDF5 output files. By
operating directly on HEC-RAS project files and HDF5 outputs rather than
requiring the Windows-only Component Object Model (COM) interface, most of the
library's functionality is accessible on any platform where Python runs, while
optional COM support is retained for legacy HEC-RAS versions (3.x--5.x). The
library is distributed on PyPI, documented at ReadTheDocs, and includes 61
example Jupyter notebooks that double as functional tests against real HEC-RAS
projects.

# Statement of Need

Hydraulic modeling with HEC-RAS is central to flood risk assessment, floodplain
mapping, dam breach analysis, and infrastructure design across federal, state,
and local agencies in the United States and internationally
[@hecras_hydraulic_ref]. Despite this ubiquity, programmatic automation of
HEC-RAS has been constrained by the limitations of its official COM-based
HECRASController interface [@goodell2014]: it is restricted to Windows, tightly
coupled to a single HEC-RAS installation, and provides limited access to the
rich simulation outputs stored in HDF5 files.

Several open-source tools have addressed parts of this gap. PyRAS [@pyras] and
raspy [@raspy] wrap the COM interface in Python but inherit its platform and
version constraints. The FEMA Future of Flood Risk Data (FFRD) initiative
produced `rashdf` [@rashdf], a read-only library for HDF5 result extraction.
`pyHMT2D` [@liu2024] supports 2D model automation and cross-model comparison
but focuses on calibration workflows and COM-based execution. Dysarz
[-@dysarz2018] demonstrated Python scripting for HEC-RAS control and
calibration, establishing early patterns for automation.

`ras-commander` addresses the need for a single, integrated library that spans
the complete modeling workflow---from project file manipulation through parallel
execution to results analysis---without requiring COM for modern HEC-RAS
versions. Its target audience includes hydraulic engineers performing batch
scenario analysis, researchers conducting sensitivity studies or model
calibration, and automation developers building operational flood forecasting
pipelines.

# State of the Field

The existing ecosystem of HEC-RAS automation tools can be categorized by their
primary interface mechanism. COM-based tools (PyRAS, raspy, pyHMT2D) delegate
execution to the HECRASController interface, which provides process control but
restricts users to the Windows platform and a locally installed HEC-RAS version.
File-based tools (`rashdf`) parse HDF5 outputs directly but do not provide
execution or project file manipulation capabilities.

`ras-commander` bridges these categories by combining command-line execution of
HEC-RAS (invoking the solver directly as a subprocess) with comprehensive
file-based parsing and modification. This design yields several advantages.
First, the command-line approach supports parallel and distributed execution
across multiple machines without COM registration conflicts. Second, direct
parsing of HEC-RAS text files (geometry `.g##`, plan `.p##`, unsteady flow
`.u##`) and HDF5 outputs enables cross-platform operation for all non-execution
tasks. Third, the library maintains a legacy COM interface (`RasControl` class)
for users who require compatibility with HEC-RAS versions 3.x through 5.x,
providing a migration path from older workflows.

The HDF5 extraction capabilities in `ras-commander` were initially informed by
the `rashdf` library [@rashdf] and the `pyHMT2D` project [@liu2024], then
substantially extended to cover 1D cross-section results, breach progression
data, pipe networks, pump stations, hydraulic property tables, and spatial mesh
queries across 18 specialized classes.

# Software Design

## Architecture

`ras-commander` is organized around a static class pattern where most classes
expose functionality through `@staticmethod` methods, eliminating the need for
instantiation and providing a functional, predictable API. The library comprises
119 Python modules across 11 subpackages (\autoref{fig:architecture}).

![High-level architecture of `ras-commander` showing core subpackages and their
responsibilities.\label{fig:architecture}](architecture.png)

The core execution pipeline uses `RasPrj` for project state management (parsing
`.prj` files into pandas DataFrames), `RasCmdr` for plan execution via
subprocess invocation of `Ras.exe`, and the `hdf` subpackage for results
extraction from HDF5 files using `h5py` [@h5py].

## Key Design Decisions

**DataFrame-first metadata**: All project metadata---plan inventory, geometry
files, flow files, boundary conditions, and execution status---is maintained in
pandas DataFrames [@pandas] that serve as the single source of truth. This
eliminates fragile file path construction and enables expressive queries:

```python
from ras_commander import init_ras_project, ras
init_ras_project("/path/to/project", "6.6")

# Query executed plans via DataFrame
executed = ras.plan_df[ras.plan_df["HDF_Results_Path"].notna()]
```

**Smart execution skip**: A file modification time comparison algorithm
automatically detects when simulation results are current relative to their
input files (plan, geometry, flow), skipping unnecessary re-execution. This
provides significant time savings during iterative development and batch
processing.

**Parallel and distributed execution**: `RasCmdr.compute_parallel()` creates
isolated worker folders and executes multiple plans simultaneously using
Python's `concurrent.futures`. For distributed workloads,
`compute_parallel_remote()` dispatches plans to remote machines via PsExec
(Windows), Docker containers, or SSH, with automatic file staging and result
collection.

**Real-time monitoring**: An extensible callback system
(`ExecutionCallback` base class) enables real-time monitoring of HEC-RAS solver
progress, supporting console output, file logging, and progress bar display.

## Subpackage Overview

| Subpackage | Modules | Purpose |
|:-----------|--------:|:--------|
| `hdf`      | 23      | HDF5 results extraction (WSE, velocity, depth, breach, structures) |
| `usgs`     | 14      | USGS gauge discovery, data retrieval, boundary condition generation |
| `geom`     | 13      | Geometry file parsing and modification (cross sections, structures) |
| `remote`   | 12      | Distributed execution across remote workers |
| `precip`   | 7       | Precipitation data integration (AORC, NOAA Atlas 14) |
| `fixit`    | 6       | Automated geometry repair (blocked obstructions) |
| `check`    | 5       | Model quality assurance validation |
| `dss`      | 3       | HEC-DSS boundary condition reading and validation |
| `terrain`  | 3       | Terrain HDF creation via CLI |
| `results`  | 3       | Results summary aggregation |

# Research Impact Statement

`ras-commander` has been applied in professional hydraulic engineering practice
at CLB Engineering Corporation for flood risk assessment, dam breach analysis,
and floodplain mapping projects. The library's parallel execution capabilities
have enabled batch sensitivity analyses (Manning's roughness, precipitation
depth, breach parameters) that would be impractical through the HEC-RAS
graphical interface alone.

The library's integration with USGS National Water Information System data
(14-module `usgs` subpackage) supports operational forecasting workflows that
combine real-time gauge observations with HEC-RAS simulations. Its precipitation
subpackage automates the retrieval and application of NOAA Atlas 14 design
storms and Analysis of Record for Calibration (AORC) historical precipitation
data, enabling reproducible rain-on-grid modeling workflows.

The approach of combining command-line HEC-RAS execution with HDF5-based results
extraction provides a foundation for high-throughput computational experiments,
including Monte Carlo uncertainty quantification and ensemble flood forecasting,
that are active areas of research in the water resources community.

The library and its predecessor, HEC-Commander Tools [@hec_commander], were
presented at the Association of State Floodplain Managers (ASFPM) Annual
Conference [@katzenmeyer2024], introducing the concepts of LLM-assisted
hydraulic engineering automation to the professional community.

# AI Usage Disclosure

`ras-commander` was developed using an "LLM Forward" methodology, where large
language models (primarily Anthropic Claude and OpenAI models) were used
extensively as coding assistants throughout the development process. AI tools
were used for code generation, documentation writing, test development, and
refactoring. All AI-generated code was reviewed, tested against real HEC-RAS
projects, and validated by the author, a licensed Professional Engineer. The
library's test-driven development approach---using real HEC-RAS example projects
rather than mocks---ensures that all functionality is validated against actual
simulation software behavior regardless of how the code was initially generated.
This paper was drafted with AI assistance and reviewed and edited by the author.

# Acknowledgements

The HDF5 extraction capabilities were initially informed by the `rashdf` library
developed by the FEMA Future of Flood Risk Data (FFRD) initiative [@rashdf] and
the `pyHMT2D` project by Xiaofeng Liu [@liu2024]. The library depends on the
scientific Python ecosystem, including NumPy [@numpy], pandas [@pandas],
GeoPandas [@geopandas], and h5py [@h5py]. The author thanks the HEC-RAS
development team at the U.S. Army Corps of Engineers Hydrologic Engineering
Center for maintaining HEC-RAS as publicly available software and for providing
the example projects used in testing.

# References
