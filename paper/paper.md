---
title: "ras-commander: A Python Library for LLM-Accelerated HEC-RAS Hydraulic Modeling Automation"
tags:
  - Python
  - hydraulic modeling
  - HEC-RAS
  - flood simulation
  - water resources engineering
  - hydrology
  - automation
  - LLM-assisted engineering
authors:
  - name: William M. Katzenmeyer
    orcid: 0009-0003-2907-1906
    affiliation: 1
affiliations:
  - name: CLB Engineering Corporation, United States of America
    index: 1
date: 3 March 2026
bibliography: paper.bib
---

# Summary

`ras-commander` is a Python library for automating HEC-RAS (Hydrologic Engineering Center's River Analysis System) hydraulic modeling workflows, engineered from the ground up as a first-class substrate for AI agent collaboration [@hecras2024]. The library enables hydraulic engineers and researchers to automate the full modeling lifecycle: project initialization, plan execution (single, parallel, and distributed remote), geometry and boundary condition manipulation, and extraction of simulation results from HDF5 output files.

Critically, `ras-commander` is not merely a programmatic interface---it embodies an "LLM Forward" engineering methodology [@katzenmeyer2024] wherein domain experts collaborate with large language models to accelerate engineering innovation. The repository's cognitive infrastructure---hierarchical knowledge rules, specialist AI agents, and workflow skills---constitutes a systematic framework for reproducible, expert-guided AI assistance in professional hydraulic engineering practice.

By operating directly on HEC-RAS project files and HDF5 outputs rather than requiring the Windows-only Component Object Model (COM) interface, most functionality is accessible on any platform where Python runs, while optional COM support is retained for legacy HEC-RAS versions (3.x--5.x). The library is distributed on PyPI, documented at ReadTheDocs, and includes 67 example Jupyter notebooks organized in a numbered series (100s--950s) that serve as both user documentation and whole-project functional tests against real HEC-RAS projects.

# Statement of Need

Hydraulic modeling with HEC-RAS is central to flood risk assessment, floodplain mapping, dam breach analysis, and infrastructure design across federal, state, and local agencies in the United States and internationally [@hecras_hydraulic_ref]. Despite this ubiquity, programmatic automation has been constrained by the limitations of the official COM-based HECRASController interface [@goodell2014]: it is restricted to Windows, tightly coupled to a single HEC-RAS installation, and provides limited access to simulation outputs stored in HDF5 files.

Several open-source tools have addressed parts of this gap. PyRAS [@pyras] and raspy [@raspy] wrap the COM interface in Python but inherit its platform and version constraints. The FEMA FFRD initiative produced `rashdf` [@rashdf], a read-only HDF5 extraction library. `pyHMT2D` [@liu2024] supports 2D model automation but focuses on calibration and COM-based execution. Dysarz [-@dysarz2018] demonstrated Python scripting for HEC-RAS automation, establishing early patterns.

`ras-commander` addresses the need for a single, integrated library spanning the complete modeling workflow without requiring COM for modern HEC-RAS versions. Beyond workflow automation, it addresses a gap that no existing tool fills: a hydraulic modeling library designed specifically for AI-agent collaboration, with embedded domain knowledge that enables LLMs to assist licensed Professional Engineers without compromising professional standards.

# LLM Forward Methodology

`ras-commander` was developed under the **LLM Forward** methodology---a framework for domain experts leveraging AI to accelerate engineering innovation while maintaining professional responsibility [@katzenmeyer2024]. The six core tenets are:

1. **Professional Responsibility First**: Public safety, ethics, and licensure remain paramount
2. **LLMs Forward, Not First**: Technology accelerates engineering insight without replacing professional judgment
3. **Multi-Level Verifiability**: HEC-RAS GUI review + visual outputs + code audit trails
4. **Human-in-the-Loop**: Multiple review pathways for traditional engineering validation
5. **Domain Expertise Accelerated**: H\&H knowledge translated efficiently into working code
6. **Focus on LLMs Specifically**: LLMs excel at code generation and documentation---not general AI/ML

This methodology is formalized at [engineeringwithllms.info](https://engineeringwithllms.info) [@llmforward2024] and was introduced to the professional hydraulic engineering community at the 2024 ASFPM Annual Conference [@katzenmeyer2024].

# Software Design

## Architecture

`ras-commander` is organized around a static class pattern where most classes expose functionality through `@staticmethod` methods, eliminating instantiation requirements and providing a functional, predictable API. The library comprises 119 Python modules across 11 subpackages (\autoref{fig:architecture}).

![High-level architecture of `ras-commander` showing core subpackages and their responsibilities.\label{fig:architecture}](architecture.png)

The core execution pipeline uses `RasPrj` for project state management (parsing `.prj` files into pandas DataFrames [@pandas]), `RasCmdr` for plan execution via subprocess invocation of `Ras.exe`, and the `hdf` subpackage for results extraction from HDF5 files using h5py [@h5py].

## Key Design Decisions

**DataFrame-first metadata**: All project metadata---plan inventory, geometry files, flow files, boundary conditions, and execution status---is maintained in pandas DataFrames that serve as the single source of truth, eliminating fragile file path construction:

```python
from ras_commander import init_ras_project, ras
init_ras_project("/path/to/project", "6.6")
executed = ras.plan_df[ras.plan_df["HDF_Results_Path"].notna()]
```

**Smart execution skip**: A file modification time comparison algorithm automatically detects when simulation results are current relative to their input files (plan, geometry, flow), skipping unnecessary re-execution. In a batch of 10 plans where only 2 have been modified, this delivers approximately 80% time savings without any user configuration.

**HTAB batch optimization**: Hydraulic property table (HTAB) modification uses a single read/write cycle across all cross sections, achieving a measured 125× speed improvement: 0.04 seconds versus 31.5 seconds for 63 cross sections in an iterative approach. Dual-format compatibility handles both modern (separate lines) and legacy (combined line) HTAB formats.

**Parallel and distributed execution**: `RasCmdr.compute_parallel()` creates isolated worker folders and executes multiple plans simultaneously. For distributed workloads, `compute_parallel_remote()` dispatches plans across eight worker types (three implemented: `PsexecWorker`, `LocalWorker`, `DockerWorker`; five stubs: `SshWorker`, `WinrmWorker`, `SlurmWorker`, `AwsEc2Worker`, `AzureFrWorker`). A critical undocumented HEC-RAS requirement: remote workers must use `session_id=2` (the interactive desktop session); `system_account=True` causes silent execution failure because HEC-RAS is a GUI application.

## Cognitive Infrastructure

The repository implements a four-level hierarchical knowledge architecture designed for AI-agent discoverability:

- **Root `CLAUDE.md`**: Strategic overview and LLM Forward tenets
- **Subpackage `CLAUDE.md`/`AGENTS.md`**: Tactical workflows and API details
- **`.claude/rules/`**: 36 auto-loaded topic-specific rule files (Python patterns, HEC-RAS domain, testing, documentation)
- **`.claude/agents/` and `.claude/skills/`**: 30+ specialist agents and 17 workflow skills

A Phase 4 refactoring replaced duplicated documentation with lightweight navigators pointing to authoritative sources, achieving 83.6% content reduction (30,201 lines → 4,937 lines) with 100% duplication eliminated and 60 redundant files deleted. This enables LLMs to load the right context precisely without bloating every interaction with repeated content.

The `qa_review_triple-model` skill exemplifies multi-model orchestration: it launches four independent AI reviewers (Claude Opus, Google Gemini, OpenAI Codex, Kimi K2.5) in parallel, each writing findings to separate markdown files, with the orchestrator synthesizing a consensus quality assessment. This represents a novel QA methodology for computational engineering code review.

## Subpackage Overview

| Subpackage | Modules | Purpose |
|:-----------|--------:|:--------|
| `hdf`      | 23      | HDF5 results extraction (WSE, velocity, depth, breach, structures) |
| `usgs`     | 14      | USGS gauge discovery, data retrieval, boundary condition generation |
| `geom`     | 13      | Geometry file parsing and modification (cross sections, HTAB) |
| `remote`   | 12      | Distributed execution across 8 worker types |
| `precip`   | 7       | Precipitation data integration (AORC [@aorc2021], NOAA Atlas 14) |
| `fixit`    | 6       | Automated geometry repair (blocked obstructions) |
| `check`    | 5       | Model quality assurance validation |
| `dss`      | 3       | HEC-DSS boundary condition reading and validation |
| `terrain`  | 3       | Terrain HDF creation via `RasProcess.exe` CLI |
| `results`  | 3       | Results summary aggregation |

## eBFE/BLE Model Organization

FEMA's estimated Base Flood Elevation (eBFE) Base Level Engineering (BLE) models are delivered in a fundamentally broken state: HDF output files (40+ GB) stored outside the project directory, terrain with incorrect `.rasmap` references, and absolute DSS paths from the original system. `RasEbfeModels` applies three automated fixes: (1) moves Output HDF files into project folders, (2) moves Terrain into project folders so `.rasmap` references resolve, and (3) converts all paths to relative references.

The Upper Guadalupe BLE model (55 GB, 4 cascaded sub-models) required moving 56 HDF result files and validating 10,248 DSS pathnames. Manual processing typically requires 60--120 minutes; `RasEbfeModels.organize_upper_guadalupe()` completes the same task in 15--20 minutes, yielding a model that opens cleanly in the HEC-RAS GUI with no error dialogs [@fema_ble2023].

## RasCheck Model Validation

The `check` subpackage implements eight validation categories against configurable FEMA and USACE regulatory thresholds:

1. Manning's roughness coefficient range checks
2. Cross-section spacing adequacy
3. Structure geometry compatibility
4. Floodway surcharge limits (FEMA: 1.0 ft; USACE: 0.5 ft)
5. Hydraulic profile consistency
6. Unsteady mass balance error bounds
7. Unsteady simulation stability metrics
8. 2D mesh cell quality

`ValidationThresholds` accepts custom thresholds, and results are exported as structured CSV/HTML reports with `ERROR`/`WARNING`/`INFO`/`PASS` severity classifications for direct use in project documentation.

# Research Impact Statement

`ras-commander` has been applied in professional hydraulic engineering practice at CLB Engineering Corporation for flood risk assessment, dam breach analysis, and floodplain mapping projects. The library's parallel execution capabilities enable batch sensitivity analyses that would be impractical through the HEC-RAS GUI alone.

The USGS subpackage (14 modules) supports operational forecasting workflows combining real-time gauge observations with HEC-RAS simulations, including threshold detection and flash flood alerting via `RasUsgsRealTime`. The precipitation subpackage automates retrieval and application of NOAA AORC historical precipitation [@aorc2021] and Atlas 14 design storms, enabling reproducible rain-on-grid modeling. These components combine in an end-to-end operational pipeline: USGS real-time monitoring → HRRR weather forecast download (3 km resolution, NOAA NOMADS) → AORC historical calibration → coupled HMS-RAS execution, demonstrated in notebooks 918--919.

Cloud-native export capabilities (`hecras_export_cloud-native` skill) produce GeoParquet, PMTiles, DuckDB, and PostGIS outputs for modern GIS interoperability, extending results accessibility beyond traditional desktop GIS workflows.

# AI Usage Disclosure and Whole-Project Testing

## Development Methodology

`ras-commander` was developed using the LLM Forward methodology described above, with Claude (Anthropic) and other LLMs serving as collaborative coding assistants for code generation, documentation, refactoring, and test development. All AI-generated code was reviewed, tested against real HEC-RAS projects, and validated by the author, a licensed Professional Engineer.

## Whole-Project Test-Driven Development

The library deliberately rejects mocked unit tests in favor of **whole-project functional tests** using real HEC-RAS example projects. The `RasExamples` class extracts authentic USACE Hydrologic Engineering Center example projects---no synthetic data---providing genuine validation of file parsing, execution, and results extraction across multiple HEC-RAS versions and model types.

The 67 example notebooks (100-series: setup; 200-series: geometry; 300-series: boundary conditions; 400-series: HDF extraction; 500-series: remote execution; 600-series: floodplain mapping; 700-series: sensitivity analysis; 800-series: QA/validation; 900-series: AORC/USGS/terrain/operational) serve a dual purpose: user documentation demonstrating realistic workflows, and functional regression tests validating the complete library stack against real simulation software behavior. This approach ensures that AI-assisted code generation remains grounded in verifiable physical outcomes.

## Primitive Extraction Workflow

New library functionality follows a systematic five-phase cycle: (1) identify reusable patterns in production engineering scripts; (2) extract atomic primitives with full type hints, docstrings, and error handling; (3) create numbered example notebooks with two contrasting real-world examples each; (4) integrate into subpackage documentation; and (5) validate against real projects before publication. This workflow ensures that every library function emerges from genuine engineering need rather than speculative design.

This paper was drafted with AI assistance and reviewed and edited by the author.

# Acknowledgements

The HDF5 extraction capabilities were initially informed by the `rashdf` library [@rashdf] and the `pyHMT2D` project [@liu2024]. The library depends on the scientific Python ecosystem, including NumPy [@numpy], pandas [@pandas], GeoPandas [@geopandas], and h5py [@h5py]. The author thanks the HEC-RAS development team at the U.S. Army Corps of Engineers Hydrologic Engineering Center for maintaining HEC-RAS as publicly available software and for providing the example projects used in testing.

# References
