"""The archive member index outranks the capture's directory scan -- per project.

``_delivered_elements`` ends with a terrain project-count overlay that recomputes
which projects lack a Terrain.hdf from ``audit["terrain"]["projects"][].terrain_hdf``.
That list is the capture's scan of an EXTRACTED directory tree. The independent
review's list is the delivery's archive member index. Where they disagree about a
project, the member index wins; but the review resolves ONE reference, so it may
only speak for the project that member belongs to.

Every fixture here is a real ``_audit.json`` from ``F:\\eBFE\\audit`` trimmed to
the keys the renderer reads. Nothing is hand-authored: a made-up terrain record
omits exactly the fields that make these cases hard -- ``terrain_dirs`` recorded
on a project whose ``terrain_hdf`` is empty, and review evidence naming a
project other than the one with the gap.
"""
import copy
import sys
import types

county_module = types.ModuleType("ras_commander.sources.county")
county_module.M3Model = object
sys.modules.setdefault("ras_commander.sources.county", county_module)

from ras_commander.sources.federal.ebfe_audit import (        # noqa: E402
    AuditBundle,
    _delivered_elements,
    project_owns_member,
    render_audit_markdown,
    reviewed_terrain_member,
)


def _review(method, evidence, checked):
    return {"verdict": "analysis_gap", "method": method, "evidence": evidence,
            "corrected_to": None, "checked_utc": checked}


# F:\eBFE\audit\12050002 -- Blackwater Draw. The scan recorded no Terrain.hdf for
# BlackWaterDraw_1. The member index holds BlackWaterDraw_1/Terrain/BWD1.hdf,
# 183,969,226 bytes, root attribute File Type = "HEC Terrain", EPSG:2276, with a
# /Terrain group. The file is named BWD1.hdf; it is the DIRECTORY that is called
# Terrain. The review resolved the reference there by exact relative path.
BLACKWATER_DRAW = {
    "supporting_elements": {"terrain": {
        "state": "partial", "location": None,
        "note": "referenced 8 time(s), e.g. ..\\Terrain\\BWD1.hdf, "
                "but the layer HEC-RAS opens is incomplete",
        "referenced": True, "referenced_count": 8,
        "review": _review(
            "exact_relative_path",
            "terrain referenced and delivered as "
            "Hydraulic_Models_1.zip::BlackWaterDraw_1/Terrain/BWD1.hdf"
            " - the reference resolves there exactly against its own referencing file",
            "2026-09-09T17:43:23Z"),
    }},
    "terrain": {"delivered": 1, "gapped": 0, "rebuilt": 0, "projects": [
        {"project": "BlackWaterDraw_1/Input",
         "terrain_dirs": ["RAS Model/Hydraulic_Models_1/BlackWaterDraw_1/Terrain"],
         "terrain_hdf": [], "raster": ["BWD2_V2.BD_2.tif", "BWD2_V2.BD_1.tif"],
         "status": "SOURCE_ONLY_terrain_hdf_absent", "state": "source_only"},
        {"project": "BlackWaterDraw_2/Input",
         "terrain_dirs": ["RAS Model/Hydraulic_Models_2/BlackWaterDraw_2/Terrain"],
         "terrain_hdf": ["BlackWaterDraw2.hdf"], "raster": ["BlackWaterDraw3.BD_3.tif"],
         "status": "delivered", "state": "yes"},
    ]},
}

# F:\eBFE\audit\11090106 -- Middle Canadian-Spring. Six of seven projects have a
# Terrain.hdf. The review resolved a .tif, and resolved it under
# RAS_Submittal_1109010601, one of the six that already has terrain. The project
# actually without terrain is 1109010602, and its terrain_dirs is empty too.
MIDDLE_CANADIAN = {
    "supporting_elements": {"terrain": {
        "state": "partial", "location": None,
        "note": "referenced 6 time(s), e.g. Terrain.1109010601.tif, "
                "but the layer HEC-RAS opens is incomplete",
        "referenced": True, "referenced_count": 6,
        "review": _review(
            "archive_member_match",
            "terrain referenced and delivered as 11090106_Models.zip::"
            "11090106_Models/Hydraulic Models/RAS_Submittal_1109010601/"
            "Terrain/Terrain.1109010601.tif",
            "2026-09-09T16:56:17Z"),
    }},
    "terrain": {"delivered": 6, "gapped": 1, "rebuilt": 0, "projects": [
        {"project": "RAS_Submittal_110901060%d/Input" % n,
         "terrain_dirs": ["RAS Model/11090106_Models/Hydraulic Models/"
                          "RAS_Submittal_110901060%d/Terrain" % n],
         "terrain_hdf": ["Terrain.hdf"], "raster": ["Terrain.110901060%d.tif" % n],
         "status": "delivered", "state": "yes"}
        for n in (1, 3, 4, 5, 6, 7)
    ] + [
        {"project": "RAS_Submittal_1109010602/Input", "terrain_dirs": [],
         "terrain_hdf": [], "raster": None,
         "status": "GAP_no_terrain_delivered", "state": "no"},
    ]},
}

