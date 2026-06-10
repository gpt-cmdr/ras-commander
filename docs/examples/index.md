# Example Notebooks

The repository ships **109 canonical notebooks** under `examples/`. Each notebook
is a self-contained, executable workflow using `RasExamples` for reproducible data.
Notebooks are pre-converted to Markdown at documentation build time; stored outputs
are what appear on these pages, so execute locally before committing.

## Running Examples Locally

```bash
git clone https://github.com/gpt-cmdr/ras-commander.git
cd ras-commander
pip install -e .
pip install jupyter
jupyter notebook examples/
```

## Current Canonical Inventory

### 100s — Initialization & Execution

`100_using_ras_examples.ipynb`, `101_project_initialization.ipynb`,
`102_multiple_project_operations.ipynb`,
`103_plan_and_geometry_operations.ipynb`,
`104_plan_parameter_operations.ipynb`, `110_single_plan_execution.ipynb`,
`111_executing_plan_sets.ipynb`, `112_sequential_plan_execution.ipynb`,
`113_parallel_execution.ipynb`, `114_parameter_permutation.ipynb`,
`115_real_time_execution_monitoring.ipynb`,
`116_hdf_output_options_benchmark.ipynb`,
`116_monte_carlo_uncertainty.ipynb`,
`120_automating_ras_with_win32com.ipynb`,
`121_legacy_hecrascontroller_and_rascontrol.ipynb`,
`122_rasmapper_spatial_review.ipynb`,
`123_rasmapper_geometry_layer_updates.ipynb`,
`124_rasmapper_bank_lines.ipynb`,
`150_results_dataframe.ipynb`

### 200s — Geometry & Calibration

`201_1d_plaintext_geometry.ipynb`, `202_2d_plaintext_geometry.ipynb`,
`203_htab_parameter_optimization.ipynb`,
`205_extract_xs_xyz_from_geometry.ipynb`,
`206_structures_and_metadata.ipynb`,
`207_reference_lines_and_points.ipynb`,
`208_bridge_method_comparison.ipynb`,
`209_culvert_authoring.ipynb`,
`210_xs_interpolation_settings.ipynb`,
`211_final_mannings_and_infiltration.ipynb`,
`211_fixit_blocked_obstructions.ipynb`,
`212_landcover_mannings_n_write.ipynb`,
`213_land_classification_polygon_authoring.ipynb`,
`214_connection_authoring.ipynb`,
`215_sa2d_bridge_connection_authoring.ipynb`,
`216_1d_bridge_authoring.ipynb`,
`217_1d_levee_authoring.ipynb`,
`218_infiltration_base_override_authoring.ipynb`,
`219_1d_bridge_xs_plotting.ipynb`,
`220_calibration_workflow.ipynb`,
`221_calibration_1d_workflow.ipynb`,
`222_steady_flow_calibration.ipynb`,
`223_steady_floodway_encroachment.ipynb`,
`224_steady_flow_authoring.ipynb`,
`230_mesh_sensitivity_analysis.ipynb`,
`231_pipe_network_mesh_generation.ipynb`,
`232_weise_2d_sediment_mesh_sensitivity.ipynb`

### 300s — Unsteady & DSS

`300_unsteady_flow_operations.ipynb`,
`301_flow_hydrograph_optimization.ipynb`,
`310_dss_boundary_extraction.ipynb`,
`311_2d_floodway_encroachment.ipynb`,
`312_boundary_df_qmult_dss_paths.ipynb`,
`313_hms_to_ras_boundary_matching.ipynb`,
`314_reference_line_generation.ipynb`,
`315_2d_computation_options.ipynb`,
`315_validating_dss_paths.ipynb`,
`316_terrain_modifications.ipynb`,
`317_restart_file_settings.ipynb`,
`320_1d_boundary_condition_visualization.ipynb`

### 400s — HDF Results

`400_1d_hdf_data_extraction.ipynb`, `401_steady_flow_analysis.ipynb`,
`410_2d_hdf_data_extraction.ipynb`,
`411_2d_hdf_pipes_and_pumps.ipynb`,
`412_2d_detail_face_data_extraction.ipynb`,
`413_profile_line_flow_extraction.ipynb`,
`414_depth_varying_mannings_n.ipynb`,
`415_2d_spatial_result_queries.ipynb`,
`416_2d_velocity_profile_line.ipynb`,
`420_breach_results_extraction.ipynb`,
`430_1d_channel_capacity_analysis.ipynb`

### 500s — Remote Execution

`500_remote_execution_psexec.ipynb`, `510_linux_execution.ipynb`,
`560_modpuls_routing_extraction.ipynb`

### 600s — Floodplain Mapping

`600_floodplain_mapping_gui.ipynb`,
`601_floodplain_mapping_rasprocess.ipynb`,
`610_fluvial_pluvial_delineation.ipynb`,
`611_validating_map_layers.ipynb`

### 700s — Sensitivity & Precipitation

`700_core_sensitivity.ipynb`, `701_benchmarking_versions_6.1_to_6.6.ipynb`,
`710_mannings_sensitivity_bulk_analysis.ipynb`,
`711_mannings_sensitivity_multi_interval.ipynb`,
`720_precipitation_methods_comprehensive.ipynb`,
`721_Precipitation_Hyetograph_Comparison.ipynb`,
`722_gridded_precipitation_atlas14.ipynb`,
`723_storm_generator_abm_validation.ipynb`,
`725_atlas14_spatial_variance.ipynb`,
`726_abm_hyetograph_grid.ipynb`

### 800s — Quality Assurance

`800_quality_assurance_rascheck.ipynb`,
`801_advanced_structure_validation.ipynb`

### 900s — Data Integration

`900_aorc_precipitation.ipynb`, `901_aorc_precipitation_catalog.ipynb`,
`910_usgs_gauge_catalog.ipynb`,
`911_usgs_gauge_data_integration.ipynb`,
`911a_usgs_study_package_from_primitives.ipynb`,
`912_usgs_real_time_monitoring.ipynb`,
`913_bc_generation_from_live_gauge.ipynb`,
`914_historical_event_validation.ipynb`,
`915_realtime_forecast_workflow.ipynb`,
`916_hrrr_precipitation_forecast.ipynb`,
`917_mrms_precipitation_qpe.ipynb`,
`918_hms_ras_coupled_forecast.ipynb`,
`918_model_validation_with_usgs.ipynb`,
`919_operational_forecast_cycling.ipynb`,
`919_stofs3d_coastal_boundary.ipynb`,
`920_terrain_creation.ipynb`,
`925_xs_interpolation_surface.ipynb`,
`930_terrain_modification_analysis.ipynb`

### 950s — eBFE Delivery

`950_ebfe_spring_creek.ipynb`,
`951_ebfe_north_galveston_bay.ipynb`,
`952_ebfe_upper_guadalupe_cascade.ipynb`,
`953_ebfe_rio_hondo_steady_collection.ipynb`,
`954_ebfe_lake_maurepas_validation.ipynb`,
`955_ebfe_tickfaw_validation.ipynb`,
`957_ebfe_spring_river_validation.ipynb`,
`958_model_sources_showcase.ipynb`

### 960s — Cloud-Native Export

`960_cloud_native_geometry_export.ipynb`,
`961_cloud_native_results_export.ipynb`,
`962_cloud_native_cog_results_export.ipynb`
