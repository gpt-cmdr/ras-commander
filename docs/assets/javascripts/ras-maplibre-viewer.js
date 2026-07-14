(function () {
  const roots = document.querySelectorAll("[data-ras-maplibre-viewer]");
  if (!roots.length) {
    return;
  }

  const DEFAULT_BOUNDS = [-85.3942, 40.1896, -85.3601, 40.2057];
  const VIEWER_MANIFEST_REFRESH = "20260714Tterrain01";
  const SATELLITE_ATTRIBUTION = "Tiles &copy; Esri";
  const SATELLITE_IMAGERY_TILES = [
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  ];
  const HYBRID_BOUNDARY_TILES = [
    "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
  ];
  const HYBRID_TRANSPORTATION_TILES = [
    "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}",
  ];
  const DEFAULT_STYLES = {
    model_extents: { fill: "#f59e0b", fillOpacity: 0.08, line: "#ea580c", lineWidth: 2 },
    mesh_areas: { fill: "#60a5fa", fillOpacity: 0.1, line: "#1d4ed8", lineWidth: 1 },
    mesh_cells: { fill: "#93c5fd", fillOpacity: 0.14, line: "#2563eb", lineWidth: 0.35, minzoom: 13 },
    mesh_faces: { fill: "#2563eb", fillOpacity: 0, line: "#2563eb", lineWidth: 0.65, minzoom: 14 },
    breaklines: { fill: "#f97316", fillOpacity: 0, line: "#f97316", lineWidth: 1 },
    centerlines: { fill: "#0f766e", fillOpacity: 0, line: "#0f766e", lineWidth: 1.2 },
    river_centerlines: { fill: "#0f766e", fillOpacity: 0, line: "#0f766e", lineWidth: 1.2 },
    structures: { fill: "#dc2626", fillOpacity: 0, line: "#dc2626", lineWidth: 1.4 },
    cross_sections: { fill: "#0f766e", fillOpacity: 0, line: "#0f766e", lineWidth: 1 },
    water_surface: { fill: "#2b8cbe", fillOpacity: 0.52, line: "#045a8d", lineWidth: 0.4 },
    velocity: { fill: "#7c3aed", fillOpacity: 0, line: "#7c3aed", lineWidth: 0.9 },
  };
  const IDENTIFY_SKIP_FIELDS = new Set([
    "bbox",
    "bounds",
    "geometry",
    "wkb_geometry",
    "geom",
    "hilbert",
    "hilbert_index",
    "hilbert_key",
  ]);
  const rasterSourceCache = new Map();

  function status(root, message) {
    const el = root.querySelector("[data-status]");
    if (el) {
      el.textContent = message;
    }
  }

  function normalizeBounds(bounds) {
    if (!bounds) {
      return null;
    }
    if (Array.isArray(bounds) && bounds.length === 4 && bounds.every(Number.isFinite)) {
      return bounds;
    }
    if (
      Array.isArray(bounds) &&
      bounds.length === 2 &&
      Array.isArray(bounds[0]) &&
      Array.isArray(bounds[1])
    ) {
      return [bounds[0][0], bounds[0][1], bounds[1][0], bounds[1][1]];
    }
    return null;
  }

  function mergeBounds(items) {
    const valid = items.map(normalizeBounds).filter(Boolean);
    if (!valid.length) {
      return null;
    }
    return [
      Math.min(...valid.map((b) => b[0])),
      Math.min(...valid.map((b) => b[1])),
      Math.max(...valid.map((b) => b[2])),
      Math.max(...valid.map((b) => b[3])),
    ];
  }

  function resolveHref(baseUrl, href) {
    return new URL(href, baseUrl).toString();
  }

  function manifestUrlFor(root) {
    const params = new URLSearchParams(window.location.search);
    const requested = params.get("manifest");
    const manifestUrl = new URL(requested || root.dataset.manifest, window.location.href);
    manifestUrl.searchParams.set("viewerRefresh", VIEWER_MANIFEST_REFRESH);
    return manifestUrl.toString();
  }

  function setProjectChrome(root, manifest, manifestUrl) {
    const title = manifest.title || root.dataset.projectTitle || "Example Project";
    const heading = root.querySelector("[data-project-title]");
    if (heading) {
      heading.textContent = title;
    }
    const manifestLink = root.querySelector("[data-manifest-link]");
    if (manifestLink) {
      manifestLink.href = manifestUrl;
    }
    document.title = `${title} Map Viewer - RAS Commander Documentation`;
  }

  function resolveTileHref(baseUrl, href, manifestUrl) {
    const tileUrl = new URL(href, baseUrl);
    const manifestVersion = new URL(manifestUrl).searchParams.get("v");
    if (manifestVersion && !tileUrl.searchParams.has("v")) {
      tileUrl.searchParams.set("v", manifestVersion);
    }
    return tileUrl.toString();
  }

  function geometryTypes(layer) {
    const raw = layer.geometryTypes || [];
    const types = Array.isArray(raw) ? raw : [raw];
    return new Set(types.map((t) => String(t || "").toLowerCase()));
  }

  function styleFor(layer) {
    const raw = layer.style && typeof layer.style === "object" ? layer.style : {};
    const name = String(layer.name || "").toLowerCase();
    let fallback = DEFAULT_STYLES[layer.kind] || {};
    if (name.includes("water surface")) {
      fallback = DEFAULT_STYLES.water_surface;
    } else if (name.includes("velocity")) {
      fallback = DEFAULT_STYLES.velocity;
    }
    const style = Object.assign({}, fallback, raw);
    if (isVectorResultLayer(layer) && geometryTypes(layer).has("multipolygon")) {
      style.fillOpacity = Number.isFinite(style.fillOpacity) ? Math.min(style.fillOpacity, 0.1) : 0.08;
    } else if (isVectorResultLayer(layer) && geometryTypes(layer).has("polygon")) {
      style.fillOpacity = Number.isFinite(style.fillOpacity) ? Math.min(style.fillOpacity, 0.1) : 0.08;
    }
    return style;
  }

  function layerVisibility(layer) {
    return layer.visible ? "visible" : "none";
  }

  function isVectorResultLayer(layer) {
    const groupId = String(layer.groupId || "");
    const id = String(layer.id || "");
    return groupId === "ras-results" || id.startsWith("ras-results-");
  }

  function displayGroupName(group) {
    if (group.id === "ras-terrains") {
      return "Terrain";
    }
    if (group.id === "ras-raster-results") {
      return "Raster Results";
    }
    if (group.id === "ras-results") {
      return "Vector Results";
    }
    return group.name || group.id;
  }

  function rasterLayerGroupId(tileset) {
    if (tileset.groupId) {
      return tileset.groupId;
    }
    return tileset.id === "terrain" ? "ras-terrains" : "ras-raster-results";
  }

  function isTerrainTileset(tileset) {
    return tileset.id === "terrain"
      || tileset.groupId === "ras-terrains"
      || (tileset.storedMap && tileset.storedMap.mapType === "terrain");
  }

  function projectAvailability(manifest) {
    const tilesets = manifest.tilesets || [];
    const vectorLayers = tilesets
      .filter((tileset) => tileset.type === "vector")
      .flatMap((tileset) => tileset.layers || []);
    const hasModelExtents = vectorLayers.some((layer) => layer.kind === "model_extents");
    const is2D = vectorLayers.some((layer) => (
      ["mesh_areas", "mesh_cells", "mesh_faces", "breaklines", "refinement_regions"].includes(layer.kind)
    ));
    const terrain = tilesets.some((tileset) => tileset.type === "raster" && isTerrainTileset(tileset));
    const storedMaps = tilesets.filter((tileset) => tileset.type === "raster" && !isTerrainTileset(tileset));
    const rawResultLayers = tilesets
      .filter((tileset) => tileset.type === "vector" && tileset.groupId === "ras-results")
      .reduce((count, tileset) => count + (tileset.layers || []).length, 0);

    return [
      { label: "Basemap", detail: "Satellite imagery with labels and roads is enabled." },
      {
        label: "Model Extents",
        detail: hasModelExtents
          ? "Enabled with the default geometry configuration."
          : "Model extent geometry is not yet published for this model.",
        unavailable: !hasModelExtents,
      },
      {
        label: "Default Geometry",
        detail: is2D
          ? "2D mesh cells plus breaklines and refinement regions when supplied by the model."
          : "1D river and reach centerlines.",
      },
      {
        label: "Terrain",
        detail: terrain
          ? "Project terrain is published."
          : "No project terrain was provided or published for this model.",
        unavailable: !terrain,
      },
      {
        label: "Raster Results",
        detail: storedMaps.length
          ? `${storedMaps.length} RASMapper Stored Map raster layer${storedMaps.length === 1 ? "" : "s"} published.`
          : "No RASMapper Stored Map rasters are published.",
        unavailable: !storedMaps.length,
      },
      {
        label: "Vector Results",
        detail: rawResultLayers
          ? `${rawResultLayers} raw HDF element result layer${rawResultLayers === 1 ? "" : "s"} published.`
          : "No raw HDF vector result layers are published.",
        unavailable: !rawResultLayers,
      },
    ];
  }

  function renderProjectAvailability(root, manifest) {
    const container = root.querySelector("[data-project-availability]");
    if (!container) {
      return;
    }

    container.replaceChildren();
    const title = document.createElement("h3");
    title.textContent = "Project Availability";
    const list = document.createElement("dl");
    list.className = "ras-project-availability__list";
    for (const item of projectAvailability(manifest)) {
      const term = document.createElement("dt");
      term.textContent = item.label;
      const detail = document.createElement("dd");
      detail.textContent = item.detail;
      if (item.unavailable) {
        detail.className = "ras-project-availability__unavailable";
      }
      list.append(term, detail);
    }
    container.append(title, list);
  }

  function addHybridBasemap(map) {
    const sources = [
      ["satellite-imagery", SATELLITE_IMAGERY_TILES],
      ["hybrid-boundaries", HYBRID_BOUNDARY_TILES],
      ["hybrid-transportation", HYBRID_TRANSPORTATION_TILES],
    ];
    for (const [id, tiles] of sources) {
      map.addSource(id, {
        type: "raster",
        tiles,
        tileSize: 256,
        attribution: SATELLITE_ATTRIBUTION,
      });
      map.addLayer({ id, type: "raster", source: id });
    }
  }

  function slugify(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "unknown";
  }

  function escapeRegExp(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function planFromText(value) {
    const match = String(value || "").match(/(?:^|[^a-z0-9])(p\d+)(?=$|[^a-z0-9])/i);
    return match ? match[1].toLowerCase() : "";
  }

  function resultPlanId(layer) {
    const storedMap = layer.storedMap && typeof layer.storedMap === "object" ? layer.storedMap : {};
    const explicitPlan = layer.plan || layer.planId || storedMap.plan || storedMap.planId;
    if (explicitPlan) {
      return String(explicitPlan).trim();
    }
    return planFromText([layer.id, layer.name, layer.kind].join(" "));
  }

  function resultPlanSort(planId) {
    const match = String(planId || "").match(/^p(\d+)$/i);
    return match ? Number(match[1]) : 9999;
  }

  function resultPlanName(planId) {
    return /^p\d+$/i.test(String(planId || "")) ? `Plan ${planId}` : String(planId || "Other Results");
  }

  function resultSubgroup(layer) {
    const groupId = String(layer.groupId || "");
    if (groupId !== "ras-raster-results" && groupId !== "ras-results") {
      return null;
    }
    const planId = resultPlanId(layer);
    if (!planId) {
      return { id: "result-plan-other", name: "Other Results", sort: 99999, planId: "" };
    }
    return {
      id: `result-plan-${slugify(planId)}`,
      name: resultPlanName(planId),
      sort: resultPlanSort(planId),
      planId,
    };
  }

  function resultControlName(layer, planId) {
    const name = String(layer.name || layer.id || "");
    if (!planId) {
      return name;
    }
    return name.replace(new RegExp(`^${escapeRegExp(planId)}[\\s:_-]+`, "i"), "") || name;
  }

  function layerTreeEntry(layer) {
    const subgroup = resultSubgroup(layer);
    if (!subgroup) {
      return layer;
    }
    return Object.assign({}, layer, {
      subGroupId: subgroup.id,
      subGroupName: subgroup.name,
      subGroupSort: subgroup.sort,
      controlName: resultControlName(layer, subgroup.planId),
    });
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatFieldValue(value) {
    if (value === null || value === undefined || value === "") {
      return "";
    }
    if (typeof value === "number") {
      if (!Number.isFinite(value)) {
        return "";
      }
      if (Math.abs(value) >= 1000) {
        return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
      }
      return value.toLocaleString(undefined, { maximumFractionDigits: 3 });
    }
    if (typeof value === "boolean") {
      return value ? "true" : "false";
    }
    return String(value);
  }

  function formatFieldName(name) {
    return String(name || "")
      .replace(/^ras_/i, "")
      .replace(/_/g, " ");
  }

  function displayPropertyRows(properties, limit) {
    return Object.entries(properties || {})
      .filter(([key, value]) => !IDENTIFY_SKIP_FIELDS.has(String(key).toLowerCase()) && formatFieldValue(value) !== "")
      .slice(0, limit || 12);
  }

  function propertyRowsHtml(properties, limit) {
    const rows = displayPropertyRows(properties, limit);
    if (!rows.length) {
      return "<dt>Feature</dt><dd>No attributes available</dd>";
    }
    return rows
      .map(([key, value]) => (
        `<dt>${escapeHtml(formatFieldName(key))}</dt><dd>${escapeHtml(formatFieldValue(value))}</dd>`
      ))
      .join("");
  }

  function popupHtml(layer, properties) {
    return [
      '<div class="ras-map-popup">',
      `<div class="ras-map-popup__title">${escapeHtml(layer.name || layer.id)}</div>`,
      `<dl>${propertyRowsHtml(properties, 16)}</dl>`,
      "</div>",
    ].join("");
  }

  function bindFeatureHover(map, mapLayerId, layer, popup) {
    map.on("mousemove", mapLayerId, () => {
      map.getCanvas().style.cursor = "pointer";
    });

    map.on("mouseleave", mapLayerId, () => {
      map.getCanvas().style.cursor = "";
    });
  }

  function addVectorLayerSet(map, sourceId, layer, registry, popup, mapLayerLookup) {
    const types = geometryTypes(layer);
    const paint = styleFor(layer);
    const minzoom = Number.isFinite(paint.minzoom) ? paint.minzoom : 0;
    const layout = { visibility: layerVisibility(layer) };
    const ids = [];

    if (types.has("polygon") || types.has("multipolygon")) {
      const fillId = `${layer.id}-fill`;
      map.addLayer({
        id: fillId,
        type: "fill",
        source: sourceId,
        "source-layer": layer.sourceLayer,
        minzoom,
        layout,
        paint: {
          "fill-color": paint.fill || "#60a5fa",
          "fill-opacity": Number.isFinite(paint.fillOpacity) ? paint.fillOpacity : 0.15,
        },
      });
      ids.push(fillId);
      mapLayerLookup.set(fillId, layer);
      bindFeatureHover(map, fillId, layer, popup);

      const outlineId = `${layer.id}-outline`;
      map.addLayer({
        id: outlineId,
        type: "line",
        source: sourceId,
        "source-layer": layer.sourceLayer,
        minzoom,
        layout,
        paint: {
          "line-color": paint.line || paint.fill || "#2563eb",
          "line-width": Number.isFinite(paint.lineWidth) ? paint.lineWidth : 0.75,
          "line-opacity": 0.92,
        },
      });
      ids.push(outlineId);
      mapLayerLookup.set(outlineId, layer);
      bindFeatureHover(map, outlineId, layer, popup);
    }

    if (types.has("linestring") || types.has("multilinestring")) {
      const lineId = `${layer.id}-line`;
      map.addLayer({
        id: lineId,
        type: "line",
        source: sourceId,
        "source-layer": layer.sourceLayer,
        minzoom,
        layout,
        paint: {
          "line-color": paint.line || paint.fill || "#2563eb",
          "line-width": Number.isFinite(paint.lineWidth) ? paint.lineWidth : 1,
          "line-opacity": 0.92,
        },
      });
      ids.push(lineId);
      mapLayerLookup.set(lineId, layer);
      bindFeatureHover(map, lineId, layer, popup);
    }

    if (types.has("point") || types.has("multipoint")) {
      const pointId = `${layer.id}-point`;
      map.addLayer({
        id: pointId,
        type: "circle",
        source: sourceId,
        "source-layer": layer.sourceLayer,
        minzoom,
        layout,
        paint: {
          "circle-color": paint.fill || paint.line || "#dc2626",
          "circle-radius": 3,
          "circle-opacity": 0.9,
        },
      });
      ids.push(pointId);
      mapLayerLookup.set(pointId, layer);
      bindFeatureHover(map, pointId, layer, popup);
    }

    registry.set(layer.id, ids);
  }

  function isLayerVisible(map, registry, layerId) {
    const mapLayerIds = registry.get(layerId) || [];
    return mapLayerIds.some((mapLayerId) => (
      map.getLayer(mapLayerId) &&
      map.getLayoutProperty(mapLayerId, "visibility") !== "none"
    ));
  }

  function setManifestLayerVisible(map, registry, layerId, visible) {
    const mapLayerIds = registry.get(layerId) || [];
    for (const mapLayerId of mapLayerIds) {
      if (map.getLayer(mapLayerId)) {
        map.setLayoutProperty(mapLayerId, "visibility", visible ? "visible" : "none");
      }
    }
  }

  function setLayerOpacity(map, registry, layerId, opacity) {
    const mapLayerIds = registry.get(layerId) || [];
    for (const mapLayerId of mapLayerIds) {
      if (!map.getLayer(mapLayerId)) {
        continue;
      }
      const layer = map.getLayer(mapLayerId);
      if (layer.type === "raster") {
        map.setPaintProperty(mapLayerId, "raster-opacity", opacity);
      } else if (layer.type === "fill") {
        const current = map.getPaintProperty(mapLayerId, "fill-opacity");
        map.setPaintProperty(mapLayerId, "fill-opacity", Math.min(opacity, Number(current) || opacity));
      } else if (layer.type === "line") {
        map.setPaintProperty(mapLayerId, "line-opacity", opacity);
      }
    }
  }

  function rasterUnits(tileset) {
    if (tileset.units) {
      return tileset.units;
    }
    const id = String(tileset.id || "");
    const mapType = String(tileset.storedMap && tileset.storedMap.mapType || "");
    if (id === "terrain" || mapType === "terrain" || id.includes("wse") || id.includes("depth")) {
      return "ft";
    }
    if (id.includes("velocity") || mapType === "velocity") {
      return "ft/s";
    }
    return "";
  }

  function formatRasterValue(value, units) {
    if (!Number.isFinite(value)) {
      return "";
    }
    const formatted = Math.abs(value) >= 1000
      ? value.toLocaleString(undefined, { maximumFractionDigits: 2 })
      : value.toLocaleString(undefined, { maximumFractionDigits: 3 });
    return units ? `${formatted} ${units}` : formatted;
  }

  function rasterSourceLabel(tileset) {
    if (tileset.id === "terrain" || (tileset.storedMap && tileset.storedMap.mapType === "terrain")) {
      return "Terrain COG";
    }
    if (tileset.storedMap && tileset.storedMap.source === "RasProcess.store_maps") {
      return "RASMapper Stored Map raster";
    }
    return "Raster result COG";
  }

  function featureSourceKind(layer) {
    return isVectorResultLayer(layer) ? "raw-result" : "geometry";
  }

  function featureSourceLabel(layer) {
    return isVectorResultLayer(layer) ? "Raw HDF element result" : "Model geometry";
  }

  function rasterQueryConfig(manifest, tileset) {
    return Object.assign({}, manifest.rasterQuery || {}, tileset.rasterQuery || {});
  }

  function ensureRasterQueryLibraries() {
    if (!window.GeoTIFF || typeof window.GeoTIFF.fromUrl !== "function") {
      throw new Error("GeoTIFF reader did not load.");
    }
    if (!window.proj4) {
      throw new Error("Projection library did not load.");
    }
  }

  function projectLngLatForRaster(lngLat, manifest, tileset) {
    const query = rasterQueryConfig(manifest, tileset);
    const sourceCrs = query.sourceCrs || "EPSG:4326";
    if (sourceCrs === "EPSG:4326") {
      return [lngLat.lng, lngLat.lat];
    }
    if (!query.sourceProj4) {
      throw new Error(`No projection definition for ${sourceCrs}.`);
    }
    window.proj4.defs(sourceCrs, query.sourceProj4);
    return window.proj4("EPSG:4326", sourceCrs, [lngLat.lng, lngLat.lat]);
  }

  async function loadRasterSource(url) {
    if (!rasterSourceCache.has(url)) {
      rasterSourceCache.set(url, (async () => {
        const tiff = await window.GeoTIFF.fromUrl(url);
        const image = await tiff.getImage();
        const noDataRaw = typeof image.getGDALNoData === "function" ? image.getGDALNoData() : null;
        return {
          image,
          width: image.getWidth(),
          height: image.getHeight(),
          origin: image.getOrigin(),
          resolution: image.getResolution(),
          bbox: image.getBoundingBox(),
          noData: noDataRaw === null || noDataRaw === undefined || noDataRaw === "" ? null : Number(noDataRaw),
        };
      })());
    }
    return rasterSourceCache.get(url);
  }

  async function sampleRasterAtClick(tileset, manifest, baseUrl, lngLat) {
    ensureRasterQueryLibraries();
    const url = resolveHref(baseUrl, tileset.sourceCog);
    const source = await loadRasterSource(url);
    const [x, y] = projectLngLatForRaster(lngLat, manifest, tileset);
    const [minX, minY, maxX, maxY] = source.bbox;
    if (x < minX || x > maxX || y < minY || y > maxY) {
      return { tileset, state: "outside" };
    }

    const col = Math.floor((x - source.origin[0]) / source.resolution[0]);
    const row = Math.floor((y - source.origin[1]) / source.resolution[1]);
    if (col < 0 || row < 0 || col >= source.width || row >= source.height) {
      return { tileset, state: "outside" };
    }

    const data = await source.image.readRasters({
      window: [col, row, col + 1, row + 1],
      samples: [0],
      interleave: true,
    });
    const value = Number(data[0]);
    if (!Number.isFinite(value) || (source.noData !== null && Math.abs(value - source.noData) < 1e-9)) {
      return { tileset, state: "nodata", col, row };
    }
    return { tileset, state: "value", value, units: rasterUnits(tileset), col, row };
  }

  function stableFeatureProperties(properties) {
    const normalized = {};
    for (const [key, value] of Object.entries(properties || {}).sort(([a], [b]) => a.localeCompare(b))) {
      normalized[key] = value;
    }
    return JSON.stringify(normalized);
  }

  function collectIdentifyFeatures(map, point, mapLayerLookup) {
    const pad = 5;
    const queryLayers = Array.from(mapLayerLookup.keys())
      .filter((mapLayerId) => (
        map.getLayer(mapLayerId) &&
        map.getLayoutProperty(mapLayerId, "visibility") !== "none"
      ));
    if (!queryLayers.length) {
      return [];
    }

    const features = map.queryRenderedFeatures(
      [[point.x - pad, point.y - pad], [point.x + pad, point.y + pad]],
      { layers: queryLayers }
    );
    const seenFeatures = new Set();
    const byLayer = new Map();
    for (const feature of features) {
      const layer = mapLayerLookup.get(feature.layer && feature.layer.id);
      if (!layer) {
        continue;
      }
      const properties = feature.properties || {};
      const featureKey = `${layer.id}:${feature.id ?? stableFeatureProperties(properties)}`;
      if (seenFeatures.has(featureKey)) {
        continue;
      }
      seenFeatures.add(featureKey);

      const existing = byLayer.get(layer.id);
      if (existing) {
        existing.additionalCount += 1;
        continue;
      }

      byLayer.set(layer.id, {
        layer,
        properties,
        sourceKind: featureSourceKind(layer),
        sourceLabel: featureSourceLabel(layer),
        additionalCount: 0,
      });
    }
    return Array.from(byLayer.values()).slice(0, 10);
  }

  function identifyFeatureHtml(item) {
    const additional = item.additionalCount
      ? `<p class="ras-identify-note">${item.additionalCount.toLocaleString()} additional nearby hit${item.additionalCount === 1 ? "" : "s"} omitted.</p>`
      : "";
    return [
      '<section class="ras-identify-section">',
      `<h4><span>${escapeHtml(item.layer.name || item.layer.id)}</span><span class="ras-identify-source">${escapeHtml(item.sourceLabel)}</span></h4>`,
      `<dl>${propertyRowsHtml(item.properties, 10)}</dl>`,
      additional,
      "</section>",
    ].join("");
  }

  function identifyFeatureGroupHtml(features, kind) {
    const items = features.filter((item) => item.sourceKind === kind);
    return items.map(identifyFeatureHtml).join("");
  }

  function rasterSampleValue(sample) {
    if (sample.state === "value") {
      return formatRasterValue(sample.value, sample.units);
    }
    if (sample.state === "nodata") {
      return "NoData";
    }
    if (sample.state === "outside") {
      return "Outside extent";
    }
    return sample.error || "Unavailable";
  }

  function rasterSampleListHtml(samples) {
    if (!samples.length) {
      return "";
    }
    return [
      '<dl class="ras-identify-raster-list">',
      ...samples.map((sample) => {
        const name = sample.tileset.name || sample.tileset.id;
        const value = rasterSampleValue(sample);
        const source = rasterSourceLabel(sample.tileset);
        return `<dt>${escapeHtml(name)}</dt><dd><span>${escapeHtml(value)}</span><span class="ras-identify-source">${escapeHtml(source)}</span></dd>`;
      }),
      "</dl>",
    ].join("");
  }

  function identifyPopupHtml(lngLat, features, rasterSamples, options) {
    const pending = options && options.pending;
    const rasterTargets = options && options.rasterTargets || 0;
    const coords = `${lngLat.lng.toFixed(6)}, ${lngLat.lat.toFixed(6)}`;
    const terrainSamples = (rasterSamples || [])
      .filter((sample) => sample.tileset.id === "terrain" || sample.tileset.storedMap?.mapType === "terrain");
    const resultRasterSamples = (rasterSamples || [])
      .filter((sample) => !(sample.tileset.id === "terrain" || sample.tileset.storedMap?.mapType === "terrain"));

    let rasterHtml = "";
    if (pending) {
      rasterHtml = `<h3>Rasterized Results</h3><p class="ras-identify-empty">Reading ${rasterTargets} COG value${rasterTargets === 1 ? "" : "s"}...</p>`;
    } else {
      const rasterSections = [];
      if (resultRasterSamples.length) {
        rasterSections.push("<h3>Rasterized Results</h3>", rasterSampleListHtml(resultRasterSamples));
      }
      if (terrainSamples.length) {
        rasterSections.push("<h3>Terrain Raster</h3>", rasterSampleListHtml(terrainSamples));
      }
      rasterHtml = rasterSections.length
        ? rasterSections.join("")
        : "";
    }

    const rawResultHtml = identifyFeatureGroupHtml(features, "raw-result");
    const geometryHtml = identifyFeatureGroupHtml(features, "geometry");
    const sections = [rasterHtml];
    if (rawResultHtml) {
      sections.push("<h3>Raw HDF Results</h3>", rawResultHtml);
    }
    if (geometryHtml) {
      sections.push("<h3>Geometry Metadata</h3>", geometryHtml);
    }
    const bodyHtml = sections.filter(Boolean).join("") ||
      '<p class="ras-identify-empty">No visible queryable map data at this point.</p>';

    return [
      '<div class="ras-identify-popup">',
      '<div class="ras-identify-title">Identify</div>',
      `<div class="ras-identify-coords">${escapeHtml(coords)}</div>`,
      bodyHtml,
      "</div>",
    ].join("");
  }

  function visibleQueryableRasters(manifest, map, registry) {
    return (manifest.tilesets || [])
      .filter((tileset) => (
        tileset.type === "raster" &&
        tileset.sourceCog &&
        tileset.queryable !== false &&
        isLayerVisible(map, registry, tileset.id)
      ));
  }

  function bindIdentifyClick(root, map, manifest, registry, mapLayerLookup, baseUrl) {
    const identifyPopup = new maplibregl.Popup({
      closeButton: true,
      closeOnClick: false,
      maxWidth: "420px",
    });
    let identifySequence = 0;

    map.on("click", (event) => {
      const sequence = ++identifySequence;
      const features = collectIdentifyFeatures(map, event.point, mapLayerLookup);
      const rasterTargets = visibleQueryableRasters(manifest, map, registry);
      identifyPopup
        .setLngLat(event.lngLat)
        .setHTML(identifyPopupHtml(event.lngLat, features, [], {
          pending: rasterTargets.length > 0,
          rasterTargets: rasterTargets.length,
        }))
        .addTo(map);

      if (!rasterTargets.length) {
        return;
      }

      Promise.all(rasterTargets.map((tileset) => (
        sampleRasterAtClick(tileset, manifest, baseUrl, event.lngLat)
          .catch((error) => ({ tileset, state: "error", error: error.message || "Unavailable" }))
      ))).then((samples) => {
        if (sequence !== identifySequence) {
          return;
        }
        identifyPopup.setHTML(identifyPopupHtml(event.lngLat, features, samples, { pending: false }));
      });
    });
  }

  function buildLayerTree(root, map, manifest, registry) {
    const list = root.querySelector("[data-layer-list]");
    if (!list) {
      return;
    }
    const vectorLayers = manifest.tilesets
      .filter((tileset) => tileset.type === "vector")
      .flatMap((tileset) => tileset.layers || [])
      .map(layerTreeEntry);
    const terrainLayers = manifest.tilesets
      .filter((tileset) => tileset.type === "raster")
      .map((tileset) => layerTreeEntry({
        id: tileset.id,
        name: tileset.name || (tileset.id === "terrain" ? "Terrain" : tileset.id),
        groupId: rasterLayerGroupId(tileset),
        visible: Boolean(tileset.visible),
        featureCount: null,
        bytes: tileset.bytes,
        storedMap: tileset.storedMap,
      }));
    const allLayers = [...terrainLayers, ...vectorLayers];
    const layersByGroup = new Map();
    for (const layer of allLayers) {
      const groupId = layer.groupId || (layer.id === "terrain" ? "ras-terrains" : "ungrouped");
      if (!layersByGroup.has(groupId)) {
        layersByGroup.set(groupId, []);
      }
      layersByGroup.get(groupId).push(layer);
    }

    const groups = manifest.groups && manifest.groups.length
      ? manifest.groups.slice()
      : Array.from(layersByGroup.keys()).map((id) => ({ id, name: id, visible: true }));
    const knownGroups = new Set(groups.map((group) => group.id));
    for (const groupId of layersByGroup.keys()) {
      if (!knownGroups.has(groupId)) {
        groups.push({ id: groupId, name: displayGroupName({ id: groupId }), visible: true });
      }
    }

    list.replaceChildren();

    const geometryColumn = document.createElement("div");
    geometryColumn.className = "ras-layer-column";
    geometryColumn.dataset.layerColumn = "geometry";
    const geometryTitle = document.createElement("p");
    geometryTitle.className = "ras-layer-column__title";
    geometryTitle.textContent = "Geometry Data";
    geometryColumn.append(geometryTitle);

    const resultsColumn = document.createElement("div");
    resultsColumn.className = "ras-layer-column";
    resultsColumn.dataset.layerColumn = "results";
    const resultsTitle = document.createElement("p");
    resultsTitle.className = "ras-layer-column__title";
    resultsTitle.textContent = "Results & Terrain";
    resultsColumn.append(resultsTitle);

    list.append(geometryColumn, resultsColumn);

    function columnForGroup(groupId) {
      return String(groupId || "").startsWith("ras-geometry-") ? geometryColumn : resultsColumn;
    }

    function updateGroupCheckbox(groupId) {
      const groupCheckbox = list.querySelector(`[data-group-checkbox="${groupId}"]`);
      if (!groupCheckbox) {
        return;
      }
      const childChecks = Array.from(list.querySelectorAll(`[data-layer-group="${groupId}"]`));
      const checked = childChecks.filter((el) => el.checked).length;
      groupCheckbox.checked = childChecks.length > 0 && checked === childChecks.length;
      groupCheckbox.indeterminate = checked > 0 && checked < childChecks.length;
    }

    function updateSubgroupCheckbox(groupId, subGroupId) {
      const subgroupCheckbox = list.querySelector(
        `[data-subgroup-checkbox][data-layer-group="${groupId}"][data-layer-subgroup="${subGroupId}"]`
      );
      if (!subgroupCheckbox) {
        return;
      }
      const childChecks = Array.from(
        list.querySelectorAll(`[data-layer-group="${groupId}"][data-layer-subgroup="${subGroupId}"][data-layer-id]`)
      );
      const checked = childChecks.filter((el) => el.checked).length;
      subgroupCheckbox.checked = childChecks.length > 0 && checked === childChecks.length;
      subgroupCheckbox.indeterminate = checked > 0 && checked < childChecks.length;
    }

    function appendLayerRow(parent, layer, groupId) {
      const row = document.createElement("label");
      row.className = "ras-layer-row";
      const check = document.createElement("input");
      check.type = "checkbox";
      check.checked = Boolean(layer.visible);
      check.dataset.layerId = layer.id;
      check.dataset.layerGroup = groupId;
      if (layer.subGroupId) {
        check.dataset.layerSubgroup = layer.subGroupId;
      }

      const name = document.createElement("span");
      name.className = "ras-layer-row__name";
      name.textContent = layer.controlName || layer.name || layer.id;

      const count = document.createElement("span");
      count.className = "ras-layer-row__count";
      if (Number.isFinite(layer.featureCount)) {
        count.textContent = layer.featureCount.toLocaleString();
      } else if (Number.isFinite(layer.bytes)) {
        count.textContent = `${(layer.bytes / 1048576).toFixed(1)} MB`;
      }

      check.addEventListener("change", () => {
        setManifestLayerVisible(map, registry, layer.id, check.checked);
        if (layer.subGroupId) {
          updateSubgroupCheckbox(groupId, layer.subGroupId);
        }
        updateGroupCheckbox(groupId);
      });

      row.append(check, name, count);
      parent.append(row);
    }

    function appendLayerSubgroup(parent, groupId, subgroup) {
      const section = document.createElement("div");
      section.className = "ras-layer-subgroup";

      const header = document.createElement("label");
      header.className = "ras-layer-subgroup__header";
      const subgroupCheck = document.createElement("input");
      subgroupCheck.type = "checkbox";
      subgroupCheck.dataset.subgroupCheckbox = "true";
      subgroupCheck.dataset.layerGroup = groupId;
      subgroupCheck.dataset.layerSubgroup = subgroup.id;
      subgroupCheck.checked = subgroup.layers.every((layer) => layer.visible);
      const name = document.createElement("span");
      name.textContent = subgroup.name;
      header.append(subgroupCheck, name);
      section.append(header);

      const children = document.createElement("div");
      children.className = "ras-layer-subgroup__children";
      for (const layer of subgroup.layers) {
        appendLayerRow(children, layer, groupId);
      }

      subgroupCheck.addEventListener("change", () => {
        const checked = subgroupCheck.checked;
        for (const child of children.querySelectorAll("[data-layer-id]")) {
          child.checked = checked;
          setManifestLayerVisible(map, registry, child.dataset.layerId, checked);
        }
        subgroupCheck.indeterminate = false;
        updateGroupCheckbox(groupId);
      });

      section.append(children);
      parent.append(section);
      updateSubgroupCheckbox(groupId, subgroup.id);
    }

    for (const group of groups) {
      const groupLayers = layersByGroup.get(group.id) || [];
      if (!groupLayers.length) {
        continue;
      }

      const section = document.createElement("section");
      section.className = "ras-layer-group";

      const header = document.createElement("label");
      header.className = "ras-layer-group__header";
      const groupCheck = document.createElement("input");
      groupCheck.type = "checkbox";
      groupCheck.dataset.groupCheckbox = group.id;
      groupCheck.checked = groupLayers.every((layer) => layer.visible);
      const groupName = document.createElement("span");
      groupName.textContent = displayGroupName(group);
      header.append(groupCheck, groupName);
      section.append(header);

      const children = document.createElement("div");
      children.className = "ras-layer-group__children";

      const subgroups = new Map();
      for (const layer of groupLayers) {
        if (!layer.subGroupId) {
          appendLayerRow(children, layer, group.id);
          continue;
        }
        if (!subgroups.has(layer.subGroupId)) {
          subgroups.set(layer.subGroupId, {
            id: layer.subGroupId,
            name: layer.subGroupName || layer.subGroupId,
            sort: Number.isFinite(layer.subGroupSort) ? layer.subGroupSort : 9999,
            layers: [],
          });
        }
        subgroups.get(layer.subGroupId).layers.push(layer);
      }

      const sortedSubgroups = Array.from(subgroups.values()).sort((a, b) => (
        a.sort - b.sort || a.name.localeCompare(b.name)
      ));
      for (const subgroup of sortedSubgroups) {
        appendLayerSubgroup(children, group.id, subgroup);
      }

      groupCheck.addEventListener("change", () => {
        const checked = groupCheck.checked;
        for (const child of children.querySelectorAll("[data-layer-id]")) {
          child.checked = checked;
          setManifestLayerVisible(map, registry, child.dataset.layerId, checked);
        }
        for (const subgroupCheck of children.querySelectorAll("[data-subgroup-checkbox]")) {
          subgroupCheck.checked = checked;
          subgroupCheck.indeterminate = false;
        }
        groupCheck.indeterminate = false;
      });

      section.append(children);
      columnForGroup(group.id).append(section);
      updateGroupCheckbox(group.id);
    }

    const terrainOpacity = root.querySelector("[data-terrain-opacity]");
    if (terrainOpacity) {
      terrainOpacity.addEventListener("input", () => {
        setLayerOpacity(map, registry, "terrain", Number(terrainOpacity.value));
      });
    }
  }

  function collectVisibleBounds(manifest) {
    const bounds = [];
    for (const tileset of manifest.tilesets || []) {
      if (tileset.type !== "vector") {
        continue;
      }
      for (const layer of tileset.layers || []) {
        if (layer.visible) {
          bounds.push(layer.bounds);
        }
      }
    }
    return mergeBounds(bounds) || normalizeBounds(manifest.bounds) || DEFAULT_BOUNDS;
  }

  async function init(root) {
    if (!window.maplibregl || !window.pmtiles) {
      status(root, "Map libraries did not load.");
      return;
    }

    const manifestUrl = manifestUrlFor(root);
    const baseUrl = new URL(".", manifestUrl).toString();
    const manifest = await fetch(manifestUrl, { cache: "no-store" }).then((response) => {
      if (!response.ok) {
        throw new Error(`Manifest request failed: ${response.status}`);
      }
      return response.json();
    });
    setProjectChrome(root, manifest, manifestUrl);
    renderProjectAvailability(root, manifest);

    const protocol = new pmtiles.Protocol();
    if (!window.__rasCommanderPmtilesProtocol) {
      maplibregl.addProtocol("pmtiles", protocol.tile);
      window.__rasCommanderPmtilesProtocol = protocol;
    }

    const mapEl = root.querySelector("[data-map]");
    const bounds = collectVisibleBounds(manifest);
    const center = normalizeBounds(bounds)
      ? [(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2]
      : manifest.center || [-85.3789, 40.1967];

    const map = new maplibregl.Map({
      container: mapEl,
      style: {
        version: 8,
        glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
        sources: {},
        layers: [
          {
            id: "background",
            type: "background",
            paint: { "background-color": "#eef2f3" },
          },
        ],
      },
      center,
      zoom: manifest.zoom || 12,
      attributionControl: false,
    });

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-left");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    const registry = new Map();
    const mapLayerLookup = new Map();

    map.on("load", () => {
      addHybridBasemap(map);
      const rasterTilesets = (manifest.tilesets || []).filter((tileset) => tileset.type === "raster");
      const resultTilesets = (manifest.tilesets || []).filter((tileset) => tileset.type === "vector" && tileset.id === "results");
      const geometryTilesets = (manifest.tilesets || []).filter((tileset) => tileset.type === "vector" && tileset.id !== "results");
      const hoverPopup = new maplibregl.Popup({
        closeButton: false,
        closeOnClick: false,
        maxWidth: "360px",
      });

      for (const tileset of rasterTilesets) {
        const sourceId = `${tileset.id}-source`;
        map.addSource(sourceId, {
          type: "raster",
          url: `pmtiles://${resolveTileHref(baseUrl, tileset.href, manifestUrl)}`,
          tileSize: tileset.tileSize || 256,
        });
        const layerId = `${tileset.id}-raster`;
        map.addLayer({
          id: layerId,
          type: "raster",
          source: sourceId,
          layout: { visibility: tileset.visible ? "visible" : "none" },
          paint: { "raster-opacity": Number.isFinite(tileset.opacity) ? tileset.opacity : 1 },
        });
        registry.set(tileset.id, [layerId]);
      }

      for (const tileset of [...resultTilesets, ...geometryTilesets]) {
        const sourceId = `${tileset.id}-source`;
        map.addSource(sourceId, {
          type: "vector",
          url: `pmtiles://${resolveTileHref(baseUrl, tileset.href, manifestUrl)}`,
        });
        for (const layer of tileset.layers || []) {
          addVectorLayerSet(map, sourceId, layer, registry, hoverPopup, mapLayerLookup);
        }
      }

      buildLayerTree(root, map, manifest, registry);
      bindIdentifyClick(root, map, manifest, registry, mapLayerLookup, baseUrl);
      const sidePadding = root.clientWidth > 760 ? 60 : 28;
      map.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], {
        padding: { top: 50, right: sidePadding, bottom: 50, left: sidePadding },
        maxZoom: 15,
        duration: 0,
      });
      status(root, "Ready");
    });

    map.on("error", (event) => {
      const message = event && event.error ? event.error.message : "Map error";
      status(root, message);
    });
  }

  for (const root of roots) {
    init(root).catch((error) => {
      status(root, error.message || "Viewer failed.");
      console.error(error);
    });
  }
})();
