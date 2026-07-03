# Example Notebooks

These are the canonical, runnable examples for ras-commander. Each row links to the rendered documentation page and to the source `.ipynb` on GitHub. **Runtime** is the summed cell-execution wall time captured the last time the notebook was executed (`N/A` means the notebook was committed without execution outputs).

See [Example Projects](example-projects.md) for the CRS-valid source catalog and MapLibre review contract for ras2cng-exported model bundles.

!!! tip "New here? Start with the 100s."
    Run **100 → 101 → 110** for the core initialize → inspect → execute loop, then branch into the series that matches your work: **200s** geometry & calibration, **300s** unsteady & DSS, **400s** HDF results, **900s** data integration & forecasting.

*124 notebooks indexed - 112 with runtime data, 12 without.*

## 100s - Initialization & Execution

| Notebook | Source | Runtime |
| --- | --- | --- |
| [100 - Using RasExamples](../notebooks/100_using_ras_examples.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/100_using_ras_examples.ipynb) | 35 s |
| [101 - Project Initialization](../notebooks/101_project_initialization.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/101_project_initialization.ipynb) | 5 s |
| [102 - Multiple Project Operations](../notebooks/102_multiple_project_operations.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/102_multiple_project_operations.ipynb) | 2.2 min |
| [103 - Plan and Geometry Operations](../notebooks/103_plan_and_geometry_operations.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/103_plan_and_geometry_operations.ipynb) | 1.5 min |
| [104 - Plan Parameter Operations](../notebooks/104_plan_parameter_operations.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/104_plan_parameter_operations.ipynb) | 1.3 min |
| [110 - Single Plan Execution](../notebooks/110_single_plan_execution.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/110_single_plan_execution.ipynb) | 8.1 min |
| [111 - Executing Plan Sets](../notebooks/111_executing_plan_sets.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/111_executing_plan_sets.ipynb) | 3.0 min |
| [112 - Sequential Plan Execution](../notebooks/112_sequential_plan_execution.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/112_sequential_plan_execution.ipynb) | 3.3 min |
| [113 - Parallel Execution](../notebooks/113_parallel_execution.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/113_parallel_execution.ipynb) | 3.3 h |
| [114 - Parameter Permutation Sweeps with RasPermutation](../notebooks/114_parameter_permutation.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/114_parameter_permutation.ipynb) | 2.3 min |
| [115 - Real-Time Execution Monitoring with Callbacks](../notebooks/115_real_time_execution_monitoring.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/115_real_time_execution_monitoring.ipynb) | 1.4 min |
| [116 - HDF Output Options Read Benchmark](../notebooks/116_hdf_output_options_benchmark.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/116_hdf_output_options_benchmark.ipynb) | 25.6 min |
| [117 - Monte Carlo Uncertainty Analysis (Hardened API)](../notebooks/117_monte_carlo_uncertainty.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/117_monte_carlo_uncertainty.ipynb) | 11.8 min |
| [120 - Win32COM Automation](../notebooks/120_automating_ras_with_win32com.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/120_automating_ras_with_win32com.ipynb) | 13 s |
| [121 - HECRASController Profiles](../notebooks/121_legacy_hecrascontroller_and_rascontrol.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/121_legacy_hecrascontroller_and_rascontrol.ipynb) | 12.7 min |
| [122 - RASMapper Spatial Review](../notebooks/122_rasmapper_spatial_review.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/122_rasmapper_spatial_review.ipynb) | 1.1 min |
| [123 - RASMapper Geometry Layer Updates](../notebooks/123_rasmapper_geometry_layer_updates.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/123_rasmapper_geometry_layer_updates.ipynb) | 9.8 min |
| [124 - RASMapper Bank Lines](../notebooks/124_rasmapper_bank_lines.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/124_rasmapper_bank_lines.ipynb) | 44 s |
| [150 - Using results_df for Plan Results Summary](../notebooks/150_results_dataframe.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/150_results_dataframe.ipynb) | 1.1 min |

## 200s - Geometry & Calibration

