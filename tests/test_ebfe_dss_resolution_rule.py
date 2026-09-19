"""Decision rule for eBFE DSS boundary resolution (worker revision 20260909i).

The rule under test is the pure function ``decide_dss_boundary`` in the eBFE audit
worker (``_worker/ebfe_worker.py``), together with the two pure helpers it relies
on. The worker is campaign infrastructure rather than library code, so it is
located rather than imported by package name; the tests skip when it is not
reachable from this machine.

Why this rule exists. Across six tranche-2 studies the DSS bridge came up and then
resolved either everything or nothing per study:

===========  ======================  ===================================
study        boundaries resolved     what was actually wrong
===========  ======================  ===================================
12080008     62 / 62                 nothing - references were intra-project
11130207     95 / 102                7 references differed from the delivered
                                     file by one capital letter
11140301      0 / 7                  HMS DSS delivered under ``HMS Model/``
                                     after assembly moved it
11120104      0 / 42                 upstream model's DSS delivered beside the
                                     referencing model, under another name
11060006      0 / 3                  delivered one model area over
12040102      0 / 14                 genuinely undelivered, and G5 had rewritten
                                     the boundaries onto a HEC-RAS output DSS
                                     holding only FLOW/STAGE
===========  ======================  ===================================

Five of the six were delivered data the reference could not reach; one was a real
acquisition gap. Before this rule every one of them recorded the same verdict,
``inferred``. The tests below pin each of those shapes.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path

import pytest

_CANDIDATE_WORKERS = [
    os.environ.get("EBFE_WORKER"),
    # The live campaign runtime first: the rules under test are corrected there,
    # and the NAS staging copies below are older revisions kept as a fallback.
    "H:/CLB-Repos/clb-ebfe-webmap/agent_tasks/ebfe_campaign/runtime/direct_v1/ebfe_worker.py",
    "/h/CLB-Repos/clb-ebfe-webmap/agent_tasks/ebfe_campaign/runtime/direct_v1/ebfe_worker.py",
    "F:/eBFE/audit/_worker_staging/ebfe_worker.py.rev-20260909i.BUILT-ON-g-REFERENCE-ONLY",
    "/nas/ebfe/audit/_worker_staging/ebfe_worker.py.rev-20260909i.BUILT-ON-g-REFERENCE-ONLY",
    "/mnt/ras2cng-work/ebfe/scripts/ebfe_worker.py",
    "F:/eBFE/audit/_worker/ebfe_worker.py",
    "/nas/ebfe/audit/_worker/ebfe_worker.py",
]


def _load_worker():
    """Load the worker script by path. It is a standalone stdlib-only script whose
    revisions are published under names like ``ebfe_worker.py.rev-20260909i``, so
    the loader is named explicitly rather than inferred from the suffix."""
    for cand in _CANDIDATE_WORKERS:
        if not cand:
            continue
        p = Path(cand)
        if not p.is_file():
            continue
        try:
            loader = importlib.machinery.SourceFileLoader(
                "ebfe_worker_under_test", str(p))
            spec = importlib.util.spec_from_loader(loader.name, loader)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            loader.exec_module(module)
        except Exception:
            continue
        if hasattr(module, "decide_dss_boundary"):
            return module
    return None


worker = _load_worker()

pytestmark = pytest.mark.skipif(
    worker is None,
    reason="eBFE audit worker with decide_dss_boundary not reachable "
           "(set EBFE_WORKER to its path)",
)


# --------------------------------------------------------------------------- data
RAS_OUTPUT_CATALOG = [
    "//SPR_MESH: BC LINE 1/FLOW/01JAN2020/30MIN/SPR_100YR/",
    "//SPR_MESH: BC LINE 2/STAGE/01JAN2020/30MIN/SPR_100YR/",
]
HMS_CATALOG = [
    "//SUL/PRECIP-EXCESS/01JAN2021/5MIN/RUN:100YR/",
    "//SUL/FLOW/01JAN2021/5MIN/RUN:100YR/",
]
HMS_PATHNAME = "//SUL/PRECIP-EXCESS/01JAN2021-09JAN2021/5MIN/RUN:100YR/"


def cand(path, origin, catalog=None, error=None, rel=None, member=None):
    return {"path": path, "origin": origin, "catalog": catalog, "error": error,
            "relative_from_project": rel, "delivered_member": member}


# --------------------------------------------------------------------------- tests
def test_referenced_file_holds_the_pathname_is_resolved_with_no_repair():
    """12080008 shape: 62/62. The reference already points at the right file."""
    out = worker.decide_dss_boundary(
        r".\DSS\INFLOWS\1208000702.dss",
        "/REFERENCE LINES/LSC: OUT/FLOW/01JAN2020/15MINUTE/01PCT/",
        [cand("/work/p/DSS/INFLOWS/1208000702.dss", "as_referenced",
              catalog=["/REFERENCE LINES/LSC: OUT/FLOW/01JAN2020/15MINUTE/01PCT/"],
              rel=r".\DSS\INFLOWS\1208000702.dss")],
        basename_delivered=True,
    )
    assert out["verdict"] == "resolved"
    assert out["resolved_via"] == "as_referenced"
    assert out["needs_path_correction"] is False
    assert out["correction_target"] is None
    assert out["blocking"] is False


def test_d_part_wildcard_still_resolves_and_is_flagged_as_inexact():
    """HEC-RAS locates a record on A/B/C/E/F; the D part is a block-start date."""
    out = worker.decide_dss_boundary(
        r".\DSS\x.dss", HMS_PATHNAME,
        [cand("/work/p/DSS/x.dss", "as_referenced", catalog=HMS_CATALOG)],
        basename_delivered=True,
    )
    assert out["verdict"] == "resolved"
    assert out["exact_match"] is False
    assert out["hecras_match"] is True
    assert "D-part differs" in out["reason"]


def test_case_folded_delivery_resolves_and_demands_a_path_correction():
    """11130207 shape: the delivery ships ``Precip_freq_...`` and the plan text
    says ``Precip_Freq_...``. On a case-sensitive filesystem that is 7 boundaries
    lost to one capital letter, and it is a repair, not a gap."""
    pathname = "//SBVR_701/PRECIP-INC/01JAN2023/5MIN/MET:FREQ_1PCT/"
    out = worker.decide_dss_boundary(
        r".\DSS\Precip_Freq_1113020701.dss", pathname,
        [cand("/work/p/DSS/Precip_freq_1113020701.dss", "case_folded",
              catalog=[pathname], rel=r".\DSS\Precip_freq_1113020701.dss")],
        basename_delivered=True,
    )
    assert out["verdict"] == "resolved"
    assert out["resolved_via"] == "case_folded"
    assert out["needs_path_correction"] is True
    assert out["correction_target"] == r".\DSS\Precip_freq_1113020701.dss"


def test_original_delivered_elsewhere_resolves_to_the_delivered_member():
    """11140301 / 11060006 shape: assembly moved the authored DSS out of reach of a
    ``..\\..\\..`` reference. The file is in the delivery; the repair is a path
    correction to where it landed, and the verdict is resolved, not inferred."""
    out = worker.decide_dss_boundary(
        r"..\..\..\HEC_HMS_v48\SulphurHeadwaters\SulphurHeadwaters\100yr.dss",
        HMS_PATHNAME,
        [cand("/work/k/HMS Model/Hydrologic Models/HMS Models/SulphurHeadwaters/100yr.dss",
              "delivered_elsewhere", catalog=HMS_CATALOG,
              rel=r"..\..\..\..\..\HMS Model\Hydrologic Models\HMS Models\SulphurHeadwaters\100yr.dss",
              member="Hydrologic_Models.zip::Hydrologic Models/HMS Models/SulphurHeadwaters/100yr.dss")],
        basename_delivered=True,
    )
    assert out["verdict"] == "resolved"
    assert out["resolved_via"] == "delivered_elsewhere"
    assert out["needs_path_correction"] is True
    assert out["correction_target"].endswith(r"SulphurHeadwaters\100yr.dss")
    assert out["delivered_member"].startswith("Hydrologic_Models.zip::")
    assert "not where the reference points" in out["reason"]


def test_pathname_is_the_discriminator_between_same_named_copies():
    """11120104 shape: ``Town_of_Easter.dss`` ships three times - two RAS copies
    that hold the reference-line flows and one 26 KB HMS project file with an empty
    catalog. Proximity alone picked the empty one; the catalog decides."""
    pathname = ("/REFERENCE LINES/Town of Easter: Outfall_to_1112010402/FLOW/"
                "01Dec1999-01Jan2000/15Minute/10PCT/")
    real = ("/REFERENCE LINES/Town of Easter: Outfall_to_1112010402/FLOW/"
            "01Dec1999/15Minute/10PCT/")
    out = worker.decide_dss_boundary(
        r"..\TownOfEaster_1112010401\Town_of_Easter.dss", pathname,
        [cand("/work/k/.../HMS Models/Town_of_Easter/Rainfall/Town_of_Easter.dss",
              "delivered_elsewhere", catalog=[]),
         cand("/work/k/.../1112010402/Input/External DSS/Town_of_Easter.dss",
              "delivered_elsewhere", catalog=[real],
              rel=r".\External DSS\Town_of_Easter.dss")],
        basename_delivered=True,
    )
    assert out["verdict"] == "resolved"
    assert out["correction_target"] == r".\External DSS\Town_of_Easter.dss"
    assert out["catalog_size"] == 1


def test_rewrite_onto_a_ras_output_dss_is_an_acquisition_not_an_inference():
    """12040102 shape: G5 repointed 14 HMS ``PRECIP-EXCESS`` boundaries at
    ``Spring.dss``, a HEC-RAS *output* file holding only FLOW/STAGE, because it was
    the only .dss in the project. The originals are not among the 83 delivered
    members. That is a blocking acquisition for the HMS DSS, not a repair."""
    out = worker.decide_dss_boundary(
        r".\DSS Inputs\Spring.dss",
        "//SPR/PRECIP-EXCESS/01JAN2020/5MIN/RUN:100YR/",
        [cand("/work/k/.../DSS Inputs/Spring.dss", "as_referenced",
              catalog=RAS_OUTPUT_CATALOG)],
        basename_delivered=True,
    )
    assert out["verdict"] == "acquisition"
    assert out["blocking"] is True
    assert out["hecras_match"] is False
    assert "PRECIP-EXCESS" in out["reason"]
    assert "HEC-RAS output" in out["reason"]
    assert out["catalog_shape"]["looks_like_ras_output"] is True


def test_no_delivered_copy_anywhere_is_a_blocking_acquisition():
    out = worker.decide_dss_boundary(
        r"..\..\..\..\HEC-HMS_v43\Spring\100YR.dss",
        "//SPR/PRECIP-EXCESS/01JAN2020/5MIN/RUN:100YR/",
        [], basename_delivered=False,
    )
    assert out["verdict"] == "acquisition"
    assert out["blocking"] is True
    assert out["acquisition_target"].endswith("100YR.dss")
    assert "not delivered anywhere" in out["reason"]


def test_undetermined_delivery_is_inferred_not_an_acquisition():
    """`basename_delivered=None` means the delivery was never searched. Absence of
    evidence is recorded as such - it must not be promoted to a gap."""
    out = worker.decide_dss_boundary(
        r".\missing.dss", "//A/B/C/D/E/F/", [], basename_delivered=None)
    assert out["verdict"] == "inferred"
    assert out["blocking"] is False


@pytest.mark.skipif(not hasattr(worker, "DssCatalogUnreadable"),
                    reason="worker predates the 2026-09-19 fail-closed rule")
def test_unreadable_catalogs_hold_the_unit_instead_of_yielding_a_verdict():
    """Corrected 2026-09-19. A bridge or heclib failure is our failure, never the
    delivery's -- and it is not a verdict either.

    It used to return ``inferred``, which finalised the study with the reader's
    error recorded as if it were a finding. 39 studies and 2,104 boundaries
    reached the corpus that way (12050007, 11090201, 11100203, 11140304,
    12080007 among them), and downstream a basename match "corrected" one of
    them onto a delivered file, whose ``analysis_gap`` the renderer honoured by
    dropping the finding. A check that did not run now stops the unit with the
    reader's real error in front of the operator who can fix it.
    """
    with pytest.raises(worker.DssCatalogUnreadable) as caught:
        worker.decide_dss_boundary(
            r".\DSS\x.dss", HMS_PATHNAME,
            [cand("/work/p/DSS/x.dss", "as_referenced", catalog=None,
                  error="catalog read failed: JavaException: UnsatisfiedLinkError")],
            basename_delivered=True,
        )
    assert "catalog unreadable" in str(caught.value)
    assert "UnsatisfiedLinkError" in str(caught.value)
    assert caught.value.detail["candidates"][0]["path"] == "/work/p/DSS/x.dss"


@pytest.mark.skipif(not hasattr(worker, "DssCatalogUnreadable"),
                    reason="worker predates the 2026-09-19 fail-closed rule")
def test_the_java_not_found_reason_is_recognised_as_a_reader_failure():
    """The exact text 39 studies carry, so a stale record can be told apart from
    a finding wherever one is read."""
    assert worker._is_reader_failure_reason(
        "catalog unreadable for all 2 candidate(s): catalog read failed: "
        "RuntimeError: Java not found. Please set JAVA_HOME environment variable")
    assert worker._is_reader_failure_reason("dss bridge unavailable: ImportError: no jnius")
    assert not worker._is_reader_failure_reason(
        "B-part 'NORTH CROTON CRE: 1206010102' absent from every delivered candidate")


@pytest.mark.skipif(not hasattr(worker, "DssCatalogUnreadable"),
                    reason="worker predates the 2026-09-19 fail-closed rule")
def test_a_readable_candidate_still_answers_even_when_another_failed():
    """The hold is raised only when NOTHING could be read. One corrupt copy beside
    a readable one must not stop a study that the readable one settles."""
    out = worker.decide_dss_boundary(
        r".\DSS\x.dss", HMS_PATHNAME,
        [cand("/work/p/DSS/x.dss", "as_referenced", catalog=None,
              error="catalog read failed: RuntimeError: truncated file"),
         cand("/work/q/DSS/x.dss", "delivered_copy", catalog=HMS_CATALOG)],
        basename_delivered=True,
    )
    assert out["verdict"] == "resolved"
    assert out["needs_path_correction"] is True


def test_boundary_without_a_pathname_is_inferred():
    out = worker.decide_dss_boundary(
        r".\DSS\x.dss", None,
        [cand("/work/p/DSS/x.dss", "as_referenced", catalog=HMS_CATALOG)],
        basename_delivered=True,
    )
    assert out["verdict"] == "inferred"
    assert out["reason"] == "boundary carries no DSS pathname"


def test_candidates_are_recorded_even_when_nothing_matched():
    out = worker.decide_dss_boundary(
        r".\DSS Inputs\Spring.dss", "//SPR/PRECIP-EXCESS/01JAN2020/5MIN/RUN:100YR/",
        [cand("/a/Spring.dss", "as_referenced", catalog=RAS_OUTPUT_CATALOG),
         cand("/b/Spring.dss", "delivered_elsewhere", catalog=[])],
        basename_delivered=True,
    )
    assert [c["origin"] for c in out["candidates_considered"]] == [
        "as_referenced", "delivered_elsewhere"]
    assert [c["catalog_size"] for c in out["candidates_considered"]] == [2, 0]


def test_first_matching_candidate_wins_in_order():
    """Candidate order is the rule's priority: as referenced, then case-folded,
    then delivered copies by proximity. The decision must not reorder them."""
    p = "//A/B/FLOW/01JAN2020/1HOUR/X/"
    out = worker.decide_dss_boundary(
        r".\x.dss", p,
        [cand("/near/x.dss", "as_referenced", catalog=[p], rel=r".\x.dss"),
         cand("/far/x.dss", "delivered_elsewhere", catalog=[p], rel=r"..\far\x.dss")],
        basename_delivered=True,
    )
    assert out["resolved_path"] == "/near/x.dss"


# --------------------------------------------------------------------------- helpers
def test_proximity_rank_prefers_the_deepest_shared_ancestor():
    proj = "/work/k/RAS Model/Sub/1112010403/Input"
    ranked = worker._dss_proximity_rank(
        ["/work/k/HMS Model/Rainfall/MiddleTuleDraw.dss",
         "/work/k/RAS Model/Sub/1112010403/Input/External DSS/MiddleTuleDraw.dss",
         "/work/k/RAS Model/Sub/1112010402/Input/MiddleTuleDraw.dss"],
        proj)
    assert ranked[0].endswith("1112010403/Input/External DSS/MiddleTuleDraw.dss")
    assert ranked[1].endswith("1112010402/Input/MiddleTuleDraw.dss")
    assert ranked[2].startswith("/work/k/HMS Model/")


def test_win_rel_emits_hecras_shaped_relative_paths():
    assert worker._win_rel("/w/p/DSS/x.dss", "/w/p") == r".\DSS\x.dss"
    assert worker._win_rel("/w/q/x.dss", "/w/p").startswith("..")


def test_dss_parts_keeps_an_empty_a_part():
    """Every HEC-HMS export in this corpus is ``//B/C/D/E/F/``. Collapsing the empty
    A part shifts every field and puts the D-part wildcard on the wrong one."""
    parts = worker._dss_parts("//SUL/PRECIP-EXCESS/01JAN2021/5MIN/RUN:100YR/")
    assert parts[0] == ""
    assert parts[1] == "SUL"
    assert parts[2] == "PRECIP-EXCESS"
    assert parts[4] == "5MIN"


def test_catalog_shape_flags_a_ras_output_file():
    assert worker._dss_catalog_shape(RAS_OUTPUT_CATALOG)["looks_like_ras_output"] is True
    assert worker._dss_catalog_shape(HMS_CATALOG)["looks_like_ras_output"] is False
    assert worker._dss_catalog_shape(HMS_CATALOG)["has_precip"] is True


# --------------------------------------------------------------- candidate search
def _build_tree(root):
    """A miniature of the shape that produced 0/7 and 0/42: the four-folder
    contract, two sibling model areas, and an HMS project one folder over."""
    proj = root / "RAS Model" / "Sub" / "1112010403" / "Input"
    (proj / "External DSS").mkdir(parents=True)
    (proj / "External DSS" / "MiddleTuleDraw.dss").write_bytes(b"x")
    sib = root / "RAS Model" / "Sub" / "1112010402" / "Input"
    sib.mkdir(parents=True)
    (sib / "MiddleTuleDraw.dss").write_bytes(b"x")
    hms = root / "HMS Model" / "Rainfall"
    hms.mkdir(parents=True)
    (hms / "MiddleTuleDraw.dss").write_bytes(b"x")
    (proj / "DSS").mkdir()
    (proj / "DSS" / "Precip_freq_701.dss").write_bytes(b"x")
    return proj


def test_dss_candidates_finds_the_sibling_and_ranks_by_proximity(tmp_path):
    worker._DSS_DISK_INDEX.clear()
    proj = _build_tree(tmp_path)
    cands, delivered = worker.dss_candidates(
        proj, r"..\MiddleTuleDraw_1112010402\MiddleTuleDraw.dss")
    assert delivered is True
    # The name-based tiers, in proximity order, then the `delivered_by_record`
    # tier appended on 2026-09-19 -- last, so this ordering is unchanged.
    named = [c for c in cands if c["origin"] != "delivered_by_record"]
    assert [c["origin"] for c in named] == ["delivered_elsewhere"] * 3
    assert named[0]["path"].replace("\\", "/").endswith(
        "1112010403/Input/External DSS/MiddleTuleDraw.dss")
    assert named[0]["relative_from_project"] == r".\External DSS\MiddleTuleDraw.dss"
    assert named[-1]["path"].replace("\\", "/").endswith(
        "HMS Model/Rainfall/MiddleTuleDraw.dss")
    assert cands[:len(named)] == named, "the record tier must come last"


def _case_sensitive_fs(tmp_path):
    probe = tmp_path / "CaseProbe.tmp"
    probe.write_bytes(b"x")
    return not (tmp_path / "caseprobe.tmp").exists()


def test_dss_candidates_case_folds_before_falling_back(tmp_path):
    """The workers run on Linux, where ``Precip_Freq_`` and ``Precip_freq_`` are two
    different files and 7 of Southern Beaver's 102 boundaries fell through the gap.
    Skipped on a case-insensitive filesystem, where the literal path already
    resolves and there is nothing to case-fold."""
    if not _case_sensitive_fs(tmp_path):
        pytest.skip("case-insensitive filesystem: the literal path already resolves")
    worker._DSS_DISK_INDEX.clear()
    proj = _build_tree(tmp_path)
    cands, delivered = worker.dss_candidates(proj, r".\DSS\Precip_Freq_701.dss")
    assert delivered is True
    assert cands[0]["origin"] == "case_folded"
    assert cands[0]["relative_from_project"] == r".\DSS\Precip_freq_701.dss"


def test_dss_candidates_reports_an_undelivered_basename(tmp_path):
    worker._DSS_DISK_INDEX.clear()
    proj = _build_tree(tmp_path)
    cands, delivered = worker.dss_candidates(
        proj, r"..\..\..\..\HEC-HMS_v43\Spring\100YR.dss")
    assert delivered is False
    # No file of that name is delivered anywhere, so every name-based tier is
    # empty; the last tier offers the other delivered files for a record-level
    # look, and none of them is a copy of the file the reference names.
    assert [c for c in cands if c["origin"] != "delivered_by_record"] == []
    assert not any(c["path"].endswith("100YR.dss") for c in cands)
    # With nothing to examine at all, the verdict is still a blocking acquisition.
    assert worker.decide_dss_boundary(
        r"..\..\..\..\HEC-HMS_v43\Spring\100YR.dss", "//A/B/PRECIP-EXCESS/D/5MIN/F/",
        [], delivered)["verdict"] == "acquisition"


def test_model_root_is_the_study_root_not_the_project(tmp_path):
    proj = _build_tree(tmp_path)
    assert worker._dss_model_root(proj) == tmp_path


# ------------------------------------------------- delivered-member evidence
# A recipe that says "point this boundary at that file" is only auditable if it
# names the delivered member the file came from. G3 persists `member_index.jsonl`;
# these tests pin the pure matcher that turns an assembled path into the review's
# "<archive>::<member>" reference. Skipped on a worker that predates it.
_HAS_EVIDENCE = worker is not None and hasattr(worker, "dss_delivered_member_match")
evidence = pytest.mark.skipif(
    not _HAS_EVIDENCE,
    reason="worker predates the delivered-member evidence revision (20260909l)")

IDX = [
    {"archive": "12060204_Models.zip", "container": None, "depth": 0,
     "member": "Engineering Models/Hydraulic_Models/RAS_Submittal/NorthBosque_1/"
               "Input/Input_DSS/100yr.dss",
     "expanded_path": "Engineering Models/Hydraulic_Models/RAS_Submittal/"
                      "NorthBosque_1/Input/Input_DSS/100yr.dss"},
    {"archive": "12060204_Models.zip", "container": None, "depth": 0,
     "member": "Engineering Models/Hydraulic_Models/RAS_Submittal/NorthBosque_2/"
               "Input/Input_DSS/100yr.dss",
     "expanded_path": "Engineering Models/Hydraulic_Models/RAS_Submittal/"
                      "NorthBosque_2/Input/Input_DSS/100yr.dss"},
    {"archive": "Hydrologic_Models.zip", "container": None, "depth": 0,
     "member": "Hydrologic Models/HMS Models/SulphurHeadwaters/100yr.dss",
     "expanded_path": "Hydrologic Models/HMS Models/SulphurHeadwaters/100yr.dss"},
]


@evidence
def test_delivered_member_matches_through_the_four_folder_move():
    """G4 moves a top-level subtree under `HMS Model/`, so the assembled path and
    the member's `expanded_path` share only a trailing run of segments."""
    ref, refs = worker.dss_delivered_member_match(
        "/work/11140301/HMS Model/Hydrologic_Models/Hydrologic Models/HMS Models/"
        "SulphurHeadwaters/100yr.dss", IDX)
    assert ref == ("Hydrologic_Models.zip::Hydrologic Models/HMS Models/"
                   "SulphurHeadwaters/100yr.dss")
    assert refs == [ref]


