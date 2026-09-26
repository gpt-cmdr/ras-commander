# Example Notebooks

These are the canonical, runnable examples for ras-commander. Each row links to the rendered documentation page and to the source `.ipynb` on GitHub. **Runtime** uses recorded notebook wall time when available, otherwise summed cell timings. `N/A` means no usable timing metadata; it does not mean outputs are absent. Saved outputs and runtime alone do not establish that the central workflow or hydraulic checks passed. Read each notebook's results and limitations.

Choose an operation through the [capability map](../capabilities.md), or use the summaries below to compare examples by task. Selected workflows include expandable input/output contracts.

See [Example Projects](example-projects.md) for the CRS-valid source catalog and MapLibre review contract for ras2cng-exported model bundles.

!!! tip "New here? Start with the 100s."
    Run **100 → 101 → 110** for the core initialize → inspect → execute loop, then branch into the series that matches your work: **200s** geometry & calibration, **300s** unsteady & DSS, **400s** HDF results, **900s** data integration & forecasting.

*139 notebooks indexed - 126 with runtime data, 13 without.*

## Selected Workflow Contracts

These optional contracts are curated in `examples/notebooks.yml` and published unchanged in [the catalog JSON](index.json). An omitted field means it has not been curated. Runtime requirements describe what the workflow needs; recorded runtime measures a saved execution. Evidence scope describes the example's limits, not a support badge.

??? info "101 - Project Initialization"

    [Open notebook](../notebooks/101_project_initialization.md)

    | Contract | Scope |
    | --- | --- |
    | Inputs | HEC-RAS project text and associated files |
    | Operations | Initialize independent project objects; Inspect file relationships and DataFrames |
    | Outputs | Project/plan/geometry/boundary inventories |
    | Runtime requirements | Python; HEC-RAS installation optional for file inspection |
    | Evidence scope | Inventory and path resolution do not establish that a plan can compute. |

??? info "110 - Single Plan Execution"

    [Open notebook](../notebooks/110_single_plan_execution.md)

    | Contract | Scope |
    | --- | --- |
    | Inputs | Initialized HEC-RAS project and selected plan |
    | Operations | Execute one plan through RasCmdr; Inspect return values and computation messages |
    | Outputs | ComputeResult; Native result and diagnostic files |
    | Runtime requirements | Installed HEC-RAS release compatible with the project; notebook config selects 7.0; Writable working-copy destination |
    | Evidence scope | Execution and completion evidence are separate from hydraulic acceptance; inspect the final result and diagnostics. |

??? info "117 - Monte Carlo Preparation and Ensemble Workflow"

    [Open notebook](../notebooks/117_monte_carlo_uncertainty.md)

    | Contract | Scope |
    | --- | --- |
    | Evidence scope | Saved outputs demonstrate model inspection and sampling only; no hydraulic ensemble or uncertainty estimate was computed. |

??? info "212 - Native NLCD Land Cover Authoring and Controlled Manning Validation"

    [Open notebook](../notebooks/212_landcover_mannings_n_write.md)

    | Contract | Scope |
    | --- | --- |
    | Inputs | Copied 2D projects; NLCD classes and geometry land-cover associations |
    | Operations | Author native land-cover sidecars; Modify selected Manning classes; Recompute and compare final values |
    | Outputs | Authored sidecars and geometry overrides; Cell/face roughness, WSE, and breach comparisons |
    | Runtime requirements | Windows native RASMapper dependencies and HEC-RAS; notebook config selects 7.0; NLCD data and writable project copies |
    | Evidence scope | The notebook retains controlled authoring and response comparisons for its selected models/classes; they do not qualify every land-cover or runtime combination. |

??? info "220 - Manning's n Calibration with RasCalibrate"

    [Open notebook](../notebooks/220_calibration_workflow.md)

    | Contract | Scope |
    | --- | --- |
    | Inputs | Real 2D model; Declared observation or synthetic-target dataset; Parameter bounds |
    | Operations | Evaluate objectives; Search Manning parameters; Compare event diagnostics |
    | Outputs | Objective values and parameter candidates; Modeled/target comparisons |
    | Runtime requirements | Scientific Python stack; Installed HEC-RAS required when RUN_HECRAS is enabled; configured default 6.6 |
    | Evidence scope | The execution switch and target provenance determine what a run establishes. Synthetic targets demonstrate estimation mechanics, not observational validation. |

??? info "224 - Steady Flow Authoring"

    [Open notebook](../notebooks/224_steady_flow_authoring.md)

    | Contract | Scope |
    | --- | --- |
    | Inputs | Real steady-flow project; Profile discharges and typed downstream boundaries |
    | Operations | Create and update steady-flow files; Read back authored records; Compute and inspect messages |
    | Outputs | Steady-flow files and linked plan inputs; Readback and execution diagnostics |
    | Runtime requirements | Python for text authoring; Installed HEC-RAS for the notebook computation stage |
    | Evidence scope | Text roundtrip and native computation are distinct checks; this example does not qualify floodway encroachment authoring. |

??? info "235 - Clip a Texas FEMA eBFE Model to One NWM Reach"

    [Open notebook](../notebooks/235_1d_breakout_model.md)

    | Contract | Scope |
    | --- | --- |
    | Inputs | Real 1D source project; NOAA NWM edge and selected hydraulic/export domains |
    | Operations | Select a reach slice; Assemble an independent breakout; Compare retained geometry and results |
    | Outputs | Standalone HEC-RAS project; Selection provenance and comparison evidence |
    | Runtime requirements | Source eBFE model and NWM network data; Windows/native geometry dependencies and HEC-RAS; notebook config selects 7.0 |
    | Evidence scope | Checks apply to the selected Shiloh Branch edge and retained sections; domain and boundary adequacy require review for a new extraction. |

??? info "400 - 1D HDF Data Extraction"

    [Open notebook](../notebooks/400_1d_hdf_data_extraction.md)

    | Contract | Scope |
    | --- | --- |
    | Inputs | 1D unsteady plan-result HDF; Geometry HDF or geometry embedded in results |
    | Operations | Read cross-section and structure results; Inspect runtime and volume accounting |
    | Outputs | xarray cross-section Dataset; Spatial geometry and tabular diagnostics |
    | Runtime requirements | Python HDF/geospatial dependencies; Retained compatible result HDF; no solver required for read-only extraction |
    | Evidence scope | Dataset presence and extraction establish readable stored results, not freshness or hydraulic acceptance. |

??? info "401 - Steady Flow Analysis"

    [Open notebook](../notebooks/401_steady_flow_analysis.md)

    | Contract | Scope |
    | --- | --- |
    | Inputs | 1D steady plan-result HDF |
    | Operations | List and select steady profiles; Extract and compare WSE |
    | Outputs | Profile-indexed water-surface arrays; Steady metadata and plots |
    | Runtime requirements | Python HDF dependencies for reading; Installed HEC-RAS for the notebook initial example computation |
    | Evidence scope | Steady profiles are separate from unsteady time series; the example comparisons do not establish model calibration. |

??? info "410 - 2D HDF Data Extraction"

    [Open notebook](../notebooks/410_2d_hdf_data_extraction.md)

    | Contract | Scope |
    | --- | --- |
    | Inputs | 2D geometry and unsteady result HDFs |
    | Operations | Query mesh cells/faces and result variables; Inspect time series and maximum values |
    | Outputs | GeoDataFrames; DataArray/Dataset results indexed by mesh-local cell or face IDs |
    | Runtime requirements | Python HDF, xarray, and geospatial dependencies; Requested output variables must exist in retained HDFs |
    | Evidence scope | Stored maxima, instantaneous time series, geometry, and derived quantities have different meanings; missing optional output is not zero. |

