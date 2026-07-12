---
title: 'ras-commander: A Python interface for reproducible HEC-RAS automation and analysis'
tags:
  - Python
  - HEC-RAS
  - hydraulic modeling
  - flood risk
  - reproducible workflows
authors:
  - name: William M. Katzenmeyer
    orcid: 0009-0003-2907-1906
    corresponding: true
    affiliation: 1
affiliations:
  - name: CLB Engineering Corporation, United States
    index: 1
date: 12 July 2026
bibliography: paper.bib
---

# Summary

The Hydrologic Engineering Center's River Analysis System (HEC-RAS) is used to
simulate river, floodplain, and hydraulic-structure behavior in one and
two dimensions [@hecras66]. Its desktop interface is effective for interactive
model development, but repeated simulations, systematic parameter studies, and
large results-extraction tasks require substantial manual coordination.
`ras-commander` is an open-source Python library that makes these operations
scriptable while preserving the ordinary HEC-RAS project as the engineering
record. It inventories a project into tabular metadata, edits native model
files, invokes supported HEC-RAS compute pathways, and returns hydraulic and
spatial results in analysis-ready Python objects.

The package is intended for engineers and researchers who need auditable,
repeatable workflows around HEC-RAS rather than a replacement hydraulic solver.
Its use cases include sensitivity and uncertainty analysis, calibration,
historical-event reconstruction, boundary-condition preparation, model quality
checks, and comparison of alternative geometries or mitigation concepts. Model
selection, parameter suitability, and interpretation remain the responsibility
of a qualified practitioner.

# Statement of need

HEC-RAS projects combine linked text files, HDF5 geometry and results files,
spatial configuration, terrain, and sometimes HEC-DSS time series. Automation
therefore requires more than starting an executable: a workflow must resolve
the active plan and its dependencies, keep project references consistent,
detect version-specific data layouts, and expose results without silently
changing their hydraulic meaning. Earlier HEC-RAS automation commonly used the
Windows COM controller [@goodell2014; @dysarz2018]. That interface remains
useful for legacy models, but modern one- and two-dimensional projects also
require direct handling of HDF5 and RASMapper-era data.

`ras-commander` addresses this integration problem with one maintained API for
project discovery, model-file operations, execution, preprocessing, and result
analysis. Project initialization populates pandas DataFrames [@mckinney2010]
for plans, geometry, boundaries, and map resources. These tables provide stable
identifiers and resolved paths that downstream functions reuse, reducing the
need for notebook-specific filename construction. The same project can then be
inspected, modified, computed, and queried in a single Python process, with
structured return values and logging suited to both interactive examples and
diagnostic use.

# State of the field

The HEC-RAS Python ecosystem contains valuable tools with narrower scopes.
`rashdf` exposes HEC-RAS geometry and plan HDF data through h5py-derived objects
and GeoDataFrames [@rashdf]. `pyHMT2D` provides Python tools for several
two-dimensional hydraulic models, including HEC-RAS, with capabilities for
model control and data conversion [@pyhmt2d]. COM-oriented scripts and packages
focus primarily on controlling installed HEC-RAS applications. These approaches
are complementary: `ras-commander` incorporates and acknowledges ideas from
the open HDF and hydraulic-modeling ecosystem while concentrating on major
lifecycle stages of an existing HEC-RAS project. Its distinguishing design choice is
the combination of project-wide metadata, native text and spatial editing,
local or distributed execution, modern HDF result access, and legacy COM access
behind a consistent static-method-oriented API.

# Software design

The architecture separates orchestration from the HEC-RAS solver and its files
(Figure \ref{fig:architecture}). `RasPrj` and `init_ras_project()` establish
project state. Authoring modules modify plans, steady and unsteady boundary
conditions, geometry, land cover, terrain, and RASMapper configuration.
Execution modules call HEC-RAS compute and preprocessing interfaces, capture
messages, and support local parallel work as well as implemented PsExec and
container worker paths. Data-access modules read HDF5, DSS, precipitation,
terrain, and USGS sources and return pandas, GeoPandas, or xarray structures
[@geopandas].

![Major `ras-commander` layers and data flow. HEC-RAS remains the hydraulic solver and native project files remain reviewable in its desktop tools.\label{fig:architecture}](architecture.png)

The package's modern HDF interfaces target HEC-RAS 6.2 and later file layouts.
Older projects may omit HDF files entirely; for those models, `RasControl`
provides execution and result access through the legacy HECRASController COM
interface. Some operations require Windows, an installed HEC-RAS version, Java
for DSS access, or optional geospatial and remote-execution dependencies. The
public SSH, WinRM, Slurm, AWS, and Azure worker classes are extension stubs, not
operational execution targets. The library reports unavailable model data as an
error when the requested result is
essential and uses explicit warnings where preprocessing can create the missing
dataset. It does not infer that a numerically complete simulation is
hydraulically appropriate.

The repository currently includes 127 indexed example notebooks covering
initialization, geometry and boundary editing, one- and two-dimensional result
extraction, mapping, calibration, uncertainty, remote execution, precipitation,
USGS observations, and terrain modification. The examples use published or
official HEC-RAS projects where practical; most retain executed outputs so readers
can inspect the actual workflow. Automated tests cover parsing and transformation
logic, while integration examples exercise capabilities that depend on review by
a professional engineer or external data services.

# Research impact statement

`ras-commander` supports research in which many internally consistent HEC-RAS
runs must be generated and compared. The developer has used it to construct
documented workflows for Manning's roughness calibration, Monte Carlo
uncertainty analysis, mesh-resolution sensitivity, historical precipitation
event validation against USGS observations, and spatial evaluation of benefits
and adverse-impact areas. In these workflows the package automates data movement
and repeated calculations; it does not determine whether a parameter range,
boundary condition, or alternative is professionally acceptable.

The public examples make those methods inspectable and reusable without
presenting their case-specific outputs as general research findings. This is
especially useful for studies that need provenance across model inputs,
simulation versions, and extracted results. The project has been developed in
public since 2024 and was introduced to floodplain-management practitioners in
an ASFPM conference presentation on AI-assisted HEC-RAS and HEC-HMS automation
[@katzenmeyer2024]. The software and its documentation are available from the
project repository [@rascommander].

# AI usage disclosure

Large language model coding agents, principally Anthropic Claude through Claude
Code and OpenAI models through ChatGPT and Codex, were used during software
development for code drafting, refactoring, documentation, test generation, and
independent review. Model versions changed during the 2024--2026 development
period and were not recorded for every historical contribution; the repository
therefore does not support a more exact per-commit model inventory. Agent
instructions require use of the same public APIs, DataFrame contracts, logging
policy, and model-validation practices as human contributors. AI-produced
changes were reviewed and modified by the author, checked with targeted tests,
and, when HEC-RAS behavior was involved, exercised against real model projects
and reviewable outputs. The author made the primary architecture and design
decisions; the agents did not replace hydraulic interpretation or professional
responsibility. OpenAI Codex assisted with drafting and independent factual
review of this manuscript using the `gpt-5.6-terra` model configuration; the
author fact-checked, edited, and approved the resulting text.

# Acknowledgements

The author acknowledges CLB Engineering Corporation for supporting development.
The HDF functionality includes code derived or adapted from `rashdf` and
`pyHMT2D` where identified in source files and project documentation. Additional
source-level derivations and software influences are recorded in the repository
acknowledgements. The author also thanks the U.S. Army Corps of Engineers
Hydrologic Engineering Center for making HEC-RAS, its documentation, and example
projects publicly available. No external research grant funded this work.

# References
