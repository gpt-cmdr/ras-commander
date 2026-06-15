# Bridge Geometry Automation and Bathymetric Survey Research

Research summary for Linear issue CLB-489, prepared June 15, 2026.

## Purpose

CLB collects bridge survey data using RTK GPS, total stations, and field point
codes for features such as deck edges, low chords, pier faces, abutments, and
channel bed points. This report summarizes prior art and recommends a data
schema direction for converting feature-coded survey observations into HEC-RAS
bridge geometry.

The most important conclusion is that public tools exist for HEC-RAS automation
and LiDAR-derived approximate bridge deck insertion, but no mature public
repository was found that converts conventional RTK/total-station bridge survey
point codes directly into complete HEC-RAS bridge deck, pier, abutment, and
internal cross-section records. The best path for ras-commander is therefore to
define a durable survey-observation schema first, then add deterministic
feature grouping and reviewable HEC-RAS geometry generation on top of it.

## Research Method

GitHub searches were run with terms including `HEC-RAS bridge geometry`,
`HEC-RAS geometry`, `HECRAS`, `LAS2RAS`, `bridge hydraulic model`, and
`bridge point cloud extraction`. Web research focused on agency manuals,
statewide modeling guidance, industry HEC-RAS bridge workflows, and academic
point-cloud extraction papers.

## HEC-RAS Bridge Geometry Inputs