??? info "417 - Inspecting Results and Generating Hydraulic Product Packages"

    [Open notebook](../notebooks/417_inspect_results_and_generate_hydraulic_products.md)

    | Contract | Scope |
    | --- | --- |
    | Inputs | Existing completed unsteady HEC-RAS result HDF |
    | Operations | Inspect result identity and completeness; Export and independently check derivative products |
    | Outputs | Checksum-pinned COG, Arrow/Parquet, GeoJSON, JSON, and PNG package |
    | Runtime requirements | Python export/geospatial dependencies; Retained result HDF with required geometry, CRS, units, and outputs; no solver run |
    | Evidence scope | Mechanical inspection and derivative verification do not modify the producer HDF or establish hydraulic acceptance. |

??? info "612 - Benefit-area mapping for storm-system alternatives"

    [Open notebook](../notebooks/612_benefit_area_analysis.md)

    | Contract | Scope |
    | --- | --- |
    | Inputs | Storm-system baseline and alternative projects; Comparable stored Depth rasters |
    | Operations | Author pipe/pump alternatives; Compute and compare benefits and adverse depth changes |
    | Outputs | BenefitArea rasters and polygons; Hydraulic comparisons and adverse-depth screens |
    | Runtime requirements | Installed HEC-RAS and native stored-map tooling; Geospatial raster dependencies and writable model copies |
    | Evidence scope | Benefit categories use declared depth thresholds and aligned pre/post rasters; no qualifying benefit does not imply no physical change. |

??? info "720 - Precipitation Hyetograph Generation - Complete Method Comparison"

    [Open notebook](../notebooks/720_precipitation_methods_comprehensive.md)

    | Contract | Scope |
    | --- | --- |
    | Inputs | NOAA Atlas 14 depth-duration information; Declared storm duration and temporal distribution |
    | Operations | Compare precipitation temporal methods |
    | Outputs | Hyetographs and comparison plots |
    | Runtime requirements | Python precipitation dependencies; Network or cached precipitation source data; optional StormGenerator sections depend on availability |
    | Evidence scope | Method comparison demonstrates temporal construction; it does not select a locally appropriate design storm or prove delivery to a hydraulic solver. |

??? info "721 - Precipitation Hyetograph Comparison"

    [Open notebook](../notebooks/721_precipitation_hyetograph_comparison.md)

    | Contract | Scope |
    | --- | --- |
    | Evidence scope | Pattern generation and file readback are demonstrated. Native accumulated precipitation differs from intended totals; hydraulic comparison qualification is withheld. |

??? info "800 - Quality Assurance with RasCheck"

    [Open notebook](../notebooks/800_quality_assurance_rascheck.md)

    | Contract | Scope |
    | --- | --- |
    | Inputs | Computed steady-flow example projects |
    | Operations | Run RasCheck diagnostics; Review messages and thresholds |
    | Outputs | CheckResults messages; Tabular/HTML review outputs |
    | Runtime requirements | Python HDF dependencies; Installed HEC-RAS for example computation when needed |
    | Evidence scope | Diagnostics support review and may have incomplete dataset coverage. Floodway authoring/checking remains experimental; empty messages are not a compliance finding. |

??? info "912 - USGS Real-Time Gauge Monitoring"

    [Open notebook](../notebooks/912_usgs_real_time_monitoring.md)

    | Contract | Scope |
    | --- | --- |
    | Evidence scope | Current saved setup/map output uses real HDF geometry and successful USGS station metadata. Later monitoring outputs retain their historical configuration and were not rerun. |

??? info "922 - Model Comparison with USGS Gauge Data"

    [Open notebook](../notebooks/922_model_validation_with_usgs.md)

    | Contract | Scope |
    | --- | --- |
    | Inputs | Delivered Kalamazoo HDF reference-point water levels; USGS gauge observations for the matched period |
    | Operations | Align units and time references; Calculate observation comparisons with provenance |
    | Outputs | Matched series and comparison metrics; Recorded initialization/calibration limitations |
    | Runtime requirements | Python HDF and USGS dependencies; Retained model artifacts and gauge data or network access; no new solver run in the repaired comparison |
    | Evidence scope | Retained evidence covers 276 matched observations. Initialization failed and a distinct calibrated run was unavailable; no before/after calibration improvement is claimed. |

??? info "950 - Using eBFE Models: Spring Creek 2D Analysis"

    [Open notebook](../notebooks/950_ebfe_spring_creek.md)

    | Contract | Scope |
    | --- | --- |
    | Inputs | FEMA eBFE/BLE archive and delivered model files |
    | Operations | Organize project files; Inspect boundaries, geometry, and delivered results |
    | Outputs | Organized project inventory; Data availability and model-review outputs |
    | Runtime requirements | Archive download/cache and Python HDF/geospatial dependencies; Installed HEC-RAS only for the optional geometry-preprocessor stage |
    | Evidence scope | Delivered-result inspection is distinct from newly executed model verification; RUN_GEOMETRY_PREPROCESSOR defaults to False. |

??? info "959 - eBFE 2D Breakout Geometry Preparation"

    [Open notebook](../notebooks/959_ebfe_2d_breakout_geometry_preparation.md)

    | Contract | Scope |
    | --- | --- |
    | Inputs | Pure-2D parent project and proposed contained child domain; Parent mesh and result HDF |
    | Operations | Preflight and clone plan components; Trim/remesh geometry; Review parent-face flux |
    | Outputs | Prepared child geometry; Unchanged unsteady-file evidence; Candidate flux zones |
    | Runtime requirements | Windows native geometry dependencies and installed HEC-RAS; default configuration 6.6; Retained Upper Guadalupe parent artifacts |
    | Evidence scope | Geometry preparation and unassigned flux review do not author child boundary conditions or establish a completed child solve. |

??? info "962 - Cloud Optimized GeoTIFF Results Export with ras2cng"

    [Open notebook](../notebooks/962_cloud_native_cog_results_export.md)

    | Contract | Scope |
    | --- | --- |
    | Inputs | Computed 2D result HDF and geometry |
    | Operations | Prepare example results; Export cloud-native raster results with ras2cng |
    | Outputs | COG result rasters and export metadata |
    | Runtime requirements | ras2cng and raster dependencies; Installed HEC-RAS for the example compute stage; configured version 6.6 |
    | Evidence scope | Exported products reflect the selected producer results and options; product generation alone does not establish hydraulic quality. |

## 100s - Initialization & Execution

