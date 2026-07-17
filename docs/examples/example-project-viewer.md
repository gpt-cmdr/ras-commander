---
title: Example Project Viewer
hide:
  - navigation
  - toc
---

<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.css">
<link rel="stylesheet" href="../../assets/stylesheets/ras-maplibre-viewer.css?v=20260716Tmuncie-contract-v2">

<div class="ras-maplibre-viewer" data-ras-maplibre-viewer data-manifest="https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/manifest.json?v=20260716Tmuncie-contract-v2">
  <div class="ras-viewer-topbar">
    <a class="ras-back-link" href="../example-projects/">&larr; Example Projects</a>
    <div class="ras-viewer-title">
      <p class="ras-kicker">RAS Commander Example Library</p>
      <h2 data-project-title>Example Project</h2>
    </div>
    <div class="ras-viewer-actions">
      <span class="ras-layer-status" data-status>Loading</span>
      <a class="ras-open-data" data-manifest-link href="#">Manifest</a>
    </div>
  </div>
  <div class="ras-map-shell">
    <div class="ras-map" data-map></div>
  </div>
  <section class="ras-identify-sheet" data-identify-sheet hidden aria-live="polite"></section>
  <details class="ras-layer-menu" open>
    <summary>Layer Controls</summary>
    <div class="ras-layer-menu__body">
      <p class="ras-kicker">Display</p>
      <div class="ras-layer-list" data-layer-list></div>
    </div>
  </details>
  <section class="ras-project-availability" data-project-availability></section>
</div>

<script src="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/pmtiles@4.3.0/dist/pmtiles.js"></script>
<script src="https://unpkg.com/proj4@2.11.0/dist/proj4.js"></script>
<script src="https://unpkg.com/geotiff@2.1.3/dist-browser/geotiff.js"></script>
<script src="../../assets/javascripts/ras-maplibre-viewer.js?v=20260716Tmuncie-contract-v2"></script>
