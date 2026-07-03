(function () {
  window.RAS_EXAMPLE_PROJECTS = {
    type: "FeatureCollection",
    name: "ras-commander-example-projects",
    generatedAt: "2026-07-03T00:00:00-04:00",
    features: [
      {
        type: "Feature",
        id: "muncie-muncie-rerun-7-0-20260628-193916-4120d261",
        properties: {
          title: "Muncie",
          sourceFamily: "HEC tutorial/example project",
          crs: "EPSG:2965",
          status: "MapLibre pilot",
          projectId: "muncie-muncie-rerun-7-0-20260628-193916-4120d261",
          webmap: "../example-project-viewer/",
          manifest:
            "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/manifest.json?v=20260703Tidentify02",
          projectManifest:
            "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/project.json",
          viewerType: "MapLibre",
          notes:
            "First MapLibre pilot with terrain, geometry, raw HDF vector results, and RASMapper Stored Map rasters.",
        },
        bbox: [
          -85.39413392995574,
          40.18967072465606,
          -85.36012339789563,
          40.205583441794495,
        ],
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [-85.39413392995574, 40.18967072465606],
              [-85.36012339789563, 40.18967072465606],
              [-85.36012339789563, 40.205583441794495],
              [-85.39413392995574, 40.205583441794495],
              [-85.39413392995574, 40.18967072465606],
            ],
          ],
        },
      },
      {
        type: "Feature",
        id: "neworleansmetro-neworleansmetro-rerun-7-0-20260628-194053-e13b599a",
        properties: {
          title: "New Orleans Metro",
          sourceFamily: "HEC tutorial/example project",
          crs: "EPSG:3457",
          status: "MapLibre pilot",
          projectId:
            "neworleansmetro-neworleansmetro-rerun-7-0-20260628-194053-e13b599a",
          webmap:
            "../example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fneworleansmetro-neworleansmetro-rerun-7-0-20260628-194053-e13b599a%2Fviewer%2Fmanifest.json%3Fv%3D20260703Tneworleans01",
          manifest:
            "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/neworleansmetro-neworleansmetro-rerun-7-0-20260628-194053-e13b599a/viewer/manifest.json?v=20260703Tneworleans01",
          projectManifest:
            "https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/neworleansmetro-neworleansmetro-rerun-7-0-20260628-194053-e13b599a/project.json",
          viewerType: "MapLibre",
          notes:
            "Geometry and terrain PMTiles are published. Result layers need join-to-geometry post-processing before tiling.",
        },
        bbox: [
          -90.1686239827324,
          29.91505706201988,
          -90.06119062897804,
          30.027319931336432,
        ],
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [-90.1686239827324, 29.91505706201988],
              [-90.06119062897804, 29.91505706201988],
              [-90.06119062897804, 30.027319931336432],
              [-90.1686239827324, 30.027319931336432],
              [-90.1686239827324, 29.91505706201988],
            ],
          ],
        },
      },
    ],
  };
})();