| Notebook | Source | Runtime |
| --- | --- | --- |
| [100 - Using RasExamples](../notebooks/100_using_ras_examples.md)<br>extract official HEC-RAS example projects | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/100_using_ras_examples.ipynb) | 35 s |
| [101 - Project Initialization](../notebooks/101_project_initialization.md)<br>initialize projects and inspect project DataFrames | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/101_project_initialization.ipynb) | 5 s |
| [102 - Multiple Project Operations](../notebooks/102_multiple_project_operations.md)<br>Manage separate project objects, clone and configure plans, execute the projects concurrently, and compare their execution records with explicit ras_object context. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/102_multiple_project_operations.ipynb) | 2.2 min |
| [103 - Plan and Geometry Operations](../notebooks/103_plan_and_geometry_operations.md)<br>Clone, associate, configure, and delete plan, geometry, and unsteady files; inspect project metadata and compute the modified plan in a working project. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/103_plan_and_geometry_operations.ipynb) | 1.8 min |
| [104 - Plan Parameter Operations](../notebooks/104_plan_parameter_operations.md)<br>Read and update run flags, computation/output intervals, file descriptions, and simulation dates, then inspect the saved plan configuration. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/104_plan_parameter_operations.ipynb) | 1.3 min |
| [110 - Single Plan Execution](../notebooks/110_single_plan_execution.md)<br>run plans through RAS Commander | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/110_single_plan_execution.ipynb) | 8.3 min |
| [111 - Executing Plan Sets](../notebooks/111_executing_plan_sets.md)<br>Select explicit or metadata-filtered plan sets and execute them sequentially in a test copy, including plans that lack retained HDF results. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/111_executing_plan_sets.ipynb) | 3.0 min |
| [112 - Sequential Plan Execution](../notebooks/112_sequential_plan_execution.md)<br>Run dependent plans sequentially with compute_test_mode, inspect the copied project, and summarize per-plan execution outcomes. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/112_sequential_plan_execution.ipynb) | 3.3 min |
| [113 - Parallel Execution](../notebooks/113_parallel_execution.md)<br>run plans through RAS Commander | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/113_parallel_execution.ipynb) | 3.3 h |
| [114 - Parameter Permutation Sweeps with RasPermutation](../notebooks/114_parameter_permutation.md)<br>Generate Cartesian products of parameter ranges, automatically partition into batch folders (respecting the 99-plan HEC-RAS limit), execute in parallel, and collect results into audit-friendly CSV logs. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/114_parameter_permutation.ipynb) | 2.3 min |
| [115 - Real-Time Execution Monitoring with Callbacks](../notebooks/115_real_time_execution_monitoring.md)<br>This notebook demonstrates how to use execution callbacks for real-time monitoring of HEC-RAS plan execution. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/115_real_time_execution_monitoring.ipynb) | 1.4 min |
| [116 - HDF Output Options Read Benchmark](../notebooks/116_hdf_output_options_benchmark.md)<br>Use the `BaldEagleCrkMulti2D` example project and plan `06` to compare HDF write settings by measuring ras-commander HDF read performance after the plans have been computed. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/116_hdf_output_options_benchmark.ipynb) | 25.6 min |
| [117 - Monte Carlo Preparation and Ensemble Workflow](../notebooks/117_monte_carlo_uncertainty.md)<br>Inspect a real model and generate parameter samples; retain an unexecuted ensemble recipe with explicit convergence and failure-handling requirements. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/117_monte_carlo_uncertainty.ipynb) | 10.4 min |
| [120 - Win32COM Automation](../notebooks/120_automating_ras_with_win32com.md)<br>Demonstrate Windows HEC-RAS GUI automation helpers for dialogs, RAS Mapper, and stored-map workflows that require an interactive desktop. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/120_automating_ras_with_win32com.ipynb) | 13 s |
| [121 - HECRASController Profiles](../notebooks/121_legacy_hecrascontroller_and_rascontrol.md)<br>Use the Windows HECRASController through RasControl to execute configured legacy plans and extract steady profiles or unsteady time series. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/121_legacy_hecrascontroller_and_rascontrol.ipynb) | 2.2 min |
| [122 - RASMapper Spatial Review](../notebooks/122_rasmapper_spatial_review.md)<br>Inspect RAS Mapper layer inventories, control map views and visibility, and capture screenshots and spatial review packages. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/122_rasmapper_spatial_review.ipynb) | 1.1 min |
| [123 - RASMapper Geometry Layer Updates](../notebooks/123_rasmapper_geometry_layer_updates.md)<br>Apply selected native RAS Mapper geometry-layer commands across real example projects and inspect updated cross sections, structures, and storage curves. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/123_rasmapper_geometry_layer_updates.ipynb) | 9.8 min |
| [124 - RASMapper Bank Lines](../notebooks/124_rasmapper_bank_lines.md)<br>Generate RAS Mapper bank lines from cross-section bank stations through a supervised Windows GUI workflow. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/124_rasmapper_bank_lines.ipynb) | 44 s |
| [125 - RASMapper Stored Maps: Arrival Time, Duration, and Percent Time Inundated](../notebooks/125_rasmapper_stored_maps_arrival_duration.md)<br>`RasProcess.store_maps()` generates rendered result rasters through the HEC-RAS mapping engine (RasMapperLib via the bundled `RasStoreMapHelper.exe`). This notebook covers the whole-simulation map types added alongside the profile-based WSE, depth, and velocity products. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/125_rasmapper_stored_maps_arrival_duration.ipynb) | N/A |
| [150 - Using results_df for Plan Results Summary](../notebooks/150_results_dataframe.md)<br>This notebook demonstrates the `results_df` DataFrame, which provides lightweight HDF-based results summaries for all plans. This enables quick access to execution status, volumetric errors, compute messages, and runtime data without ope... | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/150_results_dataframe.ipynb) | 1.1 min |

## 200s - Geometry & Calibration