HEC-RAS requires bridge data as structured hydraulic geometry, not as generic
survey points. The HEC-RAS User's Manual says a bridge record includes the
bridge deck, optional sloping abutments, optional piers, and bridge modeling
approach data. The deck/roadway editor expects bridge width along the stream,
distance to the upstream cross section, and upstream/downstream stationing with
high chord and low chord elevations. It also treats piers separately from both
the ground and deck so that low-flow methods compute pier blockage correctly
([HEC-RAS User's Manual, Entering and Editing Bridge Data](https://www.hec.usace.army.mil/confluence/rasdocs/rasum/6.1/entering-and-editing-geometric-data/bridges-and-culverts/entering-and-editing-bridge-data)).

For schema design, this means field survey observations should not be stored
only as CAD-style points. They must preserve enough context to become:

| HEC-RAS target | Survey-derived inputs needed |
| --- | --- |
| Deck/roadway high chord | Roadway or bridge deck top profile, bridge limits, weir crest context |
| Deck/roadway low chord | Bottom of beam/stringer/deck points on upstream and downstream faces |
| Bridge width and distance | Roadway crossing polygon or upstream/downstream bridge face lines, river stationing, adjacent cross-section geometry |
| Sloping abutments | Abutment face, toe, wingwall, and embankment breaklines |
| Piers | Pier centerline, faces/perimeter, width, shape, skew, top/bottom/cap observations |
| Internal cross sections | Channel bed, banks, toe/slope breaks, water-bottom shots, water-bottom breaklines |
| Review data | Photos, notes, datum, instrument method, confidence, and source code aliases |

## Public and Industry Prior Art

### TX-BRIDGE and LAS2RAS

The closest public bridge-automation prior art is the Texas Water Development
Board (TWDB) approximate bridge modeling effort. TWDB describes LAS2RAS as a
project to automate incorporation of LiDAR-derived bridge decks into Base Level
Engineering HEC-RAS 1D and 2D hydraulic models. TWDB says the project builds on
TX-BRIDGE, targets HEC-RAS 6.3.1, and includes a desktop tool, a single codebase
for 1D and 2D models, sensitivity analyses, documentation, and training
([TWDB Approximate Bridge Modeling Automation](https://www.twdb.texas.gov/flood/research/approximate-bridge-modeling-automation/index.asp)).

The linked TX-BRIDGE repository creates bridge deck data from USGS 3DEP Entwine
point clouds. Its README describes extracting bridge-classified points so they
can build a composite bare-earth plus bridge-deck "healed" terrain for flood
mapping and overtopping evaluation ([andycarter-pe/tx-bridge](https://github.com/andycarter-pe/tx-bridge)).

Implication for ras-commander: TX-BRIDGE/LAS2RAS validates the value of
automated deck insertion and review artifacts, but it starts from LiDAR/NBI data
rather than field-coded survey observations. CLB's schema should support both:
feature-coded survey as the authoritative detailed source, and optional
point-cloud-derived candidates as a secondary source.

### HEC-RAS Geometry Libraries

Several open-source tools can read, write, or inspect HEC-RAS geometry and
outputs, but they do not solve feature-coded bridge survey ingestion by
themselves.

| Repository or tool | Relevant capability | Gap for CLB bridge survey automation |
| --- | --- | --- |
| [mikebannis/parserasgeo](https://github.com/mikebannis/parserasgeo) | Imports, edits, and exports HEC-RAS geometry files for programmatic workflows. | Mostly cross-section oriented; not a complete bridge-survey-to-bridge-record generator. |
| [erpas/rgis](https://github.com/erpas/rgis) | QGIS plugin for creating HEC-RAS flow model geometry from spatial data, similar to HEC-GeoRAS. | GIS geometry workflow, not survey point-code interpretation for decks/piers/low chords. |
| [gpt-cmdr/ras-commander](https://github.com/gpt-cmdr/ras-commander) | Python API for automating HEC-RAS operations, parsing geometry/HDF data, and managing projects. | The natural home for the CLB schema and bridge generation API, but this specific workflow remains to be added. |
| [USACE/mcat-ras](https://github.com/USACE/mcat-ras) | Identifies model paths and extracts metadata/geospatial data from HEC-RAS projects. | Model content analysis rather than geometry creation. |
| [fema-ffrd/rashdf](https://github.com/fema-ffrd/rashdf) | Reads HEC-RAS HDF files. | Output/data extraction only. |
| [gyanz/rivia](https://github.com/gyanz/rivia) | Python interface for HEC-RAS visualization, information, and automation. | General automation, not bridge survey schema. |

### Commercial HEC-RAS Bridge Tools

Commercial tools reinforce the same data model. CivilGEO's GeoHECRAS bridge
workflow exposes deck roadway, culverts, bridge piers, sloping abutments,
internal geometry, bridge methodology, and a "Build Bridge Opening" panel that
defines geometry from span or abutment data
([CivilGEO HEC-RAS Bridge Modeling](https://knowledge.civilgeo.com/hec-ras-bridge-modeling/)).
CivilGEO's 2D bridge article describes piers as elevation-versus-width pairs
with upstream and downstream centerline stations, starting below ground and
continuing past the deck low chord
([CivilGEO HEC-RAS 2D Bridge Modeling](https://knowledge.civilgeo.com/hec-ras-2d-bridge-modeling/)).

Freese and Nichols' HEC-RAS bridge modeling guidance summarizes the bridge
opening as the intersection of the bounding cross sections with deck/roadway,
piers, and abutments, and notes that deck/roadway data are entered with station,
high chord, and low chord
([Freese and Nichols, Bridge Modeling in HEC-RAS](https://www.freese.com/blog/bridge-modeling-in-hec-ras/)).

Implication for ras-commander: the schema should map toward HEC-RAS bridge
primitives, not toward one vendor's interface. However, vendor workflows are
useful for naming expected QA views: deck profile, internal cross sections,
opening comparison, geometry adjustment, and point reduction.

## Agency Guidance on Surveys and Bathymetry

FHWA's current HDS-7 page describes the 2024 second edition of *Hydraulic Design
of Safe Bridges* as guidance for bridge hydraulic analysis and design, including
hydraulic modeling approach, model selection, scour and stream instability,
sediment transport, and bridge deck drainage
([FHWA HDS-7](https://www.fhwa.dot.gov/engineering/hydraulics/library_arc.cfm?id=192&pub_number=1)).
FHWA's hydraulics publication list also identifies HEC-18, HEC-20, HEC-23, and
2D Hydraulic Modeling for Highways in the River Environment as current bridge,
scour, and 2D modeling references
([FHWA Hydraulics Publications](https://www.fhwa.dot.gov/engineering/hydraulics/library_listing.cfm)).

USGS bridge-scour survey work demonstrates practical data collection methods
around bridges. A USGS/FHWA report on bridge scour countermeasures collected
traditional surveys, motion-compensated terrestrial LiDAR, high-resolution
multibeam bathymetry, and underwater video at bridge sites. It describes
MBES/T-lidar/INS integrated mobile mapping, overlapping swaths to reduce sonic
shadows, and multiple passes around piers and banks
([USGS SIR 2019-5080](https://pubs.usgs.gov/sir/2019/5080/sir20195080.pdf)).
USGS also documents flood-event bridge scour data collection with detailed
bathymetric and hydraulic information from digital echo sounders
([USGS real-time data collection of scour at bridges](https://www.usgs.gov/publications/real-time-data-collection-scour-bridges)).

LaDOTD's Location and Survey Manual states that streams and large drains
crossing alignments should be located per the survey request, with stream/canal
features from the Survey Feature Code Guide Book located sufficiently to define
the water bottom, and that bridge design and hydraulics sections may need to
request additional detail beyond the manual
([LaDOTD Location and Survey Manual](https://dotd.la.gov/media/cyslfdxl/location_and_survey_manual.pdf)).
The same manual describes hydrographic surveys as critical to designing,
repairing, replacing, and monitoring bridges; single-beam surveys provide spot
elevation cross sections, while multibeam surveys can map full-coverage
streambed terrain and obstructions.

## Academic and Research Methods

Academic work is strongest for point-cloud segmentation and bridge component
classification, not for deterministic HEC-RAS geometry writing.

| Source | Method | Relevance to CLB schema |
| --- | --- | --- |
| [DeepHyd, FHWA/NC/2019-03](https://rosap.ntl.bts.gov/view/dot/62502) | Deep learning classification of hydraulic structures from terrestrial LiDAR, sonar, total station, survey-grade GPS, and drone data at 11 sites. It classifies bridges from vegetation/ground and bridge components such as beams, piers, railings, and retaining walls. | Supports future point-cloud assistance, but requires annotated training data. Feature-coded RTK observations can become the labeled data source. |
| [Truong-Hong and Lindenbergh, 2021](https://research.tudelft.nl/en/publications/extracting-bridge-components-from-a-laser-scanning-point-cloud/) | Sequential extraction of bridge component surfaces from laser scanning point clouds using quadtree decomposition, density estimation, region growing, and component knowledge. | Confirms that component knowledge and ordered extraction matter; schema should encode bridge-side, component role, and expected shape. |
| [Truong-Hong and Lindenbergh, 2022](https://research.tudelft.nl/en/publications/automatically-extracting-surfaces-of-reinforced-concrete-bridges-/) | Automated extraction of reinforced-concrete bridge surfaces from terrestrial laser scans with point-to-surface, superstructure, and substructure extraction. | Useful for future QA against scans; less directly useful for conventional survey-only workflows. |
| [UAS Image-Based Point Clouds to 3D BrIM](https://rosap.ntl.bts.gov/view/dot/61970/dot_61970_DS1.pdf) | UAS imagery, structure-from-motion point clouds, and 3D bridge information model generation. | Supports optional photogrammetry source data and photo provenance fields. |
| [Alidoost et al., ISPRS 2021](https://isprs-archives.copernicus.org/articles/XLVI-4-W1-2021/77/2021/isprs-archives-XLVI-4-W1-2021-77-2021.pdf) | Projection-based 3D bridge modeling from drone-generated dense point clouds. | Reinforces that 3D bridge reconstruction often needs segmentation before model fitting. |
| [Frontiers, 2024 IFC bridge models from point clouds](https://www.frontiersin.org/journals/built-environment/articles/10.3389/fbuil.2024.1375873/full) | Semi-automatic semantic segmentation and 3D shape modeling for IFC bridge models. | Useful conceptually for semantic component classes, but BIM deliverables are more detailed than HEC-RAS needs. |

Schema implication: do not require machine learning for the first version.
Instead, make ML and point-cloud workflows downstream data sources that can
populate the same canonical feature classes as RTK/total-station points.

## Louisiana Watershed Initiative

The issue description refers to a statewide LWI effort. Public sources indicate
this is the Louisiana Watershed Initiative (LWI), a statewide watershed modeling
program created after the 2016 Louisiana floods. The Water Institute describes
LWI as procuring updated hydrologic and hydraulic modeling for the entire state,
including areas never modeled or mapped
([The Water Institute, Louisiana Watershed Initiative](https://thewaterinstitute.org/projects/louisiana-watershed-initiative)).

The LWI open-data registry describes datasets spanning bathymetry, elevation,
hydrology, infrastructure, hydrodynamic outputs, and model inputs/outputs for
HEC-HMS and HEC-RAS. It states the data are public through the State of
Louisiana and hosted in the `lwi-model-data` S3 bucket
([AWS Registry, LWI Model Data](https://registry.opendata.aws/lwi-model-data/)).

LWI's modeling methodology guidance is directly relevant. It recommends HUC8
watershed-scale HEC-HMS and hybrid 1D/2D HEC-RAS models and says topographic
and bathymetric survey information is one of the most critical inputs for
high-quality hydraulic models. Its minimum survey requirements list channel
cross-section shots at slope breaks, channel invert, centerline, low-flow toe
and bank, plus bridge survey requirements similar to culverts but including
pier spacing, shape, size, skew, guardrail height/length/type, top and low chord
elevations, state-highway completion year, and geo-photos. It also requires
feature codes using the DOTD Survey Feature Code Guide Book, NAVD 88/GEOID12B
and State Plane coordinates unless otherwise directed, detailed field notes, and
geo-referenced photos
([LWI Guidance on Modeling Methodology](https://d10zxfp0rexahe.cloudfront.net/docs/LWI_Guidance_on_Modeling_Methodology-2021-06-29.pdf)).

A 2025 LWI presentation describes raw Region 7 survey inputs as a combination
of bathymetric survey, traditional ground survey, ground-based laser scanning,
and existing survey, with more than 2,000 structures surveyed and examples of
bridge scans
([LWI presentation, 2025](https://coastal.la.gov/wp-content/uploads/2025/09/LA-Watershed-Initiative.pdf)).

LWI data governance guidance also matters for schema design. It requires
HUC8-specific geodatabases with feature classes such as bridge crossings and
culverts, source data retained and organized, metadata through EnDMC/AWS, and
metadata for bridge survey information aggregated at a watershed/HUC8 basis in
some cases
([LWI Data Governance Strategy and Data Standards](https://water-institute.files.svdcdn.com/production/Projects/LWI-Data-Governance-Strategy-And-Data-Standards.pdf?dm=1774016734)).

## Survey Point Code Conventions

Survey code systems vary by agency and collector setup, so ras-commander should
not hard-code one firm's point-code strings as the schema. It should store the
raw code and map it to canonical bridge feature classes through a configurable
alias table.

LaDOTD's Survey Feature Code Guide Book includes bridge rail lines, top of
bridge bent cap, bridge headwall/wingwall top centerlines, guardrail
centerlines, bridge pile points and lines, bottom of stringer elevation, bridge
footing lines, water body centerlines, water body banks, water's edge, high
water marks, top-of-water elevations, culvert invert lines, water bottom shots,
and water bottom breaklines
([LaDOTD Survey Feature Code Guide Book](https://www.altivasoft.com/LaDOTD/docs/Survey%20Feature%20Code%20Guide.pdf)).
Ohio DOT feature codes similarly include bottom of bridge deck, bridge rail,
beam seat, pier perimeter, pier cap bottom, top of pier, and abutment/wingwall
codes
([ODOT Survey Feature Codes](https://ftp.dot.state.oh.us/pub/cadd/caddsync/ODOTcadd/Standards/Geopak/Survey/Field_Codes/ODOT_Survey_Codes_Category.pdf)).
Illinois DOT survey codes include beam seat, bottom of beam, and bridge
approach slab categories
([IDOT Survey Feature Codes](https://idot.illinois.gov/content/dam/soi/en/web/idot/documents/doing-business/manuals-guides-and-handbooks/highways/cadd/4-17.02%20Survey%20Point%20Codes%20by%20Category.pdf)).

Recommended canonical feature groups:

| Canonical group | Common source-code aliases | HEC-RAS use |
| --- | --- | --- |
| `deck_top` | top of bridge deck, roadway crown, edge of pavement, approach slab, high chord, guardrail top where needed for roadway profile | Deck high chord / weir crest review |
| `deck_edge` | upstream bridge face, downstream bridge face, left/right deck edge, bridge rail line, approach slab edge | Bridge width, station limits, side assignment |
| `low_chord` | low chord, bottom of beam, bottom of stringer, bottom of bridge deck, low members | Deck low chord profile and pressure-flow trigger review |
| `pier` | pier face, pier perimeter, pier centerline, pile point, pile row, pier cap bottom/top, bent cap | HEC-RAS pier centerline, width-elevation table, pier skew |
| `abutment` | abutment face, abutment toe, wingwall, headwall, bridge footing | Sloping abutment and blocked-area geometry |
| `channel_bed` | water bottom shot, water bottom breakline, invert, thalweg, channel centerline | Internal bridge cross sections and bathymetry |
| `bank` | top of bank, toe of bank, water body bank, water's edge, low-flow toe | Bank stations and channel shape |
| `survey_context` | benchmark, control point, high water mark, top of water, photo point, note | QA, datum control, calibration, documentation |

Recommended alias-table fields:

| Field | Purpose |
| --- | --- |
| `source_code` | Exact field code from the data collector or CAD export. |
| `canonical_feature` | Normalized feature group such as `low_chord`, `pier`, or `channel_bed`. |
| `geometry_kind` | Expected point, line, polygon, or profile. |
| `ras_role` | Intended HEC-RAS target such as deck high chord, deck low chord, pier width table, or internal cross section. |
| `terrain_role` | Include in terrain, breakline, DTM point, or do not include. |
| `required_attributes` | Expected attributes such as material, diameter, width, side, opening id, or span id. |
| `confidence` | Default confidence or priority when multiple codes map to the same feature. |

## Recommended Schema Direction

Use a two-layer schema:

1. Raw observations remain immutable. They preserve every surveyed point, line,
   code, note, photo, instrument method, and datum exactly as received.
2. Interpreted bridge features are generated from raw observations through a
   configurable code map and grouping rules. These features are what bridge
   generation uses.

### Raw Observation Fields

Minimum raw fields:

| Field | Notes |
| --- | --- |
| `survey_id` | Unique survey package identifier. |
| `bridge_id` | Stable bridge or crossing identifier; allow NBI, DOT, client, and local aliases. |
| `point_id` | Original collector point number or UUID. |
| `source_code` | Unmodified point code from the field file. |
| `source_description` | Optional description or code-expanded label. |
| `geometry` | Point/LineString/Polygon in a known CRS. |
| `elevation` | Numeric elevation. |
| `vertical_datum`, `geoid`, `horizontal_crs`, `units` | Required for safe hydraulic use. |
| `method` | RTK, total station, single-beam, multibeam, terrestrial LiDAR, UAV/SfM, plan digitization, or manual edit. |
| `timestamp`, `crew`, `instrument` | Provenance and traceability. |
| `notes`, `photo_refs`, `source_file` | Review artifacts. |

### Interpreted Feature Fields

Minimum interpreted fields:

| Field | Notes |
| --- | --- |
| `canonical_feature` | Normalized class from the code map. |
| `side` | `upstream`, `downstream`, `left`, `right`, `center`, or unknown; left/right should be looking downstream. |
| `station_axis_id` | Axis used to compute HEC-RAS stationing. |
| `station`, `offset` | Projected coordinates in the bridge/opening coordinate system. |
| `ras_station` | Station value in the target HEC-RAS cross-section coordinate system. |
| `sequence` | Sort order along a profile or feature line. |
| `opening_id`, `span_id`, `pier_id`, `abutment_id` | Grouping keys for multi-opening bridges. |
| `elevation_role` | `high_chord`, `low_chord`, `ground`, `water_bottom`, `top`, `bottom`, etc. |
| `shape`, `width`, `diameter`, `material`, `skew` | Optional structure attributes. |
| `source_point_ids` | Raw points used to create the interpreted feature. |
| `quality_flags` | Missing side, nonmonotonic stationing, high/low chord conflict, datum mismatch, point limit exceeded, etc. |

### Derived HEC-RAS Output Objects

The generator should produce reviewable intermediate objects before writing a
geometry file:

| Derived object | Contents |
| --- | --- |
| `DeckRoadwayProfile` | Upstream and downstream station/high chord/low chord tables; bridge width and upstream distance. |
| `PierDefinition` | Upstream/downstream centerline stations, elevation-width pairs, pier shape, skew, and source features. |
| `AbutmentDefinition` | Upstream/downstream station-elevation lines and optional skew. |
| `InternalBridgeSection` | Ground station-elevation profile through the bridge opening, bank stations, and Manning's n placeholders. |
| `BridgeSurveyQAReport` | Plots, source point counts, warnings, code map used, and manual approval status. |

## Generation Workflow Recommendation

1. Load raw survey data and code-map aliases.
2. Validate coordinate reference system, vertical datum, units, and duplicate
   point identifiers before interpreting geometry.
3. Establish a bridge coordinate frame from surveyed bridge faces, roadway
   alignment, stream centerline, or adjacent HEC-RAS cross sections.
4. Project observations into bridge station/offset coordinates, with stationing
   left-to-right looking downstream.
5. Group interpreted features by bridge side, opening, span, pier, and abutment.
6. Build upstream and downstream high/low chord profiles and enforce monotonic
   stationing.
7. Build internal ground/channel sections from bed, bank, and terrain points.
8. Build pier definitions from faces/perimeters or centerline plus width
   attributes.
9. Apply HEC-RAS point limits and point reduction only after preserving the raw
   observations and the unreduced interpreted profiles.
10. Generate QA plots and tables before writing a HEC-RAS geometry file.
11. Write the bridge geometry through ras-commander geometry APIs, then require
   GUI-reviewable project artifacts and plotted evidence.

## QA and Engineering Controls

The schema and generator should produce hard warnings for:

- Missing upstream or downstream low-chord profiles.
- High chord lower than low chord at any station.
- Nonmonotonic deck, low-chord, or internal-section stationing.
- Pier points included in terrain or deck profiles instead of separate pier
  records.
- Unassigned point codes.
- Mixed vertical datums, geoids, units, or coordinate systems.
- Bridge deck or weir profiles exceeding HEC-RAS point limits.
- Abrupt low-chord or deck drops to ground without supporting source points.
- Gaps between low chord, abutment, and ground that imply a missing feature or
  invalid grouping.
- Any automated point reduction that changes opening area beyond a configurable
  tolerance.

The first implementation should treat automated output as a draft requiring
engineer review. The review artifact should include plan-view point groups,
upstream/downstream deck profiles, low chord profiles, pier placement, internal
cross sections, and a table tying each HEC-RAS row back to raw survey point IDs.

## Implementation Recommendations for ras-commander

1. Add schema classes or typed dictionaries for raw bridge survey observations,
   code-map aliases, interpreted bridge features, and derived HEC-RAS bridge
   objects before writing geometry-file mutators.
2. Keep point-code mapping configurable. CLB codes, DOTD codes, ODOT codes, and
   client-specific codes should all map to the same canonical feature classes.
3. Build deterministic survey-point workflows before ML/point-cloud workflows.
   The academic literature shows that ML can classify components, but it needs
   annotated data. CLB's field-coded survey points can become that annotation
   base later.
4. Store both raw and reduced geometry. HEC-RAS may need point reduction, but
   engineering audit requires the original survey points and unreduced profiles.
5. Make every generated bridge row traceable to source point IDs and source
   feature codes.
6. Align API outputs with existing ras-commander patterns: DataFrames for review,
   static namespace classes for geometry operations, and explicit file outputs
   that open in HEC-RAS.
7. Start with one bridge archetype: single-opening bridge with one or more piers,
   surveyed upstream/downstream deck faces, low chord, abutments, and channel
   cross section. Add multi-opening, skewed, and scanned bridges after the QA
   artifacts are stable.

## Open Questions for Follow-On Design

- Which CLB point-code dictionary should be the first supported alias map?
- Should the canonical bridge schema live in `ras_commander.geom`, a new
  `ras_commander.survey` module, or a bridge-specific subpackage?
- What file formats should be first-class inputs: CSV, LandXML, Carlson RW5,
  Trimble JOB/JXL export, DXF, GeoPackage, or ESRI geodatabase?
- What tolerance should trigger manual review for low-chord/ground gaps,
  deck-profile simplification, and opening-area changes?
- How should generated bridge geometry interact with existing HEC-RAS bounding
  cross sections and internal bridge sections in ras-commander?
