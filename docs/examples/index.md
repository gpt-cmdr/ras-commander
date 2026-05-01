# Example Notebooks


The repository currently ships **92 canonical notebooks** under `examples/`.
 under `examples/`.
This overview tracks the live notebook inventory in git. Executed copies such as
`*_executed.ipynb` and local `_test_*.py` helpers are intentionally excluded.

!!! note
    The published docs track notebook inventory and source links. Rendered
    per-notebook markdown pages are not checked into this repository, so the
    canonical source of truth is the `examples/` tree itself.

## Running Examples Locally

```bash
git clone https://github.com/gpt-cmdr/ras-commander.git
cd ras-commander
pip install -e .
pip install jupyter rasterio pyproj
jupyter notebook examples/
```

## Notebook Families

| Family | Current focus |
|--------|---------------|
| `100s` | project initialization, execution control, parameter sweeps, RASMapper review, results summaries |
| `200s` | plaintext geometry parsing, structures, calibration setup, mesh generation |
| `300s` | unsteady files, DSS workflows, HMS-to-RAS matching, reference-line generation, boundary visualization |
| `400s` | 1D and 2D HDF extraction, reference-line queries, breach and channel-capacity analysis |
| `500s` | remote, Linux, and ModPuls execution workflows |
| `600s` | floodplain mapping, fluvial-pluvial analysis, map-layer validation |
| `700s` | sensitivity testing, benchmarking, Atlas 14, and gridded precipitation workflows |
| `800s` | RasCheck and structure-validation QA workflows |
| `900s` | AORC, USGS, forecasting, STOFS-3D, terrain creation, and terrain modification |
| `950s` | eBFE delivery organization and validation |
| `960s` | cloud-native geometry and results export |

## Drift-Sensitive Notebooks

These are the notebooks most directly tied to the April 2026 docs-drift sweep.

| Notebook | Why it matters |
|----------|----------------|
| [122_rasmapper_spatial_review.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/122_rasmapper_spatial_review.ipynb) | Canonical RASMapper spatial review, screenshot capture, and evidence-bundle workflow |
| [123_rasmapper_geometry_layer_updates.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/123_rasmapper_geometry_layer_updates.ipynb) | Mutation-backed RASMapper geometry-layer update workflow |
| [150_results_dataframe.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/150_results_dataframe.ipynb) | Current `results_df` / lightweight HDF summary workflow |
| [212_landcover_mannings_n_write.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/212_landcover_mannings_n_write.ipynb) | HDF geometry association QA and land-cover update workflow |
| [611_validating_map_layers.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/611_validating_map_layers.ipynb) | RASMapper layer and HDF asset validation |
| [920_terrain_creation.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/920_terrain_creation.ipynb) | HEC-RAS terrain tutorial workflow: single-raster terrain, USGS 3DEP terrain, multi-source priority ordering, RASMapper registration, and geometry association |
| [950_ebfe_spring_creek.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/950_ebfe_spring_creek.ipynb) through [957_ebfe_spring_river_validation.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/957_ebfe_spring_river_validation.ipynb) | Current eBFE delivery-validation notebook set |
| [960_cloud_native_geometry_export.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/960_cloud_native_geometry_export.ipynb) through [962_cloud_native_cog_results_export.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/962_cloud_native_cog_results_export.ipynb) | Current cloud-native export workflow family |

## Current Canonical Inventory

### 100s

`100_using_ras_examples.ipynb`, `101_project_initialization.ipynb`,
`102_multiple_project_operations.ipynb`,
`103_plan_and_geometry_operations.ipynb`,
`104_plan_parameter_operations.ipynb`, `110_single_plan_execution.ipynb`,
`111_executing_plan_sets.ipynb`, `112_sequential_plan_execution.ipynb`,
`113_parallel_execution.ipynb`, `114_parameter_permutation.ipynb`,
`115_real_time_execution_monitoring.ipynb`,
`116_hdf_output_options_benchmark.ipynb`,
`120_automating_ras_with_win32com.ipynb`,
`121_legacy_hecrascontroller_and_rascontrol.ipynb`,
`122_rasmapper_spatial_review.ipynb`,
`123_rasmapper_geometry_layer_updates.ipynb`,
`150_results_dataframe.ipynb`

### 200s

