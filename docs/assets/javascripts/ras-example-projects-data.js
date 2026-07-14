window.RAS_EXAMPLE_PROJECTS = {
  "type": "FeatureCollection",
  "name": "ras-commander-example-projects",
  "generatedAt": "2026-07-14T01:15:00Z",
  "fallbackGeometry": "bounding-box",
  "features": [
    {
      "type": "Feature",
      "id": "muncie-muncie-rerun-7-0-20260628-193916-4120d261",
      "properties": {
        "title": "Muncie",
        "sourceFamily": "HEC tutorial/example project",
        "crs": "EPSG:2965",
        "crsDefinition": "EPSG:2965",
        "status": "MapLibre pilot",
        "projectId": "muncie-muncie-rerun-7-0-20260628-193916-4120d261",
        "webmap": "../example-project-viewer/",
        "manifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/manifest.json?v=20260703Tidentify02",
        "projectManifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/project.json",
        "viewerType": "MapLibre",
        "notes": "First MapLibre pilot with terrain, geometry, raw HDF vector results, and RASMapper Stored Map rasters.",
        "extentSource": "HdfProject.get_project_extent(geometry_type='footprint')",
        "landingExtentSource": "Exact model footprint",
        "fallbackGeometry": "bounding-box"
      },
      "bbox": [
        -85.39413392995574,
        40.18967072465606,
        -85.36033688735515,
        40.205583441794495
      ],
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              -85.39413392995574,
              40.18967072465606
            ],
            [
              -85.36033688735515,
              40.18967072465606
            ],
            [
              -85.36033688735515,
              40.205583441794495
            ],
            [
              -85.39413392995574,
              40.205583441794495
            ],
            [
              -85.39413392995574,
              40.18967072465606
            ]
          ]
        ]
      }
    },
    {
      "type": "Feature",
      "id": "neworleansmetro-neworleansmetro-rerun-7-0-20260628-194053-e13b599a",
      "properties": {
        "title": "New Orleans Metro",
        "sourceFamily": "HEC tutorial/example project",
        "crs": "EPSG:3457",
        "crsDefinition": "EPSG:3457",
        "status": "MapLibre pilot",
        "projectId": "neworleansmetro-neworleansmetro-rerun-7-0-20260628-194053-e13b599a",
        "webmap": "../example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fneworleansmetro-neworleansmetro-rerun-7-0-20260628-194053-e13b599a%2Fviewer%2Fmanifest.json%3Fv%3D20260703Tneworleans01",
        "manifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/neworleansmetro-neworleansmetro-rerun-7-0-20260628-194053-e13b599a/viewer/manifest.json?v=20260703Tneworleans01",
        "projectManifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/neworleansmetro-neworleansmetro-rerun-7-0-20260628-194053-e13b599a/project.json",
        "viewerType": "MapLibre",
        "notes": "Geometry and terrain PMTiles are published. Result layers need join-to-geometry post-processing before tiling.",
        "extentSource": "HdfProject.get_project_extent(geometry_type='footprint')",
        "landingExtentSource": "Exact model footprint",
        "fallbackGeometry": "bounding-box"
      },
      "bbox": [
        -90.1686239827324,
        29.91505706201988,
        -90.06119062897804,
        30.027319931336432
      ],
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              -90.1686239827324,
              29.91505706201988
            ],
            [
              -90.06119062897804,
              29.91505706201988
            ],
            [
              -90.06119062897804,
              30.027319931336432
            ],
            [
              -90.1686239827324,
              30.027319931336432
            ],
            [
              -90.1686239827324,
              29.91505706201988
            ]
          ]
        ]
      }
    },
    {
      "type": "Feature",
      "id": "st-joseph-st-joe-elkhart-fim-6f8e01d0",
      "properties": {
        "title": "St. Joseph / St. Joe Elkhart FIM",
        "sourceFamily": "USGS ScienceBase model release",
        "crs": "EPSG:2965",
        "crsDefinition": "EPSG:2965",
        "status": "MapLibre pilot",
        "projectId": "st-joseph-st-joe-elkhart-fim-6f8e01d0",
        "webmap": "../example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fst-joseph-st-joe-elkhart-fim-6f8e01d0%2Fviewer%2Fmanifest.json%3Fv%3D20260711Tstjoseph01",
        "manifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/st-joseph-st-joe-elkhart-fim-6f8e01d0/viewer/manifest.json?v=20260711Tstjoseph01",
        "projectManifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/st-joseph-st-joe-elkhart-fim-6f8e01d0/project.json",
        "viewerType": "MapLibre",
        "notes": "Geometry-only ScienceBase pilot with model extents, river centerline, and cross sections.",
        "extentSource": "HdfProject.get_project_extent(geometry_type='footprint')",
        "landingExtentSource": "Exact model footprint",
        "fallbackGeometry": "bounding-box"
      },
      "bbox": [
        -86.04568221655765,
        41.67223878974706,
        -85.97109503151293,
        41.6953449619564
      ],
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              -86.04568221655765,
              41.67223878974706
            ],
            [
              -85.97109503151293,
              41.67223878974706
            ],
            [
              -85.97109503151293,
              41.6953449619564
            ],
            [
              -86.04568221655765,
              41.6953449619564
            ],
            [
              -86.04568221655765,
              41.67223878974706
            ]
          ]
        ]
      }
    },
    {
      "type": "Feature",
      "id": "chippewa-2d-chippewa-2d-rerun-7-0-20260628-170311-14e51a07",
      "properties": {
        "title": "Chippewa 2D",
        "sourceFamily": "HEC tutorial/example project",
        "crs": "NAD83 / CONUS Albers (US ft)",
        "crsDefinition": "+proj=aea +lat_0=23 +lon_0=-96 +lat_1=29.5 +lat_2=45.5 +x_0=0 +y_0=0 +datum=NAD83 +units=us-ft +no_defs +type=crs",
        "status": "MapLibre geometry bundle",
        "projectId": "chippewa-2d-chippewa-2d-rerun-7-0-20260628-170311-14e51a07",
        "webmap": "../example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fchippewa-2d-chippewa-2d-rerun-7-0-20260628-170311-14e51a07%2Fviewer%2Fmanifest.json%3Fv%3D20260713Tmaplibre02",
        "manifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/chippewa-2d-chippewa-2d-rerun-7-0-20260628-170311-14e51a07/viewer/manifest.json?v=20260713Tmaplibre02",
        "projectManifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/chippewa-2d-chippewa-2d-rerun-7-0-20260628-170311-14e51a07/project.json",
        "viewerType": "MapLibre",
        "notes": "Geometry-only 2D HEC instructional example with a verified packaged Albers projection.",
        "extentSource": "HdfProject.get_project_extent(geometry_type='footprint')",
        "landingExtentSource": "Exact model footprint",
        "fallbackGeometry": "bounding-box"
      },
      "bbox": [
        -92.06462713198664,
        44.46670603904722,
        -92.05178198178692,
        44.4879997018128
      ],
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              -92.06462713198664,
              44.46670603904722
            ],
            [
              -92.05178198178692,
              44.46670603904722
            ],
            [
              -92.05178198178692,
              44.4879997018128
            ],
            [
              -92.06462713198664,
              44.4879997018128
            ],
            [
              -92.06462713198664,
              44.46670603904722
            ]
          ]
        ]
      }
    },
    {
      "type": "Feature",
      "id": "davis-davis-rerun-7-0-20260628-193602-d666d9cb",
      "properties": {
        "title": "Davis",
        "sourceFamily": "HEC tutorial/example project",
        "crs": "EPSG:2871",
        "crsDefinition": "EPSG:2871",
        "status": "MapLibre geometry bundle",
        "projectId": "davis-davis-rerun-7-0-20260628-193602-d666d9cb",
        "webmap": "../example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fdavis-davis-rerun-7-0-20260628-193602-d666d9cb%2Fviewer%2Fmanifest.json%3Fv%3D20260713Tmaplibre02",
        "manifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/davis-davis-rerun-7-0-20260628-193602-d666d9cb/viewer/manifest.json?v=20260713Tmaplibre02",
        "projectManifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/davis-davis-rerun-7-0-20260628-193602-d666d9cb/project.json",
        "viewerType": "MapLibre",
        "notes": "Geometry-only HEC example with a 2D mesh and API-derived footprint.",
        "extentSource": "HdfProject.get_project_extent(geometry_type='footprint')",
        "landingExtentSource": "Exact model footprint",
        "fallbackGeometry": "bounding-box"
      },
      "bbox": [
        -121.76683266317532,
        38.543930307093035,
        -121.7271789026235,
        38.57120542281889
      ],
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              -121.76683266317532,
              38.543930307093035
            ],
            [
              -121.7271789026235,
              38.543930307093035
            ],
            [
              -121.7271789026235,
              38.57120542281889
            ],
            [
              -121.76683266317532,
              38.57120542281889
            ],
            [
              -121.76683266317532,
              38.543930307093035
            ]
          ]
        ]
      }
    },
    {
      "type": "Feature",
      "id": "beaverlake-beaverlake-rerun-7-0-20260628-194053-eb3bacd7",
      "properties": {
        "title": "Beaver Lake",
        "sourceFamily": "HEC tutorial/example project",
        "crs": "EPSG:2274",
        "crsDefinition": "EPSG:2274",
        "status": "MapLibre geometry bundle",
        "projectId": "beaverlake-beaverlake-rerun-7-0-20260628-194053-eb3bacd7",
        "webmap": "../example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fbeaverlake-beaverlake-rerun-7-0-20260628-194053-eb3bacd7%2Fviewer%2Fmanifest.json%3Fv%3D20260713Tmaplibre02",
        "manifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/beaverlake-beaverlake-rerun-7-0-20260628-194053-eb3bacd7/viewer/manifest.json?v=20260713Tmaplibre02",
        "projectManifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/beaverlake-beaverlake-rerun-7-0-20260628-194053-eb3bacd7/project.json",
        "viewerType": "MapLibre",
        "notes": "Geometry-only HEC example with two geometry configurations and high-zoom mesh delivery.",
        "extentSource": "HdfProject.get_project_extent(geometry_type='footprint')",
        "landingExtentSource": "Exact model footprint",
        "fallbackGeometry": "bounding-box"
      },
      "bbox": [
        -89.90794513968532,
        35.2268075572939,
        -89.90025205704126,
        35.232095547756266
      ],
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              -89.90794513968532,
              35.2268075572939
            ],
            [
              -89.90025205704126,
              35.2268075572939
            ],
            [
              -89.90025205704126,
              35.232095547756266
            ],
            [
              -89.90794513968532,
              35.232095547756266
            ],
            [
              -89.90794513968532,
              35.2268075572939
            ]
          ]
        ]
      }
    },
    {
      "type": "Feature",
      "id": "balde-eagle-creek-balde-eagle-creek-rerun-7-0-20260629-224833-d0758cd9",
      "properties": {
        "title": "Bald Eagle Creek",
        "sourceFamily": "HEC tutorial/example project",
        "crs": "EPSG:2271",
        "crsDefinition": "EPSG:2271",
        "status": "MapLibre geometry bundle",
        "projectId": "balde-eagle-creek-balde-eagle-creek-rerun-7-0-20260629-224833-d0758cd9",
        "webmap": "../example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fbalde-eagle-creek-balde-eagle-creek-rerun-7-0-20260629-224833-d0758cd9%2Fviewer%2Fmanifest.json%3Fv%3D20260713Tmaplibre02",
        "manifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/balde-eagle-creek-balde-eagle-creek-rerun-7-0-20260629-224833-d0758cd9/viewer/manifest.json?v=20260713Tmaplibre02",
        "projectManifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/balde-eagle-creek-balde-eagle-creek-rerun-7-0-20260629-224833-d0758cd9/project.json",
        "viewerType": "MapLibre",
        "notes": "Geometry-only 1D HEC example with centerline, cross-section, and structure review layers.",
        "extentSource": "HdfProject.get_project_extent(geometry_type='footprint')",
        "landingExtentSource": "Exact model footprint",
        "fallbackGeometry": "bounding-box"
      },
      "bbox": [
        -77.75116831220302,
        40.96199986940711,
        -77.39934880718425,
        41.13589926637787
      ],
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              -77.75116831220302,
              40.96199986940711
            ],
            [
              -77.39934880718425,
              40.96199986940711
            ],
            [
              -77.39934880718425,
              41.13589926637787
            ],
            [
              -77.75116831220302,
              41.13589926637787
            ],
            [
              -77.75116831220302,
              40.96199986940711
            ]
          ]
        ]
      }
    },
    {
      "type": "Feature",
      "id": "kalamazoo-kalamazoo-trowbridg-b2c7eef6",
      "properties": {
        "title": "Kalamazoo",
        "sourceFamily": "USGS ScienceBase model release",
        "crs": "EPSG:6499",
        "crsDefinition": "EPSG:6499",
        "status": "MapLibre geometry bundle",
        "projectId": "kalamazoo-kalamazoo-trowbridg-b2c7eef6",
        "webmap": "../example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fkalamazoo-kalamazoo-trowbridg-b2c7eef6%2Fviewer%2Fmanifest.json%3Fv%3D20260713Tmaplibre02",
        "manifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/kalamazoo-kalamazoo-trowbridg-b2c7eef6/viewer/manifest.json?v=20260713Tmaplibre02",
        "projectManifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/kalamazoo-kalamazoo-trowbridg-b2c7eef6/project.json",
        "viewerType": "MapLibre",
        "notes": "Geometry-only ScienceBase bundle with five geometry configurations and detail-only mesh tiles.",
        "extentSource": "HdfProject.get_project_extent(geometry_type='footprint')",
        "landingExtentSource": "Exact model footprint",
        "fallbackGeometry": "bounding-box"
      },
      "bbox": [
        -85.86086342073826,
        42.48139214521074,
        -85.797099731364,
        42.527837913045765
      ],
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              -85.86086342073826,
              42.48139214521074
            ],
            [
              -85.797099731364,
              42.48139214521074
            ],
            [
              -85.797099731364,
              42.527837913045765
            ],
            [
              -85.86086342073826,
              42.527837913045765
            ],
            [
              -85.86086342073826,
              42.48139214521074
            ]
          ]
        ]
      }
    },
    {
      "type": "Feature",
      "id": "spring-river-ras-model-spring-ble-prj-15b882a5",
      "properties": {
        "title": "Spring River",
        "sourceFamily": "FEMA eBFE/BLE delivery",
        "crs": "EPSG:3433",
        "crsDefinition": "EPSG:3433",
        "status": "MapLibre geometry bundle",
        "projectId": "spring-river-ras-model-spring-ble-prj-15b882a5",
        "webmap": "../example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fspring-river-ras-model-spring-ble-prj-15b882a5%2Fviewer%2Fmanifest.json%3Fv%3D20260713Tmaplibre02",
        "manifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/spring-river-ras-model-spring-ble-prj-15b882a5/viewer/manifest.json?v=20260713Tmaplibre02",
        "projectManifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/spring-river-ras-model-spring-ble-prj-15b882a5/project.json",
        "viewerType": "MapLibre",
        "notes": "Geometry-only FEMA eBFE/BLE bundle with large 2D mesh cells delivered only at detail zoom.",
        "extentSource": "HdfProject.get_project_extent(geometry_type='footprint')",
        "landingExtentSource": "Exact model footprint",
        "fallbackGeometry": "bounding-box"
      },
      "bbox": [
        -91.98582726238398,
        36.099852088595775,
        -91.05859280387935,
        36.602553470067875
      ],
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              -91.98582726238398,
              36.099852088595775
            ],
            [
              -91.05859280387935,
              36.099852088595775
            ],
            [
              -91.05859280387935,
              36.602553470067875
            ],
            [
              -91.98582726238398,
              36.602553470067875
            ],
            [
              -91.98582726238398,
              36.099852088595775
            ]
          ]
        ]
      }
    },
    {
      "type": "Feature",
      "id": "baldeaglecrkmulti2d-baldeaglecrkmulti2d-remote-7-0-20260628-212722-1d3b97ab",
      "properties": {
        "title": "Bald Eagle Creek Multi2D",
        "sourceFamily": "HEC tutorial/example project",
        "crs": "EPSG:2271",
        "crsDefinition": "EPSG:2271",
        "status": "MapLibre geometry bundle",
        "projectId": "baldeaglecrkmulti2d-baldeaglecrkmulti2d-remote-7-0-20260628-212722-1d3b97ab",
        "webmap": "../example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fbaldeaglecrkmulti2d-baldeaglecrkmulti2d-remote-7-0-20260628-212722-1d3b97ab%2Fviewer%2Fmanifest.json%3Fv%3D20260714Tbaldeagle01",
        "manifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/baldeaglecrkmulti2d-baldeaglecrkmulti2d-remote-7-0-20260628-212722-1d3b97ab/viewer/manifest.json?v=20260714Tbaldeagle01",
        "projectManifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/baldeaglecrkmulti2d-baldeaglecrkmulti2d-remote-7-0-20260628-212722-1d3b97ab/project.json",
        "viewerType": "MapLibre",
        "notes": "Geometry-only HEC instructional example with ten geometry configurations and high-zoom 2D mesh tiles.",
        "extentSource": "HdfProject.get_project_extent(geometry_type='footprint')",
        "landingExtentSource": "Exact model footprint",
        "fallbackGeometry": "bounding-box"
      },
      "bbox": [
        -77.75911860853455,
        40.961448866086826,
        -77.32752499389363,
        41.1841731878243
      ],
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              -77.75911860853455,
              40.961448866086826
            ],
            [
              -77.32752499389363,
              40.961448866086826
            ],
            [
              -77.32752499389363,
              41.1841731878243
            ],
            [
              -77.75911860853455,
              41.1841731878243
            ],
            [
              -77.75911860853455,
              40.961448866086826
            ]
          ]
        ]
      }
    },
    {
      "type": "Feature",
      "id": "spring-creek-spring-c61c5625",
      "properties": {
        "title": "Spring Creek",
        "sourceFamily": "FEMA eBFE/BLE delivery",
        "crs": "EPSG:2278",
        "crsDefinition": "EPSG:2278",
        "status": "MapLibre geometry bundle",
        "projectId": "spring-creek-spring-c61c5625",
        "webmap": "../example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fspring-creek-spring-c61c5625%2Fviewer%2Fmanifest.json%3Fv%3D20260714Tebfe02",
        "manifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/spring-creek-spring-c61c5625/viewer/manifest.json?v=20260714Tebfe02",
        "projectManifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/spring-creek-spring-c61c5625/project.json",
        "viewerType": "MapLibre",
        "notes": "Geometry-only 2D-unsteady FEMA eBFE/BLE bundle. Stored-map output is withheld pending validation of the all-cells-NoData warnings.",
        "extentSource": "HdfProject.get_project_extent(geometry_type='footprint')",
        "landingExtentSource": "Exact model footprint",
        "fallbackGeometry": "bounding-box"
      },
      "bbox": [
        -95.99108122653325,
        29.876367023843223,
        -95.26047240157916,
        30.365745421453827
      ],
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              -95.99108122653325,
              29.876367023843223
            ],
            [
              -95.26047240157916,
              29.876367023843223
            ],
            [
              -95.26047240157916,
              30.365745421453827
            ],
            [
              -95.99108122653325,
              30.365745421453827
            ],
            [
              -95.99108122653325,
              29.876367023843223
            ]
          ]
        ]
      }
    },
    {
      "type": "Feature",
      "id": "upper-guadalupe-ras-model-upgu1-upgu1-prj-030c0a6a",
      "properties": {
        "title": "Upper Guadalupe UPGU1",
        "sourceFamily": "FEMA eBFE/BLE delivery",
        "crs": "EPSG:2278",
        "crsDefinition": "EPSG:2278",
        "status": "MapLibre geometry bundle",
        "projectId": "upper-guadalupe-ras-model-upgu1-upgu1-prj-030c0a6a",
        "webmap": "../example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fupper-guadalupe-ras-model-upgu1-upgu1-prj-030c0a6a%2Fviewer%2Fmanifest.json%3Fv%3D20260714Tebfe02",
        "manifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/upper-guadalupe-ras-model-upgu1-upgu1-prj-030c0a6a/viewer/manifest.json?v=20260714Tebfe02",
        "projectManifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/upper-guadalupe-ras-model-upgu1-upgu1-prj-030c0a6a/project.json",
        "viewerType": "MapLibre",
        "notes": "Geometry-only 2D-unsteady FEMA eBFE/BLE bundle with high-zoom mesh delivery.",
        "extentSource": "HdfProject.get_project_extent(geometry_type='footprint')",
        "landingExtentSource": "Exact model footprint",
        "fallbackGeometry": "bounding-box"
      },
      "bbox": [
        -99.69714999942667,
        29.897157415573655,
        -99.2220823291806,
        30.26653385380407
      ],
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              -99.69714999942667,
              29.897157415573655
            ],
            [
              -99.2220823291806,
              29.897157415573655
            ],
            [
              -99.2220823291806,
              30.26653385380407
            ],
            [
              -99.69714999942667,
              30.26653385380407
            ],
            [
              -99.69714999942667,
              29.897157415573655
            ]
          ]
        ]
      }
    },
    {
      "type": "Feature",
      "id": "upper-guadalupe-ras-model-upgu2-upgu2-prj-917be43b",
      "properties": {
        "title": "Upper Guadalupe UPGU2",
        "sourceFamily": "FEMA eBFE/BLE delivery",
        "crs": "EPSG:2278",
        "crsDefinition": "EPSG:2278",
        "status": "MapLibre geometry bundle",
        "projectId": "upper-guadalupe-ras-model-upgu2-upgu2-prj-917be43b",
        "webmap": "../example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fupper-guadalupe-ras-model-upgu2-upgu2-prj-917be43b%2Fviewer%2Fmanifest.json%3Fv%3D20260714Tebfe02",
        "manifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/upper-guadalupe-ras-model-upgu2-upgu2-prj-917be43b/viewer/manifest.json?v=20260714Tebfe02",
        "projectManifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/upper-guadalupe-ras-model-upgu2-upgu2-prj-917be43b/project.json",
        "viewerType": "MapLibre",
        "notes": "Geometry-only 2D-unsteady FEMA eBFE/BLE bundle with high-zoom mesh delivery.",
        "extentSource": "HdfProject.get_project_extent(geometry_type='footprint')",
        "landingExtentSource": "Exact model footprint",
        "fallbackGeometry": "bounding-box"
      },
      "bbox": [
        -99.32670834487111,
        29.83715073849448,
        -98.88598300221824,
        30.18415771461644
      ],
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              -99.32670834487111,
              29.83715073849448
            ],
            [
              -98.88598300221824,
              29.83715073849448
            ],
            [
              -98.88598300221824,
              30.18415771461644
            ],
            [
              -99.32670834487111,
              30.18415771461644
            ],
            [
              -99.32670834487111,
              29.83715073849448
            ]
          ]
        ]
      }
    },
    {
      "type": "Feature",
      "id": "upper-guadalupe-ras-model-upgu3-upgu3-prj-c79886b4",
      "properties": {
        "title": "Upper Guadalupe UPGU3",
        "sourceFamily": "FEMA eBFE/BLE delivery",
        "crs": "EPSG:2278",
        "crsDefinition": "EPSG:2278",
        "status": "MapLibre geometry bundle",
        "projectId": "upper-guadalupe-ras-model-upgu3-upgu3-prj-c79886b4",
        "webmap": "../example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fupper-guadalupe-ras-model-upgu3-upgu3-prj-c79886b4%2Fviewer%2Fmanifest.json%3Fv%3D20260714Tebfe02",
        "manifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/upper-guadalupe-ras-model-upgu3-upgu3-prj-c79886b4/viewer/manifest.json?v=20260714Tebfe02",
        "projectManifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/upper-guadalupe-ras-model-upgu3-upgu3-prj-c79886b4/project.json",
        "viewerType": "MapLibre",
        "notes": "Geometry-only 2D-unsteady FEMA eBFE/BLE bundle with high-zoom mesh delivery.",
        "extentSource": "HdfProject.get_project_extent(geometry_type='footprint')",
        "landingExtentSource": "Exact model footprint",
        "fallbackGeometry": "bounding-box"
      },
      "bbox": [
        -98.93222243990395,
        29.811974086782772,
        -98.56304224349145,
        30.1297641051496
      ],
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              -98.93222243990395,
              29.811974086782772
            ],
            [
              -98.56304224349145,
              29.811974086782772
            ],
            [
              -98.56304224349145,
              30.1297641051496
            ],
            [
              -98.93222243990395,
              30.1297641051496
            ],
            [
              -98.93222243990395,
              29.811974086782772
            ]
          ]
        ]
      }
    },
    {
      "type": "Feature",
      "id": "upper-guadalupe-ras-model-upgu4-upgu4-prj-a9a9000f",
      "properties": {
        "title": "Upper Guadalupe UPGU4",
        "sourceFamily": "FEMA eBFE/BLE delivery",
        "crs": "EPSG:2278",
        "crsDefinition": "EPSG:2278",
        "status": "MapLibre geometry bundle",
        "projectId": "upper-guadalupe-ras-model-upgu4-upgu4-prj-a9a9000f",
        "webmap": "../example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fupper-guadalupe-ras-model-upgu4-upgu4-prj-a9a9000f%2Fviewer%2Fmanifest.json%3Fv%3D20260714Tebfe02",
        "manifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/upper-guadalupe-ras-model-upgu4-upgu4-prj-a9a9000f/viewer/manifest.json?v=20260714Tebfe02",
        "projectManifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/upper-guadalupe-ras-model-upgu4-upgu4-prj-a9a9000f/project.json",
        "viewerType": "MapLibre",
        "notes": "Geometry-only 2D-unsteady FEMA eBFE/BLE bundle and large-model streaming validation case with high-zoom mesh delivery.",
        "extentSource": "HdfProject.get_project_extent(geometry_type='footprint')",
        "landingExtentSource": "Exact model footprint",
        "fallbackGeometry": "bounding-box"
      },
      "bbox": [
        -98.71760442029861,
        29.796267715490476,
        -98.17561174692321,
        30.049603345714218
      ],
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              -98.71760442029861,
              29.796267715490476
            ],
            [
              -98.17561174692321,
              29.796267715490476
            ],
            [
              -98.17561174692321,
              30.049603345714218
            ],
            [
              -98.71760442029861,
              30.049603345714218
            ],
            [
              -98.71760442029861,
              29.796267715490476
            ]
          ]
        ]
      }
    },
    {
      "type": "Feature",
      "id": "squannacook-squannacook-15df5e30",
      "properties": {
        "title": "Squannacook",
        "sourceFamily": "USGS ScienceBase model release",
        "crs": "EPSG:2249",
        "crsDefinition": "EPSG:2249",
        "status": "MapLibre geometry and raw 1D steady-result bundle",
        "projectId": "squannacook-squannacook-15df5e30",
        "webmap": "../example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fsquannacook-squannacook-15df5e30%2Fviewer%2Fmanifest.json%3Fv%3D20260714T2300Z",
        "manifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/squannacook-squannacook-15df5e30/viewer/manifest.json?v=20260714T2300Z",
        "projectManifest": "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/squannacook-squannacook-15df5e30/project.json",
        "viewerType": "MapLibre",
        "notes": "1D-steady USGS ScienceBase bundle with fifteen separate plan and geometry configurations. Raw HEC-RAS HDF cross-section results are published by plan and profile; no RASMapper stored-map rasters are included in the source package.",
        "extentSource": "HdfProject.get_project_extent(geometry_type='footprint')",
        "landingExtentSource": "Model coverage envelope (concave hull of exact 1D reach footprints)",
        "fallbackGeometry": "bounding-box"
      },
      "bbox": [
        -71.84107686475589,
        42.63043149093957,
        -71.67063643962399,
        42.6928489295816
      ],
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              -71.84107686475589,
              42.63043149093957
            ],
            [
              -71.67063643962399,
              42.63043149093957
            ],
            [
              -71.67063643962399,
              42.6928489295816
            ],
            [
              -71.84107686475589,
              42.6928489295816
            ],
            [
              -71.84107686475589,
              42.63043149093957
            ]
          ]
        ]
      }
    }
  ]
};
