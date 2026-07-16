(function () {
  const roots = document.querySelectorAll("[data-ras-maplibre-viewer]");
  if (!roots.length) {
    return;
  }

  const DEFAULT_BOUNDS = [-85.3942, 40.1896, -85.3601, 40.2057];
  const VIEWER_MANIFEST_REFRESH = "20260716Tmanifest-v2-03";
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
    pipe_conduits: { fill: "#0891b2", fillOpacity: 0, line: "#0891b2", lineWidth: 1.6 },
    pipe_nodes: { fill: "#facc15", fillOpacity: 0.72, line: "#a16207", lineWidth: 0.9 },
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
  const viewerTilesetCache = new WeakMap();

  function isManifestV2(manifest) {
    return manifest.schema === "rascommander.maplibre/v2"
      && manifest.layers
      && typeof manifest.layers === "object"
      && Array.isArray(manifest.tree);
  }

  function v2LayerAsLegacy(manifest, layerId, legacyLayer) {
    const layer = manifest.layers[layerId] || {};
    const resource = manifest.resources?.[layer.resource] || {};
    const numericResourceId = layer.query?.numericResource;
    const numericResource = numericResourceId ? manifest.resources?.[numericResourceId] || {} : {};
    const provenance = layer.provenance && typeof layer.provenance === "object" ? layer.provenance : {};
    const raster = layer.raster && typeof layer.raster === "object" ? layer.raster : {};
    const legendId = layer.style?.legendRef;
    const legend = legendId ? manifest.legends?.[legendId] || {} : {};
    const merged = Object.assign({}, legacyLayer || {}, layer, {
      id: layerId,
      kind: layer.role || legacyLayer?.kind,
      sourceLayer: layer.sourceLayer || legacyLayer?.sourceLayer,
      href: resource.href || legacyLayer?.href,
      sourceCog: numericResource.href || legacyLayer?.sourceCog,
      bytes: resource.bytes ?? legacyLayer?.bytes,
      visible: Boolean(layer.visible),
      queryable: layer.query?.enabled !== false,
      units: raster.units || numericResource.units || legacyLayer?.units,
      rasterStats: raster.statistics || numericResource.statistics || legacyLayer?.rasterStats,
      legend: Object.assign({}, legacyLayer?.legend || {}, legend),
      numericResourceId,
      serviceAsset: numericResource.serviceAsset || legacyLayer?.serviceAsset,
      serviceRevision: numericResource.serviceRevision || legacyLayer?.serviceRevision,
      rasterService: manifest.services?.numericRaster || legacyLayer?.rasterService,
      rawResult: layer.sourceKind === "raw-hdf" ? provenance : legacyLayer?.rawResult,
      storedMap: ["stored-map", "calculated", "terrain"].includes(layer.sourceKind)
        ? provenance
        : legacyLayer?.storedMap,
      sourceKind: layer.sourceKind,
      opacity: layer.style?.opacity ?? legacyLayer?.opacity,
      rasterQuery: Object.assign({}, legacyLayer?.rasterQuery || {}, {
        sourceCrs: numericResource.crs,
        sourceProj4: numericResource.proj4,
      }),
    });
    if (layer.style && typeof layer.style === "object") {
      merged.style = Object.assign({}, legacyLayer?.style || {}, layer.style);
    }
    return merged;
  }

  function viewerTilesets(manifest) {
    if (viewerTilesetCache.has(manifest)) {
      return viewerTilesetCache.get(manifest);
    }

    let tilesets = Array.isArray(manifest.tilesets) ? manifest.tilesets : [];
    if (isManifestV2(manifest) && tilesets.length) {
      tilesets = tilesets.map((tileset) => {
        if (tileset.type === "vector") {
          return Object.assign({}, tileset, {
            layers: (tileset.layers || []).map((layer) => (
              v2LayerAsLegacy(manifest, layer.id, layer)
            )),
          });
        }
        if (tileset.type === "raster" && manifest.layers[tileset.id]) {
          return Object.assign({}, tileset, v2LayerAsLegacy(manifest, tileset.id, tileset));
        }
        return tileset;
      });
    } else if (isManifestV2(manifest)) {
      const vectorResources = new Map();
      const rasterTilesets = [];
      for (const [layerId, layer] of Object.entries(manifest.layers)) {
        const resource = manifest.resources?.[layer.resource] || {};
        if (resource.type === "vector-pmtiles") {
          if (!vectorResources.has(layer.resource)) {
            vectorResources.set(layer.resource, {
              id: layer.resource,
              type: "vector",
              href: resource.href,
              bytes: resource.bytes,
              layers: [],
            });
          }
          vectorResources.get(layer.resource).layers.push(v2LayerAsLegacy(manifest, layerId));
        } else if (resource.type === "raster-pmtiles") {
          rasterTilesets.push(Object.assign({
            id: layerId,
            type: "raster",
            href: resource.href,
            tileSize: resource.tileSize,
          }, v2LayerAsLegacy(manifest, layerId)));
        }
      }
      tilesets = [...vectorResources.values(), ...rasterTilesets];
    }

    viewerTilesetCache.set(manifest, tilesets);
    return tilesets;
  }

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
    return layer.sourceKind === "raw-hdf"
      || groupId === "ras-results"
      || id.startsWith("ras-results-");
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
      || tileset.sourceKind === "terrain"
      || tileset.groupId === "ras-terrains"
      || (tileset.storedMap && tileset.storedMap.mapType === "terrain");
  }

  function projectAvailability(manifest) {
    const tilesets = viewerTilesets(manifest);
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
      .filter((tileset) => tileset.type === "vector")
      .flatMap((tileset) => tileset.layers || [])
      .filter(isVectorResultLayer)
      .length;

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

  function addHybridBasemap(map, registry, visible) {
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
      map.addLayer({
        id,
        type: "raster",
        source: id,
        layout: { visibility: visible === false ? "none" : "visible" },
      });
    }
    registry.set("basemap-hybrid", sources.map(([id]) => id));
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
    const rasterState = registry.rasterStates?.get(layerId);
    if (rasterState) {
      const activeLayerId = rasterState.mode === "dataset" || !rasterState.dynamicReady
        ? rasterState.fixedLayerId
        : rasterState.dynamicLayerId;
      return Boolean(
        activeLayerId
        && map.getLayer(activeLayerId)
        && map.getLayoutProperty(activeLayerId, "visibility") !== "none"
      );
    }
    const mapLayerIds = registry.get(layerId) || [];
    return mapLayerIds.some((mapLayerId) => (
      map.getLayer(mapLayerId) &&
      map.getLayoutProperty(mapLayerId, "visibility") !== "none"
    ));
  }

  function setManifestLayerVisible(map, registry, layerId, visible) {
    const rasterState = registry.rasterStates?.get(layerId);
    if (rasterState) {
      rasterState.visible = visible;
      const useDynamic = rasterState.mode !== "dataset" && rasterState.dynamicReady;
      if (map.getLayer(rasterState.fixedLayerId)) {
        map.setLayoutProperty(
          rasterState.fixedLayerId,
          "visibility",
          visible && !useDynamic ? "visible" : "none"
        );
      }
      if (rasterState.dynamicLayerId && map.getLayer(rasterState.dynamicLayerId)) {
        map.setLayoutProperty(
          rasterState.dynamicLayerId,
          "visibility",
          visible && useDynamic ? "visible" : "none"
        );
      }
      return;
    }
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

  function finiteRasterDomain(domain) {
    if (!domain || domain.minimum === null || domain.minimum === undefined
      || domain.maximum === null || domain.maximum === undefined) {
      return null;
    }
    const minimum = Number(domain.minimum);
    const maximum = Number(domain.maximum);
    return Number.isFinite(minimum) && Number.isFinite(maximum) && maximum >= minimum
      ? { minimum, maximum }
      : null;
  }

  function serviceEndpoint(manifestUrl, service, path) {
    const endpoint = new URL(service.baseUrl, manifestUrl);
    const basePath = endpoint.pathname.replace(/\/$/, "");
    endpoint.pathname = `${basePath}/${String(path || "").replace(/^\//, "")}`;
    return endpoint;
  }

  function tileTemplateUrl(endpoint) {
    return endpoint.toString()
      .replace(/%7B/gi, "{")
      .replace(/%7D/gi, "}");
  }

  function createRasterStyleController(root, map, manifest, manifestUrl, registry) {
    const states = registry.rasterStates || new Map();
    let activeLayerId = null;
    let notify = () => {};

    function serviceReady(state) {
      return Boolean(
        state
        && !state.categorical
        && state.service?.baseUrl
        && state.service?.statisticsPath
        && state.service?.tilePath
        && state.serviceAsset
        && state.serviceRevision
        && state.preset
      );
    }

    function applyVisibility(state) {
      setManifestLayerVisible(map, registry, state.layerId, state.visible);
    }

    function cancelRequest(state) {
      if (state.timer) {
        window.clearTimeout(state.timer);
        state.timer = null;
      }
      if (state.abortController) {
        state.abortController.abort();
        state.abortController = null;
      }
    }

    function firstVectorLayerId() {
      return (map.getStyle().layers || []).find((candidate) => (
        ["fill", "line", "circle", "symbol"].includes(candidate.type)
      ))?.id;
    }

    function styledTileTemplate(state, domain) {
      const endpoint = serviceEndpoint(manifestUrl, state.service, state.service.tilePath);
      endpoint.searchParams.set("asset", state.serviceAsset);
      endpoint.searchParams.set("preset", state.preset);
      endpoint.searchParams.set("minimum", String(domain.minimum));
      endpoint.searchParams.set("maximum", String(domain.maximum));
      endpoint.searchParams.set("revision", state.serviceRevision);
      return tileTemplateUrl(endpoint);
    }

    function ensureDynamicLayer(state, domain) {
      const tiles = [styledTileTemplate(state, domain)];
      let source = state.dynamicSourceId && map.getSource(state.dynamicSourceId);
      if (source && typeof source.setTiles === "function") {
        source.setTiles(tiles);
      } else {
        if (state.dynamicLayerId && map.getLayer(state.dynamicLayerId)) {
          map.removeLayer(state.dynamicLayerId);
        }
        if (state.dynamicSourceId && map.getSource(state.dynamicSourceId)) {
          map.removeSource(state.dynamicSourceId);
        }
        state.dynamicSourceId = `${state.layerId}-styled-source`;
        state.dynamicLayerId = `${state.layerId}-styled-raster`;
        map.addSource(state.dynamicSourceId, {
          type: "raster",
          tiles,
          tileSize: 256,
          attribution: "RAS Commander WebGIS",
        });
        map.addLayer({
          id: state.dynamicLayerId,
          type: "raster",
          source: state.dynamicSourceId,
          layout: { visibility: "none" },
          paint: { "raster-opacity": state.opacity },
        }, firstVectorLayerId());
        const registered = registry.get(state.layerId) || [];
        registry.set(state.layerId, Array.from(new Set([...registered, state.dynamicLayerId])));
      }
      state.dynamicReady = true;
      applyVisibility(state);
    }

    function restoreDataset(state, message) {
      cancelRequest(state);
      state.mode = "dataset";
      state.domain = state.datasetDomain;
      state.dynamicReady = false;
      state.busy = false;
      state.message = message || "Dataset stretch";
      applyVisibility(state);
      notify();
    }

    async function updateCurrentView(state) {
      if (
        !serviceReady(state)
        || state.mode !== "current-view"
        || activeLayerId !== state.layerId
        || !state.visible
      ) {
        return;
      }
      cancelRequest(state);
      const abortController = new AbortController();
      state.abortController = abortController;
      state.busy = true;
      state.message = "Reading current view";
      notify();

      const bounds = map.getBounds();
      const canvas = map.getCanvas();
      const endpoint = serviceEndpoint(manifestUrl, state.service, state.service.statisticsPath);
      endpoint.searchParams.set("asset", state.serviceAsset);
      endpoint.searchParams.set(
        "bbox",
        [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].join(",")
      );
      endpoint.searchParams.set("width", String(Math.max(1, canvas.clientWidth || 1)));
      endpoint.searchParams.set("height", String(Math.max(1, canvas.clientHeight || 1)));
      endpoint.searchParams.set("exact", state.exact ? "true" : "false");
      endpoint.searchParams.set("revision", state.serviceRevision);

      try {
        const response = await fetch(endpoint, {
          signal: abortController.signal,
          headers: { Accept: "application/json" },
        });
        if (!response.ok) {
          throw new Error(`Current-view statistics failed (${response.status})`);
        }
        const result = await response.json();
        const domain = finiteRasterDomain(result.domain);
        if (!domain) {
          throw new Error("Current view has no finite raster range");
        }
        if (state.mode !== "current-view" || activeLayerId !== state.layerId) {
          return;
        }
        state.domain = domain;
        state.busy = false;
        state.message = state.exact ? "Exact range for current view" : "2nd-98th percentile for current view";
        ensureDynamicLayer(state, domain);
        notify();
      } catch (error) {
        if (error.name !== "AbortError") {
          restoreDataset(state, `${error.message}. Showing dataset stretch.`);
        }
      } finally {
        if (state.abortController === abortController) {
          state.abortController = null;
        }
      }
    }

    function scheduleCurrentView(state, delay) {
      if (!state || state.mode !== "current-view") {
        return;
      }
      if (state.timer) {
        window.clearTimeout(state.timer);
      }
      state.timer = window.setTimeout(() => {
        state.timer = null;
        updateCurrentView(state);
      }, delay ?? 250);
    }

    function setMode(state, mode) {
      cancelRequest(state);
      state.mode = mode;
      state.busy = false;
      if (mode === "dataset") {
        state.domain = state.datasetDomain;
        state.dynamicReady = false;
        state.message = "Dataset stretch";
        applyVisibility(state);
      } else if (mode === "current-view") {
        state.dynamicReady = false;
        state.message = "Waiting for current-view range";
        applyVisibility(state);
        scheduleCurrentView(state, 0);
      } else if (mode === "custom") {
        const domain = finiteRasterDomain(state.customDomain || state.datasetDomain);
        if (!domain) {
          restoreDataset(state, "The custom range is invalid. Showing dataset stretch.");
          return;
        }
        state.domain = domain;
        state.customDomain = domain;
        state.message = "Custom range";
        ensureDynamicLayer(state, domain);
      }
      notify();
    }

    function renderLegend(panel, state) {
      const legend = state.legend || {};
      const heading = document.createElement("div");
      heading.className = "ras-raster-legend__heading";
      const label = document.createElement("strong");
      label.textContent = "Legend";
      const range = document.createElement("span");
      const domain = finiteRasterDomain(state.domain || state.datasetDomain);
      range.textContent = domain
        ? `${formatRasterValue(domain.minimum, state.units)} to ${formatRasterValue(domain.maximum, state.units)}`
        : "Fixed categories";
      heading.append(label, range);
      panel.append(heading);

      if (state.categorical && Array.isArray(legend.categories)) {
        const categories = document.createElement("div");
        categories.className = "ras-raster-categories";
        for (const category of legend.categories) {
          const item = document.createElement("span");
          const swatch = document.createElement("i");
          swatch.style.backgroundColor = category.color || "#64748b";
          item.append(swatch, document.createTextNode(category.label || String(category.value)));
          categories.append(item);
        }
        panel.append(categories);
        return;
      }

      const colors = Array.isArray(legend.colors) && legend.colors.length
        ? legend.colors
        : ["#eff6ff", "#1e3a8a"];
      const bar = document.createElement("div");
      bar.className = "ras-raster-legend__bar";
      bar.style.background = `linear-gradient(90deg, ${colors.join(", ")})`;
      panel.append(bar);
    }

    function renderInspector(parent, layerId) {
      const state = states.get(layerId);
      if (!state) {
        return;
      }
      const panel = document.createElement("div");
      panel.className = "ras-raster-style";
      renderLegend(panel, state);

      if (serviceReady(state)) {
        const modes = document.createElement("div");
        modes.className = "ras-raster-modes";
        modes.setAttribute("aria-label", "Raster legend range");
        for (const [mode, name] of [
          ["dataset", "Dataset"],
          ["current-view", "Current View"],
          ["custom", "Custom"],
        ]) {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = name;
          button.className = state.mode === mode ? "is-selected" : "";
          button.setAttribute("aria-pressed", state.mode === mode ? "true" : "false");
          button.addEventListener("click", () => setMode(state, mode));
          modes.append(button);
        }
        panel.append(modes);

        if (state.mode === "current-view") {
          const exact = document.createElement("label");
          exact.className = "ras-raster-exact";
          const checkbox = document.createElement("input");
          checkbox.type = "checkbox";
          checkbox.checked = state.exact;
          checkbox.addEventListener("change", () => {
            state.exact = checkbox.checked;
            scheduleCurrentView(state, 0);
          });
          exact.append(checkbox, document.createTextNode("Use exact minimum and maximum"));
          panel.append(exact);
        }

        if (state.mode === "custom") {
          const custom = document.createElement("div");
          custom.className = "ras-raster-custom";
          const minimum = document.createElement("input");
          minimum.type = "number";
          minimum.step = "any";
          minimum.setAttribute("aria-label", "Custom minimum");
          minimum.value = String((state.customDomain || state.datasetDomain)?.minimum ?? "");
          const maximum = document.createElement("input");
          maximum.type = "number";
          maximum.step = "any";
          maximum.setAttribute("aria-label", "Custom maximum");
          maximum.value = String((state.customDomain || state.datasetDomain)?.maximum ?? "");
          const apply = document.createElement("button");
          apply.type = "button";
          apply.textContent = "Apply";
          apply.addEventListener("click", () => {
            const domain = finiteRasterDomain({
              minimum: Number(minimum.value),
              maximum: Number(maximum.value),
            });
            if (!domain) {
              state.message = "Enter a finite minimum no greater than the maximum";
              notify();
              return;
            }
            state.customDomain = domain;
            setMode(state, "custom");
          });
          custom.append(minimum, maximum, apply);
          panel.append(custom);
        }
      }

      const message = document.createElement("p");
      message.className = state.busy ? "ras-raster-style__status is-busy" : "ras-raster-style__status";
      message.textContent = state.message || (serviceReady(state)
        ? "Dataset stretch"
        : "Current-view styling is not published for this layer");
      panel.append(message);
      parent.append(panel);
    }

    return {
      setNotify(callback) {
        notify = callback || (() => {});
      },
      activate(layerId) {
        activeLayerId = layerId;
        const state = states.get(layerId);
        if (state?.mode === "current-view") {
          scheduleCurrentView(state, 0);
        }
      },
      visibilityChanged(layerId) {
        const state = states.get(layerId);
        if (state?.mode === "current-view" && state.visible && activeLayerId === layerId) {
          scheduleCurrentView(state, 0);
        }
      },
      moveEnded() {
        const state = states.get(activeLayerId);
        if (state?.mode === "current-view" && state.visible) {
          scheduleCurrentView(state, 250);
        }
      },
      setRangeMode(layerId, mode, options) {
        const state = states.get(layerId);
        if (!state || !["dataset", "current-view", "custom"].includes(mode)) {
          return false;
        }
        if (options && typeof options === "object") {
          state.exact = Boolean(options.exact);
          const customDomain = finiteRasterDomain(options.domain);
          if (customDomain) {
            state.customDomain = customDomain;
          }
        }
        setMode(state, mode);
        return true;
      },
      isIdle(layerId) {
        const state = states.get(layerId || activeLayerId);
        return !state || (!state.busy && !state.timer && !state.abortController);
      },
      refresh() {
        notify();
      },
      renderInspector,
    };
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
    if (tileset.sourceKind === "terrain"
      || tileset.id === "terrain"
      || (tileset.storedMap && tileset.storedMap.mapType === "terrain")) {
      return "Terrain COG";
    }
    if (tileset.sourceKind === "calculated") {
      return "Calculated numeric raster";
    }
    if (tileset.sourceKind === "stored-map"
      || (tileset.storedMap && tileset.storedMap.source === "RasProcess.store_maps")) {
      return "RASMapper Stored Map raster";
    }
    return "Raster result COG";
  }

  function featureSourceKind(layer) {
    return layer.sourceKind === "raw-hdf" || isVectorResultLayer(layer) ? "raw-result" : "geometry";
  }

  function featureSourceLabel(layer) {
    return layer.sourceKind === "raw-hdf" || isVectorResultLayer(layer)
      ? "Raw HDF element result"
      : "Model geometry";
  }

  function rasterQueryConfig(manifest, tileset) {
    const config = Object.assign({}, manifest.rasterQuery || {}, tileset.rasterQuery || {});
    for (const key of Object.keys(config)) {
      if (config[key] === undefined || config[key] === null || config[key] === "") {
        delete config[key];
      }
    }
    return config;
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

  async function sampleRasterFromService(tileset, manifest, manifestUrl, lngLat) {
    const service = tileset.rasterService || manifest.services?.numericRaster || {};
    if (
      !service.baseUrl
      || !service.samplePath
      || !tileset.serviceAsset
      || !tileset.serviceRevision
    ) {
      return null;
    }
    const endpoint = serviceEndpoint(manifestUrl, service, service.samplePath);
    endpoint.searchParams.set("asset", tileset.serviceAsset);
    endpoint.searchParams.set("lng", String(lngLat.lng));
    endpoint.searchParams.set("lat", String(lngLat.lat));
    endpoint.searchParams.set("revision", tileset.serviceRevision);
    const response = await fetch(endpoint, { headers: { Accept: "application/json" } });
    if (!response.ok) {
      throw new Error(`Raster point service failed (${response.status})`);
    }
    const result = await response.json();
    if (!["value", "nodata", "outside"].includes(result.state)) {
      throw new Error("Raster point service returned an invalid state");
    }
    if (result.state === "value" && !Number.isFinite(Number(result.value))) {
      throw new Error("Raster point service returned a non-numeric value");
    }
    return {
      tileset,
      state: result.state,
      value: result.state === "value" ? Number(result.value) : undefined,
      units: result.units || rasterUnits(tileset),
      col: result.column,
      row: result.row,
    };
  }

  async function sampleRasterAtClick(tileset, manifest, baseUrl, lngLat) {
    const serviceSample = await sampleRasterFromService(
      tileset,
      manifest,
      baseUrl,
      lngLat
    );
    if (serviceSample) {
      return serviceSample;
    }
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

  function createInteractionState(manifest) {
    if (!isManifestV2(manifest)) {
      return { semantic: false, activeLayerId: null, pinnedLayerIds: new Set() };
    }
    const configured = manifest.interaction || {};
    const layerIds = new Set(Object.keys(manifest.layers));
    let activeLayerId = layerIds.has(configured.activeLayerId) ? configured.activeLayerId : null;
    if (!activeLayerId) {
      activeLayerId = Object.entries(manifest.layers).find(([, layer]) => (
        layer.visible && layer.query?.enabled
      ))?.[0] || null;
    }
    const maxPinnedLayers = Number(configured.identify?.maxPinnedLayers) || 3;
    const pinnedLayerIds = new Set(
      (configured.pinnedLayerIds || [])
        .filter((layerId) => layerIds.has(layerId) && layerId !== activeLayerId)
        .slice(0, maxPinnedLayers)
    );
    return {
      semantic: true,
      activeLayerId,
      pinnedLayerIds,
      maxPinnedLayers,
    };
  }

  function identifyLayerIds(interactionState) {
    if (!interactionState.semantic) {
      return null;
    }
    return Array.from(new Set(
      [interactionState.activeLayerId, ...interactionState.pinnedLayerIds].filter(Boolean)
    ));
  }

  function isQueryableLayer(layer) {
    return Boolean(layer && layer.query && layer.query.enabled);
  }

  function stableFeatureProperties(properties) {
    const normalized = {};
    for (const [key, value] of Object.entries(properties || {}).sort(([a], [b]) => a.localeCompare(b))) {
      normalized[key] = value;
    }
    return JSON.stringify(normalized);
  }

  function collectIdentifyFeatures(map, point, mapLayerLookup, targetLayerIds) {
    const pad = 5;
    const targets = targetLayerIds ? new Set(targetLayerIds) : null;
    const queryLayers = Array.from(mapLayerLookup.keys())
      .filter((mapLayerId) => (
        map.getLayer(mapLayerId) &&
        map.getLayoutProperty(mapLayerId, "visibility") !== "none" &&
        (!targets || targets.has(mapLayerLookup.get(mapLayerId)?.id)) &&
        (!targets || mapLayerLookup.get(mapLayerId)?.query?.enabled !== false)
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
    const order = new Map((targetLayerIds || []).map((layerId, index) => [layerId, index]));
    return Array.from(byLayer.values())
      .sort((a, b) => (order.get(a.layer.id) ?? 9999) - (order.get(b.layer.id) ?? 9999))
      .slice(0, 10);
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
      .filter((sample) => sample.tileset.sourceKind === "terrain"
        || sample.tileset.id === "terrain"
        || sample.tileset.storedMap?.mapType === "terrain");
    const resultRasterSamples = (rasterSamples || [])
      .filter((sample) => !(sample.tileset.sourceKind === "terrain"
        || sample.tileset.id === "terrain"
        || sample.tileset.storedMap?.mapType === "terrain"));

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
      options?.targetLabel
        ? `<div class="ras-identify-target">${escapeHtml(options.targetLabel)}</div>`
        : "",
      bodyHtml,
      "</div>",
    ].join("");
  }

  function visibleQueryableRasters(manifest, map, registry, targetLayerIds) {
    const targets = targetLayerIds ? new Set(targetLayerIds) : null;
    return viewerTilesets(manifest)
      .filter((tileset) => (
        tileset.type === "raster" &&
        tileset.sourceCog &&
        tileset.queryable !== false &&
        (!targets || targets.has(tileset.id)) &&
        isLayerVisible(map, registry, tileset.id)
      ));
  }

  function bindIdentifyClick(root, map, manifest, registry, mapLayerLookup, baseUrl, interactionState) {
    const identifyPopup = new maplibregl.Popup({
      closeButton: true,
      closeOnClick: false,
      maxWidth: "420px",
    });
    const identifySheet = root.querySelector("[data-identify-sheet]");
    let identifySequence = 0;

    function renderIdentify(lngLat, html) {
      const mobile = window.matchMedia("(max-width: 760px)").matches;
      if (!mobile || !identifySheet) {
        identifyPopup.setLngLat(lngLat).setHTML(html).addTo(map);
        return;
      }
      identifyPopup.remove();
      identifySheet.hidden = false;
      identifySheet.replaceChildren();
      const close = document.createElement("button");
      close.type = "button";
      close.className = "ras-identify-sheet__close";
      close.setAttribute("aria-label", "Close Identify results");
      close.textContent = "\u00d7";
      close.addEventListener("click", () => {
        identifySheet.hidden = true;
        identifySheet.replaceChildren();
      });
      const body = document.createElement("div");
      body.innerHTML = html;
      identifySheet.append(close, body);
    }

    map.on("click", (event) => {
      const sequence = ++identifySequence;
      const targetLayerIds = identifyLayerIds(interactionState);
      const features = collectIdentifyFeatures(map, event.point, mapLayerLookup, targetLayerIds);
      const rasterTargets = visibleQueryableRasters(manifest, map, registry, targetLayerIds);
      const activeLayer = interactionState.activeLayerId
        ? manifest.layers?.[interactionState.activeLayerId]
        : null;
      const targetLabel = interactionState.semantic
        ? activeLayer
          ? `Active: ${activeLayer.name || interactionState.activeLayerId}${interactionState.pinnedLayerIds.size ? ` | ${interactionState.pinnedLayerIds.size} pinned` : ""}`
          : "No active query layer selected"
        : "";
      renderIdentify(event.lngLat, identifyPopupHtml(event.lngLat, features, [], {
        pending: rasterTargets.length > 0,
        rasterTargets: rasterTargets.length,
        targetLabel,
      }));

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
        renderIdentify(event.lngLat, identifyPopupHtml(event.lngLat, features, samples, {
          pending: false,
          targetLabel,
        }));
      });
    });
  }

  function buildLegacyLayerTree(root, map, manifest, registry) {
    const list = root.querySelector("[data-layer-list]");
    if (!list) {
      return;
    }
    const vectorLayers = viewerTilesets(manifest)
      .filter((tileset) => tileset.type === "vector")
      .flatMap((tileset) => tileset.layers || [])
      .map(layerTreeEntry);
    const terrainLayers = viewerTilesets(manifest)
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

  function semanticTreeLayerIds(node) {
    const ids = [];
    if (node.layerId) {
      ids.push(node.layerId);
    }
    for (const child of node.children || []) {
      ids.push(...semanticTreeLayerIds(child));
    }
    return ids;
  }

  function semanticLayerMetric(manifest, layer) {
    if (Number.isFinite(layer.featureCount)) {
      return layer.featureCount.toLocaleString();
    }
    const resource = manifest.resources?.[layer.resource] || {};
    if (Number.isFinite(resource.bytes)) {
      return `${(resource.bytes / 1048576).toFixed(1)} MB`;
    }
    const statistics = layer.raster?.statistics || {};
    if (Number.isFinite(statistics.width) && Number.isFinite(statistics.height)) {
      return `${statistics.width.toLocaleString()} x ${statistics.height.toLocaleString()}`;
    }
    return "";
  }

  function semanticSourceLabel(layer) {
    const labels = {
      "raw-hdf": "Raw HDF computation values",
      "stored-map": "RASMapper Stored Map",
      calculated: "Calculated raster",
      terrain: "Project terrain",
      geometry: "Model geometry",
      "map-layer": "Reference map",
    };
    return labels[layer.sourceKind] || "Project layer";
  }

  function buildSemanticLayerTree(
    root,
    map,
    manifest,
    registry,
    interactionState,
    rasterStyleController
  ) {
    const list = root.querySelector("[data-layer-list]");
    if (!list) {
      return;
    }
    const openNodeIds = new Set();
    const rootIds = new Set((manifest.tree || []).map((node) => node.id));

    function containsActive(node) {
      return semanticTreeLayerIds(node).includes(interactionState.activeLayerId);
    }

    function initializeOpenState(node, depth) {
      if (containsActive(node) || (depth === 0 && node.id === "geometries")) {
        openNodeIds.add(node.id);
      }
      for (const child of node.children || []) {
        initializeOpenState(child, depth + 1);
      }
    }

    for (const node of manifest.tree || []) {
      initializeOpenState(node, 0);
    }

    function setLayerVisible(layerId, visible) {
      const layer = manifest.layers[layerId];
      if (layer) {
        layer.visible = visible;
      }
      setManifestLayerVisible(map, registry, layerId, visible);
      rasterStyleController?.visibilityChanged(layerId);
    }

    function renderLayerInspector(parent, layerId, layer) {
      const inspector = document.createElement("div");
      inspector.className = "ras-layer-inspector";

      const source = document.createElement("p");
      source.className = "ras-layer-inspector__source";
      const context = [semanticSourceLabel(layer)];
      if (layer.plan) {
        context.push(`Plan ${layer.plan}`);
      }
      if (layer.geometry) {
        context.push(`Geometry ${layer.geometry}`);
      }
      source.textContent = context.join(" | ");

      const actions = document.createElement("div");
      actions.className = "ras-layer-inspector__actions";
      const bounds = normalizeBounds(layer.bounds);
      if (bounds) {
        const zoom = document.createElement("button");
        zoom.type = "button";
        zoom.textContent = "Zoom";
        zoom.addEventListener("click", () => {
          map.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], {
            padding: 48,
            maxZoom: 16,
          });
        });
        actions.append(zoom);
      }

      if (isQueryableLayer(layer)) {
        const pinned = interactionState.pinnedLayerIds.has(layerId);
        const pin = document.createElement("button");
        pin.type = "button";
        pin.textContent = pinned ? "Unpin comparison" : "Pin comparison";
        pin.disabled = !pinned
          && interactionState.pinnedLayerIds.size >= interactionState.maxPinnedLayers;
        pin.addEventListener("click", () => {
          if (pinned) {
            interactionState.pinnedLayerIds.delete(layerId);
          } else {
            interactionState.pinnedLayerIds.add(layerId);
          }
          render();
        });
        actions.append(pin);
      }

      const downloadResourceId = layer.query?.numericResource || layer.resource;
      const downloadResource = manifest.resources?.[downloadResourceId];
      if (downloadResource?.href) {
        const open = document.createElement("a");
        open.href = resolveHref(new URL(".", manifestUrlFor(root)).toString(), downloadResource.href);
        open.textContent = layer.query?.numericResource ? "Open numeric data" : "Open source";
        open.target = "_blank";
        open.rel = "noopener";
        actions.append(open);
      }

      inspector.append(source, actions);
      rasterStyleController?.renderInspector(inspector, layerId);
      parent.append(inspector);
    }

    function renderLeaf(node) {
      const layerId = node.layerId;
      const layer = manifest.layers[layerId];
      const wrapper = document.createElement("div");
      wrapper.className = "ras-tree-leaf-wrap";
      if (!layer) {
        return wrapper;
      }

      const row = document.createElement("div");
      row.className = "ras-tree-leaf";
      row.dataset.layerId = layerId;
      const active = interactionState.activeLayerId === layerId;
      if (active) {
        row.classList.add("is-active");
      }
      if (interactionState.pinnedLayerIds.has(layerId)) {
        row.classList.add("is-pinned");
      }

      const visibility = document.createElement("input");
      visibility.type = "checkbox";
      visibility.checked = Boolean(layer.visible);
      visibility.setAttribute("aria-label", `Show ${layer.name || node.name || layerId}`);
      visibility.addEventListener("change", () => {
        setLayerVisible(layerId, visibility.checked);
        render();
      });

      const swatch = document.createElement("span");
      swatch.className = `ras-tree-leaf__swatch ras-tree-leaf__swatch--${slugify(layer.sourceKind || layer.role)}`;
      swatch.setAttribute("aria-hidden", "true");

      const select = document.createElement("button");
      select.type = "button";
      select.className = "ras-tree-leaf__name";
      select.textContent = layer.name || node.name || layerId;
      select.title = `Use ${select.textContent} for Identify`;
      select.addEventListener("click", () => {
        interactionState.activeLayerId = layerId;
        interactionState.pinnedLayerIds.delete(layerId);
        rasterStyleController?.activate(layerId);
        render();
      });

      const metric = document.createElement("span");
      metric.className = "ras-tree-leaf__metric";
      metric.textContent = semanticLayerMetric(manifest, layer);
      if (interactionState.pinnedLayerIds.has(layerId)) {
        metric.textContent = metric.textContent ? `${metric.textContent} | Pinned` : "Pinned";
      }

      row.append(visibility, swatch, select, metric);
      wrapper.append(row);
      if (active) {
        renderLayerInspector(wrapper, layerId, layer);
      }
      return wrapper;
    }

    function renderBranch(node, depth, isRoot) {
      if (node.layerId) {
        return renderLeaf(node);
      }
      const details = document.createElement("details");
      details.className = isRoot ? "ras-tree-root" : "ras-tree-branch";
      details.dataset.treeNodeId = node.id;
      details.open = openNodeIds.has(node.id) || containsActive(node);

      const summary = document.createElement("summary");
      const layerIds = semanticTreeLayerIds(node);
      if (!isRoot) {
        const branchVisibility = document.createElement("input");
        branchVisibility.type = "checkbox";
        branchVisibility.setAttribute("aria-label", `Show all ${node.name}`);
        const visibleCount = layerIds.filter((layerId) => manifest.layers[layerId]?.visible).length;
        branchVisibility.checked = layerIds.length > 0 && visibleCount === layerIds.length;
        branchVisibility.indeterminate = visibleCount > 0 && visibleCount < layerIds.length;
        branchVisibility.disabled = layerIds.length === 0;
        branchVisibility.addEventListener("click", (event) => event.stopPropagation());
        branchVisibility.addEventListener("change", () => {
          for (const layerId of layerIds) {
            setLayerVisible(layerId, branchVisibility.checked);
          }
          render();
        });
        summary.append(branchVisibility);
      }

      const name = document.createElement("span");
      name.className = "ras-tree-node__name";
      name.textContent = node.name || node.id;
      const count = document.createElement("span");
      count.className = "ras-tree-node__count";
      count.textContent = layerIds.length ? layerIds.length.toLocaleString() : "";
      summary.append(name, count);

      const children = document.createElement("div");
      children.className = "ras-tree-children";
      if ((node.children || []).length) {
        for (const child of node.children) {
          children.append(renderBranch(child, depth + 1, false));
        }
      } else {
        const empty = document.createElement("p");
        empty.className = "ras-tree-empty";
        empty.textContent = "Not published";
        children.append(empty);
      }
      details.append(summary, children);
      details.addEventListener("toggle", () => {
        if (details.open) {
          openNodeIds.add(node.id);
          if (isRoot && window.matchMedia("(max-width: 760px)").matches) {
            for (const sibling of list.querySelectorAll("details.ras-tree-root[open]")) {
              if (sibling !== details) {
                sibling.open = false;
              }
            }
          }
        } else {
          openNodeIds.delete(node.id);
        }
      });
      return details;
    }

    function makeColumn(kind, title) {
      const column = document.createElement("div");
      column.className = "ras-layer-column ras-semantic-column";
      column.dataset.layerColumn = kind;
      const heading = document.createElement("p");
      heading.className = "ras-layer-column__title";
      heading.textContent = title;
      column.append(heading);
      return column;
    }

    function render() {
      list.replaceChildren();
      const modelColumn = makeColumn("model", "Model Data");
      const resultColumn = makeColumn("results", "Surfaces and Results");
      list.append(modelColumn, resultColumn);

      for (const node of manifest.tree || []) {
        const target = ["features", "geometries", "map-layers"].includes(node.id)
          ? modelColumn
          : resultColumn;
        target.append(renderBranch(node, 0, rootIds.has(node.id)));
      }
    }

    rasterStyleController?.setNotify(render);
    render();
  }

  function buildLayerTree(root, map, manifest, registry, interactionState, rasterStyleController) {
    if (isManifestV2(manifest)) {
      buildSemanticLayerTree(
        root,
        map,
        manifest,
        registry,
        interactionState,
        rasterStyleController
      );
      return;
    }
    buildLegacyLayerTree(root, map, manifest, registry);
  }

  function collectVisibleBounds(manifest) {
    const bounds = [];
    for (const tileset of viewerTilesets(manifest)) {
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
    const interactionState = createInteractionState(manifest);

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
    registry.rasterStates = new Map();
    const mapLayerLookup = new Map();

    map.on("load", () => {
      const basemapVisible = manifest.layers?.["basemap-hybrid"]?.visible !== false;
      addHybridBasemap(map, registry, basemapVisible);
      const tilesets = viewerTilesets(manifest);
      const rasterTilesets = tilesets.filter((tileset) => tileset.type === "raster");
      const resultTilesets = tilesets.filter((tileset) => (
        tileset.type === "vector"
        && (tileset.id === "results" || (tileset.layers || []).some(isVectorResultLayer))
      ));
      const geometryTilesets = tilesets.filter((tileset) => (
        tileset.type === "vector" && !resultTilesets.includes(tileset)
      ));
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
        const legend = tileset.legend && typeof tileset.legend === "object"
          ? tileset.legend
          : {};
        const datasetDomain = finiteRasterDomain(legend.domain)
          || finiteRasterDomain(tileset.rasterStats);
        const service = tileset.rasterService || manifest.services?.numericRaster || {};
        const categorical = legend.type === "categorical";
        const canStyleCurrentView = Boolean(
          !categorical
          && service.baseUrl
          && service.statisticsPath
          && service.tilePath
          && tileset.serviceAsset
          && tileset.serviceRevision
          && legend.preset
        );
        const preferredPolicy = tileset.style?.domainPolicy
          || legend.domainPolicy
          || tileset.domainPolicy
          || "fixed";
        registry.rasterStates.set(tileset.id, {
          layerId: tileset.id,
          fixedLayerId: layerId,
          dynamicLayerId: null,
          dynamicSourceId: null,
          dynamicReady: false,
          visible: Boolean(tileset.visible),
          opacity: Number.isFinite(tileset.opacity) ? tileset.opacity : 1,
          mode: preferredPolicy === "current-view" && canStyleCurrentView
            ? "current-view"
            : "dataset",
          exact: false,
          busy: false,
          message: preferredPolicy === "current-view" && canStyleCurrentView
            ? "Waiting for current-view range"
            : "Dataset stretch",
          datasetDomain,
          customDomain: datasetDomain,
          domain: datasetDomain,
          categorical,
          legend,
          units: tileset.units || legend.units || "",
          service,
          serviceAsset: tileset.serviceAsset,
          serviceRevision: tileset.serviceRevision,
          preset: legend.preset,
          timer: null,
          abortController: null,
        });
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

      const rasterStyleController = createRasterStyleController(
        root,
        map,
        manifest,
        manifestUrl,
        registry
      );
      buildLayerTree(
        root,
        map,
        manifest,
        registry,
        interactionState,
        rasterStyleController
      );
      bindIdentifyClick(root, map, manifest, registry, mapLayerLookup, baseUrl, interactionState);
      rasterStyleController.activate(interactionState.activeLayerId);
      map.on("moveend", () => rasterStyleController.moveEnded());
      window.__rasCommanderViewerInstances = window.__rasCommanderViewerInstances || [];
      window.__rasCommanderViewerInstances.push({
        root,
        map,
        manifest,
        interactionState,
        setActiveLayer(layerId) {
          if (!manifest.layers?.[layerId]) {
            return false;
          }
          interactionState.activeLayerId = layerId;
          interactionState.pinnedLayerIds.delete(layerId);
          rasterStyleController.activate(layerId);
          rasterStyleController.refresh();
          return true;
        },
        setLayerVisible(layerId, visible) {
          if (!manifest.layers?.[layerId]) {
            return false;
          }
          manifest.layers[layerId].visible = Boolean(visible);
          setManifestLayerVisible(map, registry, layerId, Boolean(visible));
          rasterStyleController.visibilityChanged(layerId);
          rasterStyleController.refresh();
          return true;
        },
        setRangeMode(layerId, mode, options) {
          return rasterStyleController.setRangeMode(layerId, mode, options);
        },
        isIdle(layerId) {
          return rasterStyleController.isIdle(layerId);
        },
      });
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