# F:\eBFE\audit\12110101 -- Nueces Headwaters. The review resolved an .hdf this
# time, but under RAS_Submittal_1211010101, which already has one.
# RAS_Submittal_1211010103 is the project with nothing.
NUECES_HEADWATERS = {
    "supporting_elements": {"terrain": {
        "state": "partial", "location": None,
        "note": "referenced 8 time(s), e.g. .\\Terrain\\Terrain_1211010101_HC.hdf, "
                "but the layer HEC-RAS opens is incomplete",
        "referenced": True, "referenced_count": 8,
        "review": _review(
            "archive_member_match",
            "terrain referenced and delivered as 12110101_Models.zip::"
            "12110101_Models_20260217/RAS_Submittal_1211010101/Terrain/"
            "Terrain_1211010101_HC.hdf",
            "2026-09-09T23:10:53Z"),
    }},
    "terrain": {"delivered": 2, "gapped": 2, "rebuilt": 0, "projects": [
        {"project": "RAS_Submittal_1211010101/Input",
         "terrain_dirs": ["RAS Model/12110101_Models_20260217/"
                          "RAS_Submittal_1211010101/Terrain"],
         "terrain_hdf": ["Terrain_1211010101_HC.hdf"],
         "raster": ["Terrain_1211010101_HC.Terrain_ 1211010101_submittal_clip.tif"],
         "status": "GAP_missing_terrain_tiles", "state": "partial"},
        {"project": "RAS_Submittal_1211010102/Input",
         "terrain_dirs": ["RAS Model/12110101_Models_20260217/"
                          "RAS_Submittal_1211010102/Terrain"],
         "terrain_hdf": ["Terrain.hdf"],
         "raster": ["Terrain.Terrain_ 1211010102_submittal_clip.tif"],
         "status": "delivered", "state": "yes"},
        {"project": "RAS_Submittal_1211010103/Input", "terrain_dirs": [],
         "terrain_hdf": [], "raster": None,
         "status": "GAP_no_terrain_delivered", "state": "no"},
        {"project": "RAS_Submittal_1211010104/Input",
         "terrain_dirs": ["RAS Model/12110101_Models_20260217/"
                          "RAS_Submittal_1211010104/RAS_Submittal_1211010104/Terrain"],
         "terrain_hdf": ["Terrain_1211010104_HC.hdf"],
         "raster": ["Terrain_1211010104_HC.Resampled.tif"],
         "status": "delivered", "state": "yes"},
    ]},
}

# F:\eBFE\audit\AL03140301\CONECUH_RIVER_TRIB_31_BLE -- the capture classified
# every terrain reference "ambiguous", and the review then resolved one of them,
# by exact relative path, to a water-surface RESULT raster.
CONECUH = {
    "supporting_elements": {"terrain": {
        "state": "no", "location": None,
        "note": "referenced 20 time(s), e.g. .\\100yr_2D\\WSE (Max).vrt, "
                "but the layer HEC-RAS opens is absent",
        "referenced": True, "referenced_count": 20,
        "review": _review(
            "exact_relative_path",
            "terrain referenced and delivered as "
            "CONECUH_RIVER_TRIB_31_BLE.zip::100yr_2D/WSE (Max).vrt"
            " - the reference resolves there exactly against its own referencing file",
            "2026-09-13T00:00:42Z"),
    }},
    "terrain": {"delivered": 0, "gapped": 1, "rebuilt": 0, "projects": [
        {"project": "RAS Model", "terrain_dirs": [], "terrain_hdf": [],
         "raster": None, "status": "GAP_no_terrain_delivered", "state": "no"},
    ]},
}


def _terrain(audit):
    return _delivered_elements(AuditBundle(key="test", audit=audit))["terrain"]


def test_a_terrain_the_member_index_proves_is_not_counted_absent():
    """12050002. Same project, same folder, resolved by exact relative path.

    Before this rule the overlay recomputed the absence from the scan and pushed
    the element back to ``partial``, and the study rendered
    ``no -- needs data not in the delivery`` on a layer FEMA shipped.
    """
    terrain = _terrain(BLACKWATER_DRAW)
    assert terrain["state"] == "yes", terrain
    assert "BlackWaterDraw_1/Terrain/BWD1.hdf" in terrain["note"]
    assert terrain["state_as_captured"] == "partial", "the capture stays on the record"