| Notebook | Source | Runtime |
| --- | --- | --- |
| [201 - 1D Geometry File Parsing](../notebooks/201_1d_plaintext_geometry.md)<br>geometry and HTAB workflows | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/201_1d_plaintext_geometry.ipynb) | 18 s |
| [202 - 2D Geometry File Parsing](../notebooks/202_2d_plaintext_geometry.md)<br>This notebook demonstrates parsing and manipulating 2D geometry elements from HEC-RAS plain text geometry files, including: - Storage Area operations (BaldEagleCrkMulti2D) - SA/2D Connection operations and dam crest profiles (BaldEagleCr... | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/202_2d_plaintext_geometry.ipynb) | 3.7 min |
| [203 - HTAB Parameter Optimization for Model Stability](../notebooks/203_htab_parameter_optimization.md)<br>geometry and HTAB workflows | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/203_htab_parameter_optimization.ipynb) | 33 s |
| [204 - Culvert GIS Reconstruction and Hydraulic-Validity Checks (1D)](../notebooks/204_culvert_gis_validation.md)<br>Reconstruct 1D culvert barrel locations from geometry, screen invert placement, and compare a pipe-to-box retrofit using computed steady profiles. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/204_culvert_gis_validation.ipynb) | 14 s |
| [205 - Extract Cross Section XYZ Coordinates from Plain Text Geometry](../notebooks/205_extract_xs_xyz_from_geometry.md)<br>geometry and HTAB workflows | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/205_extract_xs_xyz_from_geometry.ipynb) | 4 s |
| [206 - Structures and Metadata from Geometry Files](../notebooks/206_structures_and_metadata.md)<br>This notebook demonstrates parsing bridge, culvert, inline weir, and geometry metadata from HEC-RAS plain text geometry files, including: - GeomMetadata: Efficient geometry element counts (HDF-first with text fallback) - GeomBridge: Brid... | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/206_structures_and_metadata.ipynb) | 4 s |
| [207 - Reference Lines and Points for 2D Calibration](../notebooks/207_reference_lines_and_points.md)<br>This notebook demonstrates `GeomReferenceFeatures` — inserting and reading reference lines and reference points in HEC-RAS plain text geometry files. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/207_reference_lines_and_points.ipynb) | 3 s |
| [208 - Bridge Method Comparison](../notebooks/208_bridge_method_comparison.md)<br>Compare bridge hydraulic method selections with a real HEC-RAS bridge example and show the effect on computed WSE. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/208_bridge_method_comparison.ipynb) | 1.7 min |
| [209 - Culvert Authoring](../notebooks/209_culvert_authoring.md)<br>Write taxonomy-checked culvert records and adjacent ineffective-flow areas, inspect spatial placement, and compute an edited plan for result review. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/209_culvert_authoring.ipynb) | 8 s |
| [210 - Cross-Section Interpolation Settings](../notebooks/210_xs_interpolation_settings.md)<br>Interpolate cross sections and update bank stations, station/elevation arrays, and expansion/contraction coefficients in an example geometry. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/210_xs_interpolation_settings.ipynb) | 18 s |
| [211 - Final Manning's N and Infiltration Analysis](../notebooks/211_final_mannings_and_infiltration.md)<br>This notebook demonstrates how to extract final Manning's N and preprocessed infiltration values from a reproducible example project. It also includes a regression check for multi-ring infiltration override polygons. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/211_final_mannings_and_infiltration.ipynb) | 3 s |
| [212 - Native NLCD Land Cover Authoring and Controlled Manning Validation](../notebooks/212_landcover_mannings_n_write.md)<br>Author matching NLCD land-cover layers through native RASMapper APIs, change exactly two Manning classes, recompute and solve both projects, and validate final cell, face, WSE, and breach responses with explicit active-cell and regenerated-key accounting. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/212_landcover_mannings_n_write.ipynb) | 7.6 min |
| [213 - Native Land Classification Polygon Authoring](../notebooks/213_land_classification_polygon_authoring.md)<br>Add, update, list, and delete existing-class land-cover polygons through native RASMapper, reject unsupported multipart and interior-ring inputs before mutation, and verify final Manning, WSE, association, backup, and breach behavior. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/213_land_classification_polygon_authoring.ipynb) | 6.7 min |
| [214 - SA/2D Connection Authoring](../notebooks/214_connection_authoring.md)<br>Create, inspect, delete, and re-create SA/2D area connections in a real HEC-RAS geometry file. This notebook demonstrates an engineering-oriented workflow for the `Dam` connection in `BaldEagleDamBrk.g13`: | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/214_connection_authoring.ipynb) | 10 s |
| [215 - SA/2D Bridge Connection Authoring](../notebooks/215_sa2d_bridge_connection_authoring.md)<br>Read, modify, and round-trip bridge connection sub-records (routing type 32, `Conn BR:` blocks) in a HEC-RAS geometry file. This notebook demonstrates the bridge-specific API on `BaldEagleDamBrk.g03`, which contains 7 bridge connections... | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/215_sa2d_bridge_connection_authoring.ipynb) | 21 s |
| [216 - 1D Bridge Authoring](../notebooks/216_1d_bridge_authoring.md)<br>Author bridge decks, piers, abutments, coefficients, approach sections, and HTAB settings; read back the geometry and inspect computed messages/results. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/216_1d_bridge_authoring.ipynb) | 4 s |
| [217 - 1D Cross-Section Levee Authoring](../notebooks/217_1d_levee_authoring.md)<br>Read, modify, insert, and remove cross-section levee station-elevation data in a real HEC-RAS geometry file, then run the unsteady simulation on the modified geometry and verify results extraction from the HDF output. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/217_1d_levee_authoring.ipynb) | 2.4 min |
| [218 - Native Infiltration Base and Region Override Authoring](../notebooks/218_infiltration_base_override_authoring.md)<br>Create native infiltration override regions, edit geometry-wide Base Overrides and one named regional parameter table through RASMapper, then verify spatial attribution in final geometry and plan infiltration arrays and hydraulic results. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/218_infiltration_base_override_authoring.ipynb) | 16.8 min |
| [219 - 1D Bridge Cross-Section Plotting with Deck/Pier Overlay](../notebooks/219_1d_bridge_xs_plotting.md)<br>HEC-RAS 1D bridges use four cross-sections: | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/219_1d_bridge_xs_plotting.ipynb) | 5 s |
| [220 - Manning's n Calibration with RasCalibrate](../notebooks/220_calibration_workflow.md)<br>`RasCalibrate` provides parameter estimation workflows for HEC-RAS models, composing `RasPermutation`, HDF extraction helpers, and statistical metrics into a streamlined calibration API. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/220_calibration_workflow.ipynb) | 8 s |
| [221 - 1D Manning's N Calibration Workflow](../notebooks/221_calibration_1d_workflow.md)<br>Demonstrates automated Manning's n calibration for a 1D HEC-RAS unsteady model using the `RasCalibrate` module with `grid_search()` and `optimize()`. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/221_calibration_1d_workflow.ipynb) | 36.6 min |
| [222 - Steady Flow Calibration](../notebooks/222_steady_flow_calibration.md)<br>Demonstrate steady-flow Manning roughness estimation against a synthetic observed WSE profile; inspect objective values without treating the target as field validation. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/222_steady_flow_calibration.ipynb) | 39 s |
| [224 - Steady Flow Authoring](../notebooks/224_steady_flow_authoring.md)<br>Create, read, and update steady-flow files with profile discharges and typed boundary conditions, then inspect HEC-RAS execution messages. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/224_steady_flow_authoring.ipynb) | 12 s |
| [225 - Fixing Blocked Obstruction Overlaps with RasFixit](../notebooks/225_fixit_blocked_obstructions.md)<br>This notebook demonstrates using the `RasFixit` module to automatically detect and repair overlapping blocked obstructions in HEC-RAS geometry files. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/225_fixit_blocked_obstructions.ipynb) | 7 s |
| [226 - 2D Connection Culvert Invert Validation (Terrain Cell Minimum)](../notebooks/226_2d_connection_culvert_invert_validation.md)<br>Compare proposed and authored SA/2D culvert inverts with terrain-derived mesh-cell minima and visualize placement along the connection. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/226_2d_connection_culvert_invert_validation.ipynb) | 32 s |
| [227 - Authoring a 2D Connection Culvert (`Connection Culv=`)](../notebooks/227_2d_connection_culvert_authoring.md)<br>Author a culvert in a previously weir-only SA/2D connection, read back Connection Culv records, and review placement and native acceptance. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/227_2d_connection_culvert_authoring.ipynb) | 22 s |
| [228 - Manning's n from NLCD Validation](../notebooks/228_mannings_n_from_nlcd.md)<br>Validate `ManningsFromLandCover` on the real `BaldEagleCrkMulti2D` RasExamples project. The workflow compares the existing 1D geometry Manning's n blocks against automated NLCD-derived horizontal variation, checks the project RAS Mapper... | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/228_mannings_n_from_nlcd.ipynb) | 2.3 min |
| [229 - Model Extent Polygons (1D, 2D, and Overall Footprints)](../notebooks/229_model_extent_polygons.md)<br>extract 2D flow-area perimeters, generate 1D river edge lines and reach footprints, combine them into the true model extent, and compare 1D-only, 2D-only, and legacy bounding-box geometries for Bald Eagle Creek and Muncie | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/229_model_extent_polygons.ipynb) | 7 s |
| [230 - 2D Mesh Cell-Size Sensitivity for Sediment Transport](../notebooks/230_mesh_sensitivity_analysis.md)<br>**Model:** Chippewa River 2D (`Chippewa_2D`, HEC's *2D Sediment Transport* example suite, plan *"100ft Sediment"*) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/230_mesh_sensitivity_analysis.ipynb) | 6.9 min |
| [231 - Headless Mesh Generation: Pipe Networks and Refinement Regions](../notebooks/231_pipe_network_mesh_generation.md)<br>Headlessly regenerate a pipe-connected Davis mesh, then author and visually verify a 40-foot refinement region on the Chippewa 2D fixture. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/231_pipe_network_mesh_generation.ipynb) | 8 s |
| [232 - 2D Mesh Cell-Size Sensitivity for Sediment Transport - Second Case: Weise Flume](../notebooks/232_weise_2d_sediment_mesh_sensitivity.md)<br>**Model:** Weise 2D (`Weise_2D`, HEC's *2D Sediment Transport* example suite, plan *"Weise"*) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/232_weise_2d_sediment_mesh_sensitivity.ipynb) | 16.7 min |
| [233 - Manning's n Region Polygon Authoring and Solver Validation](../notebooks/233_mannings_region_polygon_authoring.md)<br>Author a regional Manning's n polygon on the real Muncie fixture, explicitly associate terrain and land cover, validate the temporary and final plan HDF cell values, and visually confirm solver propagation. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/233_mannings_region_polygon_authoring.ipynb) | 49 s |
| [234 - Headless RASMapper Geometry Completion (Edge Lines, Interpolation Surface, Flow Paths)](../notebooks/234_rasmapper_geometry_completion.md)<br>Generate the RASMapper-derived geometry layers in-process via pythonnet - river edge lines, the cross-section interpolation surface, and flow path lines - read each one back, surface per-cross-section validation diagnostics, and audit stored 1D reach lengths against freshly recomputed flow lengths on a throwaway copy of the project. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/234_rasmapper_geometry_completion.ipynb) | 29 s |
| [235 - Clip a Texas FEMA eBFE Model to One NWM Reach](../notebooks/235_1d_breakout_model.md)<br>Classify real NOAA NWM v3 reaches against the Shiloh Branch eBFE footprint, retain 10% upstream and 25% downstream hydraulic buffers around feature 5790868, rasterize a stricter one-cross-section-overlap export domain, and compare the independent breakout to the source model. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/235_1d_breakout_model.ipynb) | N/A |
| [236 - Build a Texas FEMA eBFE Breakout from Adjacent Main-Stem Models](../notebooks/236_multi_model_1d_breakout_planning.md)<br>Catalog and join two adjacent Walnut Creek FEMA eBFE main-stem projects for NOAA NWM feature 5790954, write an independent restationed HEC-RAS project, retain source-block provenance, and visually verify the centerline seam, computational/export domains, two-pass flow-path finalization, inherited geometry diagnostics, and retained-section hydraulic response against both original plans. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/236_multi_model_1d_breakout_planning.ipynb) | 42 s |

