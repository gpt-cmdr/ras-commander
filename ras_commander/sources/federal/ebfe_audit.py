"""Render an eBFE audit as a document a HEC-RAS engineer can act on.

The audit answers one question: **what stands between "FEMA delivered a zip" and
"this model runs"?** It is a recipe a future worker executes against a fresh
extraction of the raw archive -- not a record of what one worker once did.
That contract is what lets the extracted tree be disposable while the audit
is durable.

The signature defect it exists to expose is the **relative reference that
escapes the delivered bundle**. Across all of tranche 01, zero references were
absolute; the breakage is paths like ``..\\..\\..\\..\\HEC-HMS_v43\\Spring\\100YR.dss``
that were valid on the authoring machine and walk straight out of anything
FEMA shipped. :func:`escape_depth` is the classifier that turns "33 missing
references" into a sorted list of actions with known resolutions.

Specification: ``agent_tasks/2026-09-08_ebfe_audit_document_spec.md``.

The renderer is a pure function of the audit artefacts. There is exactly one
renderer, in the library, so 300-odd documents share a skeleton that never
varies; a section with nothing to report says so rather than disappearing.

Example:
    >>> from ras_commander.sources.federal.ebfe_audit import (
    ...     load_audit_bundle, render_audit_markdown,
    ... )
    >>> bundle = load_audit_bundle("F:/eBFE/audit/12040102")
    >>> markdown = render_audit_markdown(bundle)
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Union

from ras_commander.LoggingConfig import get_logger, log_call

logger = get_logger(__name__)

__all__ = [
    "AUDIT_SCHEMA_VERSION",
    "ACTION_KINDS",
    "ACTION_ORDER",
    "SUPPORTING_ELEMENTS",
    "RAS_PRODUCED_DSS_A_PARTS",
    "RepairAction",
    "AuditBundle",
    "escape_depth",
    "classify_reference",
    "dss_pathname_parts",
    "delivered_model_names",
    "chained_dss_producer",
    "chained_dss_targets",
    "chained_dss_chains",
    "chained_dss_sequence",
    "format_chain",
    "CHAINED_DSS_NOTE",
    "DSS_NAME_ONLY_REVIEW_METHODS",
    "DSS_RECORD_PROVEN_REVIEW_METHODS",
    "dss_verification_hold_reason",
    "dss_verification_is_unverified",
    "dss_review_is_record_proven",
    "dss_review_settles_delivery",
    "dss_review_may_drop_finding",
    "expected_elements",
    "study_critical_threshold",
    "actions_from_bundle",
    "load_audit_bundle",
    "render_audit_markdown",
]

#: Schema the renderer targets. Version 1 is the tranche-01 capture; version 2
#: adds the fields listed under "Capture fields to add" in the spec. The renderer
#: reads both and reports which fields were unavailable.
AUDIT_SCHEMA_VERSION = 2

#: Action kinds, in the order they must execute. Extraction precedes movement,
#: movement precedes path correction: a path cannot be corrected to point at a
#: file that has not been unpacked and placed yet. ``chained_model_rerun`` comes
#: after reconstruction because a chained sub-model needs its own terrain before
#: it will run, and before ``acquisition`` because acquisition is the only step
#: that reaches outside the delivery at all.
ACTION_KINDS = (
    "recursive_extraction",
    "file_movement",
    "path_correction",
    "reconstruction",
    "chained_model_rerun",
    "acquisition",
)
ACTION_ORDER = {kind: index for index, kind in enumerate(ACTION_KINDS)}

#: The fixed rows of section 3. Always all of them; absence is the finding.
SUPPORTING_ELEMENTS = (
    ("terrain", "Terrain"),
    ("land_cover", "Land cover / Manning's n"),
    ("infiltration", "Infiltration"),
    ("soils", "Soils"),
    ("dss", "DSS boundary data"),
    ("projection", "Projection"),
    ("rasmap", "RASMapper configuration"),
    ("results_hdf", "Results (plan HDFs)"),
    ("geometry_hdf", "Preprocessed geometry HDF"),
)

STUDY_CRITICAL_THRESHOLD_FRACTION = 0.10
STUDY_CRITICAL_ELEMENTS = ("terrain", "land_cover")
STUDY_CRITICAL_MISSING_STATES = ("no", "source_only", "partial")
UNREFERENCED_1D_TERRAIN_NOTE = "No terrain provided or referenced by model (1D)"
REFERENCED_1D_TERRAIN_NOTE = (
    "Terrain referenced but not provided (1D; informational — does not prevent recomputation)"
)
REFERENCED_1D_LAND_COVER_NOTE = (
    "Land cover / Manning's n referenced but not provided "
    "(1D; informational — cross-section n values allow recomputation)"
)

#: DSS A-parts only a HEC-RAS *simulation* writes. HEC-HMS writes basin and
#: meteorological records (``PRECIP-INC``, ``PRECIP-EXCESS``, ``RAINFALL``,
#: usually with an empty A-part); a gauge record names a stream. None of them
#: can produce ``/REFERENCE LINES/``, ``/BCLINE/`` or ``/SA CONNECTION/`` --
#: those exist only after a plan has been computed. This is what makes the
#: chained-model case decidable without opening a single DSS file.
RAS_PRODUCED_DSS_A_PARTS = frozenset({"REFERENCE LINES", "BCLINE", "SA CONNECTION"})

#: Path segments that name the delivery's scaffolding rather than a model.
_NON_MODEL_FOLDER_NAMES = frozenset({
    "input", "inputs", "ras", "rasmodel", "model", "models", "hydraulicmodels",
    "hydrologicmodels", "engineeringmodels", "rassubmittal", "rassubmittals",
    "wspmodels", "hydraulicmodels1", "hydraulicmodels2", "work", "simulations",
    "output", "outputs", "final", "finalmodel", "hh", "backup", "dss",
})

_SURFACE_TO_KIND = {
    "asset_relocation": "file_movement",
    "hdf_asset_attribute": "path_correction",
    "rasmap_attribute": "path_correction",
    "plan_text_reference": "path_correction",
    "dss_pathname": "path_correction",
}

_ENGINEER_WORDS = {
    "dss_pathname": "DSS boundary reference",
    "hdf_asset_attribute": "asset path stored in an HDF file",
    "rasmap_attribute": "RASMapper layer path",
    "plan_text_reference": "plan or flow file reference",
    "asset_relocation": "file placed where the model expects it",
    "missing_from_delivery": "the referenced file was not where the model looked",
    "separately_delivered": "the file was shipped in a separate archive",
    "relocated_by_assembly": "the file was moved during assembly",
    "broken_relative_reference": "the reference pointed outside the delivered files",
    "nested_archive": "the file was still packed inside another archive",
    "not_delivered": "the file was not shipped at all",
    "partially_delivered": "part of the layer was not shipped",
    "intermediate_results_not_delivered": (
        "the intermediate DSS results are not in the delivery; they exist nowhere "
        "until the chained sub-models are re-run in sequence"
    ),
}

#: What a chained boundary requires, in the engineer's words. One sentence, in
#: the register of the 1D terrain and land-cover informational notes, because it
#: says the same kind of thing: what the delivery does and does not settle.
CHAINED_DSS_NOTE = (
    "Requires sequential re-run of all chained sub-models "
    "(intermediate DSS results not delivered)"
)

#: Review methods that establish a DSS reference by *name* only. A name is not
#: evidence that a file holds a record: 12060101's two delivered candidates hold
#: 766 entries and not the requested B-part, and 11010008's four hold 19,986 and
#: not the requested pathname. A rewrite justified by one of these alone is a
#: guess, so the renderer refuses to honour it.
DSS_NAME_ONLY_REVIEW_METHODS = frozenset({
    "archive_member_match",
    "exact_relative_path",
})

#: Review methods that read the target DSS catalog and proved the requested
#: pathname is in it. Only these may retire a DSS finding.
DSS_RECORD_PROVEN_REVIEW_METHODS = frozenset({
    "dss_pathname_match",
    "dss_record_match",
})


# ---------------------------------------------------------------------------
# DSS verification: what counts as proof
# ---------------------------------------------------------------------------

def dss_verification_hold_reason(verification: dict) -> str:
    """Why a DSS verification could not reach a verdict, in one clause.

    The producer records the reader's own words under
    ``dss_verification.inferred_reasons``; the corpus's dominant one is
    ``catalog read failed: RuntimeError: Java not found``. Quoting it keeps the
    real error in front of the reader rather than the word "inferred".
    """
    reasons = (verification or {}).get("inferred_reasons") or {}
    if not isinstance(reasons, dict) or not reasons:
        return "the DSS catalog could not be read"
    worst = max(reasons.items(), key=lambda item: (int(item[1] or 0), str(item[0])))[0]
    text = " ".join(str(worst).split())
    return text[:200] if text else "the DSS catalog could not be read"


def dss_verification_is_unverified(verification: dict) -> bool:
    """True when boundaries were checked and none of them reached a verdict.

    Such a record is a hold that a stale run wrote to disk instead of raising.
    It is never a pass.
    """
    verification = verification or {}
    checked = int(verification.get("boundaries_checked") or 0)
    if not checked:
        return False
    return (int(verification.get("boundaries_inferred") or 0) > 0
            and not int(verification.get("boundaries_resolved") or 0)
            and not int(verification.get("boundaries_acquisition") or 0))


def dss_review_is_record_proven(review: dict) -> bool:
    """May this deficiency-review verdict retire or rewrite a DSS reference?

    Only when something read the target DSS catalog and found the requested
    pathname in it. A basename or archive-member match proves a file of that
    NAME was delivered, which is the question the reference was never asking.

    12050007 is the worked example. The producer could not read any catalog
    (Java absent), so the review fell through to ``match_reference`` on the
    basename, found ``.../1205000705_06/Input/1205000705_06.dss``, called the
    finding an ``analysis_gap`` and rewrote the boundary onto it. The renderer
    honoured the verdict, dropped the row, and the finding vanished -- with no
    evidence that the file holds the record at all.
    """
    review = review or {}
    method = str(review.get("method") or "")
    if method in DSS_RECORD_PROVEN_REVIEW_METHODS:
        return True
    if method in DSS_NAME_ONLY_REVIEW_METHODS:
        return False
    # Unknown methods fail closed: a verdict whose provenance the renderer
    # cannot name is not allowed to drop an engineer-facing finding.
    return bool(review.get("record_proven"))


#: Review methods that settle the ELEMENT question -- "was a DSS file delivered
#: at the path this model references?" -- without settling the record question.
#:
#: Only ``exact_relative_path``, and the distinction is the whole point.
#: ``resolve_exact`` builds the full expected member path from the referencing
#: file's OWN delivered location plus the raw reference, normalises it, and
#: requires whole-path equality (case-folded) against a UNIQUE delivered member.
#: The basename lookup in front of it is a prefilter, not the test. So it proves
#: exactly what the element row claims: a file is delivered where this model
#: looks for it.
#:
#: ``archive_member_match`` is NOT here and never will be: it is "unique
#: basename, or a >=2-segment suffix unique among several" -- the guessing that
#: retired 12050007's boundaries onto a file nothing had read. It remains
#: refused for every purpose.
DSS_DELIVERY_SETTLING_REVIEW_METHODS = frozenset({"exact_relative_path"})


def dss_review_settles_delivery(review: dict) -> bool:
    """May this review settle whether the DSS element was DELIVERED?

    Narrower than it looks, and deliberately separate from
    ``dss_review_is_record_proven``: this answers only "is a file delivered at
    the referenced path", never "does that file hold the requested pathname".
    It may set the element state and nothing else -- it must never retire a
    boundary, rewrite a reference, drop a finding or touch ``dss_verification``,
    all of which continue to go through ``dss_review_is_record_proven``.

    The two questions were conflated until 2026-09-19, which left 14 studies
    hatched as though FEMA had not shipped DSS that is demonstrably delivered at
    the exact referenced path. The codebase already drew this line for non-DSS
    surfaces in ``dss_review_may_drop_finding``: "there the question really is
    'was a file of that name delivered'".
    """
    review = review or {}
    if dss_review_is_record_proven(review):
        return True
    return str(review.get("method") or "") in DSS_DELIVERY_SETTLING_REVIEW_METHODS


def _dss_correction_is_record_proven(recipe: dict) -> bool:
    """May this DSS ``path_correction`` be described to an engineer as resolved?

    Only when whatever produced it read the target catalog. The worker's own
    corrections carry ``verified_by == "dss_pathname"`` and ``confidence ==
    "resolved"`` because ``decide_dss_boundary`` matched the pathname. A
    deficiency-review correction built from an archive-member match carries
    ``confidence: "inferred"`` and no ``verified_by``; it is a lead, not a
    destination.
    """
    recipe = recipe or {}
    if recipe.get("verified_by") == "dss_pathname":
        return True
    if recipe.get("record_proven"):
        return True
    return (recipe.get("confidence") == "resolved"
            and dss_review_is_record_proven(recipe.get("review") or {"method": "dss_record_match"}))


def dss_review_may_drop_finding(recipe: dict) -> bool:
    """True when a recipe's ``analysis_gap`` may remove its repair action.

    Applies the record-level gate to DSS surfaces only; other surfaces (a land
    cover raster, a projection file) ARE settled by an archive-member match,
    because there the question really is "was a file of that name delivered".
    """
    recipe = recipe or {}
    review = recipe.get("review") or {}
    if review.get("verdict") != "analysis_gap":
        return False
    if str(recipe.get("surface") or "") != "dss_pathname":
        return True
    return dss_review_is_record_proven(review)


# ---------------------------------------------------------------------------
# Reference classification
# ---------------------------------------------------------------------------

def escape_depth(reference: str) -> int:
    """How many directory levels above the model root a relative reference reaches.

    ``0`` means the reference resolves inside the model folder. Anything higher
    walks out of the delivered bundle -- the signature defect of this corpus.

    Absolute references return ``-1`` so they sort distinctly; they do not
    occur in tranche 01 but the classifier must not mistake one for in-bundle.

    >>> escape_depth(r".\\DSS Inputs\\Spring.dss")
    0
    >>> escape_depth(r"..\\..\\..\\..\\HEC-HMS_v43\\Spring\\100YR.dss")
    4
    >>> escape_depth(r"C:\\Projects\\Spring\\100YR.dss")
    -1
    """
    if not reference:
        return 0
    text = str(reference).strip().strip("\"'")
    normalized = text.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", normalized) or normalized.startswith("//") or normalized.startswith("/"):
        return -1
    depth = 0
    for segment in normalized.split("/"):
        if segment == "..":
            depth += 1
        elif segment in ("", "."):
            continue
        else:
            break  # first real path segment ends the climb
    return depth


def classify_reference(
    raw_value: str,
    target_present_in_delivery: Optional[bool],
    target_in_nested_archive: bool = False,
    reconstruction_source_present: bool = False,
) -> tuple[str, str]:
    """Map one reference to an action kind and a reason.

    Returns ``(kind, reason)`` where ``kind`` is one of :data:`ACTION_KINDS` or
    ``"none"`` when nothing is required.
    """
    depth = escape_depth(raw_value)
    if depth == 0 and target_present_in_delivery:
        return "none", ""
    if target_in_nested_archive:
        return "recursive_extraction", "nested_archive"
    if target_present_in_delivery:
        return "path_correction", "broken_relative_reference" if depth != 0 else "separately_delivered"
    if reconstruction_source_present:
        return "reconstruction", "not_delivered"
    return "acquisition", "not_delivered"


# ---------------------------------------------------------------------------
# Chained models: one model's output DSS is the next model's boundary
# ---------------------------------------------------------------------------
#
# The corpus carries 118 unresolved boundary pathnames whose A-part is one HEC-RAS
# writes -- REFERENCE LINES, BCLINE, SA CONNECTION -- across fourteen studies. They
# are not missing data. They are the *computed output* of another model, and in
# most of those studies that model is in the same archive.
#
# Two ways the old classification got this wrong, and both were wrong in the
# engineer's face:
#
#   * The deficiency review matched the basename to a delivered file, declared
#     "original HMS file is in the delivery; G5 rewrote to RAS output", and
#     rewrote the reference onto the producer's *input* DSS -- which holds no
#     REFERENCE LINES record and never will. Salt Fork Brazos (12050007) had
#     ``..\..\1205000701_02\Simulations\1205000701_02.dss`` rewritten to
#     ``..\..\1205000701_02\Input\1205000701_02.dss``, and the whole finding then
#     disappeared from the document as a gap in our own analysis.
#   * Where the record-level check did run, it reported an acquisition -- "needs
#     data not in the delivery" -- for data FEMA shipped the means to produce.
#
# Neither the A-part rule nor the producer rule needs a DSS file opened, so both
# hold for studies whose catalog could not be read at all.
#
# The rule does not weaken the existing one. A boundary whose producer is absent
# stays a blocking acquisition, and nothing is ever rewritten onto an output DSS
# to make it resolve.

def dss_pathname_parts(pathname) -> tuple:
    """Split a DSS pathname into its six parts, ``()`` when it is not one.

    >>> dss_pathname_parts("/REFERENCE LINES/1205000701_02: 1205000701/FLOW/31Dec1999/15Minute/01PCT/")[0]
    'REFERENCE LINES'
    >>> dss_pathname_parts("//SUBBASIN/PRECIP-INC/01Jan2000/15Minute/RUN:100YR/")[0]
    ''
    >>> dss_pathname_parts("not a pathname")
    ()
    """
    text = str(pathname or "")
    if not text.startswith("/"):
        return ()
    parts = [piece.strip() for piece in text.split("/")[1:7]]
    if len(parts) < 6:
        parts.extend([""] * (6 - len(parts)))
    return tuple(parts[:6])


def _model_token(text) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _expand_model_ids(token: str) -> set:
    """A combined project names several models: ``1205000701_02`` is both of them.

    The convention throughout this corpus is a ten-digit model id followed by the
    two-digit tails of its siblings -- ``1206010107_0809`` is 07, 08 and 09.

    >>> sorted(_expand_model_ids("120500070102")) == sorted(
    ...     {"120500070102", "1205000701", "1205000702"})
    True
    """
    names = {token}
    if token.isdigit() and len(token) >= 12 and (len(token) - 10) % 2 == 0:
        base = token[:10]
        names.add(base)
        for index in range(10, len(token), 2):
            names.add(base[:-2] + token[index:index + 2])
    return names


def _names_for_project(prj_file, project_folder) -> set:
    """Every name by which one delivered project can be referred to."""
    names: set = set()
    stem = _model_token(Path(str(prj_file or "")).stem)
    if stem:
        names |= _expand_model_ids(stem)
    for segment in str(project_folder or "").replace("\\", "/").split("/"):
        token = _model_token(segment)
        if not token or token in _NON_MODEL_FOLDER_NAMES:
            continue
        names |= _expand_model_ids(token)
        trimmed = re.sub(r"^rassubmittals?", "", token)
        if trimmed and trimmed != token:
            names |= _expand_model_ids(trimmed)
    return {name for name in names if len(name) >= 4}


def delivered_model_names(models: Iterable) -> dict:
    """``normalised name -> display label`` for every project in the delivery."""
    out: dict = {}
    for model in models or []:
        if not isinstance(model, dict):
            continue
        label = Path(str(model.get("prj_file") or "")).stem or str(model.get("project_name") or "")
        if not label:
            continue
        for name in _names_for_project(model.get("prj_file"), model.get("project_folder")):
            out.setdefault(name, label)
    return out


#: Where a ``dss_pathname`` recipe's DSS reference was authored. The DSS
#: boundary check reads unsteady-flow boundary conditions; a DSS File entry in a
#: ``.prj`` is a PROJECT-level reference the check never examines. Calling both
#: "DSS boundary data" made 12050007 read "35 of 35 boundaries verified against
#: delivered DSS" beside "Obtain 04PCT.dss" -- two true statements about
#: different things, presented as one list.
#:
#: Corpus-wide: 646 boundary-anchored acquisition rows and 17 project-anchored
#: ones across 40 records; 4 records carry both shapes (08040206, 11060004,
#: 11140307, 12050007) and one carries only the project shape.
DSS_BOUNDARY_ANCHOR = re.compile(r"\.u\d+", re.I)
DSS_PROJECT_ANCHOR = re.compile(r"\.prj(?![A-Za-z0-9])", re.I)
#: A HEC-RAS PLAN file. Its DSS File entry is the plan's own DSS -- output
#: and observed-data references -- not a boundary condition, which lives in
#: the unsteady flow file. 60 such rows exist across 3 records (08040301,
#: and two others); all are path corrections today, so none has yet become
#: an "Obtain" line, but they were reaching the boundary label by fallback.
DSS_PLAN_ANCHOR = re.compile(r"\.p\d+", re.I)


def dss_reference_scope(recipe: dict) -> str:
    """"boundary", "project" or "other" -- what this DSS reference is.

    Decided from the file the reference was authored in, which is the only thing
    that says whether the boundary check covers it.
    """
    recipe = recipe or {}
    if str(recipe.get("surface") or "") != "dss_pathname":
        return "other"
    where = "%s|%s" % (recipe.get("file") or "", recipe.get("locator") or "")
    if DSS_BOUNDARY_ANCHOR.search(where):
        return "boundary"
    if DSS_PROJECT_ANCHOR.search(where):
        return "project"
    if DSS_PLAN_ANCHOR.search(where):
        return "plan"
    # Nothing names where it was authored, so nothing establishes that the
    # boundary check covers it. Falling back to "boundary" would make that claim
    # by default; there are no such rows in the corpus today and this keeps it
    # that way if one appears.
    return "other"


#: What an engineer is being asked to obtain, by scope.
DSS_ACQUISITION_LABELS = {
    "boundary": "DSS boundary data",
    "project": "DSS referenced by the project (not a boundary condition)",
    "plan": "DSS referenced by the plan (not a boundary condition)",
    "other": "DSS referenced by the model (reference location not recorded)",
}

#: Scopes the DSS boundary check does not examine.
DSS_SCOPES_OUTSIDE_BOUNDARY_CHECK = ("project", "plan")

#: Appended to the evidence so the line says what established it.
DSS_ACQUISITION_BASIS = {
    "boundary": "established by the boundary check: no delivered DSS holds the "
                "records this boundary needs",
    "project": "a project-level DSS File reference; the DSS boundary check covers "
               "boundary conditions and does not examine it",
    "plan": "a plan-level DSS File reference; the DSS boundary check covers "
            "boundary conditions and does not examine it",
    "other": "the file this reference was authored in is not recorded, so the DSS "
             "boundary check cannot be said to cover it",
}


def _unresolved_pathnames(bundle: "AuditBundle", recipe: dict) -> list:
    """The pathnames recorded against the DSS file this recipe cannot reach.

    The audit's ``dss_verification.acquisition_targets`` is per DSS file and is
    preferred; a recipe's own ``acquisition_pathnames`` can aggregate several
    files' records and is only the fallback.
    """
    target = str(recipe.get("acquisition_target") or recipe.get("from") or "")
    targets = ((bundle.audit.get("dss_verification") or {}).get("acquisition_targets") or [])
    for entry in targets:
        if str(entry.get("dss_file") or "") == target:
            return list(entry.get("pathnames") or [])
    for entry in targets:
        if str(entry.get("dss_file") or "").casefold() == target.casefold():
            return list(entry.get("pathnames") or [])
    return list(recipe.get("acquisition_pathnames") or [])


def chained_dss_producer(bundle: "AuditBundle", recipe: dict) -> Optional[str]:
    """The delivered model that computes this boundary, or ``None``.

    ``None`` means the old classification stands: a boundary whose producer is
    not in the delivery is still a blocking acquisition.
    """
    if recipe.get("surface") != "dss_pathname":
        return None
    parsed = [p for p in (dss_pathname_parts(p) for p in _unresolved_pathnames(bundle, recipe)) if p]
    if not parsed:
        return None
    # Every record this file must supply has to be one only HEC-RAS writes. A
    # file that also owes a meteorological record still owes data from outside.
    if not all(part[0].upper() in RAS_PRODUCED_DSS_A_PARTS for part in parsed):
        return None
    target = str(recipe.get("acquisition_target") or recipe.get("from") or "")
    stem = Path(target.replace("\\", "/")).stem
    # The file's own name is the strongest evidence of which model writes it;
    # the B-part is the fallback for a file named after something else. Salt
    # Fork Brazos lists one model's reference-line records against several
    # files, so taking the B-part first would misname the producer.
    primary = sorted(_expand_model_ids(_model_token(stem))) if stem else []
    secondary: set = set()
    for part in parsed:
        # B is "<flow area or reference line>: <model>" for a RAS output record.
        for half in part[1].split(":"):
            token = _model_token(half)
            if token:
                secondary |= _expand_model_ids(token)
    candidates = primary + sorted(secondary - set(primary))
    # The consuming project cannot be its own upstream model. Without this, a
    # staged input DSS named after its own project (12060101's
    # ``.\DSS Inputs\1206010103LakeDutch.dss``) would name the consumer.
    consumer = _names_for_project(None, recipe.get("project"))
    for model in bundle.models:
        folder = _model_token(model.get("project_folder"))
        against = _model_token(recipe.get("project"))
        if folder and against and (folder.endswith(against) or against.endswith(folder)):
            consumer |= _names_for_project(model.get("prj_file"), model.get("project_folder"))
    delivered = delivered_model_names(bundle.models)
    for name in candidates:
        if len(name) >= 4 and name not in consumer and name in delivered:
            return delivered[name]
    return None


def _consuming_model(bundle: "AuditBundle", recipe: dict) -> Optional[str]:
    """The delivered model whose project reads this boundary."""
    against = _model_token(recipe.get("project"))
    if not against:
        return None
    best = None
    for model in bundle.models:
        folder = _model_token(model.get("project_folder"))
        if folder and (folder.endswith(against) or against.endswith(folder)):
            label = Path(str(model.get("prj_file") or "")).stem
            if label and (best is None or len(folder) > best[0]):
                best = (len(folder), label)
    return best[1] if best else None


def _chained_dss_records(bundle: "AuditBundle") -> list:
    """One record per unresolved DSS file the delivery can produce.

    Deduplicated on the basename exactly as :func:`actions_from_bundle` dedupes
    acquisitions, and bounded by the same ``.prj`` registration scope, so the
    two always name the same set of files. Without the registration filter the
    supporting-data row could report a producer for a boundary that generates
    no step -- and, because the ``requires_chain_rerun`` state suppresses the
    element-level DSS acquisition, the study would lose that finding entirely.
    """
    by_base: dict = {}
    order: list = []
    for recipe in bundle.recipes:
        if not _recipe_targets_registered_element(bundle, recipe):
            continue
        if not (recipe.get("kind") == "acquisition" or recipe.get("confidence") == "acquisition"):
            continue
        target = str(recipe.get("acquisition_target") or recipe.get("from") or recipe.get("file") or "")
        base = Path(target.replace("\\", "/")).name or target
        if not base:
            continue
        if base not in by_base:
            order.append(base)
        by_base.setdefault(base, []).append((recipe, chained_dss_producer(bundle, recipe)))
    out: list = []
    for base in order:
        entries = by_base[base]
        # Actions are deduplicated on the basename, so one name is one finding.
        # Two references can share a name and disagree: Fort Supply (11100201)
        # reads Rosston's SA-connection output as
        # ``..\..\..\TownOfRoston_NewBorder\RAS\Input\TownOfRosston.dss`` while
        # Rosston's own ``.\DSS Inputs\TownOfRosston.dss`` needs a PRECIP-EXCESS
        # record no HEC-RAS run writes. A name is a chain re-run only when EVERY
        # reference to it is producible; otherwise something under that name
        # still has to be obtained, and the blocking acquisition stands. Testing
        # every entry also makes the classification independent of recipe order.
        if all(producer for _recipe, producer in entries):
            recipe, producer = entries[0]
            out.append({"file": base, "producer": producer,
                        "consumer": _consuming_model(bundle, recipe)})
    return out


def chained_dss_targets(bundle: "AuditBundle") -> dict:
    """``basename -> producer label`` for every unresolved DSS the delivery can produce."""
    return {record["file"]: record["producer"] for record in _chained_dss_records(bundle)}


def _chain_order(records: Iterable) -> tuple:
    """``(order_for, sequence)`` -- what must be re-run, dependencies first.

    A chained model may itself read another chained model's output: Lower
    Brazos-San Gabriel (12050007) runs 1205000701_02 and 1205000703_04 before
    1205000705_06 before 1205000707, and Current River (11010008) is four deep.
    So the requirement is a *sequential re-run of the whole chain*, not one run,
    and the order is derivable from which delivered model consumes which.

    ``order_for`` maps each file to the ordered models that produce it. A cycle
    -- which no study in this corpus has -- yields the models with no order
    claimed rather than an invented one.
    """
    needs: dict = {}
    for record in records:
        needs.setdefault(record["consumer"], set()).add(record["producer"])

    cycles = {"seen": False}

    def walk(model, stack=()):
        if model in stack:
            cycles["seen"] = True
            return []
        ordered: list = []
        for dependency in sorted(needs.get(model, ())):
            for item in walk(dependency, stack + (model,)):
                if item not in ordered:
                    ordered.append(item)
        if model not in ordered:
            ordered.append(model)
        return ordered

    order_for = {record["file"]: walk(record["producer"]) for record in records}
    sequence: list = []
    for record in sorted(records, key=lambda r: str(r["file"]).casefold()):
        for model in order_for[record["file"]]:
            if model not in sequence:
                sequence.append(model)
    if cycles["seen"]:
        order_for = {key: sorted(set(value), key=str.casefold) for key, value in order_for.items()}
        sequence = sorted(set(sequence), key=str.casefold)
    return order_for, sequence


def chained_dss_chains(bundle: "AuditBundle") -> dict:
    """``basename -> ordered models to re-run`` for each chained DSS file."""
    return _chain_order(_chained_dss_records(bundle))[0]


def chained_dss_sequence(bundle: "AuditBundle") -> list:
    """Every chained sub-model of this study, in an order that can be re-run."""
    return _chain_order(_chained_dss_records(bundle))[1]


def format_chain(models: Iterable, tick: str = "`") -> str:
    """``A -> B -> C``, the sequence as the documents and the sidebar print it."""
    return " -> ".join(f"{tick}{model}{tick}" for model in models)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RepairAction:
    """One step from delivered to runnable. See spec section 4."""

    order: int
    kind: str
    target: str
    reason: str
    evidence: str
    confidence: str = "resolved"
    blocking: bool = True
    escape_depth: int = 0
    from_value: Optional[str] = None
    to_value: Optional[str] = None
    archive: Optional[str] = None
    member: Optional[str] = None
    nesting_depth: Optional[int] = None
    source: Optional[str] = None
    project: Optional[str] = None

    def as_record(self) -> dict:
        record = asdict(self)
        record["from"] = record.pop("from_value")
        record["to"] = record.pop("to_value")
        return record


@dataclass
class AuditBundle:
    """Everything the renderer reads for one study, loaded from ``audit/<key>/``."""

    key: str
    audit: dict
    models: list = field(default_factory=list)
    recipes: list = field(default_factory=list)
    gaps: list = field(default_factory=list)
    references: list = field(default_factory=list)
    folder: Optional[Path] = None


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


@log_call
def load_audit_bundle(folder: Union[str, Path]) -> AuditBundle:
    """Load ``_audit.json`` and its sidecar row files from an audit directory."""
    folder = Path(folder)
    audit_path = folder / "_audit.json"
    if not audit_path.exists():
        raise FileNotFoundError(f"No _audit.json in {folder}")
    with open(audit_path, "r", encoding="utf-8") as handle:
        audit = json.load(handle)
    key = str(audit.get("key") or folder.name)
    if not audit.get("name"):
        # Schema v1 did not carry the study name; the roster does.
        roster = folder.parent.parent / "_index" / "studies.csv"
        if roster.exists():
            import csv
            with open(roster, "r", encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    if row.get("key") == key and row.get("name"):
                        audit["name"] = row["name"]
                        break
    return AuditBundle(
        key=key,
        audit=audit,
        models=_read_jsonl(folder / "models.jsonl"),
        recipes=_read_jsonl(folder / "repair_recipe.jsonl"),
        gaps=_read_jsonl(folder / "gaps.jsonl"),
        references=_read_jsonl(folder / "references.jsonl"),
        folder=folder,
    )


# ---------------------------------------------------------------------------
# Derivations
# ---------------------------------------------------------------------------

def _model_type(bundle: AuditBundle) -> tuple[str, str]:
    """(dimensionality, flow regime) from the audit, engineer's vocabulary.

    Schema v2 captures ``model_type`` and ``flow_regime`` from the loaded
    projects; those are authoritative and are used when present. The
    inference below is the schema v1 fallback only -- deriving from prose
    produced "unknown" for one unit and must not override a captured value.
    """
    captured_type = str(bundle.audit.get("model_type") or "").strip()
    captured_regime = str(bundle.audit.get("flow_regime") or "").strip().lower()
    if captured_type and captured_regime in ("steady", "unsteady"):
        dims = {"1d": "1D", "2d": "2D", "mixed": "mixed"}.get(captured_type.lower(), captured_type)
        return dims, captured_regime

    findings = bundle.audit.get("study_findings", {}) or {}
    families = (bundle.audit.get("g7_rascheck", {}) or {}).get("flow_type_families", {}) or {}
    unsteady_pct = findings.get("projects_with_unsteady_flow_pct")
    geom_hdf_pct = findings.get("preprocessed_geometry_hdf_present_pct")

    if "UNSTEADY" in families or (unsteady_pct or 0) > 0:
        regime = "unsteady"
    elif "STEADY" in families or unsteady_pct == 0:
        regime = "steady"
    else:
        regime = "unknown"

    interpretation = str(findings.get("interpretation", "")).lower()
    if "2d" in interpretation:
        dims = "2D"
    elif "1d" in interpretation:
        dims = "1D"
    elif geom_hdf_pct and geom_hdf_pct > 0 and regime == "unsteady":
        dims = "2D"
    else:
        dims = "1D" if regime == "steady" else "unknown"
    return dims, regime


def expected_elements(dims: str, regime: str, referenced: Optional[dict] = None) -> dict:
    """Which supporting elements this model is expected to carry.

    Derived from the model, never asserted. Two tiers:

    * **Structural** -- terrain, projection, and RASMapper configuration for 2D
      -- follow from the model type.
    * **Optional layers** -- infiltration, soils, land cover, DSS -- are
      expected **only when the model references them**. Spring Creek handles
      losses in HEC-HMS upstream and never references an infiltration layer;
      its absence is not-applicable, not a gap. Asserting it "expected" for
      every 2D unsteady model made every study read "needs external data" and
      the verdict stopped discriminating.

    ``referenced`` maps optional-layer keys to booleans. Keys absent from it
    fall back to a conservative default (infiltration and soils: not expected).

    Land cover / Manning's n (user direction, 2026-09-16): a 1D model never
    requires it, because its cross sections carry their own n values, so a
    referenced but undelivered layer is informational. A 2D model requires it
    only when the model references it. Infiltration likewise stays expected
    only when a RASMapper file references it.
    """
    # A "mixed" study has at least one 2D project, so it expects what 2D expects.
    is_2d = dims in ("2D", "mixed")
    unsteady = regime == "unsteady"
    ref = referenced or {}

    def optional(key: str, default: bool) -> bool:
        return bool(ref[key]) if key in ref else default

    # Terrain and projection are computation inputs for 2D; for 1D they are
    # mapping inputs only. A 1D steady model computes from its cross sections
    # and runs with neither -- 12090301's 2,378 projects reference no terrain
    # and no projection, and calling those "needs external data" was wrong.
    return {
        "terrain": is_2d,
        "land_cover": dims != "1D" and optional("land_cover", is_2d),
        "infiltration": optional("infiltration", False),
        "soils": optional("soils", False),
        "dss": optional("dss", unsteady),
        "projection": is_2d or optional("projection", False),
        "rasmap": is_2d,
        "results_hdf": False,          # nice to have; never required to run
        "geometry_hdf": False,         # regenerated by preprocessing
    }


_LAYER_HINTS = {
    "infiltration": ("infiltration", "infil"),
    "soils": ("soil",),
    "land_cover": ("land cover", "landcover", "land_cover", "manning"),
    "dss": (".dss",),
    "terrain": ("terrain",),
    # Not ".prj": HEC-RAS project files share that extension, so it would mark
    # every study as referencing a projection.
    "projection": ("projection",),
}


def _referenced_elements(bundle: "AuditBundle") -> dict:
    """Which optional layers the model actually references.

    Reads an explicit ``supporting_elements[key].referenced`` flag when the
    capture provides one; otherwise a delivered state counts as referenced, and
    failing that any reference or gap row naming the layer does. Keys with no
    signal are left unset so :func:`expected_elements` applies its default.
    """
    explicit = bundle.audit.get("supporting_elements", {}) or {}
    rows = list(bundle.references) + list(bundle.gaps)
    out: dict = {}
    for key, hints in _LAYER_HINTS.items():
        entry = explicit.get(key) or {}
        if "referenced" in entry:
            out[key] = bool(entry["referenced"])
            continue
        state = entry.get("state")
        if state in ("yes", "partial", "source_only", "rebuilt"):
            out[key] = True
            continue
        hit = any(
            hint in f"{r.get('raw_value', '')} {r.get('role', '')} {r.get('surface', '')}".lower()
            for r in rows for hint in hints
        )
        if hit:
            out[key] = True
        elif state is not None:
            out[key] = False    # capture looked, found nothing referencing it
    return out


def _unique_model_identity(row: dict) -> tuple:
    """Return the stable study denominator identity for one captured model row."""
    project = str(row.get("project_folder") or "").replace("\\", "/").rstrip("/").casefold()
    prj = str(row.get("prj_file") or "").casefold()
    if project or prj:
        return project, prj
    explicit = str(row.get("model_id") or row.get("canonical_id") or "").casefold()
    if explicit:
        return "id", explicit
    return (
        "fallback",
        str(row.get("group") or "").casefold(),
        str(row.get("project_name") or "").casefold(),
    )


def study_critical_threshold(bundle: AuditBundle) -> dict:
    """Measure 1D missing supporting data over total unique model rows.

    Missing terrain and missing land cover/Manning's n are informational for an
    integrated 1D study at every prevalence: cross-section computations need
    neither. (Until 2026-09-16 land cover became study-critical at 10 percent
    of unique models; the user retired that rule.) The prevalence is still
    measured and reported. Duplicate
    captures of one project/prj pair do not inflate either numerator or
    denominator. The structurally required 2D terrain rule is unchanged.
    """
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    labels: dict[tuple, str] = {}
    for row in bundle.models:
        identity = _unique_model_identity(row)
        grouped[identity].append(row)
        labels.setdefault(
            identity,
            str(row.get("project_folder") or row.get("project_name") or row.get("model_id") or identity),
        )

    denominator = len(grouped)
    dims, _ = _model_type(bundle)
    applies = bool(denominator) and dims == "1D"
    result = {
        "rule": "integrated_1d_terrain_and_land_cover_informational",
        "threshold_fraction": STUDY_CRITICAL_THRESHOLD_FRACTION,
        "threshold_percent": 10,
        "denominator_definition": "total unique model rows by normalized project_folder + prj_file",
        "missing_states": list(STUDY_CRITICAL_MISSING_STATES),
        "model_dimensions": dims,
        "applies_to_integrated_1d": applies,
        "elements": {},
    }
    for element in STUDY_CRITICAL_ELEMENTS:
        affected = []
        unreferenced_not_delivered = []
        for identity, rows in grouped.items():
            values = [((row.get("supporting_elements") or {}).get(element) or {}) for row in rows]
            referenced = any(bool(value.get("referenced")) for value in values)
            not_delivered = any(
                str(value.get("state") or "unknown") in STUDY_CRITICAL_MISSING_STATES
                for value in values
            )
            if referenced and not_delivered:
                affected.append(labels[identity])
            if not referenced and not_delivered:
                unreferenced_not_delivered.append(labels[identity])
        numerator = len(affected)
        fraction = float(numerator) / denominator if denominator else 0.0
        row = {
            "numerator": numerator,
            "denominator": denominator,
            "fraction": round(fraction, 8),
            "percent": round(100.0 * fraction, 4),
            # Neither element is ever study-critical for integrated 1D.
            "study_critical": False,
            "affected_models": affected,
            "unreferenced_not_delivered": len(unreferenced_not_delivered),
            "display": f"{numerator}/{denominator} unique model rows ({100.0 * fraction:.2f}%)",
        }
        if element == "terrain" and applies and (affected or unreferenced_not_delivered):
            row["informational"] = (
                REFERENCED_1D_TERRAIN_NOTE
                if affected
                else UNREFERENCED_1D_TERRAIN_NOTE
            )
        if element == "land_cover" and applies and affected:
            row["informational"] = REFERENCED_1D_LAND_COVER_NOTE
        result["elements"][element] = row
    return result


def _delivered_elements(bundle: AuditBundle) -> dict:
    """Best available present/absent per supporting element, with location."""
    audit = bundle.audit
    findings = audit.get("study_findings", {}) or {}
    terrain = audit.get("terrain", {}) or {}
    explicit = audit.get("supporting_elements", {}) or {}   # schema v2

    def pct_to_state(value):
        if value is None:
            return "unknown"
        return "yes" if value >= 99.999 else ("partial" if value > 0 else "no")

    out = {}
    for key, _label in SUPPORTING_ELEMENTS:
        if key in explicit:
            entry = dict(explicit[key])
            # The independent review checks every referenced-but-absent element
            # against the archive members. An ``analysis_gap`` verdict means the
            # layer *is* in the delivery -- the capture looked in the wrong place.
            # Reporting it as an acquisition would hatch the study on the map for
            # data FEMA shipped (North Bosque's Manning's n, Lower Brazos's land
            # cover). The review is the later, independent word; it wins --
            # except on ``dss``, where a delivered file of the right name is not
            # evidence that it holds the record the boundary asks for.
            review = entry.get("review") or {}
            if (review.get("verdict") == "analysis_gap"
                    and entry.get("state") in ("no", "partial", "source_only")
                    and (key != "dss" or dss_review_settles_delivery(review))):
                evidence = str(review.get("evidence") or "")
                member = evidence.split("::", 1)[1] if "::" in evidence else None
                entry["state_as_captured"] = entry.get("state")
                entry["state"] = "yes"
                entry["location"] = member or entry.get("location")
                entry["note"] = f"found by independent review: {evidence}" if evidence else "found by independent review"
                if key == "dss" and not dss_review_is_record_proven(review):
                    # Settled on DELIVERY evidence only: a member exists at the
                    # exact referenced path. That is the element question and
                    # nothing more -- no catalog was read, so no record in the
                    # file was verified. Saying "Yes" without saying that is the
                    # half-truth this rule was split to avoid.
                    entry["record_verified"] = False
                    entry["note"] += (" -- delivered at the referenced path; the boundary "
                                      "records inside it were not verified")
            out[key] = entry
            continue
        # v1 fallbacks -- aggregate only, no location
        if key == "terrain":
            d, g, r = terrain.get("delivered", 0), terrain.get("gapped", 0), terrain.get("rebuilt", 0)
            state = "yes" if d and not g else ("partial" if d else ("rebuilt" if r else "no"))
            out[key] = {"state": state, "location": None, "note": f"{d} delivered, {g} gapped, {r} rebuilt"}
        elif key == "dss":
            out[key] = {"state": pct_to_state(findings.get("projects_with_dss_boundary_pct")), "location": None, "note": None}
        elif key == "rasmap":
            out[key] = {"state": pct_to_state(findings.get("rasmapper_configuration_present_pct")), "location": None, "note": None}
        elif key == "geometry_hdf":
            out[key] = {"state": pct_to_state(findings.get("preprocessed_geometry_hdf_present_pct")), "location": None, "note": None}
        else:
            out[key] = {"state": "not captured", "location": None, "note": "schema v1 did not record this"}

    # The deficiency review can supersede a synthetic DSS location without
    # changing the producer capture.  Aransas (12100407) originally collapsed
    # every boundary onto ``.\\DSS Inputs\\Aransas.dss``; review matched twenty
    # file references to the delivered ``..\\DSS\\*.dss`` members and appended
    # one locator-aware correction per reference.  The engineer-facing
    # supporting-data row must describe those reviewed destinations, not the
    # capture's placeholder path.
    #
    # Corrected 2026-09-19: only when the correction was proven at the record.
    # A reviewer that matched a basename in the archive member index has shown a
    # file of that name shipped and nothing about its contents, and this row
    # would hand the engineer the exact path nothing read. Aransas (12100407)
    # is that case: its twenty corrections were name matches made while the DSS
    # catalog reader was failing, so the row stays with what the check said.
    reviewed_dss = [
        recipe for recipe in bundle.recipes
        if recipe.get("surface") == "dss_pathname"
        and recipe.get("origin") == "deficiency_review"
        and recipe.get("from") and recipe.get("to")
        and _dss_correction_is_record_proven(recipe)
    ]
    if reviewed_dss:
        destinations = sorted({str(recipe["to"]) for recipe in reviewed_dss}, key=str.casefold)
        entry = dict(out.get("dss") or {})
        entry["state"] = "yes"
        entry["location"] = ", ".join(destinations)
        entry["note"] = (
            f"{len(reviewed_dss)} reviewed references resolve to "
            f"{len(destinations)} delivered DSS file{'s' if len(destinations) != 1 else ''} "
            "(path corrections required)"
        )
        entry["reviewed_correction_count"] = len(reviewed_dss)
        out["dss"] = entry

    # Keep the plan-HDF count and the displayed list as one derivation.  Some
    # captures sampled the location list even though their note retained the
    # full count.  A registered plan HDF that carries an HDF-asset correction
    # is direct evidence that the file was opened, so it may safely complete
    # the list without changing the producer record.
    results = dict(out.get("results_hdf") or {})
    if results.get("state") == "yes":
        locations = {
            item.strip()
            for item in str(results.get("location") or "").split(",")
            if item.strip()
        }
        locations.update(
            Path(str(recipe.get("file") or "").replace("\\", "/")).name
            for recipe in bundle.recipes
            if recipe.get("surface") == "hdf_asset_attribute"
            and re.search(r"\.p\d{2}\.hdf$", str(recipe.get("file") or ""), re.I)
            and _recipe_targets_registered_element(bundle, recipe)
        )
        if locations:
            ordered = sorted(locations, key=str.casefold)
            results["location"] = ", ".join(ordered)
            results["note"] = f"{len(ordered)} plan HDF{'s' if len(ordered) != 1 else ''}"
            out["results_hdf"] = results

    # DSS: the boundary verification (worker rev i) is the authority on whether
    # the DSS a boundary was authored for is in the delivery. The element
    # capture still says "no" when the file is not at the literal post-assembly
    # path -- Tule (11120104) had all 42 boundaries verified against delivered
    # members and the row read "absent". Verification counts win.
    #
    # ``inferred`` is NOT a finding and NOT a pass: it is a verdict the check
    # could not reach. The worker now raises a hold rather than recording one
    # (``DssCatalogUnreadable``), but 39 studies / 2,104 boundaries already on
    # disk carry ``inferred`` because ``RasDss.get_catalog`` raised "Java not
    # found" and the old code degraded silently. Such a record must never be
    # read as a verified one, so an unverified boundary downgrades a captured
    # "yes" here and the row says how many could not be checked.
    verification = audit.get("dss_verification") or {}
    checked = int(verification.get("boundaries_checked") or 0)
    captured_dss_state = out.get("dss", {}).get("state")
    acquisition_count = int(verification.get("boundaries_acquisition") or 0)
    inferred_count = int(verification.get("boundaries_inferred") or 0)
    if checked and (captured_dss_state in ("no", "partial", None)
                    or (captured_dss_state == "yes"
                        and (acquisition_count or inferred_count))):
        resolved = int(verification.get("boundaries_resolved") or 0)
        acquisition = acquisition_count
        inferred = inferred_count
        entry = dict(out.get("dss") or {})
        entry.setdefault("state_as_captured", entry.get("state"))
        if inferred and not resolved and not acquisition:
            # Nothing was established either way. Saying "Yes" here is the
            # silent degradation this rule exists to stop.
            entry["state"] = "unverified"
            entry["note"] = (f"{inferred} of {checked} boundaries could not be verified: "
                             + dss_verification_hold_reason(verification))
        elif acquisition and not resolved:
            entry["state"] = "no"
            entry["note"] = (f"{acquisition} of {checked} boundaries need DSS that is not in the delivery"
                             + (f"; {inferred} could not be verified" if inferred else ""))
        elif resolved == checked:
            entry["state"] = "yes"
            entry["note"] = (f"{resolved} of {checked} boundaries verified against delivered DSS"
                             + (" (path corrections required)" if verification.get("resolved_needing_path_correction") else ""))
        elif resolved and acquisition:
            # Some boundaries were PROVEN to need data no delivered DSS holds.
            # That is a real partial delivery, and any unverified remainder is
            # reported beside it rather than folded into it.
            entry["state"] = "partial"
            entry["note"] = (f"{resolved} of {checked} boundaries verified; {acquisition} need DSS not in the delivery"
                             + (f"; {inferred} could not be verified" if inferred else ""))
        elif resolved and inferred:
            # Corrected 2026-09-19. This used to read "partial", which renders as
            # "incomplete in the delivery: part of the layer was not shipped" --
            # an assertion of non-delivery about boundaries the check never
            # established. 12070104/LB_MA02 is the case: 21 checked, 14 resolved,
            # 0 acquisition, 7 inferred, every one of the 7 "DSS file not found
            # on disk", which the producer emits only when the delivery was NOT
            # searched. Nothing there was shown to be missing.
            #
            # No `inferred` reason in this corpus is an acquisition. The producer
            # already routes genuine non-delivery to `acquisition` when
            # `basename_delivered is False`; the inferred reasons are "the
            # delivery was not searched", a reader failure, "boundary carries no
            # DSS pathname", or a miss against ONE target catalog -- and that
            # last one may still resolve against another delivered file, which is
            # exactly what the record tier proved for 28 of 12050007's boundaries.
            #
            # So a mixed record reports both parts and the unverified part stays
            # a check that did not run.
            entry["state"] = "unverified"
            entry["note"] = (f"{resolved} of {checked} boundaries verified; "
                             f"{inferred} could not be verified: "
                             + dss_verification_hold_reason(verification))
        if inferred:
            entry["boundaries_unverified"] = inferred
        out["dss"] = entry

    # A boundary whose DSS is the computed output of a model that IS in the
    # delivery is not missing data. What is absent is the *intermediate* result,
    # and the requirement is a sequential re-run of the whole chain -- which may
    # be several models deep -- not one run. So the row names the sequence and
    # says so, and the engineer is sent to HEC-RAS and not to FEMA. Chained
    # files the delivery cannot produce keep the row's absent state.
    records = _chained_dss_records(bundle)
    chained = {record["file"]: record["producer"] for record in records}
    if chained:
        sequence = _chain_order(records)[1]
        entry = dict(out.get("dss") or {})
        entry.setdefault("state_as_captured", entry.get("state"))
        files = sorted(chained, key=str.casefold)
        shown = ", ".join(files[:3]) + (f" and {len(files) - 3} more" if len(files) > 3 else "")
        outstanding = [
            recipe for recipe in bundle.recipes
            if _recipe_targets_registered_element(bundle, recipe)
            and (recipe.get("kind") == "acquisition" or recipe.get("confidence") == "acquisition")
            and not dss_review_may_drop_finding(recipe)
            and (Path(str(recipe.get("acquisition_target") or recipe.get("from")
                          or recipe.get("file") or "").replace("\\", "/")).name or "") not in chained
        ]
        note = ((f"Re-run in sequence: {format_chain(sequence, tick='')}. "
                 if len(sequence) > 1 else f"Re-run {format_chain(sequence, tick='')}. ")
                + f"Produces {len(files)} DSS file{'s' if len(files) != 1 else ''} the "
                  f"boundaries were authored against ({shown}).")
        if outstanding:
            entry["note"] = ((entry.get("note") or "") + ("; " if entry.get("note") else "")
                             + CHAINED_DSS_NOTE + ". " + note)
        else:
            entry["state"] = "requires_chain_rerun"
            entry["note"] = note
            # The reviewed destination is the producer's *input* DSS -- the file
            # the basename match wrongly pointed at. Naming it here would hand
            # the engineer the path that does not hold the record.
            entry["location"] = format_chain(sequence, tick='')
        entry["chained_producers"] = dict(chained)
        entry["chained_sequence"] = list(sequence)
        out["dss"] = entry

    # "Delivered" terrain must mean the Terrain.hdf HEC-RAS opens, not merely the
    # rasters it could be built from. San Gabriel (12070205) ships DEM tiles for
    # all five projects and a Terrain.hdf for none of them; that is a
    # reconstruction step, not a delivered terrain, and the verdict must say so.
    projects = terrain.get("projects") or []
    if projects and out.get("terrain", {}).get("state") in ("yes", "partial"):
        hdf_absent = [p for p in projects if isinstance(p, dict) and not p.get("terrain_hdf")]
        rasters_present = [p for p in hdf_absent if p.get("raster")]
        if hdf_absent and len(hdf_absent) == len(projects):
            out["terrain"] = {
                "state": "source_only" if rasters_present else "no",
                "location": out["terrain"].get("location"),
                "note": (f"DEM rasters delivered for {len(rasters_present)} of {len(projects)} "
                         f"projects; no Terrain.hdf for any -- build with RasProcess CreateTerrain"),
            }
        elif hdf_absent:
            out["terrain"] = {
                "state": "partial",
                "location": out["terrain"].get("location"),
                "note": f"Terrain.hdf absent for {len(hdf_absent)} of {len(projects)} projects",
            }
    return out


_RAS_ELEMENT_FILE = re.compile(
    r"^(?P<stem>.+)\.(?P<suffix>[pgfuq])(?P<number>\d{2})(?:\.hdf)?$", re.I
)
_ELEMENT_SUFFIX = {
    "plan": "p",
    "geometry": "g",
    "steady_flow": "f",
    "flow": "f",
    "unsteady_flow": "u",
    "quasi_unsteady_flow": "q",
}


def _registered_element_identities(bundle: AuditBundle) -> Optional[set[tuple[str, str, str]]]:
    """Return registered ``(project stem, suffix, number)`` identities.

    ``None`` means the capture has no element-level registration inventory, so
    old schema records retain their historical behavior instead of being
    filtered on missing evidence.
    """
    identities: set[tuple[str, str, str]] = set()
    captured = False
    for model in bundle.models:
        elements = model.get("elements")
        if not isinstance(elements, list):
            continue
        captured = True
        stem = Path(str(model.get("prj_file") or "")).stem.casefold()
        if not stem:
            continue
        for element in elements:
            if not element.get("registered"):
                continue
            suffix = _ELEMENT_SUFFIX.get(str(element.get("type") or "").casefold())
            number = str(element.get("number") or "").zfill(2)
            if suffix and number:
                identities.add((stem, suffix, number))
    return identities if captured else None


def _recipe_targets_registered_element(bundle: AuditBundle, recipe: dict) -> bool:
    """Whether an element-file recipe is in the captured ``.prj`` scope.

    Non-element files (RASMapper, supporting rasters, and similar) are not
    constrained by this predicate.  When the record has an element inventory,
    however, a recipe for an unregistered ``.uNN/.pNN/...`` file is evidence
    about delivered corpus residue, not a step required to run the project.
    """
    registered = _registered_element_identities(bundle)
    if registered is None:
        return True
    name = Path(str(recipe.get("file") or "").replace("\\", "/")).name
    match = _RAS_ELEMENT_FILE.match(name)
    if not match:
        return True
    identity = (
        match.group("stem").casefold(),
        match.group("suffix").casefold(),
        match.group("number"),
    )
    return identity in registered


def _nested_archives(bundle: AuditBundle) -> list:
    probe = bundle.audit.get("g2_probe", {}) or {}
    return list(probe.get("nested_archives") or [])


def _relocations(bundle: AuditBundle) -> list:
    return list((bundle.audit.get("asset_relocation", {}) or {}).get("relocated") or [])


@log_call
def actions_from_bundle(bundle: AuditBundle) -> list[RepairAction]:
    """Build the ordered action list (spec section 4) from recipes and probe data."""
    actions: list[RepairAction] = []

    for entry in _nested_archives(bundle):
        if isinstance(entry, dict):
            member = entry.get("member") or entry.get("path") or entry.get("name") or ""
            archive = entry.get("archive") or entry.get("container") or bundle.key
            depth = entry.get("depth") or entry.get("level")
        else:
            member, archive, depth = str(entry), bundle.key, None
        actions.append(RepairAction(
            order=0, kind="recursive_extraction", target=member, reason="nested_archive",
            evidence=f"{archive}:{member}", archive=archive, member=member,
            nesting_depth=depth, blocking=True,
        ))

    for entry in _relocations(bundle):
        actions.append(RepairAction(
            order=0, kind="file_movement",
            target=entry.get("to") or entry.get("destination") or "",
            reason="separately_delivered",
            evidence=entry.get("evidence") or entry.get("archive") or "asset_relocation",
            from_value=entry.get("from") or entry.get("source"),
            to_value=entry.get("to") or entry.get("destination"),
            archive=entry.get("archive"), blocking=True,
        ))

    # A relocation is recorded twice by the worker -- once in the audit's
    # asset_relocation block and once as an asset_relocation recipe. One move,
    # one step; otherwise the blocking count doubles.
    seen_moves = {(a.kind, a.target, a.from_value, a.to_value, None) for a in actions}

    acquired_files: set = set()
    chain_rerun_files: set = set()
    # A chained sub-model may itself read another's output, so the step names
    # the whole sequence, not the one model nearest the boundary.
    chains = chained_dss_chains(bundle)
    for recipe in bundle.recipes:
        if not _recipe_targets_registered_element(bundle, recipe):
            continue
        surface = recipe.get("surface", "")
        kind = _SURFACE_TO_KIND.get(surface, "path_correction")
        raw_from = recipe.get("from") or ""
        raw_to = recipe.get("to")
        if recipe.get("kind") == "acquisition" or recipe.get("confidence") == "acquisition":
            target_file = str(recipe.get("acquisition_target") or raw_from or recipe.get("file") or "")
            base = Path(target_file.replace("\\", "/")).name or target_file
            # One model's computed output is the next model's boundary. This is
            # decided before the review is honoured, because the review's premise
            # -- "original HMS file is in the delivery" -- is false by
            # construction here: no HMS run and no relocation puts a
            # /REFERENCE LINES/ or /BCLINE/ record into a file. Its correction
            # rewrites the reference onto a delivered *input* DSS that does not
            # hold the record and never will, and then deletes the finding.
            # Membership in the pre-computed map, not a fresh per-recipe test:
            # the step list, the supporting-data row and the webmap mirror must
            # classify a name identically, and only one source of truth can
            # guarantee that.
            if base in chains:
                if base in chain_rerun_files:
                    continue
                chain_rerun_files.add(base)
                reason_text = str(recipe.get("confidence_reason") or recipe.get("why") or "")
                actions.append(RepairAction(
                    order=0, kind="chained_model_rerun", target=f"DSS boundary data ({base})",
                    reason="intermediate_results_not_delivered",
                    evidence=(f"{recipe.get('locator', '')}: {reason_text}").strip(": "),
                    source=" -> ".join(chains.get(base) or [producer]),
                    confidence="resolved", blocking=True,
                    escape_depth=escape_depth(raw_from), from_value=raw_from or None,
                    project=recipe.get("project"),
                ))
                continue
            # The independent review is authoritative over the producer's
            # provisional acquisition classification.  When it finds the
            # source file in the delivered archive, the reviewer marks the
            # original recipe ``analysis_gap`` and appends the corrected path
            # recipe.  Retaining both would falsely tell the engineer to
            # obtain a file that was delivered (Aransas 12100407).
            #
            # For a DSS surface that authority is bounded by what the review
            # actually read. An ``archive_member_match`` proves a file of that
            # NAME was delivered, not that it holds the requested record, so it
            # may not drop the acquisition (12050007).
            review = recipe.get("review") or {}
            if dss_review_may_drop_finding(recipe):
                continue
            # Worker rev i: the DSS a boundary was authored for is in no
            # delivered archive (reviewed "real" by the archive-member match).
            # Spring Creek carries 24 of these and still rendered "after
            # repair" because every dss_pathname recipe mapped to a path
            # correction. One acquisition per missing file, named.
            if base in acquired_files:
                continue
            acquired_files.add(base)
            scope = dss_reference_scope(recipe)
            label = (DSS_ACQUISITION_LABELS[scope] if surface == "dss_pathname"
                     else "Referenced file")
            reason_text = str(recipe.get("confidence_reason") or recipe.get("why") or "")
            basis = DSS_ACQUISITION_BASIS.get(scope) if surface == "dss_pathname" else None
            if basis:
                reason_text = (reason_text + " -- " + basis) if reason_text else basis
            actions.append(RepairAction(
                order=0, kind="acquisition", target=f"{label} ({base})", reason="not_delivered",
                evidence=(f"{recipe.get('locator', '')}: {reason_text}").strip(": "),
                confidence="resolved", blocking=True, escape_depth=escape_depth(raw_from),
                from_value=raw_from or None, project=recipe.get("project"),
            ))
            continue
        if raw_from and raw_to and str(raw_from) == str(raw_to):
            continue    # an identity rewrite is not an action
        target = recipe.get("file", "")
        if (kind, target, raw_from or None, raw_to) in seen_moves:
            continue
        identity = (
            kind,
            target,
            raw_from or None,
            raw_to,
            recipe.get("locator") if kind == "path_correction" else None,
        )
        if identity in seen_moves:
            continue
        seen_moves.add(identity)
        depth = escape_depth(raw_from)
        reason = recipe.get("why") or ("broken_relative_reference" if depth > 0 else "separately_delivered")
        if depth > 0 and reason == "missing_from_delivery":
            reason = "broken_relative_reference"
        actions.append(RepairAction(
            order=0, kind=kind, target=target, reason=reason,
            evidence=recipe.get("locator", ""), confidence=recipe.get("confidence", "resolved"),
            blocking=surface in ("dss_pathname", "asset_relocation", "hdf_asset_attribute"),
            escape_depth=depth, from_value=raw_from or None, to_value=recipe.get("to"),
            project=recipe.get("project"),
        ))

    # An expected supporting element that was not delivered is an action, not a
    # footnote. Without this, section 3 says "No" and section 4 says "nothing to
    # do" -- and the verdict calls the model runnable. Reconstruction when the
    # source material shipped; acquisition when it did not. Never fabricate.
    dims, regime = _model_type(bundle)
    expected = expected_elements(dims, regime, _referenced_elements(bundle))
    threshold = study_critical_threshold(bundle)
    if threshold["applies_to_integrated_1d"]:
        expected["terrain"] = False
        expected["land_cover"] = False
    delivered = _delivered_elements(bundle)
    labels = dict(SUPPORTING_ELEMENTS)
    for ekey, is_expected in expected.items():
        if not is_expected:
            continue
        state = (delivered.get(ekey) or {}).get("state")
        if state in ("yes", "rebuilt", "not captured", "unknown", None):
            continue
        if state == "unverified":
            # The check did not run. Asking an engineer to obtain a layer we
            # never established was missing invents work; the supporting-data
            # row and section 6 say the check is outstanding instead.
            continue
        if ekey == "dss" and (acquired_files or chain_rerun_files):
            continue    # the missing DSS files are already named one by one above
        if ekey == "dss" and state == "requires_chain_rerun":
            continue    # every boundary is satisfied by running a delivered model
        location = (delivered.get(ekey) or {}).get("location")
        note = (delivered.get(ekey) or {}).get("note") or ""
        if state == "source_only":
            # Rebuilding from the delivered rasters yields a runnable terrain -- but
            # terrain modifications (channel cuts, levees, polygon overrides) live
            # inside the missing Terrain.hdf, and it is unlikely any of these models
            # was built without one. So this is two actions: reconstruct to run, and
            # obtain the original modified terrain for fidelity. The second is the
            # critical one, and it cannot be satisfied from the delivery.
            mods = ((bundle.audit.get("terrain") or {}).get("modifications") or {})
            referenced = mods.get("referenced_in_rasmap")
            layers = mods.get("rasmap_layers") or []
            mod_count = sum(len(l.get("modifications") or []) for l in layers if isinstance(l, dict))
            if referenced:
                why_mods = f"{mod_count} terrain modification(s) referenced in the .rasmap"
            elif referenced is False:
                why_mods = "no modification references survive in the .rasmap, but they lived in the missing file"
            else:
                why_mods = "modification references not captured"
            actions.append(RepairAction(
                order=0, kind="reconstruction", target=labels[ekey], reason="not_delivered",
                evidence=f"supporting_elements.{ekey} (runnable but without the original modifications)",
                source=location or "delivered rasters", blocking=True, confidence="resolved",
            ))
            actions.append(RepairAction(
                order=0, kind="acquisition", target=f"{labels[ekey]} (as modified -- Terrain.hdf)",
                reason="not_delivered", evidence=f"supporting_elements.{ekey}: {why_mods}",
                blocking=True, confidence="resolved",
            ))
        else:  # "no" or "partial"
            # A partial layer (Terrain.hdf delivered, two of its DEM source tiles
            # not) is still an acquisition -- but "not in the delivery" would be
            # false for it, and the sidebar prints these words.
            actions.append(RepairAction(
                order=0, kind="acquisition", target=labels[ekey],
                reason="partially_delivered" if state == "partial" else "not_delivered",
                evidence=f"supporting_elements.{ekey}" + (f" ({note})" if note else ""),
                blocking=True, confidence="resolved",
            ))

    actions.sort(key=lambda a: (ACTION_ORDER.get(a.kind, 99), a.target, a.evidence))
    for index, action in enumerate(actions, start=1):
        action.order = index
    return actions


def _group_gaps(bundle: AuditBundle) -> dict:
    """Missing references grouped by what they are, deduplicated on raw value.

    Honours the deficiency review: a gap whose ``review.verdict`` is
    ``analysis_gap`` was *ours*, not FEMA's -- the file exists under another
    path or case, or a detector disagreed with the rows. Those are pulled out
    of "still missing" and "must obtain" and reported separately, so an
    engineer never chases a gap in our own analysis.
    """
    grouped: dict[str, Counter] = defaultdict(Counter)
    example_source: dict[tuple, str] = {}
    by_verdict: Counter = Counter()
    analysis_counts: Counter = Counter()
    analysis_evidence: dict[str, str] = {}
    dims, _ = _model_type(bundle)
    for gap in bundle.gaps:
        if gap.get("gap") != "MISSING_REFERENCE":
            continue
        raw = str(gap.get("raw_value", ""))
        review = gap.get("review") or {}
        verdict = review.get("verdict") or "unreviewed"
        by_verdict[verdict] += 1
        ext = Path(raw.replace("\\", "/")).suffix.lower()
        # A ``.dss`` gap is retired only by record-level proof. A basename that
        # matches an archive member says a file of that name was delivered; the
        # gap is about a pathname inside it (12050007, 12060101, 11010008).
        if verdict == "analysis_gap" and (
                ext != ".dss" or dss_review_is_record_proven(review)):
            analysis_counts[raw] += 1
            analysis_evidence.setdefault(raw, str(review.get("evidence", "")))
            continue
        if ext in (".dss",):
            group = "DSS boundary data"
        elif ext in (".tif", ".tiff", ".vrt", ".hdf") and "terrain" in raw.lower():
            group = "Terrain"
        elif ext in (".shp", ".shx", ".dbf", ".gdb"):
            group = "Shapefiles and GIS layers"
        elif ext in (".hdf",):
            group = "HDF results or geometry"
        elif ext in (".tif", ".tiff", ".vrt"):
            group = "Rasters (land cover, depth grids, terrain tiles)"
        elif ext in (".prj",):
            group = "Projection"
        else:
            group = f"Other ({ext or 'no extension'})"
        # A referenced terrain asset remains useful mapping context, but it is
        # not something an integrated 1D model must obtain to recompute. Keep
        # its prevalence in section 3 instead of restating it as a deficiency
        # in sections 5 and 6.
        if dims == "1D" and group == "Terrain":
            continue
        grouped[group][raw] += 1
        example_source.setdefault((group, raw), gap.get("source_file", ""))
    # Element-level reclassifications: a supporting layer the capture called
    # absent that the review found among the archive members. Listed with the
    # reference gaps so the engineer sees why the layer is not in section 6.
    labels = dict(SUPPORTING_ELEMENTS)
    for ekey, entry in (bundle.audit.get("supporting_elements") or {}).items():
        review = (entry or {}).get("review") or {}
        if (review.get("verdict") == "analysis_gap"
                and entry.get("state") in ("no", "partial", "source_only")
                and (ekey != "dss" or dss_review_is_record_proven(review))):
            label = labels.get(ekey, ekey)
            analysis_counts[f"{label} (layer)"] += int(entry.get("referenced_count") or 1)
            analysis_evidence.setdefault(f"{label} (layer)", str(review.get("evidence", "")))
    return {
        "groups": grouped,
        "sources": example_source,
        "by_verdict": by_verdict,
        "analysis_gaps": [
            (raw, count, analysis_evidence.get(raw, ""))
            for raw, count in analysis_counts.most_common()
        ],
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _yes_no(state: str) -> str:
    return {
        "yes": "Yes",
        "no": "**No**",
        "partial": "**Partial** -- delivered, but incomplete (see note)",
        "source_only": "**Source rasters only** -- no Terrain.hdf; must be rebuilt",
        "requires_chain_rerun": ("**Requires sequential re-run of all chained sub-models** "
                                 "(intermediate DSS results not delivered)"),
        "unverified": ("**Not verified** -- the check could not be run, so this row "
                       "establishes nothing either way (see note)"),
        "rebuilt": "Rebuilt (stored with this audit)",
        "unknown": "Unknown",
        "not captured": "*not captured*",
    }.get(state, str(state))


def _md_escape(value) -> str:
    return str(value if value is not None else "").replace("|", "\\|")


def _describe_action(action: RepairAction) -> str:
    what = _ENGINEER_WORDS.get(action.reason, action.reason.replace("_", " "))
    if action.kind == "recursive_extraction":
        depth = f" (nesting depth {action.nesting_depth})" if action.nesting_depth else ""
        return f"Extract `{action.member}` from `{action.archive}`{depth} -- {what}."
    if action.kind == "file_movement":
        return f"Place `{action.from_value}` at `{action.to_value}` -- {what}."
    if action.kind == "path_correction":
        climb = f" It climbed {action.escape_depth} level(s) above the model folder." if action.escape_depth > 0 else ""
        return (f"In `{action.target}`, change `{action.from_value}` to `{action.to_value}` "
                f"-- {what}.{climb}")
    if action.kind == "reconstruction":
        return f"Rebuild `{action.target}` from `{action.source}` -- {what}."
    if action.kind == "chained_model_rerun":
        chain = [m for m in str(action.source or "").split(" -> ") if m]
        if len(chain) > 1:
            return (f"Re-run the chained sub-models in sequence ({format_chain(chain)}) "
                    f"to produce `{action.target}` -- {what}.")
        return (f"Re-run the chained sub-model `{action.source}` to produce "
                f"`{action.target}` -- {what}.")
    climb = (f" The reference climbed {action.escape_depth} level(s) above the model folder."
             if action.escape_depth and action.escape_depth > 0 else "")
    return f"Obtain `{action.target}` from outside the delivery -- {what}.{climb}"


@log_call
def render_audit_markdown(bundle: AuditBundle) -> str:
    """Render the fixed seven-section document. Every section always present."""
    audit = bundle.audit
    key = bundle.key
    name = audit.get("name") or audit.get("study_name") or key
    dims, regime = _model_type(bundle)
    expected = expected_elements(dims, regime, _referenced_elements(bundle))
    threshold = study_critical_threshold(bundle)
    if threshold["applies_to_integrated_1d"]:
        expected["terrain"] = False
        expected["land_cover"] = False
    delivered = _delivered_elements(bundle)
    actions = actions_from_bundle(bundle)
    load = audit.get("g6a_load", {}) or {}
    total, loaded = load.get("projects_total", 0), load.get("projects_loaded", 0)
    blocking = [a for a in actions if a.blocking]
    unavailable: list[str] = []

    authored = audit.get("authored_version")
    if not authored:
        unavailable.append("authored_version")
        for model in bundle.models:
            for line in model.get("loader_error_log", []) or []:
                match = re.search(r"HEC-RAS Version ([\d.]+)", str(line))
                if match:
                    authored = match.group(1) + " (inferred from loader log)"
                    break
            if authored:
                break

    # "Runnable as delivered" means exactly that: zero actions. A model that
    # needs even a non-blocking path fix is not runnable *from extraction*.
    # Then split repairs the engineer can do from the delivery alone from those
    # that need data FEMA did not ship -- that is the question they will ask.
    needs_external = any(a.kind == "acquisition" for a in actions)
    # A chained boundary is not "data not in the delivery" -- FEMA shipped the
    # models that produce it, and what is absent is the intermediate result. It
    # is also not runnable as delivered, and the campaign never recomputes a
    # plan itself, so the extra burden is named rather than folded into the
    # plain "after repair".
    needs_chain_rerun = any(a.kind == "chained_model_rerun" for a in actions)
    if not total or loaded < total:
        runnable = "no -- one or more projects will not open"
    elif not actions:
        runnable = "yes"
    elif needs_external:
        runnable = "no -- needs data not in the delivery"
    elif needs_chain_rerun:
        runnable = ("after repair (from the delivery alone, including a sequential "
                    "re-run of chained sub-models)")
    else:
        runnable = "after repair (from the delivery alone)"

    lines: list[str] = []
    w = lines.append

    # 1 -----------------------------------------------------------------
    w(f"# {name} ({key}) -- eBFE audit and repair recipe")
    w("")
    w("## 1. Verdict")
    w("")
    w(f"| | |")
    w(f"|---|---|")
    w(f"| Model type | **{dims} {regime}** |")
    w(f"| Authored HEC-RAS version | {authored or '*not captured*'} |")
    w(f"| Projects | {loaded} of {total} open |")
    w(f"| Runnable as delivered | **{runnable}** |")
    w(f"| Actions required | {len(actions)} ({len(blocking)} blocking) |")
    # Critical data missing: delivered-but-unusable-for-fidelity. Captured as
    # audit["critical_missing"]; derived from the terrain state when absent, so a
    # missing Terrain.hdf is never quietly folded into "needs data".
    # Present-but-empty means the capture looked and found nothing critical --
    # e.g. 2,378 HEC-RAS 4.10 1D steady projects with no .rasmap, where terrain
    # is not applicable. Only an *absent* field (a v1 capture) gets the derived
    # fallback, and only when the model type expects terrain at all.
    captured_critical = audit.get("critical_missing")
    if captured_critical is not None:
        critical = list(captured_critical)
        # The capture's terrain rule fired on a *partial* terrain -- Terrain.hdf
        # delivered with its modifications, two DEM source tiles not (Middle
        # Guadalupe MIDG01/02). "Terrain.hdf absent" is then false, and the
        # sidebar prints it. Where the record itself shows the HDF delivered for
        # every project the entry names, the entry is dropped; the partial
        # terrain still surfaces as an acquisition with the capture's note.
        terrain_projects = {
            str(p.get("project") or p.get("name") or ""): p
            for p in ((audit.get("terrain") or {}).get("projects") or []) if isinstance(p, dict)
        }
        kept = []
        for item in critical:
            element = str(item.get("element") or "")
            if (
                threshold["applies_to_integrated_1d"]
                and element in STUDY_CRITICAL_ELEMENTS
                and not threshold["elements"][element]["study_critical"]
            ):
                continue
            if element == "land_cover" and not expected.get("land_cover"):
                # A 1D capture may still carry a land-cover row; it is informational.
                continue
            if str(item.get("element")) == "terrain" and str(item.get("reason", "")).startswith("terrain_hdf_absent"):
                named = [str(p) for p in (item.get("projects") or [])]
                if named and all(terrain_projects.get(p, {}).get("terrain_hdf") for p in named):
                    continue
            kept.append(item)
        critical = kept
    elif expected.get("terrain") and delivered.get("terrain", {}).get("state") in ("source_only", "no"):
        critical = [{"element": "terrain", "reason": "terrain_hdf_absent_modifications_unknown"}]
    else:
        critical = []
    # "Critical" is any data the model needs that the delivery does not contain --
    # every acquisition action, not only terrain. The terrain-modification entries
    # add their specific reason. This is the same definition the webmap hatches on
    # (verdict: needs data not in the delivery), so document and map agree.
    parts = []
    for item in critical:
        element = str(item.get("element", "")).replace("_", " ")
        reason = str(item.get("reason", "")).replace("_", " ")
        projects = item.get("projects") or []
        scope = f" ({len(projects)} project{'s' if len(projects) != 1 else ''})" if projects else ""
        parts.append(f"**{element}**{scope} -- {reason}")
    named = {str(item.get("element", "")).lower() for item in critical}
    # A DSS acquisition the producer recorded while its own record check could
    # not run is reported, not retired -- and not asserted flatly either. The
    # qualifier is the difference between "FEMA did not ship this" and "we could
    # not check, and this is what the run recorded".
    _held = dss_verification_is_unverified(audit.get("dss_verification") or {})
    for a in actions:
        if a.kind != "acquisition":
            continue
        base = a.target.split(" (")[0]
        if base.lower() in named:
            continue
        named.add(base.lower())
        wording = "incomplete in the delivery" if a.reason == "partially_delivered" else "not in the delivery"
        if _held and base.lower().startswith("dss boundary data"):
            wording += " (unconfirmed: the DSS record check did not run)"
        parts.append(f"**{base}** -- {wording}")
    if parts:
        w(f"| Critical data missing | {'; '.join(parts)} |")

    grouped = _group_gaps(bundle)
    bv = grouped["by_verdict"]
    # deficiency_review (schema v2) is the authoritative tally: it covers every
    # reviewed gap kind, not only MISSING_REFERENCE rows. The row-derived count
    # is the fallback for captures that predate the review.
    review = audit.get("deficiency_review") or {}
    if review.get("reported") is not None:
        w(f"| Reported gaps | {review.get('reported', 0)} reported: "
          f"**{review.get('real', 0)} real**, "
          f"{review.get('analysis_gap', 0)} were gaps in our analysis, "
          f"{review.get('unverifiable', 0)} unverifiable |")
    else:
        reported = sum(bv.values())
        if reported and any(k != "unreviewed" for k in bv):
            w(f"| Reported gaps | {reported} reported: **{bv.get('real', 0)} real**, "
              f"{bv.get('analysis_gap', 0)} were gaps in our analysis, "
              f"{bv.get('unverifiable', 0)} unverifiable"
              + (f", {bv['unreviewed']} not yet reviewed" if bv.get("unreviewed") else "") + " |")
        elif reported:
            w(f"| Reported gaps | {reported} -- *not yet independently reviewed; treat as provisional* |")
    # A DSS verification that could not read a catalog is a HOLD the producer
    # should have raised. Records written before that rule carry the hold as
    # `inferred` boundaries, and this row is what stops a reader taking the
    # study's DSS row as verified.
    _ver = audit.get("dss_verification") or {}
    _unverified = int(_ver.get("boundaries_inferred") or 0)
    if _unverified and dss_verification_is_unverified(_ver):
        w(f"| DSS boundary verification | **Did not run** -- "
          f"{_unverified} of {int(_ver.get('boundaries_checked') or 0)} boundaries "
          f"unverified: {_md_escape(dss_verification_hold_reason(_ver))} |")
    # The boundary count covers BOUNDARY CONDITIONS. When the record also carries
    # project-level DSS File references, say so here, so "N of N boundaries
    # verified" is never read as covering references the check never examined.
    _project_dss = sorted({
        Path(str(r.get("acquisition_target") or r.get("from") or "").replace("\\", "/")).name
        for r in bundle.recipes
        if (r.get("kind") == "acquisition" or r.get("confidence") == "acquisition")
        and dss_reference_scope(r) in DSS_SCOPES_OUTSIDE_BOUNDARY_CHECK})
    if _project_dss and int(_ver.get("boundaries_checked") or 0):
        w("| DSS references outside the boundary check | "
          f"{len(_project_dss)} project- or plan-level DSS reference(s) "
          f"({_md_escape(', '.join(_project_dss[:4]))}) are not boundary conditions "
          "and were not examined by it |")
    _never_ran = (not int(_ver.get("boundaries_checked") or 0)
                  and bool((delivered.get("dss") or {}).get("referenced")))
    if _never_ran:
        w("| DSS boundary verification | **Did not run** -- no DSS boundary was examined |")
    if blocking:
        first = blocking[0]
        w(f"| Most important | {_describe_action(first)} |")
    w("")
    if _never_ran:
        w("**The DSS boundary check did not run for this study.** No DSS boundary was "
          "examined, so nothing in this document establishes which records the "
          "delivered DSS files hold. Where a DSS element reads \"Yes\" it means a "
          "file is delivered at the path the model references -- the delivery "
          "question -- and not that the boundary records inside it were verified.")
        w("")
    if _unverified and dss_verification_is_unverified(_ver):
        w("**The DSS boundary check did not run for this study.** No boundary was "
          "resolved and none was proven to need data from outside the delivery; the "
          "record says only that the reader failed. Nothing in this document about "
          "DSS boundary data is verified, and no DSS reference may be rewritten on "
          "the strength of it. Re-run the audit's verification stage once the reader "
          "works, then re-render.")
        w("")

    # 2 -----------------------------------------------------------------
    w("## 2. Model inventory")
    w("")
    if not bundle.models:
        w("*No project records were captured for this study.*")
    for model in bundle.models:
        pname = model.get("project_name") or model.get("prj_file") or "project"
        w(f"### `{model.get('prj_file', pname)}`")
        w("")
        w(f"Opened with ras-commander: **{'yes' if model.get('init_ok') else 'no'}**")
        w("")
        elements = model.get("elements")  # schema v2
        if elements:
            w("| Type | Number | Title | Short ID | In .prj | On disk |")
            w("|---|---|---|---|---|---|")
            for row in elements:
                w(f"| {row.get('type','')} | {row.get('number','')} | {_md_escape(row.get('title',''))} "
                  f"| {_md_escape(row.get('short_id',''))} | {'yes' if row.get('registered') else '**no**'} "
                  f"| {'yes' if row.get('on_disk') else '**no**'} |")
        else:
            unavailable.append("elements (names)")
            w("| Type | Registered in .prj | Loaded |")
            w("|---|---:|---:|")
            w(f"| Plans | {model.get('prj_plan_count', '?')} | {model.get('plan_df_rows', '?')} |")
            w(f"| Geometries | {model.get('prj_geom_count', '?')} | {model.get('geom_df_rows', '?')} |")
            w(f"| Steady flow files | {model.get('prj_flow_count', '?')} | {model.get('flow_df_rows', '?')} |")
            w(f"| Unsteady flow files | {model.get('prj_unsteady_count', '?')} | {model.get('unsteady_df_rows', '?')} |")
            w(f"| Boundary conditions | -- | {model.get('boundaries_df_rows', '?')} |")
            w("")
            w("*Element names were not captured under schema v1; counts only.*")
        w("")

    # 3 -----------------------------------------------------------------
    w("## 3. Required supporting data")
    w("")
    w("| Element | Expected | Delivered | Location | Note |")
    w("|---|---|---|---|---|")
    for ekey, label in SUPPORTING_ELEMENTS:
        exp = (
            "Informational only (1D)"
            if ekey in STUDY_CRITICAL_ELEMENTS and threshold["applies_to_integrated_1d"]
            else ("Yes" if expected[ekey] else "Not used by this model")
        )
        d = delivered.get(ekey, {})
        state = _yes_no(d.get("state", "unknown"))
        if not expected[ekey] and d.get("state") in ("no", "unknown", "not captured"):
            state = "--"
        note = d.get("note") or ""
        if ekey in STUDY_CRITICAL_ELEMENTS and threshold["applies_to_integrated_1d"]:
            note = threshold["elements"][ekey].get("informational") or note
        w(f"| {label} | {exp} | {state} | {_md_escape(d.get('location') or '')} | {_md_escape(note)} |")
    if threshold["applies_to_integrated_1d"]:
        w("")
        w("Study-critical prevalence for integrated 1D supporting data:")
        w("")
        w("| Element | Referenced and not delivered | Total unique models | Fraction | Study-critical |")
        w("|---|---:|---:|---:|---|")
        for ekey in STUDY_CRITICAL_ELEMENTS:
            row = threshold["elements"][ekey]
            label = "Land cover / Manning's n" if ekey == "land_cover" else "Terrain"
            w(f"| {label} | {row['numerator']} | {row['denominator']} | {row['percent']:.2f}% "
              f"| {'yes' if row['study_critical'] else 'no'} |")
    w("")

    # 4 -----------------------------------------------------------------
    w("## 4. From delivered to runnable")
    w("")
    if not actions:
        w("**No actions required.** Every reference resolves inside the delivered files.")
    else:
        w(f"{len(actions)} steps, in execution order. Extraction precedes movement, movement "
          f"precedes path correction. Blocking steps are marked; the model will not open or "
          f"run until they are done.")
        w("")
        by_kind = Counter(a.kind for a in actions)
        w("| Kind | Steps |")
        w("|---|---:|")
        for kind in ACTION_KINDS:
            if by_kind.get(kind):
                w(f"| {kind.replace('_', ' ')} | {by_kind[kind]} |")
        w("")
        for action in actions:
            flag = " **[blocking]**" if action.blocking else ""
            conf = "" if action.confidence == "resolved" else f" *(inferred -- review)*"
            w(f"{action.order}. {_describe_action(action)}{flag}{conf}  ")
            w(f"    evidence: `{action.evidence}`")
    w("")

    # 5 -----------------------------------------------------------------
    w("## 5. What is still missing")
    w("")
    grouped = _group_gaps(bundle)
    if not grouped["groups"]:
        w("**Nothing.** Every reference the model makes was found in the delivery or repaired above.")
    else:
        total_missing = sum(sum(c.values()) for c in grouped["groups"].values())
        distinct = sum(len(c) for c in grouped["groups"].values())
        w(f"{total_missing} missing references, {distinct} distinct files, grouped by kind. "
          f"A file referenced many times is one finding with a count.")
        w("")
        for group, counter in sorted(grouped["groups"].items(), key=lambda kv: -sum(kv[1].values())):
            w(f"### {group} ({sum(counter.values())} references, {len(counter)} files)")
            w("")
            w("| Referenced as | Times | First seen in |")
            w("|---|---:|---|")
            for raw, count in counter.most_common():
                src = grouped["sources"].get((group, raw), "")
                w(f"| `{_md_escape(raw)}` | {count} | `{_md_escape(src)}` |")
            w("")

    if grouped["analysis_gaps"]:
        n_refs = sum(c for _, c, _ in grouped["analysis_gaps"])
        w(f"### Reclassified during review -- gaps in our analysis, not in the delivery "
          f"({n_refs} references, {len(grouped['analysis_gaps'])} files)")
        w("")
        w("These were first reported as missing. Independent review found each one in the "
          "delivery -- under another path, another case, or inside a nested archive -- or found "
          "a detector disagreeing with the reference rows. They are **not** deficiencies and do "
          "not appear in section 6. Where a resolution was found, it has been added to section 4.")
        w("")
        w("| First reported as | Times | What review found |")
        w("|---|---:|---|")
        for raw, count, evidence in grouped["analysis_gaps"]:
            w(f"| `{_md_escape(raw)}` | {count} | {_md_escape(evidence)} |")
        w("")
    unverifiable = grouped["by_verdict"].get("unverifiable", 0)
    if unverifiable:
        w(f"*{unverifiable} reference(s) could not be verified either way -- typically DSS "
          f"pathnames with no DSS bridge available in the audit environment. They are listed "
          f"above but should be treated as unconfirmed, not as deficiencies.*")
        w("")

    # 6 -----------------------------------------------------------------
    w("## 6. What you must obtain")
    w("")
    acq = [a for a in actions if a.kind in ("acquisition", "reconstruction")]
    chain_rerun = [a for a in actions if a.kind == "chained_model_rerun"]
    still_missing = grouped["groups"]
    if not acq and not still_missing:
        w("**Nothing external.** The delivery is self-contained once the steps in section 4 are applied.")
    else:
        if acq:
            for a in acq:
                w(f"- {_describe_action(a)}")
        for group, counter in still_missing.items():
            w(f"- **{group}**: {len(counter)} file(s) referenced by the model and not delivered. "
              f"See section 5 for the exact names.")
    if chain_rerun:
        w("")
        sequence = chained_dss_sequence(bundle)
        w(f"Nothing above covers the {len(chain_rerun)} chained boundary "
          f"file{'s' if len(chain_rerun) != 1 else ''}. {CHAINED_DSS_NOTE}: "
          f"{format_chain(sequence)}. "
          f"{'Those models are' if len(sequence) != 1 else 'That model is'} in this delivery "
          f"and no file can be obtained that substitutes for re-running "
          f"{'them' if len(sequence) != 1 else 'it'}. See section 4.")
    w("")

    # 7 -----------------------------------------------------------------
    w("## 7. Provenance and method")
    w("")
    prov = audit.get("provenance", {}) or {}
    g1 = audit.get("g1_verify", {}) or {}
    g3 = audit.get("g3_extract", {}) or {}
    g7 = audit.get("g7_validate", {}) or {}
    rc = audit.get("g7_rascheck", {}) or {}
    w(f"- Stage: `{audit.get('stage', '?')}`; completed {audit.get('completed_utc', '?')} on "
      f"`{prov.get('worker_host', '?')}`")
    w(f"- Code: `ras_commander` commit `{str(prov.get('git_commit', '?'))[:12]}`, "
      f"working-tree diff `{str(prov.get('git_diff_HEAD_sha256', '?'))[:12]}`, "
      f"{prov.get('working_tree_dirty_files', '?')} uncommitted files -- the diff hash, not the "
      f"commit, identifies this build")
    w(f"- Source verified by size against the provenance sidecar, ETag identity, and the zip's "
      f"own CRC-32: sizes match = {g1.get('all_sizes_match', '?')}. No hashing.")
    w(f"- Extraction: {g3.get('members_written', '?')} members, "
      f"{len(g3.get('crc_failures') or [])} CRC failures, "
      f"{len(g3.get('size_mismatches') or [])} size mismatches, "
      f"{len(g3.get('truncated_members') or [])} truncated")
    w(f"- Windows path closure: {g7.get('windows_path_closure', '?')} "
      f"(longest projected path {g7.get('max_projected_windows_len', '?')} chars); "
      f"absolute-path closure: {g7.get('absolute_path_closure', '?')} "
      f"({g7.get('absolute_reference_count', '?')} absolute references)")
    fam = rc.get("flow_type_families") or {}
    w(f"- RasCheck: {rc.get('outcome', '?')}"
      + (f", families {dict(fam)}" if fam else "")
      + " -- a pass is only as strong as the family that ran")
    if unavailable:
        w(f"- Fields not available in this capture (schema v1): {', '.join(sorted(set(unavailable)))}")
    # A record whose DSS facts were corrected in place is not a re-run record,
    # and must never be read as one. The correction stamps itself; this is where
    # a reader of the document meets it.
    reverification = audit.get("dss_reverification") or {}
    if reverification.get("schema"):
        before = reverification.get("boundaries_before") or {}
        after = reverification.get("boundaries_after") or {}
        w(f"- **DSS boundaries re-verified in place on {reverification.get('performed_utc', '?')}**, "
          f"not re-run: the record check was re-answered from the delivered DSS members "
          f"because {reverification.get('why', 'the original reader failed')}. "
          f"Resolved {before.get('boundaries_resolved', '?')} -> {after.get('boundaries_resolved', '?')}, "
          f"acquisition {before.get('boundaries_acquisition', '?')} -> {after.get('boundaries_acquisition', '?')}, "
          f"unverified {before.get('boundaries_inferred', '?')} -> {after.get('boundaries_inferred', '?')}. "
          f"Everything outside the DSS facts is as the original run left it "
          f"(`{reverification.get('tool', 'reverify_dss.py')}`, corrected from "
          f"`{str(reverification.get('corrected_from_audit_sha256', '?'))[:12]}`).")
    w("")
    w("*This document is a recipe. It is executed against a fresh extraction of the raw "
      "archive; the extracted tree it was derived from has been discarded.*")
    w("")
    return "\n".join(lines)
