(function () {
  const roots = document.querySelectorAll("[data-ras-example-library]");
  if (!roots.length) {
    return;
  }

  const DEFAULT_BOUNDS = [-125, 24, -66, 50];

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
    const manifest = props.manifest ? resolveHref(props.manifest) : "";
    return [
      '<div class="ras-library-popup">',
      `<h3>${escapeHtml(props.title || feature.id || "Example Project")}</h3>`,
      "<dl>",
      `<dt>Source</dt><dd>${escapeHtml(props.sourceFamily || "Unknown")}</dd>`,
      `<dt>CRS</dt><dd>${escapeHtml(props.crs || "Unknown")}</dd>`,
      `<dt>Status</dt><dd>${escapeHtml(props.status || "Published")}</dd>`,
      "</dl>",
      props.notes ? `<p>${escapeHtml(props.notes)}</p>` : "",
      '<div class="ras-library-popup__actions">',
      webmap ? `<a href="${escapeHtml(webmap)}">Open webmap</a>` : "",
      manifest ? `<a href="${escapeHtml(manifest)}">Manifest</a>` : "",
      "</div>",
      "</div>",
    ].join("");
  }

  function projectCard(feature) {
    const props = feature.properties || {};
    const article = document.createElement("article");
    article.className = "ras-library-project";
    article.dataset.projectId = feature.id || "";

    const title = document.createElement("h3");
    title.textContent = props.title || feature.id || "Example Project";
    const meta = document.createElement("p");
    meta.textContent = [props.sourceFamily, props.crs, props.status].filter(Boolean).join(" | ");
    const link = document.createElement("a");
    link.href = props.webmap ? resolveHref(props.webmap) : "#";
    link.textContent = "Open webmap";
    if (!props.webmap) {
      link.setAttribute("aria-disabled", "true");
    }
    article.append(title, meta, link);
    return article;
  }

  function renderProjectList(root, features) {
    const list = root.querySelector("[data-project-list]");
    if (!list) {
      return;
    }
    list.replaceChildren(...features.map(projectCard));
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
    renderProjectList(root, features);

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