## 300s - Unsteady Flow & DSS

| Notebook | Source | Runtime |
| --- | --- | --- |
| [300 - Unsteady Flow Operations](../notebooks/300_unsteady_flow_operations.md)<br>Inspect and edit unsteady boundary tables, clone flow and plan files, scale hydrographs, and compare computed cross-section water levels. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/300_unsteady_flow_operations.ipynb) | 26 s |
| [301 - Flow Hydrograph Optimization](../notebooks/301_flow_hydrograph_optimization.md)<br>Configure native flow-hydrograph optimization, inspect trial results, and compare the optimized hydrograph and WSE; retain a separate multiplier-search fallback. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/301_flow_hydrograph_optimization.ipynb) | 1.0 min |
| [310 - DSS Boundary Extraction](../notebooks/310_dss_boundary_extraction.md)<br>from ras_commander import * | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/310_dss_boundary_extraction.ipynb) | 5 s |
| [312 - Boundary DataFrame Enhancement: QMult, QMin, and DSS Path Parsing](../notebooks/312_boundary_df_qmult_dss_paths.md)<br>DSS boundary workflows | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/312_boundary_df_qmult_dss_paths.ipynb) | 49 s |
| [313 - HMS-to-RAS Boundary Condition Matching](../notebooks/313_hms_to_ras_boundary_matching.md)<br>This notebook demonstrates **correlation-based matching** between HEC-HMS DSS hydrograph outputs and HEC-RAS boundary condition locations using the **BaldEagleCrkMulti2D** example project. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/313_hms_to_ras_boundary_matching.ipynb) | 5 s |
| [314 - Breakline-Derived Reference Lines And USGS Gauge Points](../notebooks/314_reference_line_generation.md)<br>This notebook authors 2D HEC-RAS reference features from hydraulic geometry, not arbitrary straight lines. It uses channel-aligned 2D breaklines as longitudinal reference lines, generates 250 ft perpendicular transects from those centerl... | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/314_reference_line_generation.ipynb) | 3.3 min |
| [315 - 2D Computation Options](../notebooks/315_2d_computation_options.md)<br>Clone 2D plans with typed computation options, run scenario plans, and compare HDF settings, stability messages, and maximum WSE. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/315_2d_computation_options.ipynb) | 2.4 min |
| [316 - Terrain Modifications: High-Ground and Polygon Writer Validation](../notebooks/316_terrain_modifications.md)<br>This notebook validates ras-commander terrain modification writers with a real HEC-RAS example project. It creates copied terrain sidecar modifications for high-ground lines, boundary-sampled polygon multipoint grading, and `shape_z` pol... | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/316_terrain_modifications.ipynb) | 2.9 min |
| [317 - Restart File Output and Warm-Start Settings](../notebooks/317_restart_file_settings.md)<br>This notebook validates the restart-file API split used by warm-start workflows: | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/317_restart_file_settings.ipynb) | 24 s |
| [318 - Validating DSS File Paths and Data Availability](../notebooks/318_validating_dss_paths.md)<br>DSS boundary workflows | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/318_validating_dss_paths.ipynb) | 4 s |
| [319 - Post-fire debris-flow 2D modeling, built from scratch (non-Newtonian)](../notebooks/319_post_fire_debris_flow_nonnewtonian.md)<br>This example builds a **complete 2D HEC-RAS debris-flow model from nothing** — no starting project — and runs a clear-water baseline plus **Bingham non-Newtonian** mud/debris-flow variants, then derives hazard-intensity and arrival-time... | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/319_post_fire_debris_flow_nonnewtonian.ipynb) | 6.3 min |
| [320 - 1D Boundary Condition Visualization](../notebooks/320_1d_boundary_condition_visualization.md)<br>This notebook demonstrates how to extract and visualize 1D boundary conditions from a HEC-RAS project. The workflow: | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/320_1d_boundary_condition_visualization.ipynb) | 5 s |

## 400s - HDF Results Extraction

| Notebook | Source | Runtime |
| --- | --- | --- |
| [400 - 1D HDF Data Extraction](../notebooks/400_1d_hdf_data_extraction.md)<br>Read 1D unsteady HDF geometry and results, including cross-section time series, storage curves, structures, runtime, and volume accounting. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/400_1d_hdf_data_extraction.ipynb) | 1.6 min |
| [401 - Steady Flow Analysis](../notebooks/401_steady_flow_analysis.md)<br>Read steady HDF profile names, WSE arrays, messages, and metadata; select profiles by name or index and compare their longitudinal elevations. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/401_steady_flow_analysis.ipynb) | 5.8 min |
| [410 - 2D HDF Data Extraction](../notebooks/410_2d_hdf_data_extraction.md)<br>HDF mesh and results extraction | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/410_2d_hdf_data_extraction.ipynb) | 5.4 min |
| [411 - Pipes and Pumps](../notebooks/411_2d_hdf_pipes_and_pumps.md)<br>Extract pipe-network and pump geometry/time series from HDF results and inspect pipe flow and velocity along profile lines. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/411_2d_hdf_pipes_and_pumps.ipynb) | 3.3 min |
| [412 - 2D Face Data Extraction](../notebooks/412_2d_detail_face_data_extraction.md)<br>HDF mesh and results extraction | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/412_2d_detail_face_data_extraction.ipynb) | 3.3 min |
| [413 - Profile Line Flow Extraction](../notebooks/413_profile_line_flow_extraction.md)<br>HDF mesh and results extraction | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/413_profile_line_flow_extraction.ipynb) | 3 s |
| [414 - Controlled Depth-Varying Manning's n for HEC-RAS 2D Linux Solves](../notebooks/414_depth_varying_mannings_n.md)<br>Experimental, non-production comparison of baseline, table-extension control, and depth-varying-Manning scenarios in the single tested HEC-RAS 7.0 April 2026 Windows-preprocess/Linux-solve temporary-HDF workflow; all other versions and workflows are untested. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/414_depth_varying_mannings_n.ipynb) | 5.4 min |
| [415 - 2D Spatial Result Queries with HdfResultsQuery](../notebooks/415_2d_spatial_result_queries.md)<br>Query water surface elevation, depth, and velocity at arbitrary (x,y) coordinates, extract profiles along transects, compute flood extent with engineering filters, and generate domain-wide statistics -- all using scipy KDTree spatial ind... | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/415_2d_spatial_result_queries.ipynb) | 5.5 min |
| [416 - 2D Velocity Profile Line Extraction](../notebooks/416_2d_velocity_profile_line.md)<br>Extract velocity, depth, and terrain along a user-defined profile line from a completed 2D plan HDF. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/416_2d_velocity_profile_line.ipynb) | 5 s |
| [417 - Inspecting Results and Generating Hydraulic Product Packages](../notebooks/417_inspect_results_and_generate_hydraulic_products.md)<br>Read and mechanically inspect an existing completed HEC-RAS result HDF, then generate and independently verify a checksum-pinned COG, Arrow/Parquet, GeoJSON, JSON, and PNG derivative package without modifying the producer HDF or generating model output. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/417_inspect_results_and_generate_hydraulic_products.ipynb) | N/A |
| [420 - Dam Breach Results](../notebooks/420_breach_results_extraction.md)<br>Read breach geometry and hydrographs, clone width and formation-time scenarios, execute the plans, and compare peak flow and breach evolution. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/420_breach_results_extraction.ipynb) | 2.9 min |
| [430 - 1D Channel Capacity Analysis](../notebooks/430_1d_channel_capacity_analysis.md)<br>This notebook demonstrates the `HdfChannelCapacity` class for analyzing 1D channel capacity using WSE results and bank station elevations. Channel capacity is determined by comparing water surface elevations from multiple AEP storm profi... | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/430_1d_channel_capacity_analysis.ipynb) | 1.3 min |

