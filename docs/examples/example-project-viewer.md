# Muncie Map Viewer

This pilot viewer uses a RAS Commander MapLibre manifest and PMTiles artifacts
served through the WebGIS data service.

<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.css">
<link rel="stylesheet" href="../../assets/stylesheets/ras-maplibre-viewer.css">

<div
  class="ras-maplibre-viewer"
  data-ras-maplibre-viewer
  data-manifest="https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/manifest.json?v=20260703Tterrainstretch01"
>
  <div class="ras-map-shell">
    <aside class="ras-layer-panel" aria-label="RAS layer tree">
      <div class="ras-layer-header">
        <div>
          <p class="ras-kicker">RAS Commander Example Library</p>
          <h2>Muncie</h2>
        </div>
        <a
          class="ras-open-data"
          href="https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/manifest.json?v=20260703Tterrainstretch01"
        >Manifest</a>
      </div>
      <div class="ras-layer-list" data-layer-list></div>
      <div class="ras-layer-status" data-status>Loading</div>
    </aside>
    <div class="ras-map" data-map></div>
  </div>
</div>

<script src="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/pmtiles@4.3.0/dist/pmtiles.js"></script>
<script src="../../assets/javascripts/ras-maplibre-viewer.js"></script>

## Artifact Bundle

| Resource | Link |
|----------|------|
| MapLibre manifest | [manifest.json](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/manifest.json?v=20260703Tterrainstretch01) |
| Geometry PMTiles | [geometry.pmtiles](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/tiles/geometry.pmtiles) |
| Results PMTiles | [results.pmtiles](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/tiles/results.pmtiles) |
| Terrain PMTiles | [terrain.pmtiles](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/tiles/terrain.pmtiles) |