@evidence
def test_delivered_member_picks_the_right_sibling_model_area():
    """Two model areas ship the same DSS basename; the trailing run separates them."""
    ref, _ = worker.dss_delivered_member_match(
        "/work/12060204/RAS Model/Engineering Models/Hydraulic_Models/RAS_Submittal/"
        "NorthBosque_2/Input/Input_DSS/100yr.dss", IDX)
    assert ref.endswith("NorthBosque_2/Input/Input_DSS/100yr.dss")


@evidence
def test_delivered_member_reports_a_tie_instead_of_guessing():
    """Equal trailing runs come back as a set. Baffin Bay's two `TerrainUpdate.hdf`
    are why this must never pick a winner on a hunch."""
    ref, refs = worker.dss_delivered_member_match(
        "/somewhere/else/Input_DSS/100yr.dss", IDX)
    assert ref is None
    assert len(refs) == 2
    assert all(r.endswith("Input/Input_DSS/100yr.dss") for r in refs)


@evidence
def test_delivered_member_is_none_when_the_basename_is_not_delivered():
    assert worker.dss_delivered_member_match("/work/k/x/nope.dss", IDX) == (None, [])


@evidence
def test_delivered_member_is_none_without_an_index():
    """A record from a worker older than the member-index revision has no index;
    the answer is 'unknown', never a fabricated reference."""
    assert worker.dss_delivered_member_match("/work/k/x/100yr.dss", []) == (None, [])
    assert worker.dss_delivered_member_match(None, IDX) == (None, [])