`201_1d_plaintext_geometry.ipynb`, `202_2d_plaintext_geometry.ipynb`,
`203_htab_parameter_optimization.ipynb`,
`205_extract_xs_xyz_from_geometry.ipynb`,
`206_structures_and_metadata.ipynb`,
`207_reference_lines_and_points.ipynb`,
`208_bridge_method_comparison.ipynb`,
`209_culvert_authoring.ipynb`,
`210_fixit_blocked_obstructions.ipynb`,
`211_final_mannings_and_infiltration.ipynb`,
`212_landcover_mannings_n_write.ipynb`,
`220_calibration_workflow.ipynb`,
`221_calibration_1d_workflow.ipynb`,
`222_steady_flow_calibration.ipynb`,
`230_mesh_sensitivity_analysis.ipynb`,
`231_pipe_network_mesh_generation.ipynb`

### 300s

`300_unsteady_flow_operations.ipynb`,
`301_flow_hydrograph_optimization.ipynb`,
`310_dss_boundary_extraction.ipynb`,
`311_validating_dss_paths.ipynb`,
`312_boundary_df_qmult_dss_paths.ipynb`,
`313_hms_to_ras_boundary_matching.ipynb`,
`314_reference_line_generation.ipynb`,
`314_restart_file_settings.ipynb`,
`320_1d_boundary_condition_visualization.ipynb`

### 400s

`400_1d_hdf_data_extraction.ipynb`, `401_steady_flow_analysis.ipynb`,
`410_2d_hdf_data_extraction.ipynb`,
`411_2d_hdf_pipes_and_pumps.ipynb`,
`412_2d_detail_face_data_extraction.ipynb`,
`413_profile_line_flow_extraction.ipynb`,
`415_2d_spatial_result_queries.ipynb`,
`420_breach_results_extraction.ipynb`,
`430_1d_channel_capacity_analysis.ipynb`

### 500s

`500_remote_execution_psexec.ipynb`, `510_linux_execution.ipynb`,
`560_modpuls_routing_extraction.ipynb`

### 600s

`600_floodplain_mapping_gui.ipynb`,
`601_floodplain_mapping_rasprocess.ipynb`,
`610_fluvial_pluvial_delineation.ipynb`,
`611_validating_map_layers.ipynb`

### 700s

`700_core_sensitivity.ipynb`, `701_benchmarking_versions_6.1_to_6.6.ipynb`,
`710_mannings_sensitivity_bulk_analysis.ipynb`,
`711_mannings_sensitivity_multi_interval.ipynb`,
`720_precipitation_methods_comprehensive.ipynb`,
`721_Precipitation_Hyetograph_Comparison.ipynb`,
`722_gridded_precipitation_atlas14.ipynb`,
`725_atlas14_spatial_variance.ipynb`,
`726_abm_hyetograph_grid.ipynb`

### 800s

`800_quality_assurance_rascheck.ipynb`,
`801_advanced_structure_validation.ipynb`

### 900s

`900_aorc_precipitation.ipynb`, `901_aorc_precipitation_catalog.ipynb`,
`910_usgs_gauge_catalog.ipynb`,
`911_usgs_gauge_data_integration.ipynb`,
`911a_usgs_study_package_from_primitives.ipynb`,
`912_usgs_real_time_monitoring.ipynb`,
`913_bc_generation_from_live_gauge.ipynb`,
`914_historical_event_validation.ipynb`,
`914_model_validation_with_usgs.ipynb`,
`915_realtime_forecast_workflow.ipynb`,
`916_hrrr_precipitation_forecast.ipynb`,
`917_stofs3d_coastal_boundary.ipynb`,
`918_hms_ras_coupled_forecast.ipynb`,
`919_operational_forecast_cycling.ipynb`, `920_terrain_creation.ipynb`,
`930_terrain_modification_analysis.ipynb`

### 950s

`950_ebfe_spring_creek.ipynb`,
`951_ebfe_north_galveston_bay.ipynb`,
`952_ebfe_upper_guadalupe_cascade.ipynb`,
`953_ebfe_rio_hondo_steady_collection.ipynb`,
`954_ebfe_lake_maurepas_validation.ipynb`,
`955_ebfe_tickfaw_validation.ipynb`,
`957_ebfe_spring_river_validation.ipynb`

### 960s

`960_cloud_native_geometry_export.ipynb`,
`961_cloud_native_results_export.ipynb`,
`962_cloud_native_cog_results_export.ipynb`

## Using Notebooks as Reference Workflows

- Use `examples/` as the live source of truth for runnable workflows.
- Use [Project Initialization](../getting-started/project-initialization.md) and
  [DataFrame Reference](../reference/dataframe-reference.md) when you need the
  stable API surface behind the notebooks.
- Use [Spatial Data & RASMapper](../user-guide/spatial-data.md) for the public
  RASMapper workflow narrative behind notebooks `122`, `123`, `611`, and `920`.
