(function () {
  const roots = document.querySelectorAll("[data-ras-example-library]");
  if (!roots.length) {
    return;
  }

  const DEFAULT_BOUNDS = [-125, 24, -66, 50];
  const LANDING_GEOMETRY_KINDS = new Set([
    "bank_lines",
    "bc_lines",
    "breaklines",
    "centerlines",
    "edge_lines",
    "flow_paths",
    "junctions",
    "mesh_areas",
    "model_extents",
    "pipe_conduits",
    "pipe_inlets",
    "pipe_nodes",
    "pump_stations",
    "refinement_regions",
    "river_reaches",
    "storage_areas",
    "structures",
  ]);

  function registerPmtilesProtocol() {
    if (!window.pmtiles || window.RAS_EXAMPLE_LIBRARY_PMTILES_PROTOCOL) {
      return;
    }
    const protocol = new window.pmtiles.Protocol();
    maplibregl.addProtocol("pmtiles", protocol.tile);
    window.RAS_EXAMPLE_LIBRARY_PMTILES_PROTOCOL = protocol;
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function resolveHref(href) {
    return new URL(href, window.location.href).toString();
  }

  function normalizeBounds(bounds) {
    if (Array.isArray(bounds) && bounds.length === 4 && bounds.every(Number.isFinite)) {
      return bounds;
    }
    return null;
  }

  function geometryBounds(geometry) {
    const xs = [];
    const ys = [];
    function visit(coords) {
      if (!Array.isArray(coords)) {
        return;
      }
      if (coords.length >= 2 && Number.isFinite(coords[0]) && Number.isFinite(coords[1])) {
        xs.push(coords[0]);
        ys.push(coords[1]);
        return;
      }
      for (const child of coords) {
        visit(child);
      }
    }
    visit(geometry && geometry.coordinates);
    if (!xs.length || !ys.length) {
      return null;
    }
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  }

  function mergeBounds(features) {
    const bounds = features
      .map((feature) => normalizeBounds(feature.bbox) || geometryBounds(feature.geometry))
      .filter(Boolean);
    if (!bounds.length) {
      return DEFAULT_BOUNDS;
    }
    return [
      Math.min(...bounds.map((b) => b[0])),
      Math.min(...bounds.map((b) => b[1])),
      Math.max(...bounds.map((b) => b[2])),
      Math.max(...bounds.map((b) => b[3])),
    ];
  }

  function safeId(value) {
    return String(value || "layer")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "layer";
  }

  function geometryFamily(layer) {
    const types = layer.geometryTypes || [];
    if (types.some((type) => String(type).includes("Polygon"))) {
      return "polygon";
    }
    if (types.some((type) => String(type).includes("Point"))) {
      return "point";
    }
    return "line";
  }

  function geometryPaint(layer, family) {
    const style = layer.style || {};
    if (family === "polygon") {
      return {
        fill: {
          "fill-color": style.fill || "#2a9d8f",
          "fill-opacity": Math.min(Number(style.fillOpacity ?? 0.16), 0.24),
        },
        line: {
          "line-color": style.line || "#155e75",
          "line-width": Math.max(Number(style.lineWidth || 1.2), 1.2),
          "line-opacity": 0.9,
        },
      };
    }
    if (family === "point") {
      return {
        circle: {
          "circle-color": style.fill || style.line || "#b45309",
          "circle-radius": 4,
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1,
        },
      };
    }
    return {
      line: {
        "line-color": style.line || "#155e75",
        "line-width": Math.max(Number(style.lineWidth || 1.3), 1.3),
        "line-opacity": 0.92,
      },
    };
  }

  function projectLocations(features) {
    return {
      type: "FeatureCollection",
      features: features
        .map((feature) => {
          const bounds = normalizeBounds(feature.bbox) || geometryBounds(feature.geometry);
          if (!bounds) {
            return null;
          }
          return {
            type: "Feature",
            id: feature.id,
            properties: {
              ...(feature.properties || {}),
              projectId: feature.id || feature.properties?.projectId || "",
            },
            geometry: {
              type: "Point",
              coordinates: [(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2],
            },
          };
        })
        .filter(Boolean),
    };
  }

  function popupHtml(feature) {
    const props = feature.properties || {};
    const webmap = props.webmap ? resolveHref(props.webmap) : "";
    return [
      '<div class="ras-library-popup">',
      `<h3>${escapeHtml(props.title || feature.id || "Example Project")}</h3>`,
      "<dl>",
      `<dt>Source</dt><dd>${escapeHtml(props.sourceFamily || "Unknown")}</dd>`,
      `<dt>CRS</dt><dd>${escapeHtml(props.crs || "Unknown")}</dd>`,
      `<dt>Status</dt><dd>${escapeHtml(props.status || "Published")}</dd>`,
      props.landingExtentSource
        ? `<dt>Map extent</dt><dd>${escapeHtml(props.landingExtentSource)}</dd>`
        : "",
      "</dl>",
      props.notes ? `<p>${escapeHtml(props.notes)}</p>` : "",
      '<div class="ras-library-popup__actions">',
      webmap ? `<a href="${escapeHtml(webmap)}">Open webmap</a>` : "",
      "</div>",
      "</div>",
    ].join("");
  }

  function projectRow(feature) {
    const props = feature.properties || {};
    const row = document.createElement("tr");
    row.dataset.projectId = feature.id || "";

    const project = document.createElement("td");
    const link = document.createElement("a");
    link.href = props.webmap ? resolveHref(props.webmap) : "#";
    link.textContent = props.title || feature.id || "Example Project";
    if (!props.webmap) {
      link.setAttribute("aria-disabled", "true");
    }
    project.append(link);

    const information = document.createElement("td");
    information.className = "ras-library-project-information";
    information.textContent = props.notes || "Published MapLibre project bundle.";

    const source = document.createElement("td");
    source.textContent = props.sourceFamily || "Unknown";

    const crs = document.createElement("td");
    crs.textContent = props.crs || "Unknown";

    row.append(project, information, source, crs);
    return row;
  }

  function renderProjectTable(root, features) {
    const table = root.querySelector("[data-project-table]");
    if (!table) {
      return;
    }
    table.replaceChildren(...features.map(projectRow));
  }

  async function loadProjectIndex(dataUrl) {
    try {
      const response = await fetch(dataUrl, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`Example project index request failed: ${response.status}`);
      }
      return response.json();
    } catch (error) {
      if (window.RAS_EXAMPLE_PROJECTS) {
        return window.RAS_EXAMPLE_PROJECTS;
      }
      throw error;
    }
  }

  async function init(root) {
    const mapEl = root.querySelector("[data-library-map]");
    if (!mapEl || !window.maplibregl) {
      return;
    }

    registerPmtilesProtocol();
    const dataUrl = root.dataset.index ||
      "https://rascommander.info/data/rasexamples/hec-ras-7.0/example-projects.geojson";
    const collection = await loadProjectIndex(dataUrl);
    const features = (collection.features || []).filter((feature) => feature.geometry);
    const featuresById = new Map(
      features.flatMap((feature) => [
        [String(feature.id), feature],
        [String(feature.properties?.projectId || feature.id), feature],
      ])
    );
    renderProjectTable(root, features);
    const status = root.querySelector("[data-library-status]");
    if (status) {
      status.textContent = `${features.length} published MapLibre project extents`;
    }

    const bounds = mergeBounds(features);
    const map = new maplibregl.Map({
      container: mapEl,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "&copy; OpenStreetMap contributors",
          },
          projects: {
            type: "geojson",
            data: collection,
          },
          "selected-project": {
            type: "geojson",
            data: { type: "FeatureCollection", features: [] },
          },
        },
        layers: [
          {
            id: "osm",
            type: "raster",
            source: "osm",
            paint: { "raster-opacity": 0.82 },
          },
          {
            id: "project-extents-fill",
            type: "fill",
            source: "projects",
            paint: {
              "fill-color": "#2563eb",
              "fill-opacity": 0.18,
            },
          },
          {
            id: "project-extents-line",
            type: "line",
            source: "projects",
            paint: {
              "line-color": "#163ea5",
              "line-width": 3,
              "line-opacity": 0.94,
            },
          },
          {
            id: "selected-project-extent-fill",
            type: "fill",
            source: "selected-project",
            paint: {
              "fill-color": "#f97316",
              "fill-opacity": 0.3,
            },
          },
          {
            id: "selected-project-extent-halo",
            type: "line",
            source: "selected-project",
            paint: {
              "line-color": "#ffffff",
              "line-width": 9,
              "line-opacity": 0.9,
            },
          },
          {
            id: "selected-project-extent",
            type: "line",
            source: "selected-project",
            paint: {
              "line-color": "#d94801",
              "line-width": 5,
              "line-opacity": 1,
            },
          },
        ],
      },
      bounds,
      fitBoundsOptions: { padding: 56, maxZoom: 12 },
      attributionControl: true,
    });

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-left");

    let selectedGeometry = { layers: [], sources: [] };
    let selectedGeometryRequest = 0;

    function clearSelectedGeometry() {
      for (const layerId of [...selectedGeometry.layers].reverse()) {
        if (map.getLayer(layerId)) {
          map.removeLayer(layerId);
        }
      }
      for (const sourceId of selectedGeometry.sources) {
        if (map.getSource(sourceId)) {
          map.removeSource(sourceId);
        }
      }
      selectedGeometry = { layers: [], sources: [] };
    }

    async function showSelectedProjectGeometry(feature) {
      const manifestHref = feature.properties?.manifest;
      const request = ++selectedGeometryRequest;
      clearSelectedGeometry();
      if (!manifestHref || !window.pmtiles) {
        return;
      }
      if (!map.isStyleLoaded()) {
        await new Promise((resolve) => map.once("load", resolve));
      }
      const manifestUrl = resolveHref(manifestHref);
      const response = await fetch(manifestUrl, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`Project manifest request failed: ${response.status}`);
      }
      const manifest = await response.json();
      if (request !== selectedGeometryRequest) {
        return;
      }
      const projectId = safeId(feature.id || feature.properties?.projectId);
      const beforeId = map.getLayer("selected-project-extent-fill")
        ? "selected-project-extent-fill"
        : undefined;
      for (const tileset of manifest.tilesets || []) {
        if (tileset.type !== "vector" || tileset.id === "geometry-detail") {
          continue;
        }
        const layers = (tileset.layers || []).filter((layer) => (
          LANDING_GEOMETRY_KINDS.has(layer.kind)
          && layer.kind !== "model_extents"
          && layer.sourceKind !== "raw-hdf"
          && layer.sourceKind !== "stored-map"
        ));
        if (!layers.length || !tileset.href) {
          continue;
        }
        const sourceId = `selected-model-${projectId}-${safeId(tileset.id)}`;
        const tileUrl = new URL(tileset.href, manifestUrl).toString();
        map.addSource(sourceId, {
          type: "vector",
          url: `pmtiles://${tileUrl}`,
        });
        selectedGeometry.sources.push(sourceId);
        for (const layer of layers) {
          const family = geometryFamily(layer);
          const paint = geometryPaint(layer, family);
          const baseId = `${sourceId}-${safeId(layer.id)}`;
          const common = {
            source: sourceId,
            "source-layer": layer.sourceLayer,
            minzoom: Number(tileset.minzoom || 0),
          };
          if (family === "polygon") {
            const fillId = `${baseId}-fill`;
            const lineId = `${baseId}-line`;
            map.addLayer({ id: fillId, type: "fill", ...common, paint: paint.fill }, beforeId);
            map.addLayer({ id: lineId, type: "line", ...common, paint: paint.line }, beforeId);
            selectedGeometry.layers.push(fillId, lineId);
          } else {
            const layerId = `${baseId}-${family}`;
            map.addLayer({ id: layerId, type: family === "point" ? "circle" : "line", ...common, paint: paint[family === "point" ? "circle" : "line"] }, beforeId);
            selectedGeometry.layers.push(layerId);
          }
        }
      }
    }

    function openProjectPopup(lngLat, feature) {
      if (!feature) {
        return;
      }
      new maplibregl.Popup({ closeButton: true, maxWidth: "360px" })
        .setLngLat(lngLat)
        .setHTML(popupHtml(feature))
        .addTo(map);
    }

    function zoomToProject(feature) {
      const projectBounds = normalizeBounds(feature.bbox) || geometryBounds(feature.geometry);
      if (!projectBounds) {
        return;
      }
      map.getSource("selected-project").setData({
        type: "FeatureCollection",
        features: [feature],
      });
      map.fitBounds(
        [
          [projectBounds[0], projectBounds[1]],
          [projectBounds[2], projectBounds[3]],
        ],
        { padding: 64, maxZoom: 15, duration: 600 }
      );
      showSelectedProjectGeometry(feature).catch(() => {
        clearSelectedGeometry();
      });
    }

    function renderedFeatures(event, layerIds) {
      return map.queryRenderedFeatures(event.point, { layers: layerIds });
    }

    for (const location of projectLocations(features).features) {
      const feature =
        featuresById.get(String(location.id)) ||
        featuresById.get(String(location.properties?.projectId));
      if (!feature) {
        continue;
      }
      const markerElement = document.createElement("button");
      markerElement.type = "button";
      markerElement.className = "ras-library-project-marker";
      markerElement.setAttribute("aria-label", `Open ${feature.properties?.title || feature.id}`);
      markerElement.title = feature.properties?.title || feature.id;
      markerElement.addEventListener("click", (event) => {
        event.stopPropagation();
        zoomToProject(feature);
        openProjectPopup(location.geometry.coordinates, feature);
      });
      new maplibregl.Marker({ element: markerElement, anchor: "center" })
        .setLngLat(location.geometry.coordinates)
        .addTo(map);
    }

    map.on("click", (event) => {
      const feature = renderedFeatures(event, ["project-extents-fill", "project-extents-line"])[0];
      if (feature) {
        zoomToProject(feature);
        openProjectPopup(event.lngLat, feature);
      }
    });

    map.on("mousemove", (event) => {
      const interactive = renderedFeatures(event, ["project-extents-fill", "project-extents-line"]);
      map.getCanvas().style.cursor = interactive.length ? "pointer" : "";
    });
  }

  for (const root of roots) {
    init(root).catch((error) => {
      const status = root.querySelector("[data-library-status]");
      if (status) {
        status.textContent = error.message || "Example library map failed to load.";
      }
    });
  }
})();