@evidence
def test_member_ref_uses_the_reviews_own_shape():
    assert worker.dss_member_ref(IDX[0]) == (
        "12060204_Models.zip::Engineering Models/Hydraulic_Models/RAS_Submittal/"
        "NorthBosque_1/Input/Input_DSS/100yr.dss")


# -- the final candidate tier: a record can live under another name ---------
#
# Every tier before this one searches by NAME, which assumes the reference names
# the file the record is in. 11090201 shows it need not: all 14 of its
# boundaries ask for "/BCLINE/TOC_Flow_Area: TOC_BC_OUT/STAGE/..." through a
# reference to "Town_of_Taloga_Cana.dss" (700 entries, B-part absent), while the
# delivered "townofcamargo.dss" (756 entries) holds it. Without the tier those
# boundaries read "acquisition" -- the claim that FEMA did not ship the data,
# made about data FEMA did ship.

TOC_PATHNAME = "/BCLINE/TOC_Flow_Area: TOC_BC_OUT/STAGE/01Dec2019-01Jan2020/1Hour/1PAC/"
TOC_CATALOG = ["/BCLINE/TOC_Flow_Area: TOC_BC_OUT/STAGE/01Dec2019/1Hour/1PAC/",
               "/BCLINE/TOC_Flow_Area: TOC_BC_OUT/STAGE/01Jan2020/1Hour/1PAC/"]
