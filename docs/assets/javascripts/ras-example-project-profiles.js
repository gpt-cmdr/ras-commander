window.RAS_EXAMPLE_PROJECT_PROFILES = {
  projects: {
    "muncie-muncie-rerun-7-0-20260628-193916-4120d261": {
      modelType: "1D, coupled 1D/2D, and 2D unsteady",
      version: "HEC-RAS 7.0 (rerun)",
      summary: "Three unsteady configurations of the same study area: a nine-storage-area 1D model, a coupled 1D/2D model with a 50-foot mesh, and a 2D 50-foot mesh with user-defined Manning's n regions. The variants make this a compact comparison of storage-area routing, 1D/2D connections, and roughness-region effects.",
    },
    "neworleansmetro-neworleansmetro-rerun-7-0-20260628-194053-e13b599a": {
      modelType: "2D unsteady metropolitan model",
      version: "HEC-RAS 7.0 (rerun)",
      summary: "A metropolitan 2D hydraulic model with hydraulic structures and one completed unsteady plan. Its urban setting provides a useful example of large-area 2D flow routing around dense infrastructure.",
    },
    "st-joseph-st-joe-elkhart-fim-6f8e01d0": {
      modelType: "1D steady flood-inundation model",
      version: "HEC-RAS 4.10 source; validated with 7.0",
      summary: "A USGS flood-inundation mapping model built from river reaches, cross sections, and hydraulic structures. The steady-flow profiles are useful for inspecting element-level water-surface results and traditional 1D model organization.",
    },
    "chippewa-2d-chippewa-2d-rerun-7-0-20260628-170311-14e51a07": {
      modelType: "2D unsteady",
      version: "HEC-RAS 7.0 (rerun)",
      summary: "A focused HEC 2D instructional model with a single completed unsteady plan. It provides a straightforward mesh, boundary-condition, terrain, and raster-results example without the plan and geometry volume of the larger public models.",
    },
    "davis-davis-rerun-7-0-20260628-193602-d666d9cb": {
      modelType: "2D unsteady with storm-drain network",
      version: "HEC-RAS 7.0 (rerun)",
      summary: "An urban surface-flow model coupled to a storm-drain network. The geometry includes 2D mesh cells, pipe conduits, and pipe nodes, making it the primary example for reviewing linked surface and subsurface drainage elements.",
    },
    "beaverlake-beaverlake-rerun-7-0-20260628-194053-eb3bacd7": {
      modelType: "2D unsteady",
      version: "HEC-RAS 7.0 (rerun)",
      summary: "A 2D instructional model with two geometry configurations and hydraulic structures. The alternate geometries support comparison of mesh and structure setup while retaining a common terrain and study area.",
    },
    "balde-eagle-creek-balde-eagle-creek-rerun-7-0-20260629-224833-d0758cd9": {
      modelType: "1D steady and unsteady",
      version: "HEC-RAS 7.0 (rerun)",
      summary: "A 1D river model with cross sections, structures, and two diversions, provided with both steady and unsteady plans. It shares its project area and coordinate system with Bald Eagle Creek Multi2D; the Multi2D terrain is used only as shared display context in the web viewer.",
      relatedGroup: "bald-eagle",
    },
    "kalamazoo-kalamazoo-trowbridg-b2c7eef6": {
      modelType: "2D unsteady",
      version: "HEC-RAS 6.6 (bundled results)",
      summary: "A USGS ScienceBase 2D model with five geometry configurations and 21 completed plans. Its combination of many alternatives and a large mesh is useful for reviewing how geometry and plan variants are organized in a public model release.",
    },
    "fox-river-chain-of-lakes-661e9565": {
      modelType: "2D unsteady calibration and validation model",
      version: "HEC-RAS 6.5 source; solver-validated with 6.6",
      summary: "A Fox River and Chain of Lakes model centered on Stratton Dam, with three geometries representing torque-tube gates and a cofferdam alternative. Six plans include 2022-2024 calibration events and a 2017 validation event; five completed result sets are published, while Plan 01 retains its explicit curator-approved no-rerun status.",
    },
    "silver-creek-scott-afb-644c1526": {
      modelType: "2D unsteady calibration, frequency, and future-precipitation model",
      version: "HEC-RAS 6.5 source; validated with 6.6",
      summary: "A Scott AFB/Silver Creek model with eight geometries and 35 completed plans. The alternatives cover observed-event calibration, culvert sensitivity, detention configurations, current-frequency storms, and future-precipitation scenarios from the 2-year through 500-year events.",
    },
    "spring-river-ras-model-spring-ble-prj-15b882a5": {
      modelType: "2D unsteady",
      version: "HEC-RAS 6.1 (bundled results)",
      summary: "A FEMA base-level engineering model with seven completed unsteady plans over a large 2D domain. It represents the structure and scale of a regional BLE delivery rather than a compact instructional fixture.",
    },
    "baldeaglecrkmulti2d-baldeaglecrkmulti2d-remote-7-0-20260628-212722-1d3b97ab": {
      modelType: "1D/2D unsteady dam-break",
      version: "HEC-RAS 7.0 (rerun)",
      summary: "A dam-break instructional project with ten geometry configurations and 11 completed plans combining 1D and 2D hydraulic features. It shares the Bald Eagle Creek study area and supplies the terrain used as display context for the companion 1D example.",
      relatedGroup: "bald-eagle",
    },
    "spring-creek-spring-c61c5625": {
      modelType: "2D unsteady",
      version: "HEC-RAS 5.0.7 source; rerun with 7.0",
      summary: "A FEMA BLE model with one geometry and seven frequency-based plans: 10-, 25-, 50-, 100-, and 500-year conditions plus 100-year upper and lower variants. It is a concise example of scenario-based regional floodplain modeling.",
    },
    "upper-guadalupe-ras-model-upgu1-upgu1-prj-030c0a6a": {
      modelType: "2D unsteady",
      version: "HEC-RAS 6.3.1 (bundled results)",
      summary: "Uppermost domain in the four-model Upper Guadalupe cascade.",
      groupId: "upper-guadalupe",
      variantLabel: "UPGU1",
    },
    "upper-guadalupe-ras-model-upgu2-upgu2-prj-917be43b": {
      modelType: "2D unsteady",
      version: "HEC-RAS 6.3.1 (bundled results)",
      summary: "Second domain in the four-model Upper Guadalupe cascade.",
      groupId: "upper-guadalupe",
      variantLabel: "UPGU2",
    },
    "upper-guadalupe-ras-model-upgu3-upgu3-prj-c79886b4": {
      modelType: "2D unsteady",
      version: "HEC-RAS 6.3.1 (bundled results)",
      summary: "Third domain in the four-model Upper Guadalupe cascade.",
      groupId: "upper-guadalupe",
      variantLabel: "UPGU3",
    },
    "upper-guadalupe-ras-model-upgu4-upgu4-prj-a9a9000f": {
      modelType: "2D unsteady",
      version: "HEC-RAS 6.3.1 (bundled results)",
      summary: "Downstream domain in the four-model Upper Guadalupe cascade.",
      groupId: "upper-guadalupe",
      variantLabel: "UPGU4",
    },
  },
  groups: {
    "upper-guadalupe": {
      title: "Upper Guadalupe Model Suite",
      sourceLabel: "FEMA eBFE/BLE delivery",
      modelType: "Four cascading 2D unsteady models",
      version: "HEC-RAS 6.3.1 (bundled results)",
      summary: "Four adjoining 2D models divide the Upper Guadalupe watershed into a cascading regional system. Each model contains seven frequency-based plans covering the 10%, 4%, 2%, 1%, and 0.2% annual-chance events plus upper and lower 1% variants.",
    },
  },
};
