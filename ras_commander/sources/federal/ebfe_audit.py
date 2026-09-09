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
    "RepairAction",
    "AuditBundle",
    "escape_depth",
    "classify_reference",
    "expected_elements",
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
#: file that has not been unpacked and placed yet.
ACTION_KINDS = (
    "recursive_extraction",
    "file_movement",
    "path_correction",
    "reconstruction",
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
}


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
        "terrain": optional("terrain", is_2d),
        "land_cover": optional("land_cover", is_2d),
        "infiltration": optional("infiltration", False),
        "soils": optional("soils", False),
        "dss": optional("dss", unsteady),
        "projection": optional("projection", is_2d),
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
            # cover). The review is the later, independent word; it wins.
            review = entry.get("review") or {}
            if review.get("verdict") == "analysis_gap" and entry.get("state") in ("no", "partial", "source_only"):
                evidence = str(review.get("evidence") or "")
                member = evidence.split("::", 1)[1] if "::" in evidence else None
                entry["state_as_captured"] = entry.get("state")
                entry["state"] = "yes"
                entry["location"] = member or entry.get("location")
                entry["note"] = f"found by independent review: {evidence}" if evidence else "found by independent review"
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
    seen_moves = {(a.kind, a.from_value, a.to_value) for a in actions}

    for recipe in bundle.recipes:
        surface = recipe.get("surface", "")
        kind = _SURFACE_TO_KIND.get(surface, "path_correction")
        raw_from = recipe.get("from") or ""
        raw_to = recipe.get("to")
        if raw_from and raw_to and str(raw_from) == str(raw_to):
            continue    # an identity rewrite is not an action
        if (kind, raw_from or None, raw_to) in seen_moves:
            continue
        seen_moves.add((kind, raw_from or None, raw_to))
        depth = escape_depth(raw_from)
        reason = recipe.get("why") or ("broken_relative_reference" if depth > 0 else "separately_delivered")
        if depth > 0 and reason == "missing_from_delivery":
            reason = "broken_relative_reference"
        actions.append(RepairAction(
            order=0, kind=kind, target=recipe.get("file", ""), reason=reason,
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
    delivered = _delivered_elements(bundle)
    labels = dict(SUPPORTING_ELEMENTS)
    for ekey, is_expected in expected.items():
        if not is_expected:
            continue
        state = (delivered.get(ekey) or {}).get("state")
        if state in ("yes", "rebuilt", "not captured", "unknown", None):
            continue
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
    for gap in bundle.gaps:
        if gap.get("gap") != "MISSING_REFERENCE":
            continue
        raw = str(gap.get("raw_value", ""))
        review = gap.get("review") or {}
        verdict = review.get("verdict") or "unreviewed"
        by_verdict[verdict] += 1
        if verdict == "analysis_gap":
            analysis_counts[raw] += 1
            analysis_evidence.setdefault(raw, str(review.get("evidence", "")))
            continue
        ext = Path(raw.replace("\\", "/")).suffix.lower()
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
        grouped[group][raw] += 1
        example_source.setdefault((group, raw), gap.get("source_file", ""))
    # Element-level reclassifications: a supporting layer the capture called
    # absent that the review found among the archive members. Listed with the
    # reference gaps so the engineer sees why the layer is not in section 6.
    labels = dict(SUPPORTING_ELEMENTS)
    for ekey, entry in (bundle.audit.get("supporting_elements") or {}).items():
        review = (entry or {}).get("review") or {}
        if review.get("verdict") == "analysis_gap" and entry.get("state") in ("no", "partial", "source_only"):
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
    return f"Obtain `{action.target}` from outside the delivery -- {what}."


@log_call
def render_audit_markdown(bundle: AuditBundle) -> str:
    """Render the fixed seven-section document. Every section always present."""
    audit = bundle.audit
    key = bundle.key
    name = audit.get("name") or audit.get("study_name") or key
    dims, regime = _model_type(bundle)
    expected = expected_elements(dims, regime, _referenced_elements(bundle))
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
    if not total or loaded < total:
        runnable = "no -- one or more projects will not open"
    elif not actions:
        runnable = "yes"
    elif needs_external:
        runnable = "no -- needs data not in the delivery"
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
    for a in actions:
        if a.kind != "acquisition":
            continue
        base = a.target.split(" (")[0]
        if base.lower() in named:
            continue
        named.add(base.lower())
        wording = "incomplete in the delivery" if a.reason == "partially_delivered" else "not in the delivery"
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
    if blocking:
        first = blocking[0]
        w(f"| Most important | {_describe_action(first)} |")
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
        exp = "Yes" if expected[ekey] else "Not used by this model"
        d = delivered.get(ekey, {})
        state = _yes_no(d.get("state", "unknown"))
        if not expected[ekey] and d.get("state") in ("no", "unknown", "not captured"):
            state = "--"
        w(f"| {label} | {exp} | {state} | {_md_escape(d.get('location') or '')} | {_md_escape(d.get('note') or '')} |")
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
    w("")
    w("*This document is a recipe. It is executed against a fresh extraction of the raw "
      "archive; the extracted tree it was derived from has been discarded.*")
    w("")
    return "\n".join(lines)