OTHER_CATALOG = ["/BCLINE/TAL_Flow_Area: TAL_BC_OUT/STAGE/01Dec2019/1Hour/1PAC/"]


@pytest.mark.skipif(not hasattr(worker, "DSS_CANDIDATE_LIMIT"),
                    reason="worker predates the delivered_by_record tier")
def test_a_record_delivered_under_another_name_resolves_with_a_correction():
    out = worker.decide_dss_boundary(
        r".\DSS Inputs\Town_of_Taloga_Cana.dss", TOC_PATHNAME,
        [cand("/work/p/Taloga/Input/DSS Inputs/Town_of_Taloga_Cana.dss",
              "as_referenced", catalog=OTHER_CATALOG),
         cand("/work/p/Camargo/Input/townofcamargo.dss",
              "delivered_by_record", catalog=TOC_CATALOG)],
        basename_delivered=True,
    )
    assert out["verdict"] == "resolved"
    assert out["needs_path_correction"] is True
    assert out["resolved_via"] == "delivered_by_record"
    assert out["resolved_path"].endswith("townofcamargo.dss")


@pytest.mark.skipif(not hasattr(worker, "DSS_CANDIDATE_LIMIT"),
                    reason="worker predates the delivered_by_record tier")
def test_the_tier_cannot_displace_a_better_named_candidate():
    """It is last, so a file that really does hold the record under its own name
    still wins and no correction is proposed."""
    out = worker.decide_dss_boundary(
        r".\DSS Inputs\Town_of_Taloga_Cana.dss", TOC_PATHNAME,
        [cand("/work/p/Taloga/Input/DSS Inputs/Town_of_Taloga_Cana.dss",
              "as_referenced", catalog=TOC_CATALOG),
         cand("/work/p/Camargo/Input/townofcamargo.dss",
              "delivered_by_record", catalog=TOC_CATALOG)],
        basename_delivered=True,
    )
    assert out["verdict"] == "resolved" and out["needs_path_correction"] is False


