# Capabilities by Task

Choose an operation from the inputs you already have and the output you need.
Each row links to the guide, API contract, and a concrete example. For exact
signatures and return fields, use the linked API reference; for model-specific
settings and retained evidence, read the example's configuration and results.

| Task | Inputs → outputs | Guide and API | Examples |
|---|---|---|---|
| Discover and inspect projects | Project files → plan, geometry, boundary, and result inventories with resolved paths | [Initialization](getting-started/project-initialization.md) · [RasPrj / RasPlan](api/core.md) | [101: project inventory](notebooks/101_project_initialization.md), [104: plan parameters](notebooks/104_plan_parameter_operations.md) |
| Execute plans and inspect completion | Project, plan, selected runtime → result object, native artifacts, messages, and completion evidence | [Execution and return contracts](user-guide/plan-execution.md) · [RasCmdr](api/core.md#rascmdr) · [Remote execution](api/remote.md) | [110: one plan](notebooks/110_single_plan_execution.md), [113: parallel plans](notebooks/113_parallel_execution.md) |
| Read 1D results | Steady or unsteady HDF → profile-indexed WSE or cross-section time series | [HDF extraction](user-guide/hdf-data-extraction.md) · [Steady results](user-guide/steady-flow-analysis.md) · [HDF API](api/hdf.md) | [400: unsteady 1D](notebooks/400_1d_hdf_data_extraction.md), [401: steady profiles](notebooks/401_steady_flow_analysis.md) |
| Query 2D results | Mesh geometry and results → cell, face, point, or line quantities with spatial/time coordinates | [HDF extraction and result shapes](user-guide/hdf-data-extraction.md) · [HdfResultsMesh](api/hdf.md#hdfresultsmesh) | [410: mesh extraction](notebooks/410_2d_hdf_data_extraction.md), [412: faces](notebooks/412_2d_detail_face_data_extraction.md), [413: line flow](notebooks/413_profile_line_flow_extraction.md) |
| Author geometry and structures | Working geometry, terrain, or land-cover inputs → edited model plus readback and native-processing evidence | [Geometry operations](user-guide/geometry-operations.md) · [Geometry API](api/geometry.md) | [212: Manning layers](notebooks/212_landcover_mannings_n_write.md), [216: bridges](notebooks/216_1d_bridge_authoring.md), [227: connection culverts](notebooks/227_2d_connection_culvert_authoring.md) |
| Author steady flows | Profile discharges and typed boundaries → steady-flow files and linked plans | [Steady-flow guide](user-guide/steady-flow-analysis.md) · [RasSteady](api/core.md#rassteady) | [224: steady-flow authoring](notebooks/224_steady_flow_authoring.md) |
| Prepare precipitation and boundaries | Observed, design, or forecast data → time/units conversion, hyetographs, DSS, or model forcing | [Boundary conditions](user-guide/boundary-conditions.md) · [Gridded precipitation](user-guide/gridded-precipitation.md) · [DSS API](api/dss.md) | [313: HMS/DSS matching](notebooks/313_hms_to_ras_boundary_matching.md), [720: storm methods](notebooks/720_precipitation_methods_comprehensive.md), [923: coastal stages](notebooks/923_stofs3d_coastal_boundary.md) |
| Calibrate and explore uncertainty | Model, declared targets/observations, parameter design → objective values, candidates, and ensemble diagnostics | [Workflow patterns](user-guide/workflows-and-patterns.md) · [Calibration and uncertainty APIs](api/core.md) · [Gauge data](user-guide/usgs-gauge-data.md) | [220: calibration](notebooks/220_calibration_workflow.md), [117: uncertainty](notebooks/117_monte_carlo_uncertainty.md), [922: delivered-model/gauge comparison](notebooks/922_model_validation_with_usgs.md) |
| Acquire and inspect model sources | Catalog or archive → identified projects, provenance, inventories, and delivered-result inspection | [eBFE delivery guide](user-guide/ebfe-delivery-validation.md) · [Model-source API](api/model-sources.md) | [950: eBFE organization](notebooks/950_ebfe_spring_creek.md), [958: source catalogs](notebooks/958_model_sources_showcase.md) |
| Conflate or extract a submodel | Network edge or proposed domain plus source models → coverage/selection plan, assembled project or prepared geometry, seam/flux review | [Hydrofabric](api/hydrofabric.md) · [1D breakout](api/breakout-1d.md) · [2D breakout](api/breakout-2d.md) | [235: 1D extraction](notebooks/235_1d_breakout_model.md), [236: multi-model assembly](notebooks/236_multi_model_1d_breakout_planning.md), [959: 2D preparation](notebooks/959_ebfe_2d_breakout_geometry_preparation.md) |
| Generate GIS and result products | Compatible geometry/results or aligned depth rasters → spatial exports, product manifests, checksums, and comparison maps | [Cloud-native export](user-guide/cloud-native-export.md) · [HdfResultsProducts](api/hdf.md#hdfresultsproducts) · [BenefitArea](api/benefits.md) | [417: retained-result products](notebooks/417_inspect_results_and_generate_hydraulic_products.md), [612: benefit/impact maps](notebooks/612_benefit_area_analysis.md), [962: COG export](notebooks/962_cloud_native_cog_results_export.md) |
| Screen model diagnostics | Geometry and computed outputs → scoped messages, tables, and review reports | [Quality assurance and RasCheck calls](user-guide/quality-assurance.md) | [800: steady-model diagnostics](notebooks/800_quality_assurance_rascheck.md), [801: structures](notebooks/801_advanced_structure_validation.md) |

**Floodway authoring and checking remain experimental.** The
[Floodway Check contract](user-guide/quality-assurance/floodway-check.md) records
parser, dataset-access, coverage, and qualification limitations. The steady-flow
authoring example above does not qualify encroachment trials. There is currently
no qualified floodway notebook route in this catalog.

## Choose the Runtime for the Operation

| Operation | Requirement to establish before running |
|---|---|
| Inspect text, HDF, or retained results | Python dependencies and the required stored datasets; reading results does not require a new solve |
| Edit text geometry, plans, or boundaries | A writable working copy; readback confirms stored inputs, while dependent preprocessing/results may need regeneration |
| Native geometry or sidecar authoring | The API's specified HEC-RAS/RASMapper version and platform; validate associations before interpreting final cell/face values |
| Execute a plan | A compatible installed solver or configured remote runtime, the exact project/plan, and the applicable runtime preflight |
| Use COM or GUI workflows | Windows, the selected registered/native HEC-RAS version, and an interactive desktop where required |
| Export products or compare observations | Compatible source quantity, coordinates, units, vertical/time reference, and declared output/metric settings |

Consult [installation requirements](getting-started/installation.md), the
[gridded-precipitation route guidance](user-guide/gridded-precipitation.md), and
the operation's API restrictions. A library import or documentation build does
not qualify every solver/platform combination. The
[release notes](development/release-notes.md) distinguish installed releases from
later documentation and development changes.

## Interpret the Evidence

Inventory means files were identified; readback means stored fields were read;
preprocessing means native inputs were prepared; completion means the execution
contract was checked. Numerical diagnostics, observation comparisons, and
engineering acceptance answer additional questions. Keep those claims separate
when using a result for a new model or study purpose.

For example, a signed profile-line flux differs from summed absolute face flows;
a maximum differs from an instantaneous sample; missing output differs from
zero; and a benefit-area category does not describe every physical change.
The linked contracts specify these distinctions where they apply.

The [complete example catalog](examples/index.md) provides task summaries and
selected expandable input/output/runtime/evidence contracts. Its
[machine-readable JSON](examples/index.json) exposes the same curated fields
from `examples/notebooks.yml`. Missing optional metadata means the field has
not been curated. Saved output and recorded execution time remain separate
from workflow qualification.