## 500s - Remote Execution

| Notebook | Source | Runtime |
| --- | --- | --- |
| [500 - Remote Execution with ras-commander](../notebooks/500_remote_execution_psexec.md)<br>This notebook demonstrates how to execute HEC-RAS plans using: 1. **Local parallel execution** - `RasCmdr.compute_parallel()` on your local machine 2. **Remote execution** - `compute_parallel_remote()` on remote machines via PsExec/Docker | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/500_remote_execution_psexec.ipynb) | 8.7 min |
| [510 - Linux Execution of HEC-RAS with ras-commander](../notebooks/510_linux_execution.md)<br>This notebook demonstrates how to execute HEC-RAS simulations on Linux servers using `RasCmdr.compute_plan_linux()`. This enables scalable, headless execution on cloud VMs, Proxmox containers, Docker, or any Linux host with the HEC-RAS L... | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/510_linux_execution.ipynb) | N/A |
| [511 - Headless Linux/Wine/Ras2Cng Setup and Qualification](../notebooks/511_headless_linux_wine_ras2cng.md)<br>Set up an isolated Linux task that uses official HEC-RAS Linux executables where supported and the same Windows HEC-RAS version under Wine only for RasProcess/RASMapper gaps and ras2cng stored-map export. This is a qualification workflow... | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/511_headless_linux_wine_ras2cng.ipynb) | N/A |
| [512 - Docker Precompute and Native Linux Compute](../notebooks/512_docker_precompute_and_linux_compute.md)<br>Run the same two Python calls on Windows or Linux: first prepare a HEC-RAS plan with the Wine container, then execute the matching native Linux unsteady container. Both containers use [ras-commander](https://rascommander.info/ras/) APIs... | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/512_docker_precompute_and_linux_compute.ipynb) | N/A |
| [560 - Modified Puls Routing Extraction from HEC-RAS 2D Models](../notebooks/560_modpuls_routing_extraction.md)<br>> **⚠️ BETA**: `RasModPuls` and this notebook are currently **beta** and have not yet been > validated in production. The workflow, API, and outputs may change in future releases. > We welcome feedback from third-party users looking to v... | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/560_modpuls_routing_extraction.ipynb) | 3.5 min |

## 600s - Floodplain Mapping

| Notebook | Source | Runtime |
| --- | --- | --- |
| [600 - Floodplain Mapping via GUI Automation](../notebooks/600_floodplain_mapping_gui.md)<br>This notebook demonstrates floodplain mapping using **HEC-RAS GUI automation** to generate: - Maximum Water Surface Elevation (WSE) rasters - Maximum Depth rasters | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/600_floodplain_mapping_gui.ipynb) | 19.5 min |
| [601 - Headless Stored Map Generation Using RasMapper](../notebooks/601_headless_stored_map_generation_rasmapper.md)<br>This notebook demonstrates headless stored map generation using **RasMapper** through RasProcess.store_maps() to create maximum WSE rasters, maximum depth rasters, and inundation boundary polygons. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/601_headless_stored_map_generation_rasmapper.ipynb) | 6.1 min |
| [610 - Generate Fluvial Pluvial Delineations using Max WSE Arrival Time](../notebooks/610_generate_fluvial_pluvial_delineations_max_wse_arrival_time.md)<br>Use differences in time of maximum 2D WSE to derive draft fluvial/pluvial transition lines and polygons for interpretation and map review. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/610_generate_fluvial_pluvial_delineations_max_wse_arrival_time.ipynb) | 1.0 h |
| [611 - Validating RAS Mapper Layers and Terrain Files](../notebooks/611_validating_map_layers.md)<br>Discover registered RAS Mapper layers and screen their format, CRS, raster metadata, spatial extent, and terrain/land-cover associations. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/611_validating_map_layers.ipynb) | 9 s |
| [612 - Benefit-area mapping for storm-system alternatives](../notebooks/612_benefit_area_analysis.md)<br>This example builds and computes HEC-RAS 7.0 conduit, second-pump, and combined alternatives, compares hydraulic performance, and maps categorical benefits, adverse depth increases, and building-footprint exposure. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/612_benefit_area_analysis.ipynb) | 1.3 min |

## 700s - Sensitivity & Precipitation

| Notebook | Source | Runtime |
| --- | --- | --- |
| [700 - Core Sensitivity Testing with results_df](../notebooks/700_core_sensitivity.md)<br>This notebook demonstrates **processor core sensitivity analysis** for HEC-RAS 2D unsteady flow models. Understanding how computational performance scales with available CPU cores is essential for: | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/700_core_sensitivity.ipynb) | 17.0 min |
| [701 - Version Benchmarking and Core Scaling (HEC-RAS 5.0.5, 6.0, 6.3.1, 6.6, 7.0)](../notebooks/701_benchmarking_versions_6.1_to_6.6.md)<br>Benchmark one 2D plan across selected HEC-RAS versions and core counts; compare execution time, speedup, continuity diagnostics, and completion evidence. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/701_benchmarking_versions_6.1_to_6.6.ipynb) | 2 s |
| [710 - Manning's n Bulk Sensitivity Analysis](../notebooks/710_mannings_sensitivity_bulk_analysis.md)<br>This notebook demonstrates **bulk Manning's n sensitivity analysis** for HEC-RAS 2D models with spatially variable roughness. The workflow: | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/710_mannings_sensitivity_bulk_analysis.ipynb) | 2.0 min |
| [711 - One-at-a-Time (OAT) Manning's n Sensitivity Analysis](../notebooks/711_mannings_sensitivity_multi_interval.md)<br>This notebook performs a one-at-a-time Manning's n sensitivity analysis on the Muncie 2D example project using GeomLandCover edits, local parallel execution, preprocessed cell roughness propagation QA, and POI max-WSE sensitivity plots. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/711_mannings_sensitivity_multi_interval.ipynb) | 12.1 min |
| [720 - Precipitation Hyetograph Generation - Complete Method Comparison](../notebooks/720_precipitation_methods_comprehensive.md)<br>precipitation methods | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/720_precipitation_methods_comprehensive.ipynb) | 16 s |
| [721 - Precipitation Hyetograph Comparison](../notebooks/721_precipitation_hyetograph_comparison.md)<br>Generate and read back 30 precipitation patterns through the public API; compare intended forcing with native evidence from two bounded Davis runs. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/721_precipitation_hyetograph_comparison.ipynb) | 44.1 min |
| [722 - Gridded Precipitation with Atlas 14: Current Workflow](../notebooks/722_gridded_precipitation_atlas14.md)<br>Migration guide to the implemented Atlas 14 workflow in notebook 727, with capability lookup and links to GeoTIFF, MRMS, and HRRR examples. Retires obsolete placeholder APIs and raw meteorology edits. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/722_gridded_precipitation_atlas14.ipynb) | 1.1 min |
| [723 - StormGenerator Alternating Block Method - Independent Textbook Validation](../notebooks/723_storm_generator_abm_validation.md)<br>Compare StormGenerator alternating-block hyetographs with an independent reference calculation and optional HMS storm classes; check depth conservation and temporal placement. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/723_storm_generator_abm_validation.ipynb) | 5 s |
| [725 - Atlas 14 Spatial Variance Analysis](../notebooks/725_atlas14_spatial_variance.md)<br>precipitation methods | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/725_atlas14_spatial_variance.ipynb) | 1.3 min |
| [726 - Gridded ABM Hyetograph Generation](../notebooks/726_abm_hyetograph_grid.md)<br>Generate spatial ABM design-storm interval depths in CF NetCDF and identify the separate HEC-RAS conversion and qualification steps. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/726_abm_hyetograph_grid.ipynb) | 2.4 min |
| [727 - Atlas 14 Gridded Design Storm Rain-on-Grid in HEC-RAS](../notebooks/727_atlas14_gridded_rain_on_grid_hecras.md)<br>Convert spatial NOAA Atlas 14 depths to projected ABM rain-on-grid forcing, execute controlled no-rain, spatial, and equivalent-uniform Bald Eagle HEC-RAS scenarios, and quantify the modeled hydraulic response. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/727_atlas14_gridded_rain_on_grid_hecras.ipynb) | 16.5 min |
| [728 - Extending Gridded DSS Forcing Through the Simulation Window](../notebooks/728_extend_gridded_dss_forcing_window.md)<br>preserve and extend a model-covering gridded DSS family with three explicit dry intervals, then verify temporary/final HDF forcing, a HEC-RAS 7.0 compute, the dry-tail plateau, active-cell agreement, runtime diagnostics, and hydraulic results on Bald Eagle Creek | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/728_extend_gridded_dss_forcing_window.ipynb) | 1.3 min |
| [729 - Direct GeoTIFF Gridded Rain-on-Grid](../notebooks/729_direct_geotiff_gridded_rain_on_grid.md)<br>Author projected precipitation GeoTIFFs, validate temporary plan-HDF rainfall, compute Bald Eagle, and inspect final rainfall and hydraulics | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/729_direct_geotiff_gridded_rain_on_grid.ipynb) | 42 s |
| [730 - Raster Processing Performance Profiling](../notebooks/730_raster_processing_performance_profiling.md)<br>Measure stored-map and VRT-to-GeoTIFF configurations, graph CPU, memory, throughput, and IOPS tradeoffs, and write an HTML decision report from a copied HEC-RAS project. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/730_raster_processing_performance_profiling.ipynb) | N/A |

