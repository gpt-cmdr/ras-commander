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
    classify_reference,
    escape_depth,
    expected_elements,
    load_audit_bundle,
    render_audit_markdown,
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


def test_1d_steady_expects_terrain_when_it_references_one():
    expected = expected_elements("1D", "steady", {"terrain": True, "projection": True})
    assert expected["terrain"] and expected["projection"]


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
