(function () {
  const roots = document.querySelectorAll("[data-ras-maplibre-viewer]");
  if (!roots.length) {
    return;
  }

  const DEFAULT_BOUNDS = [-85.3942, 40.1896, -85.3601, 40.2057];
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
    return Object.assign({}, fallback, raw);
  }

  function layerVisibility(layer) {
    return layer.visible ? "visible" : "none";
  }

  function addVectorLayerSet(map, sourceId, layer, registry) {
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
    }

    registry.set(layer.id, ids);
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

  function buildLayerTree(root, map, manifest, registry) {
    const list = root.querySelector("[data-layer-list]");
    if (!list) {
      return;
    }
    const vectorLayers = manifest.tilesets
      .filter((tileset) => tileset.type === "vector")
      .flatMap((tileset) => tileset.layers || []);
    const terrainLayers = manifest.tilesets
      .filter((tileset) => tileset.type === "raster")
      .map((tileset) => ({
        id: tileset.id,
        name: "Terrain",
        groupId: "ras-terrains",
        visible: Boolean(tileset.visible),
        featureCount: null,
        bytes: tileset.bytes,
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
      ? manifest.groups
      : Array.from(layersByGroup.keys()).map((id) => ({ id, name: id, visible: true }));

    list.replaceChildren();

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
      groupName.textContent = group.name;
      header.append(groupCheck, groupName);
      section.append(header);

      const children = document.createElement("div");
      children.className = "ras-layer-group__children";

      for (const layer of groupLayers) {
        const row = document.createElement("label");
        row.className = "ras-layer-row";
        const check = document.createElement("input");
        check.type = "checkbox";
        check.checked = Boolean(layer.visible);
        check.dataset.layerId = layer.id;
        check.dataset.layerGroup = group.id;

        const name = document.createElement("span");
        name.className = "ras-layer-row__name";
        name.textContent = layer.name || layer.id;

        const count = document.createElement("span");
        count.className = "ras-layer-row__count";
        if (Number.isFinite(layer.featureCount)) {
          count.textContent = layer.featureCount.toLocaleString();
        } else if (Number.isFinite(layer.bytes)) {
          count.textContent = `${(layer.bytes / 1048576).toFixed(1)} MB`;
        }

        check.addEventListener("change", () => {
          setManifestLayerVisible(map, registry, layer.id, check.checked);
          updateGroupCheckbox(group.id);
        });

        row.append(check, name, count);
        children.append(row);
      }

      groupCheck.addEventListener("change", () => {
        const checked = groupCheck.checked;
        for (const child of children.querySelectorAll("[data-layer-id]")) {
          child.checked = checked;
          setManifestLayerVisible(map, registry, child.dataset.layerId, checked);
        }
        groupCheck.indeterminate = false;
      });

      section.append(children);
      list.append(section);
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

    const manifestUrl = root.dataset.manifest;
    const baseUrl = new URL(".", manifestUrl).toString();
    const manifest = await fetch(manifestUrl, { cache: "no-store" }).then((response) => {
      if (!response.ok) {
        throw new Error(`Manifest request failed: ${response.status}`);
      }
      return response.json();
    });

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

    const registry = new Map();

    map.on("load", () => {
      const terrainTilesets = (manifest.tilesets || []).filter((tileset) => tileset.type === "raster");
      const resultTilesets = (manifest.tilesets || []).filter((tileset) => tileset.type === "vector" && tileset.id === "results");
      const geometryTilesets = (manifest.tilesets || []).filter((tileset) => tileset.type === "vector" && tileset.id !== "results");

      for (const tileset of terrainTilesets) {
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
          addVectorLayerSet(map, sourceId, layer, registry);
        }
      }

      buildLayerTree(root, map, manifest, registry);
      const leftPadding = root.clientWidth > 760 ? 370 : 42;
      map.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], {
        padding: { top: 42, right: 42, bottom: 42, left: leftPadding },
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
