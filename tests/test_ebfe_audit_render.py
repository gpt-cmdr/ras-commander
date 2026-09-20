"""The eBFE audit renderer: one skeleton, engineer's vocabulary, escape depth.

Spec: agent_tasks/2026-09-08_ebfe_audit_document_spec.md. The invariants here
are the ones that make 300-odd documents comparable: every section present in
every document, expected-ness derived from the model, and the reference
classifier that turns a raw path into an action.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ras_commander.sources.federal.ebfe_audit import (
    ACTION_KINDS,
    SUPPORTING_ELEMENTS,
    AuditBundle,
    actions_from_bundle,
    CHAINED_DSS_NOTE,
    chained_dss_chains,
    chained_dss_producer,
    chained_dss_sequence,
    chained_dss_targets,
    classify_reference,
    delivered_model_names,
    dss_pathname_parts,
    escape_depth,
    expected_elements,
    load_audit_bundle,
    render_audit_markdown,
    study_critical_threshold,
)

SECTIONS = [
    "## 1. Verdict",
    "## 2. Model inventory",
    "## 3. Required supporting data",
    "## 4. From delivered to runnable",
    "## 5. What is still missing",
    "## 6. What you must obtain",
    "## 7. Provenance and method",
]


# -- escape depth: the classifier the document rests on ----------------------

@pytest.mark.parametrize(
    "reference, depth",
    [
        (r".\DSS Inputs\Spring.dss", 0),
        ("g01", 0),
        ("", 0),
        (r"..\Terrain\Terrain.hdf", 1),
        (r"..\..\..\..\HEC-HMS_v43\Spring\100YR.dss", 4),
        ("../../GIS/Working/Spring.shp", 2),
        (r"C:\Projects\Spring\100YR.dss", -1),
        (r"\\server\share\x.dss", -1),
        ("/mnt/data/x.dss", -1),
    ],
)
def test_escape_depth(reference, depth):
    assert escape_depth(reference) == depth


def test_in_bundle_reference_needs_no_action():
    assert classify_reference(r".\x.dss", target_present_in_delivery=True) == ("none", "")


def test_escaping_reference_with_target_present_is_a_path_correction():
    kind, reason = classify_reference(r"..\..\x.dss", target_present_in_delivery=True)
    assert kind == "path_correction"
    assert reason == "broken_relative_reference"


def test_nested_archive_wins_over_path_correction():
    kind, _ = classify_reference(r"..\x.dss", target_present_in_delivery=True, target_in_nested_archive=True)
    assert kind == "recursive_extraction"


def test_absent_target_is_acquisition_unless_reconstructible():
    assert classify_reference(r"..\x.dss", target_present_in_delivery=False)[0] == "acquisition"
    assert classify_reference(
        r"..\x.dss", target_present_in_delivery=False, reconstruction_source_present=True
    )[0] == "reconstruction"


# -- expected-ness is derived from the model, never asserted blindly ---------

def test_1d_steady_expects_nothing_it_does_not_reference():
    """A 1D steady model computes from its cross sections.

    Terrain and projection are mapping inputs, not computation inputs, for 1D.
    12090301's 2,378 projects reference neither; calling them "needs external
    data" was the same blind assertion as infiltration-for-every-2D-model.
    """
    expected = expected_elements("1D", "steady")
    for key in ("terrain", "projection", "infiltration", "soils", "dss", "land_cover", "rasmap"):
        assert not expected[key], key


def test_1d_steady_keeps_referenced_terrain_informational():
    expected = expected_elements("1D", "steady", {"terrain": True, "projection": True})
    assert not expected["terrain"] and expected["projection"]


def test_2d_always_expects_terrain_and_projection():
    expected = expected_elements("2D", "unsteady")
    assert expected["terrain"] and expected["projection"]


def test_1d_with_no_terrain_delivered_or_referenced_is_runnable():
    """The 12090301 shape: capture says terrain 'no', projection 'no', nothing references them."""
    bundle = _minimal_bundle(
        terrain={"delivered": 0, "gapped": 1, "rebuilt": 0, "projects": [
            {"project": "P", "terrain_hdf": [], "raster": [], "status": "gapped"}]},
        supporting_elements={
            "terrain": {"state": "no", "location": None, "note": "GAP_no_terrain_delivered"},
            "projection": {"state": "no", "location": None, "note": ""},
        },
    )
    kinds = {(a.kind, a.target) for a in actions_from_bundle(bundle)}
    assert ("acquisition", "Terrain") not in kinds
    assert ("acquisition", "Projection") not in kinds
    assert "| Runnable as delivered | **yes** |" in render_audit_markdown(bundle)


def test_2d_unsteady_expects_the_structural_set():
    """Terrain, projection, RASMapper config and DSS follow from the model type."""
    expected = expected_elements("2D", "unsteady")
    for key in ("terrain", "projection", "rasmap", "dss", "land_cover"):
        assert expected[key], key


def _threshold_bundle(total, affected=0, element="terrain", dims="1D", referenced=True):
    aggregate = {
        "terrain": {"state": "yes", "referenced": False},
        "land_cover": {"state": "yes", "referenced": False},
    }
    models = []
    for index in range(total):
        supporting = {
            "terrain": {"state": "yes", "referenced": False},
            "land_cover": {"state": "yes", "referenced": False},
        }
        if index < affected:
            supporting[element] = {"state": "no", "referenced": referenced}
        models.append({
            "model_id": f"m{index}",
            "project_name": f"m{index}",
            "model_type": dims,
            "supporting_elements": supporting,
        })
    if affected:
        aggregate[element] = {"state": "no", "referenced": referenced}
    bundle = _minimal_bundle(
        model_type=dims,
        flow_regime="steady" if dims == "1D" else "unsteady",
        g6a_load={"projects_total": total, "projects_loaded": total},
        supporting_elements=aggregate,
        critical_missing=[{
            "element": element,
            "reason": "legacy_capture_claim",
            "projects": [f"m{i}" for i in range(affected)],
        }] if affected else [],
    )
    bundle.models = models
    return bundle


@pytest.mark.parametrize(
    "total,affected",
    [(10, 0), (100, 1), (1, 1), (100, 100)],
)
def test_1d_terrain_is_informational_at_every_prevalence(total, affected):
    row = study_critical_threshold(_threshold_bundle(total, affected))["elements"]["terrain"]
    assert (row["numerator"], row["denominator"]) == (affected, total)
    assert row["study_critical"] is False


def test_unreferenced_1d_terrain_is_exact_informational_text_only():
    bundle = _threshold_bundle(10, 10, referenced=False)
    threshold = study_critical_threshold(bundle)
    assert threshold["elements"]["terrain"]["numerator"] == 0
    assert not threshold["elements"]["terrain"]["study_critical"]
    assert not any(action.target == "Terrain" for action in actions_from_bundle(bundle))
    markdown = render_audit_markdown(bundle)
    assert "No terrain provided or referenced by model (1D)" in markdown
    assert "Critical data missing" not in markdown
    assert "needs data not in the delivery" not in markdown


def test_delivered_1d_terrain_does_not_emit_absence_note():
    bundle = _threshold_bundle(10, 0)
    threshold = study_critical_threshold(bundle)
    assert "informational" not in threshold["elements"]["terrain"]
    assert "No terrain provided or referenced by model (1D)" not in render_audit_markdown(bundle)


def test_below_threshold_1d_reference_is_not_study_critical_and_reports_denominator():
    bundle = _threshold_bundle(100, 9)
    assert not any(action.target == "Terrain" for action in actions_from_bundle(bundle))
    markdown = render_audit_markdown(bundle)
    assert "| Terrain | 9 | 100 | 9.00% | no |" in markdown
    assert "legacy capture claim" not in markdown


def test_referenced_1d_terrain_is_exact_informational_text_only_even_at_100_percent():
    bundle = _threshold_bundle(10, 10)
    assert not any(action.target.startswith("Terrain") for action in actions_from_bundle(bundle))
    markdown = render_audit_markdown(bundle)
    assert (
        "Terrain referenced but not provided (1D; informational — does not prevent recomputation)"
        in markdown
    )
    assert "| Terrain | 10 | 10 | 100.00% | no |" in markdown
    assert "Critical data missing" not in markdown
    assert "Obtain `Terrain`" not in markdown
    assert "Rebuild `Terrain`" not in markdown


@pytest.mark.parametrize("total,affected", [(10, 1), (85, 85)])
def test_1d_land_cover_is_informational_at_every_prevalence(total, affected):
    """User direction 2026-09-16: missing land cover is not fatal for a 1D model.

    Wheeler Lake (AL06030002) references land cover in all 85 models and delivers
    it in none; it was hatched "critical data missing" under the retired 10% rule.
    """
    bundle = _threshold_bundle(total, affected, element="land_cover")
    threshold = study_critical_threshold(bundle)
    row = threshold["elements"]["land_cover"]
    assert (row["numerator"], row["denominator"]) == (affected, total)
    assert row["study_critical"] is False
    assert row["informational"].startswith("Land cover / Manning's n referenced but not provided (1D")
    assert not any(action.target == "Land cover / Manning's n" for action in actions_from_bundle(bundle))
    markdown = render_audit_markdown(bundle)
    percent = f"{100.0 * affected / total:.2f}%"
    assert f"| Land cover / Manning's n | {affected} | {total} | {percent} | no |" in markdown
    assert "Critical data missing | land cover" not in markdown
    assert "needs data not in the delivery" not in markdown


def test_1d_referenced_land_cover_is_not_expected():
    expected = expected_elements("1D", "unsteady", {"land_cover": True})
    assert not expected["land_cover"]


def test_2d_requires_land_cover_only_when_referenced():
    assert expected_elements("2D", "unsteady", {"land_cover": True})["land_cover"]
    assert not expected_elements("2D", "unsteady", {"land_cover": False})["land_cover"]
    assert not expected_elements("mixed", "steady", {"land_cover": False})["land_cover"]


def test_unknown_model_type_keeps_referenced_land_cover():
    assert expected_elements("unknown", "unsteady", {"land_cover": True})["land_cover"]
    assert not expected_elements("unknown", "unsteady", {"land_cover": False})["land_cover"]


def test_2d_infiltration_is_expected_only_when_referenced():
    assert not expected_elements("2D", "unsteady", {})["infiltration"]
    assert not expected_elements("2D", "unsteady", {"infiltration": False})["infiltration"]
    assert expected_elements("2D", "unsteady", {"infiltration": True})["infiltration"]


def test_duplicate_model_row_does_not_inflate_threshold_denominator():
    bundle = _threshold_bundle(10, 1)
    bundle.models.append(dict(bundle.models[0]))
    row = study_critical_threshold(bundle)["elements"]["terrain"]
    assert (row["numerator"], row["denominator"]) == (1, 10)


def test_2d_required_missing_terrain_remains_fatal():
    bundle = _threshold_bundle(1, 1, dims="2D", referenced=False)
    threshold = study_critical_threshold(bundle)
    assert not threshold["applies_to_integrated_1d"]
    terrain = [a for a in actions_from_bundle(bundle) if a.target == "Terrain"]
    assert len(terrain) == 1 and terrain[0].blocking and terrain[0].kind == "acquisition"
    markdown = render_audit_markdown(bundle)
    assert "needs data not in the delivery" in markdown


def test_optional_layers_are_expected_only_when_referenced():
    """Infiltration and soils are not asserted for every 2D unsteady model.

    Spring Creek handles losses in HEC-HMS upstream and never references an
    infiltration layer. Calling that "missing" made every study read
    "needs external data" and the verdict stopped discriminating.
    """
    assert expected_elements("2D", "unsteady")["infiltration"] is False
    assert expected_elements("2D", "unsteady")["soils"] is False
    assert expected_elements("2D", "unsteady", {"infiltration": True})["infiltration"] is True
    assert expected_elements("2D", "unsteady", {"soils": True})["soils"] is True
    assert expected_elements("2D", "unsteady", {"infiltration": False})["infiltration"] is False


def _two_d_unsteady(**overrides) -> AuditBundle:
    base = dict(
        study_findings={"interpretation": "2d unsteady", "projects_with_unsteady_flow_pct": 100.0},
        g7_rascheck={"outcome": "RAN", "flow_type_families": {"UNSTEADY": 1}},
        terrain={"delivered": 1, "gapped": 0, "rebuilt": 0,
                 "projects": [{"project": "P", "terrain_hdf": ["Terrain.hdf"], "raster": ["DEM.tif"], "status": "delivered"}]},
    )
    base.update(overrides)
    return _minimal_bundle(**base)


def test_unreferenced_absent_infiltration_is_not_a_gap():
    """The Spring Creek case: capture says 'no' and nothing references it."""
    bundle = _two_d_unsteady(supporting_elements={
        "infiltration": {"state": "no", "location": None, "note": "no infiltration layer referenced"},
        "soils": {"state": "no", "location": None, "note": "no soils layer referenced"},
    })
    targets = {a.target for a in actions_from_bundle(bundle)}
    assert "Infiltration" not in targets and "Soils" not in targets
    markdown = render_audit_markdown(bundle)
    assert "needs data not in the delivery" not in markdown
    row = next(l for l in markdown.splitlines() if l.startswith("| Infiltration |"))
    assert "Not used by this model" in row and "**No**" not in row


def test_referenced_but_absent_infiltration_is_an_acquisition():
    """Same capture state, but the model references the layer: now it is a real gap."""
    bundle = _two_d_unsteady(supporting_elements={
        "infiltration": {"state": "no", "location": None, "referenced": True, "note": "referenced by Spring.rasmap"},
    })
    acq = [a for a in actions_from_bundle(bundle) if a.kind == "acquisition" and a.target == "Infiltration"]
    assert len(acq) == 1 and acq[0].blocking
    assert "needs data not in the delivery" in render_audit_markdown(bundle)


def test_reference_rows_count_as_referenced_when_capture_has_no_flag():
    """v2 captures without an explicit flag: a gap row naming the layer is the signal."""
    bundle = _two_d_unsteady(supporting_elements={"soils": {"state": "no", "location": None, "note": ""}})
    bundle.gaps = [{"gap": "MISSING_REFERENCE", "source_file": "x.rasmap", "role": "rasmap_attribute",
                    "raw_value": r"..\Soils\ssurgo.hdf"}]
    assert any(a.target == "Soils" and a.kind == "acquisition" for a in actions_from_bundle(bundle))


def test_results_and_preprocessed_hdf_are_never_required():
    for dims, regime in (("1D", "steady"), ("2D", "unsteady")):
        expected = expected_elements(dims, regime)
        assert not expected["results_hdf"]
        assert not expected["geometry_hdf"]


# -- the skeleton never varies ---------------------------------------------

def _minimal_bundle(**overrides) -> AuditBundle:
    audit = {
        "key": "99999999",
        "name": "Test Study",
        "stage": "audited",
        "g6a_load": {"projects_total": 1, "projects_loaded": 1},
        "study_findings": {"interpretation": "1d steady", "projects_with_unsteady_flow_pct": 0.0},
        "g7_rascheck": {"outcome": "RAN", "flow_type_families": {"STEADY": 1}},
        "terrain": {"delivered": 1, "gapped": 0, "rebuilt": 0},
        "provenance": {"git_commit": "abc", "worker_host": "test"},
        "g1_verify": {"all_sizes_match": True},
        "g3_extract": {"members_written": 10},
        "g7_validate": {"windows_path_closure": True, "absolute_path_closure": True, "absolute_reference_count": 0},
    }
    audit.update(overrides)
    return AuditBundle(key="99999999", audit=audit)


def test_every_section_appears_even_when_empty():
    markdown = render_audit_markdown(_minimal_bundle())
    for heading in SECTIONS:
        assert heading in markdown, heading
    # Empty sections say so rather than vanishing.
    assert "No actions required" in markdown
    assert "**Nothing.**" in markdown
    assert "Nothing external" in markdown


def test_every_supporting_element_row_is_always_present():
    markdown = render_audit_markdown(_minimal_bundle())
    for _, label in SUPPORTING_ELEMENTS:
        assert f"| {label} |" in markdown, label


def test_no_internal_vocabulary_leaks_into_the_engineer_sections():
    markdown = render_audit_markdown(_minimal_bundle())
    body = markdown.split("## 7. Provenance")[0]
    for token in ("boundaries_df", "ras_object", "init_ras_project", "INIT_FAILED", "G5", "unclassified_separator_value"):
        assert token not in body, token


def test_verdict_reports_not_expected_rather_than_missing():
    markdown = render_audit_markdown(_minimal_bundle())
    # 1D steady: infiltration is not for this model type, and must not read as "No".
    infiltration_row = next(l for l in markdown.splitlines() if l.startswith("| Infiltration |"))
    assert "Not used by this model" in infiltration_row
    assert "**No**" not in infiltration_row


# -- actions are ordered by dependency ---------------------------------------

def test_actions_execute_extraction_before_movement_before_correction():
    bundle = _minimal_bundle(
        g2_probe={"nested_archives": [{"archive": "A.zip", "member": "inner/B.zip", "depth": 1}]},
        asset_relocation={"relocated": [{"from": "Results/p01.hdf", "to": "RAS Model/p01.hdf", "archive": "Results.zip"}]},
    )
    bundle.recipes = [{
        "file": "RAS Model/x.u01", "surface": "dss_pathname", "locator": "x.u01:9:DSS File",
        "from": r"..\..\x.dss", "to": r".\DSS Inputs\x.dss", "why": "missing_from_delivery",
        "confidence": "resolved",
    }]
    actions = actions_from_bundle(bundle)
    kinds = [a.kind for a in actions]
    assert kinds == ["recursive_extraction", "file_movement", "path_correction"]
    assert [a.order for a in actions] == [1, 2, 3]
    assert all(k in ACTION_KINDS for k in kinds)


def test_broken_relative_reference_is_named_and_measured():
    bundle = _minimal_bundle()
    bundle.recipes = [{
        "file": "RAS Model/x.u01", "surface": "dss_pathname", "locator": "x.u01:9:DSS File",
        "from": r"..\..\..\..\HEC-HMS_v43\x.dss", "to": r".\DSS Inputs\x.dss",
        "why": "missing_from_delivery", "confidence": "resolved",
    }]
    action = actions_from_bundle(bundle)[0]
    assert action.reason == "broken_relative_reference"
    assert action.escape_depth == 4
    assert action.blocking
    markdown = render_audit_markdown(bundle)
    assert "climbed 4 level(s)" in markdown
    assert "**[blocking]**" in markdown


def test_missing_references_are_listed_in_full_and_grouped():
    bundle = _minimal_bundle()
    bundle.gaps = [
        {"gap": "MISSING_REFERENCE", "source_file": "x.rasmap", "role": "rasmap_attribute", "raw_value": r"..\Shp\a.shp"},
        {"gap": "MISSING_REFERENCE", "source_file": "x.rasmap", "role": "rasmap_attribute", "raw_value": r"..\Shp\a.shp"},
        {"gap": "MISSING_REFERENCE", "source_file": "x.u01", "role": "dss", "raw_value": r"..\x.dss"},
    ]
    markdown = render_audit_markdown(bundle)
    section = markdown.split("## 5. What is still missing")[1].split("## 6.")[0]
    assert "3 missing references, 2 distinct files" in section
    assert "Shapefiles and GIS layers" in section
    assert "DSS boundary data" in section
    assert r"`..\Shp\a.shp` | 2 |" in section          # deduplicated with a count


# -- "runnable as delivered" means zero actions ------------------------------

def test_any_action_means_not_runnable_as_delivered():
    """A non-blocking path fix is still a repair. Runnable means from extraction, untouched."""
    bundle = _minimal_bundle()
    bundle.recipes = [{
        "file": "RAS Model/x.rasmap", "surface": "rasmap_attribute", "locator": "x.rasmap:3:Filename",
        "from": r".\a.tif", "to": r".\Land Cover\a.tif", "why": "relocated_by_assembly",
        "confidence": "resolved",
    }]
    markdown = render_audit_markdown(bundle)
    verdict = markdown.split("## 1. Verdict")[1].split("## 2.")[0]
    assert "| Runnable as delivered | **yes** |" not in verdict
    assert "after repair" in verdict


def test_source_only_terrain_is_a_blocking_reconstruction_not_delivered():
    """San Gabriel: DEM rasters for every project, Terrain.hdf for none.

    The audit called that "delivered". An engineer cannot run it without a
    CreateTerrain step, so it is a reconstruction action and the verdict must
    not say runnable.
    """
    bundle = _minimal_bundle(
        study_findings={"interpretation": "2d unsteady", "projects_with_unsteady_flow_pct": 100.0},
        g7_rascheck={"outcome": "RAN", "flow_type_families": {"UNSTEADY": 5}},
        terrain={
            "delivered": 5, "gapped": 0, "rebuilt": 0,
            "projects": [
                {"project": f"P{i}", "terrain_hdf": [], "raster": ["DEM_1.tif"], "status": "delivered"}
                for i in range(5)
            ],
        },
    )
    actions = actions_from_bundle(bundle)
    recon = [a for a in actions if a.kind == "reconstruction"]
    assert len(recon) == 1 and recon[0].target == "Terrain" and recon[0].blocking
    # Terrain modifications live inside the missing HDF: rebuilding from rasters
    # runs but is not faithful, so the modified terrain is also an acquisition.
    acq = [a for a in actions if a.kind == "acquisition" and a.target.startswith("Terrain")]
    assert len(acq) == 1 and acq[0].blocking
    markdown = render_audit_markdown(bundle)
    assert "Source rasters only" in markdown
    assert "| Runnable as delivered | **yes** |" not in markdown
    assert "needs data not in the delivery" in markdown
    assert "| Critical data missing |" in markdown
    assert "terrain hdf absent modifications unknown" in markdown


def test_captured_critical_missing_is_rendered_with_scope():
    bundle = _minimal_bundle(critical_missing=[{
        "element": "terrain", "reason": "terrain_hdf_absent_modifications_referenced",
        "projects": ["LBSG_501", "LBSG_502"], "evidence": "rasmap: 3 modification elements",
    }])
    verdict = render_audit_markdown(bundle).split("## 1. Verdict")[1].split("## 2.")[0]
    assert "| Critical data missing | **terrain** (2 projects) -- terrain hdf absent modifications referenced |" in verdict


def test_captured_empty_critical_missing_suppresses_the_fallback():
    """The capture looked and found nothing critical; the renderer must not second-guess it.

    12090301: 2,378 HEC-RAS 4.10 1D steady projects, no .rasmap, terrain not
    applicable -- the worker wrote critical_missing: [] and the fallback still
    emitted a "terrain hdf absent" row from the terrain state.
    """
    bundle = _minimal_bundle(
        critical_missing=[],
        terrain={"delivered": 0, "gapped": 1, "rebuilt": 0, "projects": [
            {"project": "P", "terrain_hdf": [], "raster": [], "status": "gapped"}]},
        supporting_elements={"terrain": {"state": "no", "location": None, "note": "not applicable"}},
    )
    verdict = render_audit_markdown(bundle).split("## 1. Verdict")[1].split("## 2.")[0]
    assert "| Critical data missing |" not in verdict


def test_fallback_does_not_fire_when_terrain_is_not_expected():
    """A v1 capture (field absent) on a 1D steady model that references no terrain."""
    bundle = _minimal_bundle(
        terrain={"delivered": 0, "gapped": 1, "rebuilt": 0, "projects": [
            {"project": "P", "terrain_hdf": [], "raster": [], "status": "gapped"}]},
        supporting_elements={"terrain": {"state": "no", "location": None, "note": ""}},
    )
    assert "critical_missing" not in bundle.audit
    verdict = render_audit_markdown(bundle).split("## 1. Verdict")[1].split("## 2.")[0]
    assert "| Critical data missing |" not in verdict


def test_critical_row_names_every_acquisition_not_only_terrain():
    """"Critical" is any data the model needs that the delivery lacks -- the same
    definition the map hatches on -- so the row must name infiltration and soils
    gaps, not only a missing Terrain.hdf."""
    bundle = _two_d_unsteady(
        critical_missing=[],
        supporting_elements={
            "infiltration": {"state": "no", "location": None, "referenced": True, "note": "referenced by rasmap"},
            "soils": {"state": "no", "location": None, "referenced": True, "note": "referenced by rasmap"},
        },
    )
    verdict = render_audit_markdown(bundle).split("## 1. Verdict")[1].split("## 2.")[0]
    row = next(l for l in verdict.splitlines() if l.startswith("| Critical data missing |"))
    assert "**Infiltration** -- not in the delivery" in row
    assert "**Soils** -- not in the delivery" in row
    assert "needs data not in the delivery" in verdict


def test_terrain_entry_and_other_acquisitions_coexist_without_duplicating_terrain():
    bundle = _two_d_unsteady(
        critical_missing=[{"element": "terrain", "reason": "terrain_hdf_absent_modifications_referenced",
                           "projects": ["P"], "evidence": ""}],
        terrain={"delivered": 1, "gapped": 0, "rebuilt": 0,
                 "projects": [{"project": "P", "terrain_hdf": [], "raster": ["DEM.tif"], "status": "delivered"}]},
        supporting_elements={"soils": {"state": "no", "location": None, "referenced": True, "note": ""}},
    )
    verdict = render_audit_markdown(bundle).split("## 1. Verdict")[1].split("## 2.")[0]
    row = next(l for l in verdict.splitlines() if l.startswith("| Critical data missing |"))
    assert row.count("**terrain**") + row.count("**Terrain**") == 1     # once, with its specific reason
    assert "modifications referenced" in row
    assert "**Soils** -- not in the delivery" in row


def test_referenced_modifications_are_named_in_the_acquisition_evidence():
    bundle = _minimal_bundle(
        study_findings={"interpretation": "2d unsteady", "projects_with_unsteady_flow_pct": 100.0},
        g7_rascheck={"outcome": "RAN", "flow_type_families": {"UNSTEADY": 1}},
        terrain={"delivered": 1, "gapped": 0, "rebuilt": 0,
                 "projects": [{"project": "P", "terrain_hdf": [], "raster": ["DEM.tif"], "status": "delivered"}],
                 "modifications": {"referenced_in_rasmap": True,
                                   "rasmap_layers": [{"name": "Terrain", "filename": "Terrain.hdf",
                                                      "modifications": [{"element": "Channel", "name": "cut1"},
                                                                        {"element": "Levee", "name": "lv1"}]}]}},
    )
    acq = next(a for a in actions_from_bundle(bundle) if a.kind == "acquisition" and a.target.startswith("Terrain"))
    assert "2 terrain modification(s) referenced" in acq.evidence


def test_absent_expected_element_is_acquisition_and_needs_external_data():
    bundle = _minimal_bundle(
        study_findings={"interpretation": "2d unsteady", "projects_with_unsteady_flow_pct": 100.0},
        g7_rascheck={"outcome": "RAN", "flow_type_families": {"UNSTEADY": 1}},
        terrain={"delivered": 0, "gapped": 1, "rebuilt": 0, "projects": [
            {"project": "P", "terrain_hdf": [], "raster": [], "status": "gapped"}]},
    )
    actions = actions_from_bundle(bundle)
    acq = [a for a in actions if a.kind == "acquisition" and a.target == "Terrain"]
    assert len(acq) == 1 and acq[0].blocking
    markdown = render_audit_markdown(bundle)
    assert "needs data not in the delivery" in markdown
    # And it must surface in the shopping list, not only the verdict.
    section6 = markdown.split("## 6. What you must obtain")[1].split("## 7.")[0]
    assert "Terrain" in section6


def test_not_expected_elements_never_generate_actions():
    """1D steady never wants infiltration; its absence must not become an action."""
    bundle = _minimal_bundle()   # 1D steady, terrain delivered
    kinds = [(a.kind, a.target) for a in actions_from_bundle(bundle)]
    assert ("acquisition", "Infiltration") not in kinds
    assert ("acquisition", "DSS boundary data") not in kinds


# -- schema v2 captured fields win over v1 inference -------------------------

def test_captured_model_type_is_preferred_over_prose_inference():
    """The prose-derived fallback produced 'unknown' for one unit; a captured field must win."""
    bundle = _minimal_bundle(model_type="2D", flow_regime="unsteady",
                             study_findings={"interpretation": "1d steady", "projects_with_unsteady_flow_pct": 0.0})
    verdict = render_audit_markdown(bundle).split("## 1. Verdict")[1].split("## 2.")[0]
    assert "**2D unsteady**" in verdict


def test_mixed_study_expects_what_2d_expects():
    expected = expected_elements("mixed", "unsteady")
    assert expected["terrain"] and expected["rasmap"] and expected["projection"]


def test_verdict_uses_deficiency_review_totals_when_present():
    """deficiency_review counts every reviewed gap kind, not only MISSING_REFERENCE rows."""
    bundle = _minimal_bundle(deficiency_review={"reported": 2, "real": 2, "analysis_gap": 0, "unverifiable": 0})
    bundle.gaps = [  # only ONE of the two reviewed gaps is a MISSING_REFERENCE row
        {"gap": "MISSING_REFERENCE", "source_file": "x", "role": "r", "raw_value": "a",
         "review": {"verdict": "real", "evidence": ""}},
        {"gap": "TERRAIN_ABSENT_STUDY_WIDE", "source_file": "", "role": "terrain", "raw_value": "",
         "review": {"verdict": "real", "evidence": ""}},
    ]
    verdict = render_audit_markdown(bundle).split("## 1. Verdict")[1].split("## 2.")[0]
    assert "2 reported: **2 real**" in verdict


# -- deficiency review: real vs gap in our own analysis ----------------------

def _reviewed_gap(raw, verdict, evidence="", source="x.rasmap"):
    return {"gap": "MISSING_REFERENCE", "source_file": source, "role": "rasmap_attribute",
            "raw_value": raw, "review": {"verdict": verdict, "evidence": evidence,
                                          "method": "archive_member_match"}}


def test_analysis_gaps_leave_missing_and_must_obtain_but_are_reported_separately():
    """A gap that review found in the delivery was ours. The engineer must not chase it."""
    bundle = _minimal_bundle()
    bundle.gaps = [
        _reviewed_gap(r"..\Shp\real.shp", "real", "no member matches basename real.shp in 412 members"),
        _reviewed_gap(r"..\Land_Cover\lc.tif", "analysis_gap", "found as Land Cover/lc.tif in Models.zip"),
        _reviewed_gap(r"..\Land_Cover\lc.tif", "analysis_gap", "found as Land Cover/lc.tif in Models.zip"),
    ]
    markdown = render_audit_markdown(bundle)
    section5 = markdown.split("## 5. What is still missing")[1].split("## 6.")[0]
    section6 = markdown.split("## 6. What you must obtain")[1].split("## 7.")[0]

    assert r"`..\Shp\real.shp` | 1 |" in section5             # real: still listed
    assert "Reclassified during review" in section5
    assert r"`..\Land_Cover\lc.tif` | 2 | found as Land Cover/lc.tif" in section5
    # The reclassified file must not be counted among what is still missing.
    assert "1 missing references, 1 distinct files" in section5
    assert "lc.tif" not in section6


def test_verdict_reports_reviewed_counts():
    bundle = _minimal_bundle()
    bundle.gaps = [
        _reviewed_gap("a", "real"), _reviewed_gap("b", "analysis_gap"),
        _reviewed_gap("c", "unverifiable"), _reviewed_gap("d", "analysis_gap"),
    ]
    verdict = render_audit_markdown(bundle).split("## 1. Verdict")[1].split("## 2.")[0]
    assert "4 reported: **1 real**, 2 were gaps in our analysis, 1 unverifiable" in verdict


def test_unreviewed_gaps_are_marked_provisional():
    bundle = _minimal_bundle()
    bundle.gaps = [{"gap": "MISSING_REFERENCE", "source_file": "x", "role": "r", "raw_value": "a"}]
    verdict = render_audit_markdown(bundle).split("## 1. Verdict")[1].split("## 2.")[0]
    assert "not yet independently reviewed" in verdict


def test_unverifiable_gaps_are_flagged_not_counted_as_deficiencies():
    bundle = _minimal_bundle()
    bundle.gaps = [_reviewed_gap(r"..\x.dss", "unverifiable", "dss bridge unavailable", source="x.u01")]
    section5 = render_audit_markdown(bundle).split("## 5. What is still missing")[1].split("## 6.")[0]
    assert "could not be verified either way" in section5


# -- real data, when the audit tree is reachable -----------------------------

REAL = Path("F:/eBFE/audit/12040102")


@pytest.mark.skipif(not REAL.exists(), reason="corpus audit tree not mounted")
def test_renders_real_tranche01_study_with_all_sections():
    bundle = load_audit_bundle(REAL)
    markdown = render_audit_markdown(bundle)
    for heading in SECTIONS:
        assert heading in markdown
    assert "2D unsteady" in markdown
    assert "climbed 4 level(s)" in markdown              # the signature defect, measured
    assert "Spring Creek" in markdown or "12040102" in markdown


# -- the independent review overrides an element the capture called absent ---

def _reviewed_absent_layer(verdict: str):
    return _two_d_unsteady(supporting_elements={
        "land_cover": {
            "state": "no", "location": None, "referenced": True, "referenced_count": 4,
            "note": "referenced 4 time(s), but the layer HEC-RAS opens is absent",
            "review": {"verdict": verdict, "method": "archive_member_match",
                       "evidence": "land_cover referenced and delivered as X.zip::Models/NB_1/Landcover/Manning_N.hdf"},
        },
    })


def test_review_analysis_gap_on_a_layer_is_not_an_acquisition():
    """North Bosque (12060204): the capture said Manning's n was absent, the review found it
    at exactly the referenced path. The document must not call that "needs data"."""
    bundle = _reviewed_absent_layer("analysis_gap")
    actions = actions_from_bundle(bundle)
    assert not any(a.kind == "acquisition" for a in actions)
    markdown = render_audit_markdown(bundle)
    assert "needs data not in the delivery" not in markdown
    assert "Critical data missing" not in markdown
    row = next(l for l in markdown.splitlines() if l.startswith("| Land cover / Manning's n |"))
    assert "Yes" in row and "**No**" not in row
    assert "Landcover/Manning_N.hdf" in row
    # and the reclassification is visible in section 5
    assert "Land cover / Manning's n (layer)" in markdown
    assert "Reclassified during review" in markdown


def test_review_real_on_a_layer_keeps_the_acquisition():
    bundle = _reviewed_absent_layer("real")
    acq = [a for a in actions_from_bundle(bundle) if a.kind == "acquisition"]
    assert [a.target for a in acq] == ["Land cover / Manning's n"]
    assert "needs data not in the delivery" in render_audit_markdown(bundle)


def test_relocation_recorded_twice_renders_as_one_step():
    """The worker writes each relocation into asset_relocation AND as a recipe."""
    move = {"from": "RAS Model/A/Output/x.IC.O01", "to": "RAS Model/A/Input/x.IC.O01"}
    bundle = _two_d_unsteady(asset_relocation={"assets_relocated": 1, "relocated": [dict(move, archive="k", evidence="e")]})
    bundle.recipes = [dict(move, file=move["to"], surface="asset_relocation", locator="A/Output/x.IC.O01",
                           why="separately_delivered", confidence="resolved")]
    moves = [a for a in actions_from_bundle(bundle) if a.kind == "file_movement"]
    assert len(moves) == 1


def test_identity_recipe_is_not_an_action():
    bundle = _two_d_unsteady()
    bundle.recipes = [{"file": "x.rasmap", "surface": "rasmap_attribute", "locator": "L",
                       "from": r"..\Terrain\Terrain.hdf", "to": r"..\Terrain\Terrain.hdf",
                       "why": "relocated_by_assembly", "confidence": "resolved", "origin": "deficiency_review"}]
    assert actions_from_bundle(bundle) == []


def test_captured_terrain_absent_entry_is_dropped_when_the_record_shows_the_hdf_delivered():
    """Middle Guadalupe (12100202): the capture wrote terrain_hdf_absent_modifications_referenced
    for MIDG01/MIDG02, yet terrain.projects shows Terrain.hdf delivered for both -- only DEM
    source tiles are missing (state partial). The document must not say the HDF is absent."""
    bundle = _two_d_unsteady(
        supporting_elements={"terrain": {"state": "partial", "location": None, "referenced": True,
                                         "note": "2 source tiles missing"}},
        terrain={"delivered": 2, "gapped": 0, "rebuilt": 0,
                 "projects": [{"project": "MIDG01/Input", "terrain_hdf": ["Terrain.hdf"], "raster": ["a.tif"]},
                              {"project": "MIDG02/Input", "terrain_hdf": ["Terrain (1).hdf"], "raster": ["b.tif"]}],
                 "modifications": {"referenced_in_rasmap": True, "rasmap_layers": []}},
        critical_missing=[{"element": "terrain", "reason": "terrain_hdf_absent_modifications_referenced",
                           "projects": ["MIDG01/Input", "MIDG02/Input"], "evidence": "x"}],
    )
    markdown = render_audit_markdown(bundle)
    assert "terrain hdf absent" not in markdown
    # the partial terrain is still an acquisition, so the verdict is unchanged
    assert "needs data not in the delivery" in markdown
    assert "**Terrain** -- incomplete in the delivery" in markdown
    assert "**Terrain** -- not in the delivery" not in markdown


def test_captured_terrain_absent_entry_is_kept_when_the_hdf_really_is_absent():
    bundle = _two_d_unsteady(
        supporting_elements={"terrain": {"state": "source_only", "location": None, "referenced": True, "note": ""}},
        terrain={"delivered": 0, "gapped": 1, "rebuilt": 0,
                 "projects": [{"project": "SG/Input", "terrain_hdf": [], "raster": ["dem.tif"]}],
                 "modifications": {"referenced_in_rasmap": True, "rasmap_layers": []}},
        critical_missing=[{"element": "terrain", "reason": "terrain_hdf_absent_modifications_referenced",
                           "projects": ["SG/Input"], "evidence": "x"}],
    )
    assert "terrain hdf absent modifications referenced" in render_audit_markdown(bundle)


# -- DSS element state follows the boundary verification (worker rev i) ------

def test_dss_state_follows_verification_when_every_boundary_resolved():
    """Tule (11120104): 42 of 42 boundaries verified against delivered DSS members,
    yet the element capture said "no" because the file was not at the literal
    post-assembly path. The verification is the authority."""
    bundle = _two_d_unsteady(
        supporting_elements={"dss": {"state": "no", "location": None, "referenced": True, "referenced_count": 86,
                                     "note": "referenced 86 time(s) but the layer HEC-RAS opens is absent"}},
        dss_verification={"bridge_available": True, "boundaries_checked": 42, "boundaries_resolved": 42,
                          "boundaries_acquisition": 0, "boundaries_inferred": 0,
                          "resolved_needing_path_correction": 42},
    )
    assert not any(a.kind == "acquisition" and a.target == "DSS boundary data" for a in actions_from_bundle(bundle))
    markdown = render_audit_markdown(bundle)
    row = next(l for l in markdown.splitlines() if l.startswith("| DSS boundary data |"))
    assert "Yes" in row and "42 of 42" in row


def test_dss_state_partial_when_some_boundaries_need_data():
    bundle = _two_d_unsteady(
        supporting_elements={"dss": {"state": "no", "location": None, "referenced": True, "referenced_count": 14, "note": ""}},
        dss_verification={"bridge_available": True, "boundaries_checked": 14, "boundaries_resolved": 5,
                          "boundaries_acquisition": 9, "boundaries_inferred": 0},
    )
    acq = [a for a in actions_from_bundle(bundle) if a.kind == "acquisition" and a.target == "DSS boundary data"]
    assert len(acq) == 1 and acq[0].reason == "partially_delivered"
    assert "incomplete in the delivery" in render_audit_markdown(bundle)


def test_dss_captured_yes_is_not_downgraded_by_unverified_boundaries():
    bundle = _two_d_unsteady(
        supporting_elements={"dss": {"state": "yes", "location": "DSS/x.dss", "referenced": True, "note": ""}},
        dss_verification={"bridge_available": True, "boundaries_checked": 3, "boundaries_resolved": 0,
                          "boundaries_acquisition": 0, "boundaries_inferred": 3},
    )
    row = next(l for l in render_audit_markdown(bundle).splitlines() if l.startswith("| DSS boundary data |"))
    assert "Yes" in row


def test_acquisition_recipes_become_acquisition_actions_and_the_verdict_needs_data():
    """Spring Creek (12040102) under worker rev i: 24 dss_pathname recipes with
    confidence "acquisition" (the HMS DSS is in no archive, reviewed real), yet
    the document read "after repair" because every dss_pathname recipe mapped to
    a path correction."""
    bundle = _two_d_unsteady(
        supporting_elements={"dss": {"state": "yes", "location": "DSS Inputs/Spring.dss", "referenced": True, "note": ""}},
        dss_verification={"bridge_available": True, "boundaries_checked": 14, "boundaries_resolved": 0,
                          "boundaries_acquisition": 14, "boundaries_inferred": 0},
    )
    hms = "..\\..\\..\\..\\HEC-HMS_v43\\Spring\\"

    def recipe(plan, dss):
        return {"file": f"RAS Model/HECRAS_507/Spring.{plan}", "surface": "dss_pathname",
                "locator": f"Spring.{plan}:23:DSS File", "from": hms + dss,
                "to": None, "why": "missing_from_delivery", "confidence": "acquisition", "kind": "acquisition",
                "acquisition_target": hms + dss,
                "confidence_reason": "C-part PRECIP-EXCESS absent from every delivered candidate",
                "blocking": True, "project": "RAS Model/HECRAS_507",
                "review": {"verdict": "real", "method": "archive_member_match"}}

    bundle.recipes = [recipe("u05", "50YR.dss"), recipe("u06", "50YR.dss"), recipe("u01", "100YR.dss")]
    actions = actions_from_bundle(bundle)
    acq = [a for a in actions if a.kind == "acquisition"]
    assert sorted(a.target for a in acq) == ["DSS boundary data (100YR.dss)", "DSS boundary data (50YR.dss)"]
    assert all(a.blocking and a.escape_depth == 4 for a in acq)
    assert not any(a.kind == "path_correction" for a in actions)
    markdown = render_audit_markdown(bundle)
    assert "needs data not in the delivery" in markdown
    assert "| Critical data missing | **DSS boundary data** -- not in the delivery |" in markdown
    row = next(l for l in markdown.splitlines() if l.startswith("| DSS boundary data |"))
    assert "**No**" in row and "14 of 14" in row


def test_reviewed_analysis_gap_dss_acquisition_is_replaced_by_corrected_path_action():
    """Aransas (12100407): an unreadable DSS catalog caused 20 provisional
    acquisitions. Review found each authored DSS file in the delivery and
    appended the corrected path recipe, so the predecessor acquisition must
    not survive into the engineer-facing action list or critical verdict.

    Corrected 2026-09-19. "Found" now has to mean found the RECORD. The review
    that produced these corrections matched a basename in the archive member
    index, which shows a file of that name was delivered and nothing about what
    is inside it -- and where the reader worked, such files repeatedly did not
    hold the requested pathname (12060101, 11010008). So the replacement holds
    only for a record-proven review; a name match leaves the acquisition
    standing, which is the case the second half of this test pins.
    """
    bundle = _two_d_unsteady(
        supporting_elements={
            "dss": {
                "state": "yes",
                "location": "DSS Inputs/Aransas.dss",
                "referenced": True,
                "note": "",
            }
        },
        dss_verification={
            "bridge_available": False,
            "boundaries_checked": 1,
            "boundaries_resolved": 1,
            "boundaries_acquisition": 0,
            "boundaries_inferred": 0,
            "resolved_needing_path_correction": 1,
        },
    )
    acquisition = {
        "file": "RAS Model/HECRAS_507/Aransas.u01",
        "surface": "dss_pathname",
        "locator": "Aransas.u01:9:DSS File",
        "from": r"..\..\..\..\HEC-HMS_v43\Aransas\100YR.dss",
        "to": r".\DSS Inputs\Aransas.dss",
        "why": "relocated_by_assembly",
        "confidence": "acquisition",
        "kind": "acquisition",
        "acquisition_target": r"..\..\..\..\HEC-HMS_v43\Aransas\100YR.dss",
        "review": {
            "verdict": "analysis_gap",
            "method": "dss_record_match",
            "evidence": ("original 100YR.dss delivered as Models.zip::_Final/DSS/100YR.dss; "
                         "its catalog holds //ARANSAS/PRECIP-INC/.../RUN:100YR/"),
        },
    }
    correction = {
        "file": acquisition["file"],
        "surface": "dss_pathname",
        "locator": acquisition["locator"],
        "from": r".\DSS Inputs\Aransas.dss",
        "to": r"..\DSS\100YR.dss",
        "why": "relocated_by_assembly",
        "confidence": "inferred",
        "origin": "deficiency_review",
        "blocking": True,
    }
    bundle.recipes = [acquisition, correction]

    actions = actions_from_bundle(bundle)
    assert [a.kind for a in actions] == ["path_correction"]
    assert actions[0].to_value == r"..\DSS\100YR.dss"
    markdown = render_audit_markdown(bundle)
    assert "needs data not in the delivery" not in markdown
    assert "Critical data missing" not in markdown
    assert "Obtain `DSS boundary data" not in markdown
    assert "change `.\\DSS Inputs\\Aransas.dss` to `..\\DSS\\100YR.dss`" in markdown

    # The same review, decided by NAME. 12050007 is where that went wrong: the
    # finding was dropped and the engineer was sent to a file nothing had read.
    acquisition["review"] = {
        "verdict": "analysis_gap",
        "method": "archive_member_match",
        "evidence": "original 100YR.dss delivered as Models.zip::_Final/DSS/100YR.dss",
    }
    bundle.recipes = [acquisition, correction]
    kinds = [a.kind for a in actions_from_bundle(bundle)]
    assert kinds == ["path_correction", "acquisition"]
    assert "Obtain `DSS boundary data (100YR.dss)" in render_audit_markdown(bundle)


def test_path_corrections_with_same_values_but_different_files_are_not_deduplicated():
    bundle = _two_d_unsteady()
    shared = {
        "surface": "dss_pathname",
        "from": r".\DSS Inputs\Aransas.dss",
        "to": r"..\DSS\100YR.dss",
        "why": "relocated_by_assembly",
        "confidence": "inferred",
        "origin": "deficiency_review",
    }
    bundle.recipes = [
        dict(shared, file="Aransas.u01", locator="Aransas.u01:9:DSS File"),
        dict(shared, file="Aransas.u01", locator="Aransas.u01:40:DSS File"),
        dict(shared, file="Aransas.u02", locator="Aransas.u02:9:DSS File"),
    ]
    corrections = [action for action in actions_from_bundle(bundle) if action.kind == "path_correction"]
    assert [(action.target, action.evidence) for action in corrections] == [
        ("Aransas.u01", "Aransas.u01:40:DSS File"),
        ("Aransas.u01", "Aransas.u01:9:DSS File"),
        ("Aransas.u02", "Aransas.u02:9:DSS File"),
    ]


def test_registered_element_scope_excludes_unregistered_flow_actions():
    bundle = _two_d_unsteady()
    bundle.models = [{
        "prj_file": "Aransas.prj",
        "elements": [
            {"type": "unsteady_flow", "number": "01", "registered": True},
            {"type": "unsteady_flow", "number": "02", "registered": True},
        ],
    }]
    shared = {
        "surface": "dss_pathname",
        "from": r".\DSS Inputs\Aransas.dss",
        "to": r"..\DSS\100YR.dss",
        "why": "relocated_by_assembly",
        "confidence": "inferred",
        "origin": "deficiency_review",
    }
    bundle.recipes = [
        dict(shared, file="Aransas.u01", locator="Aransas.u01:9:DSS File"),
        dict(shared, file="Aransas.u03", locator="Aransas.u03:9:DSS File"),
        dict(shared, file="Backup.u01", locator="Backup.u01:9:DSS File"),
    ]
    corrections = [action for action in actions_from_bundle(bundle) if action.kind == "path_correction"]
    assert [(action.target, action.evidence) for action in corrections] == [
        ("Aransas.u01", "Aransas.u01:9:DSS File"),
    ]


def test_reviewed_dss_destinations_and_plan_hdf_list_replace_sampled_capture():
    bundle = _two_d_unsteady(supporting_elements={
        "dss": {
            "state": "yes", "location": r".\DSS Inputs\Aransas.dss",
            "referenced": True, "note": "1 referenced, 1 resolve",
        },
        "results_hdf": {
            "state": "yes", "location": "Aransas.p09.hdf", "referenced": True,
            "note": "2 plan HDFs",
        },
    })
    bundle.models = [{
        "prj_file": "Aransas.prj",
        "elements": [
            {"type": "plan", "number": "09", "registered": True},
            {"type": "plan", "number": "10", "registered": True},
            {"type": "unsteady_flow", "number": "01", "registered": True},
            {"type": "unsteady_flow", "number": "02", "registered": True},
        ],
    }]
    bundle.recipes = [
        # ``verified_by: dss_pathname`` is the record-level proof a DSS
        # destination needs before this row may name it (2026-09-19).
        {"file": "Aransas.u01", "surface": "dss_pathname", "locator": "u01:9",
         "from": r".\DSS Inputs\Aransas.dss", "to": r"..\DSS\100YR.dss",
         "origin": "deficiency_review", "verified_by": "dss_pathname"},
        {"file": "Aransas.u02", "surface": "dss_pathname", "locator": "u02:9",
         "from": r".\DSS Inputs\Aransas.dss", "to": r"..\DSS\500YR.dss",
         "origin": "deficiency_review", "verified_by": "dss_pathname"},
        {"file": "Aransas.p09.hdf", "surface": "hdf_asset_attribute", "locator": "Geometry@x",
         "from": "old", "to": "new"},
        {"file": "Aransas.p10.hdf", "surface": "hdf_asset_attribute", "locator": "Geometry@x",
         "from": "old", "to": "new"},
    ]
    markdown = render_audit_markdown(bundle)
    dss = next(line for line in markdown.splitlines() if line.startswith("| DSS boundary data |"))
    assert r"..\DSS\100YR.dss, ..\DSS\500YR.dss" in dss
    assert "2 reviewed references resolve to 2 delivered DSS files" in dss
    assert r".\DSS Inputs\Aransas.dss" not in dss
    results = next(line for line in markdown.splitlines() if line.startswith("| Results (plan HDFs) |"))
    assert "Aransas.p09.hdf, Aransas.p10.hdf" in results
    assert "2 plan HDFs" in results


@pytest.mark.skipif(not Path(r"F:\eBFE\audit\12100407\_audit.json").is_file(), reason="Aransas audit unavailable")
def test_aransas_reviewed_render_is_registration_scoped_and_inventory_complete():
    """Aransas is one of the 39 studies whose DSS record check never ran.

    It read 0 resolved / 0 acquisition / 14 inferred, every reason "catalog read
    failed: RuntimeError: Java not found", and its twenty reviewed DSS
    corrections were basename matches made while that reader was failing. This
    test pinned the held state.

    Updated 2026-09-19 after the check was re-answered from the delivered DSS
    members: all 14 boundaries resolve against catalogs that were actually read,
    so the row names its location instead of explaining a hold, and the fourteen
    DSS actions are gone. The twenty `dss_pathname` acquisitions that remain in
    the record belong to UNREGISTERED unsteady files (u03-u07), which is why
    they do not appear here -- registration scoping is what this test is really
    about, and it is unchanged in both directions.
    """
    bundle = load_audit_bundle(Path(r"F:\eBFE\audit\12100407"))
    actions = actions_from_bundle(bundle)
    dss_actions = [action for action in actions if action.evidence.endswith(":DSS File")]
    assert len(actions) == 26
    assert sum(action.blocking for action in actions) == 24
    # The boundaries resolved, so nothing is asked of the operator for them.
    assert len(dss_actions) == 0
    assert not any(
        Path(action.target).name in {
            "Aransas.u03", "Aransas.u04", "Aransas.u05", "Aransas.u06", "Aransas.u07", "Backup.u01"
        }
        for action in actions
    )

    markdown = render_audit_markdown(bundle)
    dss = next(line for line in markdown.splitlines() if line.startswith("| DSS boundary data |"))
    # The check ran, so the row states what was read rather than why it could not be.
    assert "Not verified" not in dss
    assert "Java not found" not in dss
    assert r".\DSS Inputs\Aransas.dss" in dss
    assert "1 referenced, 1 resolve" in dss
    # Nothing is held any more ...
    assert "**Did not run**" not in markdown
    assert "The DSS boundary check did not run for this study." not in markdown
    assert "unconfirmed: the DSS record check did not run" not in markdown
    # ... and a corrected record says so on its face, so it is never mistaken
    # for a re-run record.
    assert "re-verified in place on 2026-09-19T23:25:13Z" in markdown
    assert "not re-run" in markdown
    # The producer's own acquisitions are still reported, now as established facts.
    for name in ("01__MINUS.dss", "10_ACE.dss", "100YR.dss", "100YR_PLUS.dss", "25YR.dss", "500YR.dss", "50YR.dss"):
        assert f"DSS boundary data ({name})" in markdown
    results = next(line for line in markdown.splitlines() if line.startswith("| Results (plan HDFs) |"))
    for number in ("09", "10", "11", "16", "17", "18", "19"):
        assert f"Aransas.p{number}.hdf" in results
    assert "7 plan HDFs" in results


# -- chained models: one model's output DSS is the next model's boundary -----
#
# Salt Fork Brazos (12050007) is the worked shape: 1205000705_06 reads
# ``..\..\1205000701_02\Simulations\1205000701_02.dss``, the producing model is
# in the same archive, and only its *input* DSS was delivered. Corpus-wide this
# is 118 boundary pathnames across 14 studies -- 27 files in 8 of them once the
# producer must also be delivered.

def _chained_bundle(target, pathnames, project, models, **overrides):
    bundle = _two_d_unsteady(
        supporting_elements={"dss": {"state": "no", "location": None, "referenced": True, "note": ""}},
        dss_verification={
            "bridge_available": True, "boundaries_checked": 6, "boundaries_resolved": 0,
            "boundaries_acquisition": 6, "boundaries_inferred": 0,
            "acquisition_targets": [{"dss_file": target, "pathnames": list(pathnames)}],
        },
        **overrides,
    )
    bundle.models = models
    bundle.recipes = [{
        "file": "RAS Model/RAS_Submittal/1205000705_06/Input/1205000705_06.u07",
        "surface": "dss_pathname", "locator": "1205000705_06.u07:158:DSS File",
        "from": target, "to": None, "why": "missing_from_delivery",
        "confidence": "acquisition", "kind": "acquisition", "acquisition_target": target,
        "confidence_reason": "no A/B/C/E/F match from every delivered candidate (2 readable of 2)",
        "blocking": True, "project": project,
        "review": {"verdict": "real", "method": "archive_member_match"},
    }]
    return bundle


_SALT_FORK_TARGET = r"..\..\1205000701_02\Simulations\1205000701_02.dss"
_SALT_FORK_PATHNAMES = [
    "/REFERENCE LINES/1205000701_02: 1205000701/FLOW/31Dec1999 - 11Jan2000/15Minute/01PCT/",
    "/REFERENCE LINES/1205000701_02: 1205000701/FLOW/31Dec1999 - 11Jan2000/15Minute/02PCT/",
]
_SALT_FORK_CONSUMER = "RAS Model/RAS_Submittal/1205000705_06/Input"
_SALT_FORK_MODELS = [
    {"prj_file": "1205000701_02.prj", "project_folder": "/work/RAS Model/RAS_Submittal/1205000701_02/Input"},
    {"prj_file": "1205000705_06.prj", "project_folder": "/work/RAS Model/RAS_Submittal/1205000705_06/Input"},
]


@pytest.mark.parametrize(
    "pathname, a_part",
    [
        ("/REFERENCE LINES/1205000701_02: 1205000701/FLOW/31Dec1999/15Minute/01PCT/", "REFERENCE LINES"),
        ("/BCLINE/1205000705_06: 1205000705_06/FLOW/01Dec1999/15Minute/01PCT/", "BCLINE"),
        ("/SA CONNECTION/Dam_Discharge/FLOW/01Dec2019/1Hour/01PCT/", "SA CONNECTION"),
        ("//FORT_SUPPLY_BEAVER/PRECIP-EXCESS/01JAN2020/6MIN/RUN:100YR/", ""),
    ],
)
def test_dss_pathname_parts_reads_the_a_part(pathname, a_part):
    assert dss_pathname_parts(pathname)[0] == a_part


def test_a_windows_path_is_not_a_dss_pathname():
    assert dss_pathname_parts(r"..\Simulations\x.dss") == ()
    assert dss_pathname_parts(None) == ()


def test_combined_project_names_every_model_it_contains():
    """``1205000701_02`` is two models; ``1206010107_0809`` is three."""
    names = delivered_model_names([
        {"prj_file": "1205000701_02.prj", "project_folder": "/w/RAS_Submittal/1205000701_02/Input"},
        {"prj_file": "Boggy_Elm_Fish.prj", "project_folder": "/w/RAS_Submittal/1206010107_0809/Input"},
    ])
    assert names["1205000701"] == "1205000701_02"
    assert names["1205000702"] == "1205000701_02"
    assert names["1206010108"] == "Boggy_Elm_Fish"
    assert names["1206010109"] == "Boggy_Elm_Fish"
    # Scaffolding is not a model name.
    assert "input" not in names and "rassubmittal" not in names


def test_chained_output_dss_with_delivered_producer_is_a_chain_rerun_not_an_acquisition():
    bundle = _chained_bundle(_SALT_FORK_TARGET, _SALT_FORK_PATHNAMES,
                             _SALT_FORK_CONSUMER, _SALT_FORK_MODELS)
    actions = actions_from_bundle(bundle)
    runs = [a for a in actions if a.kind == "chained_model_rerun"]
    assert [a.target for a in runs] == ["DSS boundary data (1205000701_02.dss)"]
    assert runs[0].source == "1205000701_02"
    assert runs[0].blocking
    assert not [a for a in actions if a.kind == "acquisition"]
    markdown = render_audit_markdown(bundle)
    assert ("| Runnable as delivered | **after repair (from the delivery alone, "
            "including a sequential re-run of chained sub-models)** |") in markdown
    # It is not "needs data", and it is not "Critical data missing".
    assert "needs data not in the delivery" not in markdown
    assert "Critical data missing" not in markdown
    assert "Re-run the chained sub-model `1205000701_02`" in markdown


def test_chain_rerun_is_never_something_to_obtain():
    bundle = _chained_bundle(_SALT_FORK_TARGET, _SALT_FORK_PATHNAMES,
                             _SALT_FORK_CONSUMER, _SALT_FORK_MODELS)
    markdown = render_audit_markdown(bundle)
    obtain = markdown.split("## 6. What you must obtain")[1].split("## 7.")[0]
    assert "Obtain `DSS boundary data" not in obtain
    assert "no file can be obtained that substitutes for re-running" in obtain


def test_chained_output_dss_without_a_delivered_producer_stays_a_blocking_acquisition():
    """The rule must not weaken. Cross Bayou (11140304) reads Caddo Lake's
    output and Caddo Lake is in no archive."""
    target = r"..\..\CaddoLake\Final_Model\CaddoLake.dss"
    bundle = _chained_bundle(
        target, ["/BCLINE/CaddoLake: Outflow/FLOW/01Jan2020/1Hour/01PCT/"],
        "RAS Model/RAS_Submittal/Input",
        [{"prj_file": "CrossBayou.prj", "project_folder": "/work/RAS Model/RAS_Submittal/Input"}],
    )
    actions = actions_from_bundle(bundle)
    assert not [a for a in actions if a.kind == "chained_model_rerun"]
    assert [a.target for a in actions if a.kind == "acquisition"] == ["DSS boundary data (CaddoLake.dss)"]
    assert "needs data not in the delivery" in render_audit_markdown(bundle)


def test_meteorological_boundary_is_never_a_chain_rerun():
    """745 of the corpus's unresolved pathnames are HMS products. No HEC-RAS run
    writes a PRECIP-EXCESS record, so no delivered model substitutes for one."""
    target = r"..\..\HEC_HMS\Spring\100YR.dss"
    bundle = _chained_bundle(
        target, ["//SPRING/PRECIP-EXCESS/01JAN2020/6MIN/RUN:100YR/"],
        "RAS Model/RAS_Submittal/Spring/Input",
        [{"prj_file": "Spring.prj", "project_folder": "/work/RAS Model/RAS_Submittal/Spring/Input"},
         {"prj_file": "Upstream.prj", "project_folder": "/work/RAS Model/RAS_Submittal/Upstream/Input"}],
    )
    actions = actions_from_bundle(bundle)
    assert not [a for a in actions if a.kind == "chained_model_rerun"]
    assert [a.target for a in actions if a.kind == "acquisition"] == ["DSS boundary data (100YR.dss)"]


def test_a_file_that_also_owes_a_meteorological_record_stays_an_acquisition():
    """City of Shattuck (11100203): the same DSS is asked for SA CONNECTION
    records and one PRECIP-EXCESS record. Running the upstream model cannot
    supply the second, so the blocking acquisition stands."""
    target = r"..\..\..\City_of_Shattuck_Wolf_Creek\RAS\Input\CityofShattuckWolfCreek.dss"
    bundle = _chained_bundle(
        target,
        ["/SA CONNECTION/new_downstream/STAGE-HW/01Dec2019/1Hour/01PAC/",
         "//FORT_SUPPLY_BEAVER/PRECIP-EXCESS/01JAN2020/6MIN/RUN:100YR/"],
        "RAS Model/Hydraulic Models/Fort_Supply_Lake_Wolf_Creek/Input",
        [{"prj_file": "CityofShattuckWolfCreek.prj",
          "project_folder": "/work/RAS Model/Hydraulic Models/City_of_Shattuck_Wolf_Creek/Input"},
         {"prj_file": "FortSupplyLakeWolfCreek.prj",
          "project_folder": "/work/RAS Model/Hydraulic Models/Fort_Supply_Lake_Wolf_Creek/Input"}],
    )
    assert not [a for a in actions_from_bundle(bundle) if a.kind == "chained_model_rerun"]


def test_a_project_is_never_its_own_upstream_model():
    """12060101 stages its inflow in a DSS named after the *consuming* project.
    Matching the basename alone would nominate the consumer as its own producer."""
    target = r".\DSS Inputs\1206010103LakeDutch.dss"
    models = [
        {"prj_file": "1206010101NorthLitt.prj", "project_folder": "/w/RAS_Submittal/1206010101_02/Input"},
        {"prj_file": "1206010103LakeDutch.prj", "project_folder": "/w/RAS_Submittal/1206010103_04/Input"},
    ]
    bundle = _chained_bundle(
        target, ["/REFERENCE LINES/North Croton Cre: 1206010102/FLOW/01Jan2020/1Hour/01PCT/"],
        "/w/RAS_Submittal/1206010103_04/Input", models)
    runs = [a for a in actions_from_bundle(bundle) if a.kind == "chained_model_rerun"]
    assert [a.source for a in runs] == ["1206010101NorthLitt"]


def test_review_analysis_gap_cannot_rewrite_a_chained_boundary_onto_an_input_dss():
    """The review matched the basename, declared "original HMS file is in the
    delivery", and rewrote 12050007's Simulations reference onto the producer's
    Input DSS -- which holds no REFERENCE LINES record. The finding then
    vanished from the document. The A-part rule refuses that premise."""
    bundle = _chained_bundle(_SALT_FORK_TARGET, _SALT_FORK_PATHNAMES,
                             _SALT_FORK_CONSUMER, _SALT_FORK_MODELS)
    bundle.recipes[0]["review"] = {
        "verdict": "analysis_gap",
        "method": "archive_member_match",
        "evidence": "original 1205000701_02.dss delivered as Models.zip::"
                    "RAS_Submittal/1205000701_02/Input/1205000701_02.dss",
    }
    actions = actions_from_bundle(bundle)
    assert [a.kind for a in actions if a.kind == "chained_model_rerun"] == ["chained_model_rerun"]
    assert "including a sequential re-run of chained sub-models" in render_audit_markdown(bundle)


def test_ordinary_reviewed_analysis_gap_is_still_honoured():
    """Aransas's HMS file really was delivered elsewhere.

    Corrected 2026-09-19: "really was delivered" has to be proven at the record,
    not the filename. A ``dss_record_match`` leaves no per-file step of any kind
    -- no chained re-run and no "obtain 100YR.dss". An ``archive_member_match``
    proves only that a file of that name shipped, so the acquisition stands.
    """
    def reviewed(method):
        bundle = _chained_bundle(
            r"..\..\HEC-HMS_v43\Aransas\100YR.dss",
            ["//ARANSAS/PRECIP-INC/01JAN2020/15MIN/RUN:100YR/"],
            "RAS Model/HECRAS_507",
            [{"prj_file": "Aransas.prj", "project_folder": "/work/RAS Model/HECRAS_507"}],
        )
        bundle.recipes[0]["review"] = {
            "verdict": "analysis_gap", "method": method,
            "evidence": "delivered as Models.zip::DSS/100YR.dss"}
        return bundle, actions_from_bundle(bundle)

    bundle, actions = reviewed("dss_record_match")
    assert not [a for a in actions if a.kind == "chained_model_rerun"]
    assert not [a for a in actions if "100YR.dss" in a.target]
    assert chained_dss_targets(bundle) == {}

    bundle, actions = reviewed("archive_member_match")
    assert [a.kind for a in actions if "100YR.dss" in a.target] == ["acquisition"]


def test_dss_row_names_the_producing_model_rather_than_calling_the_data_absent():
    bundle = _chained_bundle(_SALT_FORK_TARGET, _SALT_FORK_PATHNAMES,
                             _SALT_FORK_CONSUMER, _SALT_FORK_MODELS)
    markdown = render_audit_markdown(bundle)
    row = next(l for l in markdown.splitlines() if l.startswith("| DSS boundary data |"))
    assert CHAINED_DSS_NOTE.split(" (")[0] in row
    assert "1205000701_02" in row
    assert "**No**" not in row


def test_chain_rerun_executes_after_path_correction_and_before_acquisition():
    assert ACTION_KINDS.index("chained_model_rerun") > ACTION_KINDS.index("path_correction")
    assert ACTION_KINDS.index("chained_model_rerun") > ACTION_KINDS.index("reconstruction")
    assert ACTION_KINDS.index("chained_model_rerun") < ACTION_KINDS.index("acquisition")


def test_an_outstanding_acquisition_still_outranks_a_chain_rerun():
    """11090102 needs five upstream runs and eight files nobody shipped. The
    harsher verdict wins, and the DSS row reports both."""
    bundle = _chained_bundle(_SALT_FORK_TARGET, _SALT_FORK_PATHNAMES,
                             _SALT_FORK_CONSUMER, _SALT_FORK_MODELS)
    bundle.audit["dss_verification"]["acquisition_targets"].append(
        {"dss_file": r"..\..\HMS\100YR.dss",
         "pathnames": ["//BASIN/PRECIP-INC/01Jan2020/15MIN/RUN:100YR/"]})
    bundle.recipes.append({
        "file": "RAS Model/RAS_Submittal/1205000705_06/Input/1205000705_06.u08",
        "surface": "dss_pathname", "locator": "1205000705_06.u08:12:DSS File",
        "from": r"..\..\HMS\100YR.dss", "to": None, "why": "missing_from_delivery",
        "confidence": "acquisition", "kind": "acquisition",
        "acquisition_target": r"..\..\HMS\100YR.dss",
        "blocking": True, "project": _SALT_FORK_CONSUMER,
        "review": {"verdict": "real", "method": "archive_member_match"},
    })
    actions = actions_from_bundle(bundle)
    assert len([a for a in actions if a.kind == "chained_model_rerun"]) == 1
    assert [a.target for a in actions if a.kind == "acquisition"] == ["DSS boundary data (100YR.dss)"]
    markdown = render_audit_markdown(bundle)
    assert "| Runnable as delivered | **no -- needs data not in the delivery** |" in markdown
    row = next(l for l in markdown.splitlines() if l.startswith("| DSS boundary data |"))
    assert "1205000701_02" in row


def test_chained_targets_obey_the_same_registration_scope_as_the_actions():
    """The DSS row and the action list must name the same files.

    ``chained_dss_targets`` feeds the supporting-data row; ``actions_from_bundle``
    builds the steps. Both are bounded by the captured ``.prj`` element
    inventory (renderer dd83b4e14): a recipe for an unregistered ``.uNN`` is
    delivered corpus residue, not a step required to run the project. Without
    that filter on the targets the row would flip to "produced upstream" -- and
    that state suppresses the element-level DSS acquisition -- while no upstream
    run was ever emitted, so the boundary would vanish from the document and the
    verdict would soften with nothing accounting for it.
    """
    models = [{
        "prj_file": "1205000705_06.prj",
        "project_folder": "/work/RAS Model/RAS_Submittal/1205000705_06/Input",
        "elements": [{"type": "unsteady_flow", "number": "07", "registered": True}],
    }, {
        "prj_file": "1205000701_02.prj",
        "project_folder": "/work/RAS Model/RAS_Submittal/1205000701_02/Input",
        "elements": [{"type": "unsteady_flow", "number": "01", "registered": True}],
    }]
    bundle = _chained_bundle(_SALT_FORK_TARGET, _SALT_FORK_PATHNAMES,
                             _SALT_FORK_CONSUMER, models)
    # The only recipe naming this DSS lives in a .u01 that the .prj of
    # 1205000705_06 does not register.
    bundle.recipes[0]["file"] = "RAS Model/RAS_Submittal/1205000705_06/Input/1205000705_06.u01"

    assert chained_dss_targets(bundle) == {}, "an unregistered element is not in scope"
    actions = actions_from_bundle(bundle)
    assert not [a for a in actions if a.kind == "chained_model_rerun"]
    # The row keeps its absent state, and the element-level acquisition stands.
    row = next(l for l in render_audit_markdown(bundle).splitlines()
               if l.startswith("| DSS boundary data |"))
    assert CHAINED_DSS_NOTE.split(" (")[0] not in row
    assert [a.target for a in actions if a.kind == "acquisition"] == ["DSS boundary data"]

    # The same recipe on a registered element is in scope, both ways.
    bundle.recipes[0]["file"] = "RAS Model/RAS_Submittal/1205000705_06/Input/1205000705_06.u07"
    assert chained_dss_targets(bundle) == {"1205000701_02.dss": "1205000701_02"}
    assert [a.kind for a in actions_from_bundle(bundle) if a.kind == "chained_model_rerun"] == [
        "chained_model_rerun"
    ]


# -- the chain is sequential, and may be several models deep -----------------
#
# A chained sub-model may itself read another chained sub-model's output. Four
# of the fourteen affected studies are deeper than one: 11010008 and 11090102
# are four deep, 12050007 and 12060101 three. So the requirement is a
# *sequential re-run of the whole chain*, and what is absent is the
# intermediate result -- not one model's output.

def _multi_level_bundle():
    """C reads B's output; B reads A's output. Re-running B alone is not enough."""
    models = [
        {"prj_file": "Alpha.prj", "project_folder": "/work/RAS Model/RAS_Submittal/Alpha/Input"},
        {"prj_file": "Bravo.prj", "project_folder": "/work/RAS Model/RAS_Submittal/Bravo/Input"},
        {"prj_file": "Charlie.prj", "project_folder": "/work/RAS Model/RAS_Submittal/Charlie/Input"},
    ]
    bundle = _two_d_unsteady(
        supporting_elements={"dss": {"state": "no", "location": None, "referenced": True, "note": ""}},
        dss_verification={
            "bridge_available": True, "boundaries_checked": 2, "boundaries_resolved": 0,
            "boundaries_acquisition": 2, "boundaries_inferred": 0,
            "acquisition_targets": [
                {"dss_file": r"..\..\Bravo\Simulations\Bravo.dss",
                 "pathnames": ["/REFERENCE LINES/Bravo: Bravo/FLOW/01Jan2020/1Hour/01PCT/"]},
                {"dss_file": r"..\..\Alpha\Simulations\Alpha.dss",
                 "pathnames": ["/REFERENCE LINES/Alpha: Alpha/FLOW/01Jan2020/1Hour/01PCT/"]},
            ],
        },
    )
    bundle.models = models

    def recipe(target, consumer, element):
        return {"file": f"RAS Model/RAS_Submittal/{consumer}/Input/{consumer}.{element}",
                "surface": "dss_pathname", "locator": f"{consumer}.{element}:9:DSS File",
                "from": target, "to": None, "kind": "acquisition", "confidence": "acquisition",
                "acquisition_target": target,
                "project": f"RAS Model/RAS_Submittal/{consumer}/Input",
                "review": {"verdict": "real", "method": "archive_member_match"}}

    bundle.recipes = [recipe(r"..\..\Bravo\Simulations\Bravo.dss", "Charlie", "u01"),
                      recipe(r"..\..\Alpha\Simulations\Alpha.dss", "Bravo", "u01")]
    return bundle


def test_a_chain_is_ordered_dependencies_first():
    bundle = _multi_level_bundle()
    assert chained_dss_targets(bundle) == {"Bravo.dss": "Bravo", "Alpha.dss": "Alpha"}
    chains = chained_dss_chains(bundle)
    # Producing B.dss means running A and then B, in that order.
    assert chains["Bravo.dss"] == ["Alpha", "Bravo"]
    assert chains["Alpha.dss"] == ["Alpha"]
    assert chained_dss_sequence(bundle) == ["Alpha", "Bravo"]


def test_a_multi_level_step_names_the_whole_sequence_in_order():
    bundle = _multi_level_bundle()
    actions = [a for a in actions_from_bundle(bundle) if a.kind == "chained_model_rerun"]
    deep = next(a for a in actions if a.target == "DSS boundary data (Bravo.dss)")
    assert deep.source == "Alpha -> Bravo"
    markdown = render_audit_markdown(bundle)
    assert "Re-run the chained sub-models in sequence (`Alpha` -> `Bravo`) to produce " \
           "`DSS boundary data (Bravo.dss)`" in markdown
    # A single-model chain keeps the singular form.
    assert "Re-run the chained sub-model `Alpha` to produce `DSS boundary data (Alpha.dss)`" in markdown


def test_a_cycle_names_the_models_without_claiming_an_order():
    """No study in this corpus has one; an invented order would be a lie."""
    bundle = _multi_level_bundle()
    bundle.audit["dss_verification"]["acquisition_targets"].append(
        {"dss_file": r"..\..\Charlie\Simulations\Charlie.dss",
         "pathnames": ["/REFERENCE LINES/Charlie: Charlie/FLOW/01Jan2020/1Hour/01PCT/"]})
    bundle.recipes.append({
        "file": "RAS Model/RAS_Submittal/Alpha/Input/A.u01", "surface": "dss_pathname",
        "locator": "Alpha.u01:9:DSS File", "from": r"..\..\Charlie\Simulations\Charlie.dss", "to": None,
        "kind": "acquisition", "confidence": "acquisition",
        "acquisition_target": r"..\..\Charlie\Simulations\Charlie.dss",
        "project": "RAS Model/RAS_Submittal/Alpha/Input",
        "review": {"verdict": "real", "method": "archive_member_match"},
    })
    assert chained_dss_sequence(bundle) == ["Alpha", "Bravo", "Charlie"]
    for chain in chained_dss_chains(bundle).values():
        assert chain == sorted(chain), "a cycle falls back to a named set, not an order"


def test_the_dss_row_carries_the_wording_the_campaign_agreed():
    bundle = _multi_level_bundle()
    markdown = render_audit_markdown(bundle)
    row = next(l for l in markdown.splitlines() if l.startswith("| DSS boundary data |"))
    assert "**Requires sequential re-run of all chained sub-models** " \
           "(intermediate DSS results not delivered)" in row
    # The location column carries the sequence, not the review's wrong rewrite target.
    assert "Alpha -> Bravo" in row
    assert "Re-run in sequence: Alpha -> Bravo." in row
    assert CHAINED_DSS_NOTE == ("Requires sequential re-run of all chained sub-models "
                                "(intermediate DSS results not delivered)")


def test_section_6_states_the_requirement_and_never_asks_for_a_file():
    bundle = _multi_level_bundle()
    obtain = render_audit_markdown(bundle).split("## 6. What you must obtain")[1].split("## 7.")[0]
    assert CHAINED_DSS_NOTE in obtain
    assert "`Alpha` -> `Bravo`" in obtain
    assert "Obtain `DSS boundary data" not in obtain


def test_the_verdict_names_the_sequential_re_run():
    bundle = _multi_level_bundle()
    markdown = render_audit_markdown(bundle)
    assert ("| Runnable as delivered | **after repair (from the delivery alone, "
            "including a sequential re-run of chained sub-models)** |") in markdown
    assert "upstream model run" not in markdown


def test_one_name_is_one_finding_when_two_references_disagree():
    """Fort Supply (11100201). Two different files share the basename
    ``TownOfRosston.dss``: the neighbour's SA-connection output, which a
    delivered model produces, and Rosston's own staged input, which needs a
    PRECIP-EXCESS record no HEC-RAS run writes. Actions are deduplicated on the
    basename, so one name is one finding -- and a name that still owes a
    meteorological record is not producible. Classifying per recipe emitted
    both, telling the engineer to re-run a model AND obtain the same file."""
    models = [
        {"prj_file": "TownOfRosston.prj",
         "project_folder": "/work/RAS Model/Hydraulic Models/Town of Rosston - Beaver River/Input"},
        {"prj_file": "Fort_Supply_Beaver.prj",
         "project_folder": "/work/RAS Model/Hydraulic Models/Town of Fort Supply - Beaver River/Input"},
    ]
    chained_target = r"..\..\..\TownOfRoston_NewBorder\RAS\Input\TownOfRosston.dss"
    own_target = r".\DSS Inputs\TownOfRosston.dss"
    bundle = _two_d_unsteady(
        supporting_elements={"dss": {"state": "no", "location": None, "referenced": True, "note": ""}},
        dss_verification={
            "bridge_available": True, "boundaries_checked": 2, "boundaries_resolved": 0,
            "boundaries_acquisition": 2, "boundaries_inferred": 0,
            "acquisition_targets": [
                {"dss_file": chained_target,
                 "pathnames": ["/SA CONNECTION/Dam_Discharge/FLOW-TOTAL/01Dec2019/1Hour/01PAC/"]},
                {"dss_file": own_target,
                 "pathnames": ["//FORT_SUPPLY_BEAVER/PRECIP-EXCESS/01JAN2020/6MIN/RUN:100YR/"]},
            ],
        },
    )
    bundle.models = models

    def recipe(target, consumer, element):
        return {"file": f"RAS Model/Hydraulic Models/{consumer}/Input/{element}",
                "surface": "dss_pathname", "locator": f"{element}:9:DSS File",
                "from": target, "to": None, "kind": "acquisition", "confidence": "acquisition",
                "acquisition_target": target,
                "project": f"RAS Model/Hydraulic Models/{consumer}/Input",
                "review": {"verdict": "real", "method": "archive_member_match"}}

    bundle.recipes = [
        recipe(chained_target, "Town of Fort Supply - Beaver River", "Fort_Supply_Beaver.u06"),
        recipe(own_target, "Town of Rosston - Beaver River", "TownOfRosston.u01"),
    ]
    actions = actions_from_bundle(bundle)
    named = [a for a in actions if "TownOfRosston.dss" in a.target]
    assert len(named) == 1, "one name, one finding"
    assert named[0].kind == "acquisition"
    assert named[0].blocking
    assert chained_dss_targets(bundle) == {}
    markdown = render_audit_markdown(bundle)
    assert "needs data not in the delivery" in markdown
    assert "Re-run the chained sub-model" not in markdown


def test_classification_does_not_depend_on_recipe_order():
    """The same evidence must decide the same way whichever row comes first."""
    models = [
        {"prj_file": "TownOfRosston.prj",
         "project_folder": "/work/RAS Model/Hydraulic Models/Town of Rosston - Beaver River/Input"},
        {"prj_file": "Fort_Supply_Beaver.prj",
         "project_folder": "/work/RAS Model/Hydraulic Models/Town of Fort Supply - Beaver River/Input"},
    ]
    chained_target = r"..\..\..\TownOfRoston_NewBorder\RAS\Input\TownOfRosston.dss"
    own_target = r".\DSS Inputs\TownOfRosston.dss"
    base = _two_d_unsteady(
        supporting_elements={"dss": {"state": "no", "location": None, "referenced": True, "note": ""}},
        dss_verification={
            "bridge_available": True, "boundaries_checked": 2, "boundaries_resolved": 0,
            "boundaries_acquisition": 2, "boundaries_inferred": 0,
            "acquisition_targets": [
                {"dss_file": chained_target,
                 "pathnames": ["/SA CONNECTION/Dam_Discharge/FLOW-TOTAL/01Dec2019/1Hour/01PAC/"]},
                {"dss_file": own_target,
                 "pathnames": ["//FORT_SUPPLY_BEAVER/PRECIP-EXCESS/01JAN2020/6MIN/RUN:100YR/"]},
            ],
        },
    )
    base.models = models

    def recipe(target, consumer, element):
        return {"file": f"RAS Model/Hydraulic Models/{consumer}/Input/{element}",
                "surface": "dss_pathname", "locator": f"{element}:9:DSS File",
                "from": target, "to": None, "kind": "acquisition", "confidence": "acquisition",
                "acquisition_target": target,
                "project": f"RAS Model/Hydraulic Models/{consumer}/Input",
                "review": {"verdict": "real", "method": "archive_member_match"}}

    forward = [recipe(chained_target, "Town of Fort Supply - Beaver River", "Fort_Supply_Beaver.u06"),
               recipe(own_target, "Town of Rosston - Beaver River", "TownOfRosston.u01")]
    base.recipes = forward
    first = [(a.kind, a.target) for a in actions_from_bundle(base)]
    base.recipes = list(reversed(forward))
    second = [(a.kind, a.target) for a in actions_from_bundle(base)]
    assert first == second


# -- a project-level DSS reference is not a boundary condition -------------

def test_a_project_level_dss_reference_is_named_for_what_it_is():
    """12050007 read "35 of 35 boundaries verified against delivered DSS" beside
    "Obtain 04PCT.dss". Both were true, about different things: the boundary
    check reads unsteady-flow boundary conditions, and those six rows are DSS
    File entries in a .prj that it never examines. The facts were right and the
    framing made them look contradictory, so the framing is what changed."""
    from ras_commander.sources.federal.ebfe_audit import (
        dss_reference_scope, DSS_ACQUISITION_LABELS)
    boundary = {"surface": "dss_pathname", "file": "m/A.u01",
                "locator": "A.u01:150:DSS File"}
    project = {"surface": "dss_pathname", "file": "m/A.prj",
               "locator": "A.prj:39:DSS File"}
    assert dss_reference_scope(boundary) == "boundary"
    assert dss_reference_scope(project) == "project"
    assert DSS_ACQUISITION_LABELS["boundary"] == "DSS boundary data"
    assert "not a boundary condition" in DSS_ACQUISITION_LABELS["project"]


def test_the_rendered_document_separates_the_two(tmp_path):
    """The real record: the project-level references are named as such, and the
    boundary count is explicitly said not to cover them."""
    bundle = load_audit_bundle(Path(r"F:\eBFE\audit\12050007"))
    markdown = render_audit_markdown(bundle)
    assert "DSS references outside the boundary check" in markdown
    assert "are not boundary conditions and were not examined by it" in markdown
    assert "Obtain `DSS referenced by the project (not a boundary condition)" in markdown
    # the verification line still states what it did establish
    assert "35 of 35 boundaries verified against delivered DSS" in markdown


def test_a_record_without_project_level_references_gains_no_extra_row():
    """The qualifier appears only where it is true."""
    bundle = load_audit_bundle(Path(r"F:\eBFE\audit\11130102"))
    markdown = render_audit_markdown(bundle)
    assert "DSS references outside the boundary check" not in markdown
    assert "not a boundary condition" not in markdown


def test_a_plan_anchored_dss_reference_is_its_own_scope():
    """A `.pNN` plan file's DSS File entry is the plan's own DSS, not a boundary
    condition. 60 such rows across 3 records were reaching the boundary label by
    fallback; the fallback itself no longer claims boundary coverage either."""
    from ras_commander.sources.federal.ebfe_audit import (
        dss_reference_scope, DSS_ACQUISITION_LABELS,
        DSS_SCOPES_OUTSIDE_BOUNDARY_CHECK)
    plan = {"surface": "dss_pathname", "file": "m/A.p07",
            "locator": "A.p07:91:DSS File"}
    unknown = {"surface": "dss_pathname", "file": "m/A.xyz", "locator": "A.xyz:1:X"}
    assert dss_reference_scope(plan) == "plan"
    assert dss_reference_scope(unknown) == "other"
    assert "not a boundary condition" in DSS_ACQUISITION_LABELS["plan"]
    assert DSS_ACQUISITION_LABELS["other"] != "DSS boundary data"
    assert DSS_SCOPES_OUTSIDE_BOUNDARY_CHECK == ("project", "plan")