## 800s - Quality Assurance

| Notebook | Source | Runtime |
| --- | --- | --- |
| [800 - Quality Assurance with RasCheck](../notebooks/800_quality_assurance_rascheck.md)<br>This notebook demonstrates how to use the RasCheck module for validating HEC-RAS steady flow models using **multiple example projects** to show different validation scenarios. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/800_quality_assurance_rascheck.ipynb) | 17 s |
| [801 - Advanced Structure Validation with RasCheck](../notebooks/801_advanced_structure_validation.md)<br>This notebook demonstrates the **advanced structure validation features** added to RasCheck in December 2025: | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/801_advanced_structure_validation.ipynb) | 4 s |

## 900s - AORC & Gridded Precipitation

| Notebook | Source | Runtime |
| --- | --- | --- |
| [900 - AORC Precipitation for HEC-RAS Rain-on-Grid Models](../notebooks/900_aorc_precipitation.md)<br>This notebook demonstrates a complete workflow for using NOAA's Analysis of Record for Calibration (AORC) gridded precipitation data with HEC-RAS 2D rain-on-grid models, including data-driven simulation buffer selection based on observed... | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/900_aorc_precipitation.ipynb) | 5.7 min |
| [901 - AORC Precipitation Catalog for HEC-RAS Rain-on-Grid Models](../notebooks/901_aorc_precipitation_catalog.md)<br>This notebook demonstrates a complete workflow for using NOAA's Analysis of Record for Calibration (AORC) gridded precipitation data with HEC-RAS 2D rain-on-grid models. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/901_aorc_precipitation_catalog.ipynb) | 3.1 min |

## 910s - Gauge Data & Validation

| Notebook | Source | Runtime |
| --- | --- | --- |
| [910 - USGS Gauge Catalog Generation](../notebooks/910_usgs_gauge_catalog.md)<br>gauge, validation, forecast, and coastal boundary workflows | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/910_usgs_gauge_catalog.ipynb) | 7.3 min |
| [911 - USGS Gauge Data Integration for HEC-RAS](../notebooks/911_usgs_gauge_data_integration.md)<br>This notebook demonstrates how to integrate USGS gauge data with HEC-RAS models using the `ras_commander.usgs` submodule. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/911_usgs_gauge_data_integration.ipynb) | 32 s |
| [912 - USGS Real-Time Gauge Monitoring](../notebooks/912_usgs_real_time_monitoring.md)<br>Inspect a real model domain with live USGS station metadata and illustrate monitoring APIs; distinguish the refreshed map from historical monitoring outputs. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/912_usgs_real_time_monitoring.ipynb) | 2.8 min |
| [913 - Boundary Condition Generation from Live USGS Gauge Data](../notebooks/913_bc_generation_from_live_gauge.md)<br>This example demonstrates how to generate HEC-RAS boundary conditions from real-time USGS gauge data. We'll use the Bald Eagle Creek model and create a flow hydrograph boundary condition from live gauge readings with drainage area scaling. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/913_bc_generation_from_live_gauge.ipynb) | 3 s |
| [914 - Historical AORC Event Diagnostic Comparison with USGS Stage](../notebooks/914_historical_event_validation.md)<br>execute an archived 48-hour AORC rain-on-grid event under HEC-RAS 7.0, verify source precipitation through durable, temporary, and final HDFs, inspect runtime and hydraulic results, and compare timezone-correct USGS stage as a diagnostic rather than calibration validation | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/914_historical_event_validation.ipynb) | 35 s |
| [921 - USGS Study Package From Primitives](../notebooks/921_usgs_study_package_from_primitives.md)<br>This notebook demonstrates the composable primitives in `ras_commander.usgs` for USGS gauge study assembly. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/921_usgs_study_package_from_primitives.ipynb) | 13 s |
| [922 - Model Comparison with USGS Gauge Data](../notebooks/922_model_validation_with_usgs.md)<br>Compare delivered Kalamazoo HDF water levels with 276 matched USGS gauge observations; retain provenance, metrics, initialization error and calibration-comparison limits. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/922_model_validation_with_usgs.ipynb) | 9 s |

## 915s - Operational Forecast Sequence

| Notebook | Source | Runtime |
| --- | --- | --- |
| [915 - Operational Forecast Orchestration and Readiness](../notebooks/915_realtime_forecast_workflow.md)<br>build a deterministic timezone-explicit forecast-cycle manifest, inspect current public API signatures, and visually audit the executed HRRR, STOFS-3D, MRMS, and WPC component artifacts without claiming a duplicate model compute or independent format/version qualification | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/915_realtime_forecast_workflow.ipynb) | 2 s |
| [918 - HMS-RAS Coupled Forecast Execution](../notebooks/918_hms_ras_coupled_forecast.md)<br>illustrate the HMS-to-RAS handoff pattern with a synthetic outlet hydrograph and printed templates for HMS execution, inline or DSS boundary writes, plan-date alignment, and optional HEC-RAS execution; no coupled models are run | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/918_hms_ras_coupled_forecast.ipynb) | 11 s |
| [919 - Operational Forecast Cycling](../notebooks/919_operational_forecast_cycling.md)<br>compare four deterministic synthetic QPF cycles with routed flow and rating-curve stage estimates, plot crest convergence and flood-threshold exceedance, and dry-run RAS-ready cycle metadata with optional execution hooks | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/919_operational_forecast_cycling.ipynb) | 5 s |

## 916s - Forecast Inputs