def test_a_review_for_one_project_is_not_evidence_about_another():
    """11090106 and 12110101. The review is study-level; the overlay is per-project.

    Neither review names the project with the gap, so neither may clear it.
    Clearing on a study-level match would report terrain for studies that do not
    have it -- and 11090106's evidence is not even an HDF.
    """
    for audit, absent, total in ((MIDDLE_CANADIAN, 1, 7), (NUECES_HEADWATERS, 1, 4)):
        terrain = _terrain(audit)
        assert terrain["state"] == "partial", terrain
        assert terrain["note"] == f"Terrain.hdf absent for {absent} of {total} projects"
        assert terrain["projects_delivered"] == total - absent
        assert terrain["projects_total"] == total


def test_a_result_raster_is_not_a_delivered_terrain():
    """The overlay exists to insist that delivered terrain means the Terrain.hdf
    HEC-RAS opens, not the rasters it could be built from.

    CONECUH_RIVER_TRIB_31_BLE is the live case: its review resolves the terrain
    reference, by exact relative path, to ``100yr_2D/WSE (Max).vrt``, a
    water-surface RESULT raster the capture itself classified ``ambiguous``.

    The second case varies ONE field of the real 12050002 record: its review
    evidence is pointed at ``BWD2_V2.BD_1.tif``, a DEM source tile that record
    already lists in ``terrain.projects[0].raster``, delivered inside the very
    folder of the very project with the gap. That is the arrangement where only
    the extension can refuse -- the project test cannot.
    """
    entry = dict(CONECUH["supporting_elements"]["terrain"])
    entry.update(state="yes", state_as_captured="no")
    assert reviewed_terrain_member(entry) == ""
    assert _terrain(CONECUH)["state"] == "no"

    dem_instead = copy.deepcopy(BLACKWATER_DRAW)
    dem_instead["supporting_elements"]["terrain"]["review"]["evidence"] = (
        "terrain referenced and delivered as Hydraulic_Models_1.zip::"
        "BlackWaterDraw_1/Terrain/BWD2_V2.BD_1.tif"
        " - the reference resolves there exactly against its own referencing file")
    terrain = _terrain(dem_instead)
    assert terrain["state"] == "partial", terrain
    assert terrain["projects_delivered"] == 1


def test_the_absent_count_and_the_delivered_count_are_separate_fields():
    """The overlay's note counts what is ABSENT; the renderer prints what SHIPPED.

    Every other element's capture note counts the other way round ("N of M
    projects yes; K no"), and a single regex over both printed the absent count
    as the delivered one. The two numbers are now named fields, so a message
    cannot be reworded onto the wrong polarity.
    """
    terrain = _terrain(MIDDLE_CANADIAN)
    assert terrain["note"] == "Terrain.hdf absent for 1 of 7 projects"
    assert (terrain["projects_delivered"], terrain["projects_total"]) == (6, 7)


def test_a_member_belongs_to_the_project_whose_folder_holds_it():
    """The segment rule, on the real paths it has to separate.

    The project's own folder is the last segment of its recorded path, or the
    one before it when the path ends in the RAS working subfolder.
    """
    assert project_owns_member(
        "BlackWaterDraw_1/Input", "BlackWaterDraw_1/Terrain/BWD1.hdf")
    assert not project_owns_member(
        "BlackWaterDraw_2/Input", "BlackWaterDraw_1/Terrain/BWD1.hdf")
    assert not project_owns_member(
        "RAS_Submittal_1109010602/Input",
        "11090106_Models/Hydraulic Models/RAS_Submittal_1109010601/Terrain/Terrain.hdf")
    assert project_owns_member(
        "RAS_Submittal_1109010601/Input",
        "11090106_Models/Hydraulic Models/RAS_Submittal_1109010601/Terrain/Terrain.hdf")
    assert not project_owns_member("", "anything/at/all.hdf")


def _critical_row(audit, projects):
    """Render the document and return its Critical row, if it has one."""
    record = copy.deepcopy(audit)
    record["critical_missing"] = [{
        "element": "terrain",
        "reason": "terrain_hdf_absent_modifications_unknown",
        "projects": list(projects),
    }]
    markdown = render_audit_markdown(AuditBundle(key="k", audit=record))
    rows = [line for line in markdown.splitlines()
            if line.startswith("| Critical data missing |")]
    return rows[0] if rows else ""


