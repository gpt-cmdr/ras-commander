# Example Notebook Numbering Scheme

**Last Updated**: 2025-12-18
**Status**: PROPOSED REORGANIZATION for 1.0 Release

This document defines a category-based numbering system that reflects the library's functional domains.

---

## Category Overview

| Range | Category | Library Modules |
|-------|----------|-----------------|
| **100-199** | Basic Automation & Project Data | RasPrj, RasPlan, RasCmdr, RasExamples, RasControl |
| **200-299** | Geometry Parsing & Operations | RasGeometry, RasGeo, RasFixit, RasStruct |
| **300-399** | Boundary Condition Parsing & Operations | RasUnsteady, RasSteady, RasDss |
| **400-499** | HDF Data Operations | HdfBase, HdfMesh, HdfXsec, HdfResults*, HdfBreach |
| **500-599** | Remote Plan Execution | RasCmdr.compute_parallel_remote, Workers |
| **600-699** | Advanced Data Analysis | RasMap, Floodplain Mapping, Delineation |
| **700-799** | Sensitivity & Benchmarking | Performance testing, Atlas 14 workflows |
| **800-899** | Quality Assurance | RasCheck module |
| **900-999** | External Data Integrations | AORC, USGS, future data sources |

---

## 100-199: Basic Automation & Project Data

Core library functionality: project initialization, plan operations, execution modes.

### 100-109: Getting Started
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 100 | using_ras_examples | 00 | Download/extract official example projects |
| 101 | project_initialization | 01 | Initialize projects, explore components |
| 102 | multiple_project_operations | 04 | Work with multiple projects simultaneously |
| 103 | plan_and_geometry_operations | 02 | Clone/modify plan and geometry files |
| 104 | plan_parameter_operations | 09 | Retrieve/update plan parameters |
| 105-109 | *Reserved* | - | Future basics |

### 110-119: Plan Execution Modes
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 110 | single_plan_execution | 05 | Execute single plan with options |
| 111 | executing_plan_sets | 06 | Specify and execute sets of plans |
| 112 | sequential_plan_execution | 07 | Run plans in sequence (test mode) |
| 113 | parallel_execution | 08 | Run plans in parallel across workers |
| 114-119 | *Reserved* | - | Future execution modes |

### 120-129: Legacy COM Interfaces
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 120 | automating_ras_with_win32com | 16 | Direct Win32COM automation |
| 121 | legacy_hecrascontroller_and_rascontrol | 17 | RasControl for HEC-RAS 3.x-5.x |
| 122-129 | *Reserved* | - | Future COM workflows |

### 130-199: Reserved
- **130-139**: Future project management features
- **140-149**: Future plan manipulation features
- **150-199**: Reserved for expansion

---

## 200-299: Geometry Parsing & Operations

Work with geometry files: parsing, modification, repair.

### 200-209: Geometry Parsing
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 200 | plaintext_geometry_operations | 20 | Parse/modify geometry files directly |
| 201 | *1D geometry parsing* | NEW | Cross sections, bank stations |
| 202 | *2D geometry parsing* | NEW | Mesh areas, breaklines |
| 203-209 | *Reserved* | - | Future parsing notebooks |

### 210-219: Geometry Repair (RasFixit)
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 210 | fixit_blocked_obstructions | 200 | Detect/fix overlapping blocked obstructions |
| 211 | *fixit_cross_section_stations* | NEW | Fix station ordering issues |
| 212 | *fixit_bank_stations* | NEW | Fix bank station problems |
| 213-219 | *Reserved* | - | Future fixit operations |

### 220-299: Reserved
- **220-229**: Structure geometry (bridges, culverts)
- **230-239**: 2D mesh operations
- **240-299**: Reserved for expansion

---

## 300-399: Boundary Condition Parsing & Operations

Work with unsteady/steady flow files, DSS data, boundary conditions.

### 300-309: Unsteady Flow Operations
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 300 | unsteady_flow_operations | 03 | Extract/modify BC tables in .uXX files |
| 301 | *unsteady_restart_settings* | NEW | Configure warm start/restart |
| 302-309 | *Reserved* | - | Future unsteady operations |

### 310-319: DSS Operations
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 310 | dss_boundary_extraction | 22 | Read HEC-DSS boundary condition time series |
| 311 | validating_dss_paths | 33 | Validate DSS pathnames and availability |
| 312 | *dss_writing* | NEW | Write time series to DSS |
| 313-319 | *Reserved* | - | Future DSS operations |

### 320-329: Boundary Visualization
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 320 | 1d_boundary_condition_visualization | 24_1d | Visualize 1D BCs in RASMapper |
| 321 | *2d_boundary_condition_visualization* | NEW | Visualize 2D BCs |
| 322-329 | *Reserved* | - | Future BC visualization |

### 330-399: Reserved
- **330-339**: Steady flow operations
- **340-399**: Reserved for expansion

---

## 400-499: HDF Data Operations

Extract and analyze results from HEC-RAS HDF output files.