| Notebook | Source | Runtime |
| --- | --- | --- |
| [201 - 1D Geometry File Parsing](../notebooks/201_1d_plaintext_geometry.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/201_1d_plaintext_geometry.ipynb) | 24 s |
| [202 - 2D Geometry File Parsing](../notebooks/202_2d_plaintext_geometry.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/202_2d_plaintext_geometry.ipynb) | 3.6 min |
| [203 - HTAB Parameter Optimization for Model Stability](../notebooks/203_htab_parameter_optimization.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/203_htab_parameter_optimization.ipynb) | 1.0 min |
| [204 - Culvert GIS Reconstruction and Hydraulic-Validity Checks (1D)](../notebooks/204_culvert_gis_validation.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/204_culvert_gis_validation.ipynb) | 14 s |
| [205 - Extract Cross Section XYZ Coordinates from Plain Text Geometry](../notebooks/205_extract_xs_xyz_from_geometry.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/205_extract_xs_xyz_from_geometry.ipynb) | 4 s |
| [206 - Structures and Metadata from Geometry Files](../notebooks/206_structures_and_metadata.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/206_structures_and_metadata.ipynb) | 4 s |
| [207 - Reference Lines and Points for 2D Calibration](../notebooks/207_reference_lines_and_points.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/207_reference_lines_and_points.ipynb) | 3 s |
| [208 - Bridge Method Comparison](../notebooks/208_bridge_method_comparison.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/208_bridge_method_comparison.ipynb) | 1.7 min |
| [209 - Culvert Authoring](../notebooks/209_culvert_authoring.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/209_culvert_authoring.ipynb) | 8 s |
| [210 - Cross-Section Interpolation Settings](../notebooks/210_xs_interpolation_settings.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/210_xs_interpolation_settings.ipynb) | 18 s |
| [211 - Final Manning's N and Infiltration Analysis](../notebooks/211_final_mannings_and_infiltration.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/211_final_mannings_and_infiltration.ipynb) | 3 s |
| [212 - NLCD Land Cover Layer Authoring for RASMapper](../notebooks/212_landcover_mannings_n_write.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/212_landcover_mannings_n_write.ipynb) | 38 s |
| [213 - Land Classification Polygon Authoring](../notebooks/213_land_classification_polygon_authoring.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/213_land_classification_polygon_authoring.ipynb) | 19 s |
| [214 - SA/2D Connection Authoring](../notebooks/214_connection_authoring.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/214_connection_authoring.ipynb) | 10 s |
| [215 - SA/2D Bridge Connection Authoring](../notebooks/215_sa2d_bridge_connection_authoring.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/215_sa2d_bridge_connection_authoring.ipynb) | 21 s |
| [216 - 1D Bridge Authoring](../notebooks/216_1d_bridge_authoring.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/216_1d_bridge_authoring.ipynb) | 4 s |
| [217 - 1D Cross-Section Levee Authoring](../notebooks/217_1d_levee_authoring.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/217_1d_levee_authoring.ipynb) | 2.4 min |
| [218 - Infiltration Base Override Authoring](../notebooks/218_infiltration_base_override_authoring.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/218_infiltration_base_override_authoring.ipynb) | 4 s |
| [219 - 1D Bridge Cross-Section Plotting with Deck/Pier Overlay](../notebooks/219_1d_bridge_xs_plotting.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/219_1d_bridge_xs_plotting.ipynb) | 5 s |
| [219 - Manning's n Region Polygon Authoring](../notebooks/219_mannings_region_polygon_authoring.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/219_mannings_region_polygon_authoring.ipynb) | 3 s |
| [220 - Kalamazoo River Calibration Workflow](../notebooks/220_calibration_workflow.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/220_calibration_workflow.ipynb) | 8 s |
| [221 - 1D Manning's N Calibration Workflow](../notebooks/221_calibration_1d_workflow.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/221_calibration_1d_workflow.ipynb) | 36.6 min |
| [222 - Steady Flow Calibration](../notebooks/222_steady_flow_calibration.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/222_steady_flow_calibration.ipynb) | 39 s |
| [223 - Steady Floodway Encroachment](../notebooks/223_steady_floodway_encroachment.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/223_steady_floodway_encroachment.ipynb) | 17 s |
| [224 - Steady Flow Authoring](../notebooks/224_steady_flow_authoring.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/224_steady_flow_authoring.ipynb) | 12 s |
| [225 - Fixing Blocked Obstruction Overlaps with RasFixit](../notebooks/225_fixit_blocked_obstructions.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/225_fixit_blocked_obstructions.ipynb) | 7 s |
| [226 - 2D Connection Culvert Invert Validation (Terrain Cell Minimum)](../notebooks/226_2d_connection_culvert_invert_validation.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/226_2d_connection_culvert_invert_validation.ipynb) | 32 s |
| [227 - Authoring a 2D Connection Culvert (`Connection Culv=`)](../notebooks/227_2d_connection_culvert_authoring.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/227_2d_connection_culvert_authoring.ipynb) | 22 s |
| [228 - Manning's n from NLCD Validation](../notebooks/228_mannings_n_from_nlcd.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/228_mannings_n_from_nlcd.ipynb) | 2.3 min |
| [230 - 2D Mesh Cell-Size Sensitivity for Sediment Transport](../notebooks/230_mesh_sensitivity_analysis.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/230_mesh_sensitivity_analysis.ipynb) | 6.9 min |
| [231 - Pipe Network Mesh Generation](../notebooks/231_pipe_network_mesh_generation.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/231_pipe_network_mesh_generation.ipynb) | 10 s |
| [232 - 2D Mesh Cell-Size Sensitivity for Sediment Transport - Second Case: Weise Flume](../notebooks/232_weise_2d_sediment_mesh_sensitivity.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/232_weise_2d_sediment_mesh_sensitivity.ipynb) | 16.7 min |

## 300s - Unsteady Flow & DSS

| Notebook | Source | Runtime |
| --- | --- | --- |
| [300 - Unsteady Flow Operations](../notebooks/300_unsteady_flow_operations.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/300_unsteady_flow_operations.ipynb) | 26 s |
| [301 - Flow Hydrograph Optimization](../notebooks/301_flow_hydrograph_optimization.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/301_flow_hydrograph_optimization.ipynb) | 1.0 min |
| [310 - DSS Boundary Extraction](../notebooks/310_dss_boundary_extraction.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/310_dss_boundary_extraction.ipynb) | 5 s |
| [311 - 2D Floodway Encroachment](../notebooks/311_2d_floodway_encroachment.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/311_2d_floodway_encroachment.ipynb) | 1.2 min |
| [312 - Boundary DataFrame Enhancement: QMult, QMin, and DSS Path Parsing](../notebooks/312_boundary_df_qmult_dss_paths.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/312_boundary_df_qmult_dss_paths.ipynb) | 1.2 min |
| [313 - HMS-to-RAS Boundary Condition Matching](../notebooks/313_hms_to_ras_boundary_matching.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/313_hms_to_ras_boundary_matching.ipynb) | 5 s |
| [314 - Breakline-Derived Reference Lines And USGS Gauge Points](../notebooks/314_reference_line_generation.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/314_reference_line_generation.ipynb) | 3.3 min |
| [315 - 2D Computation Options](../notebooks/315_2d_computation_options.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/315_2d_computation_options.ipynb) | 2.4 min |
| [316 - Terrain Modifications: High-Ground and Polygon Writer Validation](../notebooks/316_terrain_modifications.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/316_terrain_modifications.ipynb) | 2.7 min |
| [317 - Restart File Output and Warm-Start Settings](../notebooks/317_restart_file_settings.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/317_restart_file_settings.ipynb) | 24 s |
| [318 - Validating DSS File Paths and Data Availability](../notebooks/318_validating_dss_paths.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/318_validating_dss_paths.ipynb) | 4 s |
| [319 - Post-fire debris-flow 2D modeling, built from scratch (non-Newtonian)](../notebooks/319_post_fire_debris_flow_nonnewtonian.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/319_post_fire_debris_flow_nonnewtonian.ipynb) | N/A |
| [320 - 1D Boundary Condition Visualization](../notebooks/320_1d_boundary_condition_visualization.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/320_1d_boundary_condition_visualization.ipynb) | 5 s |

## 400s - HDF Results Extraction

| Notebook | Source | Runtime |
| --- | --- | --- |
| [400 - 1D HDF Data Extraction](../notebooks/400_1d_hdf_data_extraction.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/400_1d_hdf_data_extraction.ipynb) | 21 s |
| [401 - Steady Flow Analysis](../notebooks/401_steady_flow_analysis.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/401_steady_flow_analysis.ipynb) | 5.8 min |
| [410 - 2D HDF Data Extraction](../notebooks/410_2d_hdf_data_extraction.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/410_2d_hdf_data_extraction.ipynb) | 5.4 min |
| [411 - Pipes and Pumps](../notebooks/411_2d_hdf_pipes_and_pumps.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/411_2d_hdf_pipes_and_pumps.ipynb) | 3.3 min |
| [412 - 2D Face Data Extraction](../notebooks/412_2d_detail_face_data_extraction.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/412_2d_detail_face_data_extraction.ipynb) | 3.3 min |
| [413 - Profile Line Flow Extraction](../notebooks/413_profile_line_flow_extraction.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/413_profile_line_flow_extraction.ipynb) | 3 s |
| [414 - Depth-Varying Manning's n for HEC-RAS 2D Models](../notebooks/414_depth_varying_mannings_n.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/414_depth_varying_mannings_n.ipynb) | 16.8 min |
| [415 - 2D Spatial Result Queries with HdfResultsQuery](../notebooks/415_2d_spatial_result_queries.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/415_2d_spatial_result_queries.ipynb) | 5.5 min |
| [416 - 2D Velocity Profile Line Extraction](../notebooks/416_2d_velocity_profile_line.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/416_2d_velocity_profile_line.ipynb) | 5 s |
| [420 - Dam Breach Results](../notebooks/420_breach_results_extraction.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/420_breach_results_extraction.ipynb) | 2.9 min |
| [430 - 1D Channel Capacity Analysis](../notebooks/430_1d_channel_capacity_analysis.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/430_1d_channel_capacity_analysis.ipynb) | 1.3 min |

## 500s - Remote Execution

| Notebook | Source | Runtime |
| --- | --- | --- |
| [500 - Remote Parallel Execution with PsExec](../notebooks/500_remote_execution_psexec.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/500_remote_execution_psexec.ipynb) | 8.7 min |
| [510 - Linux HEC-RAS Execution](../notebooks/510_linux_execution.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/510_linux_execution.ipynb) | N/A |
| [560 - Modified Puls Routing Extraction from HEC-RAS 2D Models](../notebooks/560_modpuls_routing_extraction.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/560_modpuls_routing_extraction.ipynb) | 3.5 min |

## 600s - Floodplain Mapping

| Notebook | Source | Runtime |
| --- | --- | --- |
| [600 - Floodplain Mapping via GUI Automation](../notebooks/600_floodplain_mapping_gui.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/600_floodplain_mapping_gui.ipynb) | 19.5 min |
| [601 - Floodplain Mapping via RasProcess CLI](../notebooks/601_floodplain_mapping_rasprocess.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/601_floodplain_mapping_rasprocess.ipynb) | 6.0 min |
| [610 - Generate Fluvial Pluvial Delineations using Max WSE Arrival Time](../notebooks/610_generate_fluvial_pluvial_delineations_max_wse_arrival_time.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/610_generate_fluvial_pluvial_delineations_max_wse_arrival_time.ipynb) | 1.0 h |
| [611 - Validating RAS Mapper Layers and Terrain Files](../notebooks/611_validating_map_layers.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/611_validating_map_layers.ipynb) | 9 s |

## 700s - Sensitivity & Precipitation

| Notebook | Source | Runtime |
| --- | --- | --- |
| [700 - Core Sensitivity Testing with results_df](../notebooks/700_core_sensitivity.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/700_core_sensitivity.ipynb) | 16.3 min |
| [701 - Version Benchmarking and Core Scaling (HEC-RAS 6.0, 6.3.1, 6.6, 7.0)](../notebooks/701_benchmarking_versions_6.1_to_6.6.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/701_benchmarking_versions_6.1_to_6.6.ipynb) | 5.4 h |
| [710 - Manning's n Bulk Sensitivity Analysis](../notebooks/710_mannings_sensitivity_bulk_analysis.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/710_mannings_sensitivity_bulk_analysis.ipynb) | N/A |
| [711 - One-at-a-Time (OAT) Manning's n Sensitivity Analysis](../notebooks/711_mannings_sensitivity_multi_interval.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/711_mannings_sensitivity_multi_interval.ipynb) | N/A |
| [720 - Precipitation Hyetograph Generation - Complete Method Comparison](../notebooks/720_precipitation_methods_comprehensive.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/720_precipitation_methods_comprehensive.ipynb) | 16 s |
| [721 - Precipitation Hyetograph Comparison](../notebooks/721_precipitation_hyetograph_comparison.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/721_precipitation_hyetograph_comparison.ipynb) | 44.1 min |
| [722 - Gridded Precipitation for Rain-on-Grid 2D Modeling](../notebooks/722_gridded_precipitation_atlas14.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/722_gridded_precipitation_atlas14.ipynb) | N/A |
| [723 - StormGenerator Alternating Block Method - Independent Textbook Validation](../notebooks/723_storm_generator_abm_validation.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/723_storm_generator_abm_validation.ipynb) | 5 s |
| [725 - Atlas 14 Spatial Variance Analysis](../notebooks/725_atlas14_spatial_variance.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/725_atlas14_spatial_variance.ipynb) | 1.3 min |
| [726 - Gridded ABM Hyetograph Generation](../notebooks/726_abm_hyetograph_grid.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/726_abm_hyetograph_grid.ipynb) | N/A |

## 800s - Quality Assurance

| Notebook | Source | Runtime |
| --- | --- | --- |
| [800 - Quality Assurance with RasCheck](../notebooks/800_quality_assurance_rascheck.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/800_quality_assurance_rascheck.ipynb) | 17 s |
| [801 - Advanced Structure Validation with RasCheck](../notebooks/801_advanced_structure_validation.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/801_advanced_structure_validation.ipynb) | 4 s |

## 900s - AORC & Gridded Precipitation

| Notebook | Source | Runtime |
| --- | --- | --- |
| [900 - AORC Precipitation for HEC-RAS Rain-on-Grid Models](../notebooks/900_aorc_precipitation.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/900_aorc_precipitation.ipynb) | 3.1 h |
| [901 - AORC Precipitation Catalog for HEC-RAS Rain-on-Grid Models](../notebooks/901_aorc_precipitation_catalog.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/901_aorc_precipitation_catalog.ipynb) | 1.5 min |

## 910s - Gauge Data & Validation

| Notebook | Source | Runtime |
| --- | --- | --- |
| [910 - Example 910: USGS Gauge Catalog Generation](../notebooks/910_usgs_gauge_catalog.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/910_usgs_gauge_catalog.ipynb) | 7.3 min |
| [911 - USGS Gauge Data Integration for HEC-RAS](../notebooks/911_usgs_gauge_data_integration.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/911_usgs_gauge_data_integration.ipynb) | 32 s |
| [912 - USGS Real-Time Gauge Monitoring](../notebooks/912_usgs_real_time_monitoring.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/912_usgs_real_time_monitoring.ipynb) | 2.8 min |
| [913 - Boundary Condition Generation from Live USGS Gauge Data](../notebooks/913_bc_generation_from_live_gauge.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/913_bc_generation_from_live_gauge.ipynb) | 3 s |
| [914 - Historical Event Validation with AORC Precipitation and USGS Gauges](../notebooks/914_historical_event_validation.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/914_historical_event_validation.ipynb) | 35 s |
| [921 - USGS Study Package From Primitives](../notebooks/921_usgs_study_package_from_primitives.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/921_usgs_study_package_from_primitives.ipynb) | 13 s |
| [922 - Model Validation with USGS Gauge Data](../notebooks/922_model_validation_with_usgs.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/922_model_validation_with_usgs.ipynb) | 1.8 min |

## 915s - Operational Forecast Sequence

| Notebook | Source | Runtime |
| --- | --- | --- |
| [915 - Real-Time Flood Forecast Workflow](../notebooks/915_realtime_forecast_workflow.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/915_realtime_forecast_workflow.ipynb) | 2.5 min |
| [918 - HMS-RAS Coupled Forecast Execution](../notebooks/918_hms_ras_coupled_forecast.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/918_hms_ras_coupled_forecast.ipynb) | 11 s |
| [919 - Operational Forecast Cycling](../notebooks/919_operational_forecast_cycling.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/919_operational_forecast_cycling.ipynb) | 5 s |

## 916s - Forecast Inputs

| Notebook | Source | Runtime |
| --- | --- | --- |
| [916 - HRRR Precipitation Forecast Download](../notebooks/916_hrrr_precipitation_forecast.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/916_hrrr_precipitation_forecast.ipynb) | 5.6 min |
| [917 - MRMS QPE Rain-on-Grid Workflow](../notebooks/917_mrms_precipitation_qpe.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/917_mrms_precipitation_qpe.ipynb) | 46.5 min |
| [923 - STOFS-3D Coastal Boundary Integration](../notebooks/923_stofs3d_coastal_boundary.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/923_stofs3d_coastal_boundary.ipynb) | 1.3 min |
| [924 - MRMS NetCDF Rain-on-Grid Validation](../notebooks/924_mrms_netcdf_rain_on_grid.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/924_mrms_netcdf_rain_on_grid.ipynb) | N/A |

## 920s - Terrain & Surfaces

| Notebook | Source | Runtime |
| --- | --- | --- |
| [920 - RAS Terrain Creation](../notebooks/920_terrain_creation.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/920_terrain_creation.ipynb) | 2.0 h |
| [925 - Cross-Section Interpolation Surface](../notebooks/925_xs_interpolation_surface.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/925_xs_interpolation_surface.ipynb) | 6 s |
| [930 - Terrain Modification Analysis](../notebooks/930_terrain_modification_analysis.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/930_terrain_modification_analysis.ipynb) | 15 s |

## 950s - eBFE Delivery

| Notebook | Source | Runtime |
| --- | --- | --- |
| [950 - Using eBFE Models: Spring Creek 2D Analysis](../notebooks/950_ebfe_spring_creek.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/950_ebfe_spring_creek.ipynb) | 4 s |
| [951 - Using eBFE Models: North Galveston Bay HMS + RAS Integration](../notebooks/951_ebfe_north_galveston_bay.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/951_ebfe_north_galveston_bay.ipynb) | 3 s |
| [952 - Using eBFE Models: Upper Guadalupe Cascaded Watersheds](../notebooks/952_ebfe_upper_guadalupe_cascade.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/952_ebfe_upper_guadalupe_cascade.ipynb) | 12 s |
| [953 - Using eBFE Models: Rio Hondo 1D Steady Collection](../notebooks/953_ebfe_rio_hondo_steady_collection.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/953_ebfe_rio_hondo_steady_collection.ipynb) | 9 s |
| [954 - Using eBFE Models: Lake Maurepas Validation](../notebooks/954_ebfe_lake_maurepas_validation.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/954_ebfe_lake_maurepas_validation.ipynb) | 3 s |
| [955 - Using eBFE Models: Tickfaw Results-Ready Validation](../notebooks/955_ebfe_tickfaw_validation.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/955_ebfe_tickfaw_validation.ipynb) | 3 s |
| [957 - Using eBFE Models: Spring River Validation](../notebooks/957_ebfe_spring_river_validation.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/957_ebfe_spring_river_validation.ipynb) | N/A |
| [958 - Model Sources: Unified Discovery, Download & Visualization](../notebooks/958_model_sources_showcase.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/958_model_sources_showcase.ipynb) | N/A |

## 960s - Cloud-Native Export

| Notebook | Source | Runtime |
| --- | --- | --- |
| [960 - Cloud-Native Geometry Export with ras2cng](../notebooks/960_cloud_native_geometry_export.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/960_cloud_native_geometry_export.ipynb) | N/A |
| [961 - Cloud-Native Results Export with ras2cng](../notebooks/961_cloud_native_results_export.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/961_cloud_native_results_export.ipynb) | N/A |
| [962 - Cloud Optimized GeoTIFF Results Export with ras2cng](../notebooks/962_cloud_native_cog_results_export.md) | [.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/962_cloud_native_cog_results_export.ipynb) | N/A |