@pytest.mark.skipif(not hasattr(worker, "DSS_CANDIDATE_LIMIT"),
                    reason="worker predates the delivered_by_record tier")
def test_the_tier_still_needs_a_real_record_match():
    """A delivered file that does not hold the pathname stays an acquisition;
    the tier widens the search, it does not soften the rule."""
    out = worker.decide_dss_boundary(
        r".\DSS Inputs\Town_of_Taloga_Cana.dss", TOC_PATHNAME,
        [cand("/work/p/Taloga/Input/DSS Inputs/Town_of_Taloga_Cana.dss",
              "as_referenced", catalog=OTHER_CATALOG),
         cand("/work/p/Other/other.dss", "delivered_by_record", catalog=OTHER_CATALOG)],
        basename_delivered=True,
    )
    assert out["verdict"] == "acquisition" and out["blocking"] is True


@pytest.mark.skipif(not hasattr(worker, "DSS_CANDIDATE_LIMIT"),
                    reason="worker predates the delivered_by_record tier")
def test_dss_candidates_offers_other_delivered_files_last(tmp_path):
    """The producer's own ordering, on a real tree."""
    project = tmp_path / "RAS Model" / "Taloga" / "Input"
    (project / "DSS Inputs").mkdir(parents=True)
    (project / "DSS Inputs" / "Town_of_Taloga_Cana.dss").write_bytes(b"x")
    other = tmp_path / "RAS Model" / "Camargo" / "Input"
    other.mkdir(parents=True)
    (other / "townofcamargo.dss").write_bytes(b"x")
    worker._DSS_DISK_INDEX.clear()
    candidates, delivered = worker.dss_candidates(
        project, r".\DSS Inputs\Town_of_Taloga_Cana.dss")
    origins = [c["origin"] for c in candidates]
    assert origins[0] == "as_referenced"
    assert origins[-1] == "delivered_by_record"
    assert candidates[-1]["path"].endswith("townofcamargo.dss")
    assert delivered is True


@pytest.mark.skipif(not hasattr(worker, "DSS_CANDIDATE_LIMIT"),
                    reason="worker predates the delivered_by_record tier")
def test_an_unfinished_search_holds_rather_than_claiming_absence():
    """"absent from EVERY delivered candidate" is only honest if every candidate
    was read. The largest affected study delivers 112 .dss files (12080002)."""
    too_many = [{"path": "/work/p/%d.dss" % i, "origin": "delivered_by_record"}
                for i in range(worker.DSS_CANDIDATE_LIMIT + 1)]
    with pytest.raises(worker.DssCatalogUnreadable) as caught:
        worker._dss_fill_catalogs(too_many, True)
    assert "did not finish" in str(caught.value)