### 400-409: 1D HDF Extraction
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 400 | 1d_hdf_data_extraction | 10 | 1D cross-section time series and maxima |
| 401 | steady_flow_analysis | 19 | Extract steady state results |
| 402-409 | *Reserved* | - | Future 1D HDF operations |

### 410-419: 2D HDF Extraction
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 410 | 2d_hdf_data_extraction | 11 | 2D mesh cells, faces, time series |
| 411 | 2d_hdf_pipes_and_pumps | 12 | Pipe networks and pump stations |
| 412 | 2d_detail_face_data_extraction | 13 | Detailed face data for flow analysis |
| 413-419 | *Reserved* | - | Future 2D HDF operations |

### 420-429: Specialized HDF Extraction
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 420 | breach_results_extraction | 18 | Dam breach time series and statistics |
| 421 | *hydraulic_tables_extraction* | NEW | Cross section property tables |
| 422-429 | *Reserved* | - | Future specialized extraction |

### 430-499: Reserved
- **430-439**: HDF writing operations
- **440-499**: Reserved for expansion

---

## 500-599: Remote Plan Execution

Distributed execution across remote machines.

### 500-509: Worker Types
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 500 | remote_execution_psexec | 23 | Windows remote execution via PsExec |
| 501 | *remote_execution_docker* | NEW | Container-based execution |
| 502 | *remote_execution_ssh* | NEW | SSH-based remote execution |
| 503 | *remote_execution_cloud* | NEW | AWS/Azure cloud execution |
| 504-509 | *Reserved* | - | Future worker types |

### 510-599: Reserved
- **510-519**: Worker configuration and monitoring
- **520-599**: Reserved for expansion

---

## 600-699: Advanced Data Analysis

Mapping, visualization, and advanced spatial analysis.

### 600-609: Floodplain Mapping
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 600 | floodplain_mapping_gui | 15a | RASMapper GUI automation (legacy) |
| 601 | floodplain_mapping_rasprocess | 15b | RasProcess CLI (recommended) |
| 602 | floodplain_mapping_python_gis | 15c | Pure Python mesh rasterization |
| 603 | *floodplain_mapping_comparison* | NEW | Compare mapping methods |
| 604-609 | *Reserved* | - | Future mapping workflows |

### 610-619: Spatial Analysis
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 610 | fluvial_pluvial_delineation | 14 | Classify flooding mechanism |
| 611 | validating_map_layers | 34 | Validate RASMapper layers |
| 612 | *inundation_depth_analysis* | NEW | Depth grid analysis |
| 613-619 | *Reserved* | - | Future spatial analysis |

### 620-699: Reserved
- **620-629**: Time series visualization
- **630-699**: Reserved for expansion

---

## 700-799: Sensitivity & Benchmarking

Performance testing, version comparison, parameter sensitivity.

### 700-709: Performance Testing
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 700 | core_sensitivity | 101 | Runtime vs core count experiments |
| 701 | benchmarking_versions_6.1_to_6.6 | 102 | Cross-version performance comparison |
| 702-709 | *Reserved* | - | Future performance notebooks |

### 710-719: Parameter Sensitivity
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 710 | mannings_sensitivity_bulk_analysis | 105 | Bulk Manning's n sensitivity |
| 711 | mannings_sensitivity_multi_interval | 106 | Multi-interval sensitivity testing |
| 712 | *infiltration_sensitivity* | NEW | Green-Ampt parameter sensitivity |
| 713-719 | *Reserved* | - | Future sensitivity analysis |

### 720-729: Atlas 14 Workflows
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 720 | atlas14_aep_events | 103 | Generate AEP storms from Atlas 14 |
| 721 | atlas14_caching_demo | 103b | Atlas 14 data caching |
| 722 | atlas14_multi_project | 104 | Run Atlas 14 across multiple projects |
| 723-729 | *Reserved* | - | Future Atlas 14 workflows |

### 730-799: Reserved
- **730-739**: Future storm analysis
- **740-799**: Reserved for expansion

---

## 800-899: Quality Assurance

Model validation, QA checks, certification workflows.

### 800-809: RasCheck Core
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 800 | quality_assurance_rascheck | 300 | Core RasCheck validation suite |
| 801 | advanced_structure_validation | 301 | Structure-specific validation |
| 802 | custom_workflows_and_standards | 302 | Custom QA workflows |
| 803-809 | *Reserved* | - | Future RasCheck notebooks |

### 810-899: Reserved
- **810-819**: Model comparison checks
- **820-829**: Calibration validation
- **830-899**: Reserved for expansion

---

## 900-999: External Data Integrations

Integration with external data sources: precipitation, gauges, etc.

### 900-909: AORC Precipitation
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 900 | aorc_precipitation | 24_aorc | Retrieve AORC gridded precipitation |
| 901 | aorc_precipitation_catalog | 400 | Comprehensive AORC catalog ops |
| 902 | *aorc_storm_selection* | NEW | Storm event selection |
| 903-909 | *Reserved* | - | Future AORC workflows |