| Notebook | Source | Runtime |
| --- | --- | --- |
| [916 - HRRR Forecast to HEC-RAS: Executed Rain-on-Grid Qualification](../notebooks/916_hrrr_precipitation_forecast.md)<br>reproduce an archived 8 August 2024 15Z HRRR event as 18 hourly native DSS grids, verify source-to-DSS-to-temporary-and-final-HDF forcing, compare no-rain and forecast hydraulics under HEC-RAS 7.0, and map localized convergence exceptions for manual review | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/916_hrrr_precipitation_forecast.ipynb) | 4.2 min |
| [917 - MRMS QPE Boundary-Hyetograph Hydraulic Comparison](../notebooks/917_mrms_precipitation_qpe.md)<br>inspect spatial DSS grids for two archived MRMS events, intentionally reduce each event to an area-average precipitation boundary, and compare HEC-RAS 7.0 baseline/event results with runtime, final-HDF, map, pump, figure, and animation QA; this is not global gridded-meteorology qualification | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/917_mrms_precipitation_qpe.ipynb) | 36.5 min |
| [923 - STOFS-3D Coastal Water Levels: Units and Datum](../notebooks/923_stofs3d_coastal_boundary.md)<br>Extract an archived NOAA station time series with explicit datum metadata, compare feet and meters, and distinguish source inspection from experimental stage authoring. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/923_stofs3d_coastal_boundary.ipynb) | 3 s |
| [924 - MRMS NetCDF Rain-on-Grid Validation](../notebooks/924_mrms_netcdf_rain_on_grid.md)<br>MRMS QPE workflows, including direct NetCDF rain-on-grid validation | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/924_mrms_netcdf_rain_on_grid.ipynb) | 59 s |
| [926 - WPC QPF DSS-to-HEC-RAS Rain-on-Grid Qualification](../notebooks/926_wpc_qpf_precipitation_forecast.md)<br>qualify a complete current WPC forecast through verified native-projection GRIB crops, 28 DSS grids, temporary and final HDF forcing, no-rain/event HEC-RAS 7.0 simulations, hydraulic response, mapped convergence exceptions, and explicit manual review | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/926_wpc_qpf_precipitation_forecast.ipynb) | 22 s |

## 920s - Terrain & Surfaces

| Notebook | Source | Runtime |
| --- | --- | --- |
| [920 - Creating a RAS Terrain with ras-commander](../notebooks/920_terrain_creation.md)<br>terrain and geometry surface workflows | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/920_terrain_creation.ipynb) | 12 s |
| [925 - Cross-Section Interpolation Surface](../notebooks/925_xs_interpolation_surface.md)<br>Build cross-section TIN interpolation surfaces from real geometry, write spatial review layers and optional rasters, and compare channel-only and full-extent surfaces. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/925_xs_interpolation_surface.ipynb) | 6 s |
| [930 - Terrain Modification Analysis](../notebooks/930_terrain_modification_analysis.md)<br>write and verify a channel terrain modification in the Bald Eagle Creek example, then use the optional GDAL bridge to report terrain extent and sample the modified profile and polygon elevation-volume curve; no baseline or modified hydraulic plans are run | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/930_terrain_modification_analysis.ipynb) | 15 s |
| [931 - Native RAS Mapper Terrain Export](../notebooks/931_native_rasmapper_terrain_export.md)<br>export a registered, stitched RAS Mapper terrain to one bounded and semantically validated GeoTIFF, then inspect its typed result, source inventory, receipt, grid alignment, and visual evidence | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/931_native_rasmapper_terrain_export.ipynb) | 3 s |

## 950s - eBFE Delivery

| Notebook | Source | Runtime |
| --- | --- | --- |
| [950 - Using eBFE Models: Spring Creek 2D Analysis](../notebooks/950_ebfe_spring_creek.md)<br>FEMA eBFE/BLE organization and validation | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/950_ebfe_spring_creek.ipynb) | 4 s |
| [951 - Using eBFE Models: North Galveston Bay HMS + RAS Integration](../notebooks/951_ebfe_north_galveston_bay.md)<br>Organize a compound North Galveston Bay HMS/RAS delivery and inspect its model paths; file discovery does not establish executable coupling. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/951_ebfe_north_galveston_bay.ipynb) | 3 s |
| [952 - Using eBFE Models: Upper Guadalupe Cascaded Watersheds](../notebooks/952_ebfe_upper_guadalupe_cascade.md)<br>This notebook demonstrates working with cascaded watershed models from FEMA eBFE/BLE database. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/952_ebfe_upper_guadalupe_cascade.ipynb) | 12 s |
| [953 - Using eBFE Models: Rio Hondo 1D Steady Collection](../notebooks/953_ebfe_rio_hondo_steady_collection.md)<br>This notebook demonstrates the Rio Hondo (`13060008`) eBFE/BLE 1D steady model collection. The delivery is different from the large 2D eBFE examples: it contains hundreds of small 1D steady HEC-RAS projects, and results HDF files are gen... | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/953_ebfe_rio_hondo_steady_collection.ipynb) | 9 s |
| [954 - Using eBFE Models: Lake Maurepas Validation](../notebooks/954_ebfe_lake_maurepas_validation.md)<br>This notebook validates the organized Lake Maurepas eBFE delivery format. It is intentionally scoped to the delivery-readiness gate: organize the source archive, confirm ras-commander can initialize the local HEC-RAS project, review the... | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/954_ebfe_lake_maurepas_validation.ipynb) | 3 s |
| [955 - Using eBFE Models: Tickfaw Results-Ready Validation](../notebooks/955_ebfe_tickfaw_validation.md)<br>This notebook validates the organized Tickfaw eBFE delivery as a full 2D example with source-provided result HDFs. It confirms local organization, reviews the saved ras-commander geometry-preprocessor evidence, and checks that plan resul... | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/955_ebfe_tickfaw_validation.ipynb) | 3 s |
| [956 - NextGen Hydrofabric Conflation Visual QA — Texas eBFE Shiloh Branch](../notebooks/956_hydrofabric_conflation_visual_qa.md)<br>Visually audits generic HEC-RAS-to-network conflation with the NextGen v2.2 adapter on the Texas Lower Colorado-Cummins SHILOH BRANCH model, including native flowpath and catchment IDs, candidate ranks, score components, explicit resolution states, HUC intersections, and cross-section measures. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/956_hydrofabric_conflation_visual_qa.ipynb) | 5 s |
| [957 - Using eBFE Models: Spring River Validation](../notebooks/957_ebfe_spring_river_validation.md)<br>This notebook validates the organized Spring River eBFE delivery as a results-ready HEC-RAS 6.1 example. It uses the shared delivery workspace, reviews the saved audit evidence, optionally executes a fresh geometry-preprocessor validatio... | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/957_ebfe_spring_river_validation.ipynb) | N/A |
| [958 - Model Sources: Unified Discovery, Download & Visualization](../notebooks/958_model_sources_showcase.md)<br>Discover and download representative models from several public catalogs, initialize each project, and optionally capture native RAS Mapper review images. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/958_model_sources_showcase.ipynb) | N/A |
| [959 - eBFE 2D Breakout Geometry Preparation](../notebooks/959_ebfe_2d_breakout_geometry_preparation.md)<br>Qualify and prepare a contained pure-2D HUC12 breakout from Upper Guadalupe 3 plan 08, with byte-identical unsteady cloning, geometry trimming/remeshing, parent terrain and inundation context, and unassigned parent-face flux review. | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/959_ebfe_2d_breakout_geometry_preparation.ipynb) | N/A |

## 960s - Cloud-Native Export

| Notebook | Source | Runtime |
| --- | --- | --- |
| [960 - Cloud-Native Geometry Export with ras2cng](../notebooks/960_cloud_native_geometry_export.md)<br>cloud-native export with `ras2cng` | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/960_cloud_native_geometry_export.ipynb) | N/A |
| [961 - Cloud-Native Results Export with ras2cng](../notebooks/961_cloud_native_results_export.md)<br>Export HEC-RAS simulation results to cloud-native GeoParquet, build interactive flood depth maps, and generate PMTiles for web deployment using [ras2cng](https://github.com/gpt-cmdr/ras2cng). | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/961_cloud_native_results_export.ipynb) | N/A |
| [962 - Cloud Optimized GeoTIFF Results Export with ras2cng](../notebooks/962_cloud_native_cog_results_export.md)<br>cloud-native export with `ras2cng` | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/962_cloud_native_cog_results_export.ipynb) | N/A |