def test_the_critical_row_reads_the_member_index_too():
    """The document may not contradict itself two rows apart.

    The Critical row asks the same question the overlay asks -- does this
    project have the Terrain.hdf HEC-RAS opens? -- and it had its own copy of
    the answer, reading only the capture's directory scan. When the overlay
    learned to read the archive member index and the Critical row did not,
    12050002 and 11140301 re-rendered as ``after repair (from the delivery
    alone)`` in the verdict row and ``Critical data missing: terrain`` in the
    row below it, in the same document, for the same terrain. A second copy of
    a rule is a second answer.

    Both directions, because dropping the row unconditionally would be just as
    wrong: 11090106's review names a project that already has its terrain, so
    its gap is real and the row must survive.
    """
    assert _critical_row(BLACKWATER_DRAW, ["BlackWaterDraw_1/Input"]) == "", (
        "the review resolved an .hdf inside this project's own folder")
    off_target = _critical_row(MIDDLE_CANADIAN, ["RAS_Submittal_1109010602/Input"])
    assert "**terrain**" in off_target, (
        "11090106's review names 1109010601, not the project with the gap")


# -- every rule above is load-bearing ---------------------------------------

import subprocess                                             # noqa: E402
from pathlib import Path as _Path                             # noqa: E402

import pytest                                                 # noqa: E402

import ras_commander.sources.federal.ebfe_audit as _ebfe      # noqa: E402

SOURCE = _Path(_ebfe.__file__).resolve()
REPO = SOURCE.parents[4]

_MUTATIONS = [
    pytest.param(
        "the review may only clear the project whose folder holds the member",
        b"                      and not (reviewed_member\n"
        b"                               and project_owns_member(p.get(\"project\"), reviewed_member))]",
        b"                      and not reviewed_member]",
        "test_a_review_for_one_project_is_not_evidence_about_another",
        id="per_project",
    ),
    pytest.param(
        "only an .hdf can be the delivered terrain",
        b'    return member if member.lower().endswith(".hdf") else ""',
        b'    return member',
        "test_a_result_raster_is_not_a_delivered_terrain",
        id="hdf_only",
    ),
    pytest.param(
        "a terrain the member index proves is not counted absent",
        b'        reviewed_member = reviewed_terrain_member(out.get("terrain"))',
        b'        reviewed_member = ""',
        "test_a_terrain_the_member_index_proves_is_not_counted_absent",
        id="precedence",
    ),
    pytest.param(
        "the delivered count is the complement of the absent one",
        b'                "projects_delivered": len(projects) - len(hdf_absent),',
        b'                "projects_delivered": len(hdf_absent),',
        "test_the_absent_count_and_the_delivered_count_are_separate_fields",
        id="delivered_count",
    ),
    pytest.param(
        "a review nobody acted on is not evidence",
        b'    if entry.get("state") != "yes" or "state_as_captured" not in entry:\n        return ""',
        b'    if False:\n        return ""',
        "test_a_result_raster_is_not_a_delivered_terrain",
        id="overlay_must_have_fired",
    ),
    pytest.param(
        "the Critical row reads the member index, not only the scan",
        b"            return bool(critical_reviewed_member\n"
        b"                        and project_owns_member(project_path, critical_reviewed_member))",
        b"            return False",
        "test_the_critical_row_reads_the_member_index_too",
        id="critical_row_precedence",
    ),
    pytest.param(
        "the RAS working subfolder is not the project's own folder",
        b'    if own.lower() in ("input", "simulation", "simulations", "model") and len(segments) > 1:\n        own = segments[-2]',
        b'    if False:\n        own = segments[-2]',
        "test_a_member_belongs_to_the_project_whose_folder_holds_it",
        id="segment_rule",
    ),
]


@pytest.mark.parametrize("label,anchor,replacement,covering", _MUTATIONS)
def test_every_rule_is_load_bearing(label, anchor, replacement, covering):
    """Break one rule at the byte level; the test covering it must fail.

    The anchor is asserted to occur exactly once BEFORE anything is written, so
    a replace that silently matched nothing cannot pass for a rule that works.
    The file is restored from the bytes read, in a finally, whatever happens.
    """
    original = SOURCE.read_bytes()
    assert original.count(anchor) == 1, (
        "%s: the anchor occurred %d times in %s; a replace that matches nothing "
        "looks exactly like a rule that works" % (label, original.count(anchor), SOURCE.name))
    try:
        SOURCE.write_bytes(original.replace(anchor, replacement))
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(_Path(__file__).resolve()),
             "-k", covering, "-q", "-p", "no:cacheprovider"],
            capture_output=True, text=True, cwd=str(REPO))
    finally:
        SOURCE.write_bytes(original)
    assert SOURCE.read_bytes() == original, "%s: failed to restore %s" % (label, SOURCE.name)
    assert result.returncode != 0, (
        "%s: %s still passed with the rule broken\n%s" % (label, covering, result.stdout[-3000:]))
