# RASMapper display and spatial review

Use `RasMap` to select geometry and result layers, set visibility and view bounds,
and capture review evidence. Visibility and rendering changes are persisted in
`.rasmap`; HDF feature readers supply model bounds and feature inventories.

| Task | Input | Output |
|---|---|---|
| Layer and feature discovery | Project and exact geometry/layer selector | Lists or DataFrames |
| Visibility and terrain display | Layer selector and display options | Updated XML; Boolean or changed-entry count |
| View and zoom | Explicit bounds or HDF feature selector | View/bounds dictionary |
| Open/capture/close | Project and optionally an owned process ID | Process handle, optional PNG path, closed-window count |
| Screenshot gallery / review package | Projects and output directory | Gallery records or review-bundle dictionary |

Screenshots require Windows GUI facilities and a visible RASMapper window.
Prefer the process ID returned by `open_rasmapper()` when capturing or closing
that window. `screenshot_model()` temporarily configures display layers and
restores its `.rasmap` backup after capture. Read each method's return value;
an absent screenshot is not successful visual evidence.

Examples with retained outputs: [122 — spatial review](../../notebooks/122_rasmapper_spatial_review.md),
[123 — geometry layer updates](../../notebooks/123_rasmapper_geometry_layer_updates.md),
and [124 — bank lines](../../notebooks/124_rasmapper_bank_lines.md).

## Display, features and review methods

::: ras_commander.RasMap.RasMap
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - list_geometries
        - clone_geometry_layer
        - set_geometry_visibility
        - set_all_geometries_visibility
        - list_geometry_layers
        - set_geometry_layer_visibility
        - list_result_layers
        - set_result_layer_visibility
        - list_geometry_features
        - get_current_view
        - set_current_view
        - set_terrain_layer_visibility
        - list_terrain_display_settings
        - get_terrain_display_settings
        - set_terrain_display_settings
        - set_update_legend_with_view
        - get_geometry_layer_bounds
        - get_geometry_feature_bounds
        - zoom_to_geometry_layer
        - open_rasmapper
        - capture_rasmapper_snapshot
        - close_rasmapper
        - screenshot_model
        - screenshot_model_gallery
        - create_spatial_review_package
        - set_water_surface_render_mode
        - get_water_surface_render_mode

