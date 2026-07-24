(function () {
  const roots = document.querySelectorAll("[data-ras-example-library]");
  if (!roots.length) {
    return;
  }

  const DEFAULT_BOUNDS = [-125, 24, -66, 50];
  const PIN_REPLACEMENT_PIXEL_SIZE = 44;
  const PROJECT_PIN_IMAGE_ID = "ras-project-pin";
  const PROFILE_CONFIG = window.RAS_EXAMPLE_PROJECT_PROFILES || { projects: {}, groups: {} };
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

  function projectId(feature) {
    return String(feature.id || feature.properties?.projectId || "");
  }

  function projectBounds(feature) {
    return normalizeBounds(feature.bbox) || geometryBounds(feature.geometry);
  }

  function projectPinFeature(feature) {
    const bounds = projectBounds(feature);
    if (!bounds) {
      return null;
    }
    return {
      type: "Feature",
      id: feature.id,
      geometry: {
        type: "Point",
        coordinates: [
          (bounds[0] + bounds[2]) / 2,
          (bounds[1] + bounds[3]) / 2,
        ],
      },
      properties: {
        projectId: projectId(feature),
        title: feature.properties?.title || feature.id || "Example Project",
      },
    };
  }

  function projectedExtentSize(map, feature) {
    const bounds = projectBounds(feature);
    if (!bounds) {
      return 0;
    }
    const southwest = map.project([bounds[0], bounds[1]]);
    const northeast = map.project([bounds[2], bounds[3]]);
    return Math.max(
      Math.abs(northeast.x - southwest.x),
      Math.abs(northeast.y - southwest.y)
    );
  }

  function projectDisplayCollections(map, features) {
    const extents = [];
    const pins = [];
    const extentIds = new Set();
    for (const feature of features) {
      if (projectedExtentSize(map, feature) >= PIN_REPLACEMENT_PIXEL_SIZE) {
        extents.push(feature);
        extentIds.add(projectId(feature));
      } else {
        const pin = projectPinFeature(feature);
        if (pin) {
          pins.push(pin);
        }
      }
    }
    return {
      extents: { type: "FeatureCollection", features: extents },
      pins: { type: "FeatureCollection", features: pins },
      extentIds,
    };
  }

  function createProjectPinImage() {
    const scale = 2;
    const canvas = document.createElement("canvas");
    canvas.width = 36 * scale;
    canvas.height = 48 * scale;
    const context = canvas.getContext("2d");
    context.scale(scale, scale);

    context.beginPath();
    context.moveTo(18, 47);
    context.bezierCurveTo(14.5, 40.5, 4, 29.5, 4, 18);
    context.bezierCurveTo(4, 10.3, 10.3, 4, 18, 4);
    context.bezierCurveTo(25.7, 4, 32, 10.3, 32, 18);
    context.bezierCurveTo(32, 29.5, 21.5, 40.5, 18, 47);
    context.closePath();
    context.fillStyle = "#1d4ed8";
    context.fill();
    context.lineWidth = 2;
    context.strokeStyle = "#ffffff";
    context.stroke();

    context.beginPath();
    context.arc(18, 18, 5.5, 0, Math.PI * 2);
    context.fillStyle = "#ffffff";
    context.fill();

    return context.getImageData(0, 0, canvas.width, canvas.height);
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

  function projectProfile(feature) {
    const id = String(feature.id || feature.properties?.projectId || "");
    return PROFILE_CONFIG.projects?.[id] || {};
  }

  function enrichFeature(feature) {
    const profile = projectProfile(feature);
    return {
      ...feature,
      properties: {
        ...(feature.properties || {}),
        ...profile,
        projectId: feature.id || feature.properties?.projectId || "",
        sourceLabel: profile.sourceLabel || feature.properties?.sourceFamily || "",
      },
    };
  }

  function projectPopupSection(feature) {
    const props = feature.properties || {};
    const webmap = props.webmap ? resolveHref(props.webmap) : "";
    return [
      '<section class="ras-library-popup__project">',
      `<h3>${escapeHtml(props.title || feature.id || "Example Project")}</h3>`,
      props.modelType ? `<p class="ras-library-popup__type">${escapeHtml(props.modelType)}</p>` : "",
      props.summary ? `<p>${escapeHtml(props.summary)}</p>` : "",
      props.version ? `<p class="ras-library-popup__version">${escapeHtml(props.version)}</p>` : "",
      webmap ? `<a href="${escapeHtml(webmap)}">Open project map</a>` : "",
      "</section>",
    ].join("");
  }

  function popupHtml(features) {
    const projects = Array.isArray(features) ? features : [features];
    return [
      '<div class="ras-library-popup">',
      projects.length > 1 ? `<h2>${projects.length} projects at this location</h2>` : "",
      ...projects.map(projectPopupSection),
      "</div>",
    ].join("");
  }

  function catalogEntries(features) {
    const groups = new Map();
    const entries = [];
    for (const feature of features) {
      const profile = projectProfile(feature);
      if (!profile.groupId) {
        entries.push({ type: "project", feature, profile });
        continue;
      }
      if (!groups.has(profile.groupId)) {
        const group = {
          type: "group",
          id: profile.groupId,
          profile: PROFILE_CONFIG.groups?.[profile.groupId] || {},
          features: [],
        };
        groups.set(profile.groupId, group);
        entries.push(group);
      }
      groups.get(profile.groupId).features.push(feature);
    }
    for (const entry of entries) {
      if (entry.type === "group") {
        entry.features.sort((left, right) => (
          String(projectProfile(left).variantLabel || left.properties?.title)
            .localeCompare(String(projectProfile(right).variantLabel || right.properties?.title))
        ));
      }
    }
    return entries.sort((left, right) => {
      const leftTitle = left.type === "group"
        ? left.profile.title || left.id
        : left.feature.properties?.title || left.feature.id;
      const rightTitle = right.type === "group"
        ? right.profile.title || right.id
        : right.feature.properties?.title || right.feature.id;
      return String(leftTitle).localeCompare(String(rightTitle));
    });
  }

  function projectRow(entry) {
    const feature = entry.type === "project" ? entry.feature : null;
    const props = feature?.properties || {};
    const profile = entry.type === "group" ? entry.profile : entry.profile || {};
    const row = document.createElement("tr");
    row.dataset.projectId = feature?.id || entry.id || "";

    const project = document.createElement("td");
    if (entry.type === "group") {
      const title = document.createElement("strong");
      title.textContent = profile.title || entry.id;
      project.append(title);
      const links = document.createElement("div");
      links.className = "ras-library-project-links";
      for (const child of entry.features) {
        const childProfile = projectProfile(child);
        const link = document.createElement("a");
        link.href = child.properties?.webmap ? resolveHref(child.properties.webmap) : "#";
        link.textContent = childProfile.variantLabel || child.properties?.title || child.id;
        links.append(link);
      }
      project.append(links);
    } else {
      const link = document.createElement("a");
      link.href = props.webmap ? resolveHref(props.webmap) : "#";
      link.textContent = props.title || feature.id || "Example Project";
      if (!props.webmap) {
        link.setAttribute("aria-disabled", "true");
      }
      project.append(link);
    }
    const meta = document.createElement("span");
    meta.className = "ras-library-project-meta";
    meta.textContent = [
      profile.modelType || props.modelType,
      profile.sourceLabel || props.sourceLabel || props.sourceFamily,
    ].filter(Boolean).join(" | ");
    project.append(meta);

    const information = document.createElement("td");
    information.className = "ras-library-project-information";
    information.textContent = profile.summary || props.summary || props.notes || "";

    const version = document.createElement("td");
    version.className = "ras-library-project-version";
    version.textContent = profile.version || props.version || "See project";

    row.append(project, information, version);
    return row;
  }

  function renderProjectTable(root, features) {
    const table = root.querySelector("[data-project-table]");
    if (!table) {
      return;
    }
    table.replaceChildren(...catalogEntries(features).map(projectRow));
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
    const sourceCollection = await loadProjectIndex(dataUrl);
    const features = (sourceCollection.features || [])
      .filter((feature) => feature.geometry)
      .map(enrichFeature);
    const emptyCollection = { type: "FeatureCollection", features: [] };
    const initialPins = {
      type: "FeatureCollection",
      features: features.map(projectPinFeature).filter(Boolean),
    };
    const featuresById = new Map(
      features.flatMap((feature) => [
        [projectId(feature), feature],
        [String(feature.properties?.projectId || feature.id), feature],
      ])
    );
    renderProjectTable(root, features);
    const status = root.querySelector("[data-library-status]");
    if (status) {
      status.textContent = "Select a project pin or model extent.";
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
            data: emptyCollection,
          },
          "project-pins": {
            type: "geojson",
            data: initialPins,
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
              "fill-opacity": 0.08,
            },
          },
          {
            id: "project-extents-line",
            type: "line",
            source: "projects",
            paint: {
              "line-color": "#163ea5",
              "line-width": 1.6,
              "line-opacity": 0.86,
            },
          },
          {
            id: "selected-project-extent-fill",
            type: "fill",
            source: "selected-project",
            paint: {
              "fill-color": "#f97316",
              "fill-opacity": 0.16,
            },
          },
          {
            id: "selected-project-extent-halo",
            type: "line",
            source: "selected-project",
            paint: {
              "line-color": "#ffffff",
              "line-width": 6,
              "line-opacity": 0.82,
            },
          },
          {
            id: "selected-project-extent",
            type: "line",
            source: "selected-project",
            paint: {
              "line-color": "#d94801",
              "line-width": 3,
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
    let selectedFeature = null;

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

    function updateProjectDisplay() {
      const display = projectDisplayCollections(map, features);
      map.getSource("projects")?.setData(display.extents);
      map.getSource("project-pins")?.setData(display.pins);
      if (selectedFeature && !display.extentIds.has(projectId(selectedFeature))) {
        selectedFeature = null;
        map.getSource("selected-project")?.setData(emptyCollection);
        clearSelectedGeometry();
      }
    }

    map.on("load", () => {
      if (!map.hasImage(PROJECT_PIN_IMAGE_ID)) {
        map.addImage(PROJECT_PIN_IMAGE_ID, createProjectPinImage(), { pixelRatio: 2 });
      }
      map.addLayer({
        id: "project-pins-hit",
        type: "circle",
        source: "project-pins",
        paint: {
          "circle-color": "#000000",
          "circle-radius": 18,
          "circle-opacity": 0.01,
        },
      });
      map.addLayer({
        id: "project-pins",
        type: "symbol",
        source: "project-pins",
        layout: {
          "icon-image": PROJECT_PIN_IMAGE_ID,
          "icon-anchor": "bottom",
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
        },
      });
      updateProjectDisplay();
    });
    map.on("moveend", updateProjectDisplay);
    map.on("resize", updateProjectDisplay);

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

    function openProjectPopup(lngLat, popupFeatures) {
      if (!popupFeatures?.length) {
        return;
      }
      new maplibregl.Popup({ closeButton: true, maxWidth: "360px" })
        .setLngLat(lngLat)
        .setHTML(popupHtml(popupFeatures))
        .addTo(map);
    }

    function zoomToProject(feature) {
      const bounds = projectBounds(feature);
      if (!bounds) {
        return;
      }
      selectedFeature = feature;
      map.getSource("selected-project").setData({
        type: "FeatureCollection",
        features: [feature],
      });
      map.fitBounds(
        [
          [bounds[0], bounds[1]],
          [bounds[2], bounds[3]],
        ],
        { padding: 64, maxZoom: 15, duration: 600 }
      );
      showSelectedProjectGeometry(feature).catch(() => {
        clearSelectedGeometry();
      });
    }

    function renderedFeatures(event, layerIds) {
      const existingLayers = layerIds.filter((layerId) => map.getLayer(layerId));
      return existingLayers.length
        ? map.queryRenderedFeatures(event.point, { layers: existingLayers })
        : [];
    }

    map.on("click", (event) => {
      const hits = renderedFeatures(event, [
        "project-pins-hit",
        "project-pins",
        "project-extents-fill",
        "project-extents-line",
      ]);
      const hitFeatures = [];
      const seen = new Set();
      for (const hit of hits) {
        const id = String(hit.properties?.projectId || hit.id || "");
        const feature = featuresById.get(id);
        if (feature && !seen.has(id)) {
          seen.add(id);
          hitFeatures.push(feature);
        }
      }
      if (hitFeatures.length) {
        zoomToProject(hitFeatures[0]);
        openProjectPopup(event.lngLat, hitFeatures);
      }
    });

    map.on("mousemove", (event) => {
      const interactive = renderedFeatures(event, [
        "project-pins-hit",
        "project-pins",
        "project-extents-fill",
        "project-extents-line",
      ]);
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
