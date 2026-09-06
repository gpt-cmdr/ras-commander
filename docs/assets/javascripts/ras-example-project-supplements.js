window.RAS_EXAMPLE_PROJECT_SUPPLEMENTS = {
  "type": "FeatureCollection",
  "name": "ras-commander-example-project-supplements",
  "features": [
    {
      "type": "Feature",
      "id": "san-gabriel-ble-12070205",
      "properties": {
        "title": "FEMA San Gabriel BLE (12070205)",
        "sourceFamily": "FEMA eBFE/BLE delivery",
        "crs": "EPSG:2277",
        "crsDefinition": "EPSG:2277",
        "status": "Source qualification candidate",
        "projectId": "san-gabriel-ble-12070205",
        "viewerType": "Qualification candidate",
        "recordOfDeficiencies": "https://github.com/gpt-cmdr/ras-commander/blob/main/agent_tasks/2026-09-05_san_gabriel_record_of_deficiencies.md",
        "notes": "Five linked 2D-unsteady projects. LBSG_503 covers Florence and LBSG_504 covers Round Rock. A shared HDEM-only reconstructed-terrain LBSG_503 run completed successfully and is hydraulically reasonable for QA screening; the source delivery omitted the compiled Terrain.hdf and its terrain-modification payloads, so the reconstruction is not source-equivalent.",
        "extentSource": "Union of LBSG_501-LBSG_505 footprints from HdfProject.get_project_extent()",
        "landingExtentSource": "Five-project model-system bounding box",
        "fallbackGeometry": "bounding-box"
      },
      "bbox": [
        -98.26813645701162,
        30.403250679780886,
        -97.00285606221672,
        30.918779935290782
      ],
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [-98.26813645701162, 30.403250679780886],
            [-97.00285606221672, 30.403250679780886],
            [-97.00285606221672, 30.918779935290782],
            [-98.26813645701162, 30.918779935290782],
            [-98.26813645701162, 30.403250679780886]
          ]
        ]
      }
    }
  ]
};
