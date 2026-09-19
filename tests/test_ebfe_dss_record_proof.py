"""A DSS reference moves only on record-level proof, and a check that did not run is a hold.

The defect this pins, in the shape it actually had (corpus evidence, 2026-09-19):

1. ``RasDss.get_catalog`` raised ``RuntimeError: Java not found`` on runners that
   had OpenJDK installed, because ``_configure_jvm`` only knew Windows paths. The
   audit worker recorded that as a *verdict*: every boundary ``inferred``, with
   ``dss_verification.inferred_reasons`` holding the reader's own error text.
   39 studies and 2,104 boundaries were finalised that way, among them 12050007,
   11090201, 11100203, 11140304 and 12080007.

2. Downstream, the deficiency review could not read a catalog either, so it fell
   through to a BASENAME match against the archive member index. For 12050007 it
   marked the finding ``analysis_gap`` with ``method: archive_member_match`` and
   rewrote the boundary onto the producer's delivered ``Input/1205000705_06.dss``.
   The renderer honours ``analysis_gap`` by dropping the row, so the finding
   disappeared from the engineer-facing document.

The premise that makes (2) wrong is measurable. Where the reader DID work, the
same-named delivered files were read and shown NOT to hold the requested record:

* 12060101 -- "B-part 'NORTH CROTON CRE: 1206010102' absent from every delivered
  candidate (2 readable of 2 ... 766 entries)"
* 11010008 -- "no A/B/C/E/F match from every delivered candidate (4 readable of 4
  ... 19,986 entries)"

So: a name is not a record, a reader failure is not a finding, and an ``inferred``
record already on disk is unverified rather than resolved.
"""

from __future__ import annotations

import pytest

from ras_commander.sources.federal.ebfe_audit import (
    AuditBundle,
    actions_from_bundle,
    dss_review_is_record_proven,
    dss_review_may_drop_finding,
    dss_verification_hold_reason,
    dss_verification_is_unverified,
    render_audit_markdown,
)

#: The reason string 12050007 carries, verbatim from ``_audit.json``.
JAVA_REASON = (
    "catalog unreadable for all 2 candidate(s): catalog read failed: RuntimeError: "
    "Java not found. Please set JAVA_HOME environment variable or install Java "
    "JDK/JRE.\nDownload from: https:/"
)


def _bundle(**overrides) -> AuditBundle:
    audit = {
        "key": "12050007",
        "name": "Lower Brazos-San Gabriel",
        "stage": "audited",
        "g6a_load": {"projects_total": 1, "projects_loaded": 1},
        "study_findings": {"interpretation": "2d unsteady",
                           "projects_with_unsteady_flow_pct": 100.0},
        "g7_rascheck": {"outcome": "RAN", "flow_type_families": {"UNSTEADY": 1}},
        "terrain": {"delivered": 1, "gapped": 0, "rebuilt": 0,
                    "projects": [{"project": "P", "terrain_hdf": ["Terrain.hdf"],
                                  "raster": ["DEM.tif"], "status": "delivered"}]},
        "provenance": {"git_commit": "abc", "worker_host": "test"},
        "g1_verify": {"all_sizes_match": True},
        "g3_extract": {"members_written": 10},
        "g7_validate": {"windows_path_closure": True, "absolute_path_closure": True,
                        "absolute_reference_count": 0},
    }
    audit.update(overrides)
    return AuditBundle(key="12050007", audit=audit)


#: The recipe 12050007 carries, with the review that dropped its finding.
def _dropped_recipe(method="archive_member_match"):
    return {
        "key": "12050007",
        "surface": "dss_pathname",
        "kind": "acquisition",
        "confidence": "acquisition",
        "file": "RAS Model/.../1205000707/Input/1205000707.prj",
        "locator": "1205000707.prj:39:DSS File",
        "from": r"..\..\1205000705_06\Simulations\1205000705_06.dss",
        "to": r".\DSS Inputs\1205000707.dss",
        "acquisition_target": r"..\..\1205000705_06\Simulations\1205000705_06.dss",
        "confidence_reason": JAVA_REASON,
        "review": {
            "verdict": "analysis_gap",
            "method": method,
            "evidence": ("original 1205000705_06.dss delivered as 12050007_Models.zip::"
                         "Engineering Models/Hydraulic Models/RAS_Submittal/"
                         "1205000705_06/Input/1205000705_06.dss; the G5 rewrite "
                         "target was wrong"),
        },
    }


# -- the gate itself --------------------------------------------------------

@pytest.mark.parametrize("method", ["archive_member_match", "exact_relative_path"])
def test_a_name_match_is_not_record_level_proof(method):
    assert dss_review_is_record_proven({"method": method}) is False


@pytest.mark.parametrize("method", ["dss_pathname_match", "dss_record_match"])
def test_a_catalog_read_is_record_level_proof(method):
    assert dss_review_is_record_proven({"method": method}) is True


def test_an_unknown_review_method_fails_closed():
    """A verdict whose provenance the renderer cannot name may not drop a finding."""
    assert dss_review_is_record_proven({"method": "something_new"}) is False
    assert dss_review_is_record_proven({}) is False


def test_a_non_dss_surface_is_still_settled_by_an_archive_member_match():
    """Land cover, soils, a projection file: there the question really IS the name."""
    recipe = {"surface": "plan_text_reference",
              "review": {"verdict": "analysis_gap", "method": "archive_member_match"}}
    assert dss_review_may_drop_finding(recipe) is True


