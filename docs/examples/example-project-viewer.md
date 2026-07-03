---
title: Muncie Map Viewer
hide:
  - navigation
  - toc
---

<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.css">
<link rel="stylesheet" href="../../assets/stylesheets/ras-maplibre-viewer.css">

<div class="ras-maplibre-viewer" data-ras-maplibre-viewer data-manifest="https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/manifest.json?v=20260703Tterrainstretch01">
  <div class="ras-map-shell">
    <div class="ras-viewer-topbar">
      <a class="ras-back-link" href="../example-projects/">&larr; Example Projects</a>
      <div class="ras-viewer-title">
        <p class="ras-kicker">RAS Commander Example Library</p>
        <h2>Muncie</h2>
      </div>
      <div class="ras-viewer-actions">
        <span class="ras-layer-status" data-status>Loading</span>
        <a
          class="ras-open-data"
          href="https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/manifest.json?v=20260703Tterrainstretch01"
        >Manifest</a>
      </div>
    </div>
    <details class="ras-layer-menu">
      <summary>Layers</summary>
      <div class="ras-layer-menu__body">
        <div>
          <p class="ras-kicker">Display</p>
        </div>
        <div class="ras-layer-list" data-layer-list></div>
      </div>
    </details>
    <div class="ras-map" data-map></div>
  </div>
</div>

<script src="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/pmtiles@4.3.0/dist/pmtiles.js"></script>
<script src="../../assets/javascripts/ras-maplibre-viewer.js"></script>

## Raster Results

Raster results are the visual mapping product for depth, water surface,
velocity, and similar outputs. These should be COG or raster PMTiles
derivatives created from RasProcess Stored Maps so the interpolation and
surface construction match the RAS Mapper output rather than a browser-side
approximation.

The current Muncie pilot has terrain, geometry, and vector result artifacts
published. Stored Maps COG result layers have not yet been published for this
bundle.

## Vector Results

Vector results are element-level query data. They are useful for hover and
identify workflows over 2D flow areas, mesh faces, cross sections, structures,
and other source elements because the attributes remain tied to the raw source
element. They are not the visual inundation or velocity map unless a separate
surface is generated.

The Muncie pilot currently includes vector result layers for `p03` and `p04`
maximum water surface and maximum face velocity. Turn those layers on from the
map's layer menu when you want to inspect raw element values.

## Artifact Bundle

| Resource | Link |
|----------|------|
| MapLibre manifest | [manifest.json](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/manifest.json?v=20260703Tterrainstretch01) |
| Geometry PMTiles | [geometry.pmtiles](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/tiles/geometry.pmtiles) |
| Vector results PMTiles | [results.pmtiles](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/tiles/results.pmtiles) |
| Terrain PMTiles | [terrain.pmtiles](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/tiles/terrain.pmtiles) |