### 910-919: USGS Gauge Integration
| Number | Notebook | Old # | Description |
|--------|----------|-------|-------------|
| 910 | usgs_gauge_catalog | 420 | Generate gauge catalogs |
| 911 | usgs_gauge_data_integration | 421 | Integrate gauge data with models |
| 912 | usgs_real_time_monitoring | 422 | Real-time gauge monitoring |
| 913 | bc_generation_from_live_gauge | 423 | Generate BCs from live data |
| 914 | model_validation_with_usgs | 424 | Validate results against gauges |
| 915-919 | *Reserved* | - | Future USGS workflows |

### 920-999: Reserved
- **920-929**: NOAA forecast integration
- **930-939**: NWS data sources
- **940-999**: Reserved for future data sources

---

## Migration Mapping

### Complete Old → New Mapping

| Old # | New # | Notebook Name |
|-------|-------|---------------|
| 00 | 100 | using_ras_examples |
| 01 | 101 | project_initialization |
| 02 | 103 | plan_and_geometry_operations |
| 03 | 300 | unsteady_flow_operations |
| 04 | 102 | multiple_project_operations |
| 05 | 110 | single_plan_execution |
| 06 | 111 | executing_plan_sets |
| 07 | 112 | sequential_plan_execution |
| 08 | 113 | parallel_execution |
| 09 | 104 | plan_parameter_operations |
| 10 | 400 | 1d_hdf_data_extraction |
| 11 | 410 | 2d_hdf_data_extraction |
| 12 | 411 | 2d_hdf_pipes_and_pumps |
| 13 | 412 | 2d_detail_face_data_extraction |
| 14 | 610 | fluvial_pluvial_delineation |
| 15a | 600 | floodplain_mapping_gui |
| 15b | 601 | floodplain_mapping_rasprocess |
| 15c | 602 | floodplain_mapping_python_gis |
| 16 | 120 | automating_ras_with_win32com |
| 17 | 121 | legacy_hecrascontroller_and_rascontrol |
| 18 | 420 | breach_results_extraction |
| 19 | 401 | steady_flow_analysis |
| 20 | 200 | plaintext_geometry_operations |
| 22 | 310 | dss_boundary_extraction |
| 23 | 500 | remote_execution_psexec |
| 24_aorc | 900 | aorc_precipitation |
| 24_1d | 320 | 1d_boundary_condition_visualization |
| 33 | 311 | validating_dss_paths |
| 34 | 611 | validating_map_layers |
| 101 | 700 | core_sensitivity |
| 102 | 701 | benchmarking_versions_6.1_to_6.6 |
| 103 | 720 | atlas14_aep_events |
| 103b | 721 | atlas14_caching_demo |
| 104 | 722 | atlas14_multi_project |
| 105 | 710 | mannings_sensitivity_bulk_analysis |
| 106 | 711 | mannings_sensitivity_multi_interval |
| 200 | 210 | fixit_blocked_obstructions |
| 300 | 800 | quality_assurance_rascheck |
| 301 | 801 | advanced_structure_validation |
| 302 | 802 | custom_workflows_and_standards |
| 400 | 901 | aorc_precipitation_catalog |
| 420 | 910 | usgs_gauge_catalog |
| 421 | 911 | usgs_gauge_data_integration |
| 422 | 912 | usgs_real_time_monitoring |
| 423 | 913 | bc_generation_from_live_gauge |
| 424 | 914 | model_validation_with_usgs |

---

## Naming Convention

```
{NUMBER}_{descriptive_name}.ipynb

Examples:
- 100_using_ras_examples.ipynb
- 410_2d_hdf_data_extraction.ipynb
- 800_quality_assurance_rascheck.ipynb
```

### Rules
1. **Three-digit numbers** - Always use leading zeros (100, not 1)
2. **Lowercase with underscores** - No spaces, no camelCase
3. **Descriptive names** - Clear purpose from filename
4. **No letter suffixes** - Use sequential numbers instead (600, 601, 602 not 600a, 600b)

---

## Adding New Notebooks

### Decision Tree

1. **Project setup, plan ops, execution?** → 100-199
2. **Geometry parsing or repair?** → 200-299
3. **Boundary conditions, DSS, flow files?** → 300-399
4. **HDF data extraction?** → 400-499
5. **Remote/distributed execution?** → 500-599
6. **Mapping, visualization, spatial analysis?** → 600-699
7. **Performance, sensitivity, benchmarking?** → 700-799
8. **Quality assurance, validation?** → 800-899
9. **External data (AORC, USGS, etc.)?** → 900-999

---

## Implementation Notes

### Migration Steps (When Ready)
1. Update mkdocs.yml nav with new numbers
2. Update docs/examples/index.md
3. Rename all notebooks in single commit
4. Update AGENTS.md references
5. Update any internal notebook cross-references

### Files to Update
- `mkdocs.yml` (nav section)
- `docs/examples/index.md` (all links)
- `examples/AGENTS.md` (notebook references)
- `examples/README.md` (if exists)
- Any notebooks with cross-references

---

## See Also

- `AGENTS.md` - Agent guide for navigating notebooks
- `feature_dev_notes/Example_Notebook_Holistic_Review/` - Review documentation