def test_a_basename_match_may_not_drop_a_dss_finding():
    assert dss_review_may_drop_finding(_dropped_recipe()) is False


def test_a_record_level_match_still_drops_a_dss_finding():
    assert dss_review_may_drop_finding(_dropped_recipe("dss_record_match")) is True


# -- the finding stays in the document --------------------------------------

def test_the_12050007_finding_survives_a_basename_only_correction():
    """The regression itself: the row must still reach the engineer."""
    bundle = _bundle()
    bundle.recipes = [_dropped_recipe()]
    actions = actions_from_bundle(bundle)
    acquisitions = [a for a in actions if a.kind == "acquisition"]
    assert any("1205000705_06.dss" in a.target for a in acquisitions), actions
    assert "1205000705_06.dss" in render_audit_markdown(bundle)


def test_a_record_proven_correction_still_retires_the_finding():
    """The rule is a gate on evidence, not a refusal to ever honour the review."""
    bundle = _bundle()
    bundle.recipes = [_dropped_recipe("dss_record_match")]
    acquisitions = [a for a in actions_from_bundle(bundle) if a.kind == "acquisition"]
    assert not any("1205000705_06.dss" in a.target for a in acquisitions)


def test_a_dss_gap_is_not_retired_by_a_basename_match():
    bundle = _bundle()
    bundle.gaps = [{
        "gap": "MISSING_REFERENCE", "source_file": "1205000707.prj", "role": "prj:DSS File",
        "raw_value": r"..\..\1205000705_06\Simulations\1205000705_06.dss",
        "review": {"verdict": "analysis_gap", "method": "archive_member_match",
                   "evidence": "delivered as 12050007_Models.zip::.../1205000705_06.dss"},
    }]
    markdown = render_audit_markdown(bundle)
    assert "## 5. What is still missing" in markdown
    assert "1205000705_06.dss" in markdown.split("## 5. What is still missing", 1)[1]


def test_a_dss_element_is_not_upgraded_to_yes_by_a_name_match():
    bundle = _bundle(supporting_elements={
        "dss": {"state": "no", "referenced": True, "location": None,
                "review": {"verdict": "analysis_gap", "method": "archive_member_match",
                           "evidence": "dss delivered as models.zip::a/b/x.dss"}},
    })
    row = next(line for line in render_audit_markdown(bundle).splitlines()
               if line.startswith("| DSS boundary data |"))
    delivered_column = row.split("|")[3].strip()   # | label | expected | delivered | ...
    assert delivered_column == "**No**", row


# -- a stale `inferred` record is a hold, never a pass ----------------------

#: 12050007's ``dss_verification``, reduced to the fields the renderer reads.
STALE_VERIFICATION = {
    "bridge_available": True,
    "boundaries_checked": 35,
    "boundaries_resolved": 0,
    "boundaries_acquisition": 0,
    "boundaries_inferred": 35,
    "inferred_reasons": {JAVA_REASON: 35},
}


def test_an_all_inferred_record_is_recognised_as_unverified():
    assert dss_verification_is_unverified(STALE_VERIFICATION) is True


def test_a_record_with_verdicts_is_not_called_unverified():
    assert dss_verification_is_unverified(
        dict(STALE_VERIFICATION, boundaries_resolved=7, boundaries_inferred=28)) is False
    assert dss_verification_is_unverified({"boundaries_checked": 0}) is False


def test_the_hold_reason_quotes_the_readers_own_error():
    reason = dss_verification_hold_reason(STALE_VERIFICATION)
    assert "Java not found" in reason
    assert "\n" not in reason


def test_an_inferred_boundary_is_never_rendered_as_delivered():
    """The captured element said "yes"; nothing was verified. It may not read Yes."""
    bundle = _bundle(
        dss_verification=dict(STALE_VERIFICATION),
        supporting_elements={"dss": {"state": "yes", "referenced": True,
                                     "location": r".\DSS Inputs"}},
    )
    markdown = render_audit_markdown(bundle)
    row = next(line for line in markdown.splitlines()
               if line.startswith("| DSS boundary data |"))
    assert "Not verified" in row, row
    assert "35 of 35" in row and "Java not found" in row
    assert "**Did not run**" in markdown
    assert "The DSS boundary check did not run for this study." in markdown


def test_an_unverified_dss_row_does_not_invent_an_acquisition():
    """Nothing was established to be missing, so nothing is demanded of an engineer."""
    bundle = _bundle(
        dss_verification=dict(STALE_VERIFICATION),
        supporting_elements={"dss": {"state": "no", "referenced": True, "location": None}},
    )
    acquisitions = [a for a in actions_from_bundle(bundle)
                    if a.kind == "acquisition" and "DSS" in a.target]
    assert acquisitions == []


def test_a_partly_verified_record_still_names_the_unverified_remainder():
    bundle = _bundle(
        dss_verification={"boundaries_checked": 35, "boundaries_resolved": 7,
                          "boundaries_acquisition": 0, "boundaries_inferred": 28,
                          "inferred_reasons": {JAVA_REASON: 28}},
        supporting_elements={"dss": {"state": "no", "referenced": True, "location": None}},
    )
    row = next(line for line in render_audit_markdown(bundle).splitlines()
               if line.startswith("| DSS boundary data |"))
    assert "28 could not be verified" in row, row
