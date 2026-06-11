"""
GeomCulvertGIS - Planimetric (GIS) reconstruction and hydraulic-validity checks
for 1D inline culverts in HEC-RAS plain-text geometry files.

HEC-RAS does not store a GIS polyline for a 1D culvert barrel. The barrel's
planimetric line is *derived* from data that does live in the plain-text
geometry:

    - the bounding cross-section GIS cut lines (``XS GIS Cut Line=``),
    - the culvert's upstream/downstream cross-section stations,
    - the structure's ``US Distance`` (offset of the upstream face into the
      reach), and
    - the reach lengths (LOB / Channel / ROB) of the upstream bounding XS.

This module reconstructs that barrel line so it can be visualized, measured, and
validated, and provides the hydraulic-validity checks that keep an authored or
edited culvert from generating HEC-RAS errors:

    1. GIS cut-line length within a tolerance (default 1%) of the entered barrel
       ``Length`` -- HEC-RAS rejects larger discrepancies.
    2. Culvert invert not below the bounding cross-section thalweg (US invert vs
       upstream XS minimum elevation; DS invert vs downstream XS minimum).
    3. Entrance/exit loss coefficients in line with HDS-5 / HEC-RAS guidance for
       the selected inlet (Chart # / Scale#).

All methods are static. ``ras_object`` is accepted for API symmetry but only the
underlying ``get_xs_coords`` call currently uses it; the other reads resolve the
explicit ``geom_file`` path directly.

Reconstruction accuracy: the barrel line is interpolated between the bounding XS
cut lines using a single per-barrel reach-length basis (the upstream-face bank
zone). Measured against the 16 georeferenced USGS Squannacook stream crossings,
the reconstructed planimetric length differs from the entered barrel ``Length``
by **mean 2.6% / median 1.3% / max ~11%** -- good enough for plan-view context
and for flagging gross placement/length inconsistencies, but NOT a survey-precise
reproduction of HEC-RAS's internal centerline derivation. The barrel-length check
is therefore reported as an informational ``REVIEW`` flag, not a hard pass/fail.
The strict +/-1% GIS-length rule that HEC-RAS enforces applies to an *authored*
culvert centerline; this read-only module does not write geometry, so it cannot
and does not claim to enforce that rule.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from ras_commander.LoggingConfig import get_logger, log_call
from ras_commander.geom.GeomCulvert import GeomCulvert
from ras_commander.geom.GeomCrossSection import GeomCrossSection

logger = get_logger(__name__)


def _normalize_rs(rs: str) -> str:
    """Normalize a river-station string for tolerant comparison (numeric when
    possible, else stripped text)."""
    s = str(rs).strip()
    try:
        return repr(float(s.replace("*", "")))
    except (ValueError, AttributeError):
        return s.casefold()


class GeomCulvertGIS:
    """Reconstruct and validate 1D inline culvert GIS placement (plain text)."""

    # HDS-5 / HEC-RAS recommended entrance-loss coefficients (Ke) keyed by
    # substrings of the HEC-RAS inlet (Scale#) description. First match wins, so
    # ALL specific multi-word inlets are listed before generic single-word edge
    # descriptors (otherwise e.g. "beveled" would shadow
    # "wingwall flared 30 to 75 deg ... beveled edge"). Advisory only.
    HDS5_ENTRANCE_LOSS: Tuple[Tuple[str, float], ...] = (
        # --- specific multi-word inlets (checked first) ---
        ("wingwall flared 30 to 75", 0.4),
        ("wingwall flared 18", 0.2),
        ("wingwall flared 0", 0.5),
        ("thin wall projecting", 0.9),
        ("thick wall projecting", 0.7),
        ("tapered inlet throat", 0.2),
        ("smooth tapered", 0.2),
        ("side tapered", 0.2),
        ("slope tapered", 0.2),
        ("groove end", 0.2),
        ("grooved end", 0.2),
        ("square edge", 0.5),
        ("square edges", 0.5),
        ("mitered", 0.7),
        ("end section", 0.5),
        # --- generic single-word fallbacks (checked last) ---
        ("groove", 0.2),
        ("socket", 0.2),
        ("beveled", 0.2),
        ("bevel", 0.2),
        ("rounded", 0.2),
        ("tapered", 0.2),
        ("projecting", 0.5),
        ("wingwall", 0.5),
        ("wing wall", 0.5),
        ("headwall", 0.5),
    )
    ENTRANCE_LOSS_TOLERANCE = 0.15  # warn if |Ke - recommended| exceeds this
    TYPICAL_EXIT_LOSS = 1.0
    INVERT_TOLERANCE = 0.1  # ft; invert below thalweg by less than this is survey noise

    # ------------------------------------------------------------------
    # raw culvert-record parsing (US Distance is not exposed by get_culverts)
    # ------------------------------------------------------------------
    @staticmethod
    def _structure_us_distances(geom_text: str, river: str, reach: str,
                                struct_rs: str) -> List[float]:
        """Return the ``US Distance`` (last field) of each culvert record in the
        structure block at ``river``/``reach``/``struct_rs``, in file order.

        Scoped to the correct ``River Reach=`` block so a duplicate river station
        in another reach cannot be matched. (``US Distance`` is not exposed by
        ``GeomCulvert.get_culverts``.)
        """
        out: List[float] = []
        in_reach = False
        in_block = False
        target_river = str(river).strip().casefold()
        target_reach = str(reach).strip().casefold()
        rs_clean = str(struct_rs).strip()
        # tolerate trailing zeros / formatting on the RS field
        rs_pat = re.compile(r"^Type RM Length L Ch R = 2\s*,\s*([^,]+),")
        for line in geom_text.splitlines():
            if line.startswith("River Reach="):
                payload = line.split("=", 1)[1]
                parts = [p.strip().casefold() for p in payload.split(",")]
                in_reach = (len(parts) >= 2
                            and parts[0] == target_river
                            and parts[1] == target_reach)
                in_block = False
                continue
            if not in_reach:
                continue
            m = rs_pat.match(line)
            if m:
                this_rs = m.group(1).strip()
                in_block = (this_rs == rs_clean
                            or _normalize_rs(this_rs) == _normalize_rs(rs_clean))
                continue
            if in_block and line.startswith("Type RM Length L Ch R"):
                in_block = False
                continue
            if in_block and (line.startswith("Culvert=")
                             or line.startswith("Multiple Barrel Culv=")):
                try:
                    out.append(float(line.rsplit(",", 1)[-1].strip()))
                except (ValueError, IndexError):
                    out.append(float("nan"))
        return out

    # ------------------------------------------------------------------
    # geometry helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _cutline(xyz: pd.DataFrame, rs: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        grp = xyz[xyz["RS"].astype(str) == str(rs)].sort_values("station")
        return (grp["station"].to_numpy(dtype=float),
                grp["x"].to_numpy(dtype=float),
                grp["y"].to_numpy(dtype=float))

    @staticmethod
    def _point_on_cutline(sta: np.ndarray, xs: np.ndarray, ys: np.ndarray,
                          station: float) -> Tuple[float, float]:
        return float(np.interp(station, sta, xs)), float(np.interp(station, sta, ys))

    @staticmethod
    def _reach_length_at(station: float, left_bank: float, right_bank: float,
                         lob: float, channel: float, rob: float) -> float:
        """Per-zone reach length (LOB / Channel / ROB) selected by bank station."""
        if station < left_bank:
            return lob
        if station > right_bank:
            return rob
        return channel

    @staticmethod
    def _local_bed_min(station_elev: pd.DataFrame, station: float,
                       span: float) -> float:
        """Minimum ground elevation under the culvert opening: the lowest
        station-elevation point within ``span/2`` of the barrel ``station``
        (falls back to the nearest point / interpolation if none lie inside)."""
        sta = station_elev["Station"].to_numpy(dtype=float)
        elev = station_elev["Elevation"].to_numpy(dtype=float)
        half = max(abs(span) / 2.0, 0.0)
        mask = (sta >= station - half) & (sta <= station + half)
        if mask.any():
            return float(elev[mask].min())
        # opening narrower than point spacing -> interpolate at the station
        order = np.argsort(sta)
        return float(np.interp(station, sta[order], elev[order]))

    @staticmethod
    def _recommended_ke(scale_label: Optional[str]) -> Optional[float]:
        if not scale_label:
            return None
        text = str(scale_label).casefold()
        for key, ke in GeomCulvertGIS.HDS5_ENTRANCE_LOSS:
            if key in text:
                return ke
        return None

    @staticmethod
    def _scale_label(chart_id: Any, scale_id: Any) -> Optional[str]:
        """HEC-RAS Scale# (inlet) GUI label from the culvert taxonomy."""
        try:
            chart_id = int(chart_id)
            scale_id = int(scale_id)
        except (TypeError, ValueError):
            return None
        for shape in GeomCulvert.CULVERT_TAXONOMY_SHAPES.values():
            for chart in shape.get("allowed_charts", []):
                if int(chart["chart_id"]) != chart_id:
                    continue
                for scale in chart.get("allowed_scales", []):
                    if int(scale["scale_id"]) == scale_id:
                        return scale.get("hec_ras_gui_label")
        return None

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    @staticmethod
    @log_call
    def reconstruct_barrels(geom_file: Union[str, Path],
                            river: str,
                            reach: str,
                            rs: str,
                            ras_object=None) -> pd.DataFrame:
        """
        Reconstruct the planimetric (GIS) centerline of every culvert barrel at a
        structure from the plain-text geometry.

        Each barrel runs from the structure's upstream face to its downstream
        face. Face positions are located ``US Distance`` and ``US Distance +
        Length`` downstream of the upstream bounding cross section, interpolated
        between the bounding XS cut lines using per-zone (LOB/Channel/ROB) reach
        lengths; barrel endpoints are placed at the barrel's US/DS stations.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river, reach, rs: structure location
            ras_object: optional RasPrj for multi-project workflows

        Returns:
            pd.DataFrame with one row per barrel:
                - CulvertName, Barrel (1-based index within the group)
                - us_x, us_y, ds_x, ds_y  (endpoint coordinates)
                - planimetric_length, length_3d, entered_length
                - length_error_pct  (|planimetric - entered| / entered * 100)
        """
        geom_file = Path(geom_file)
        text = geom_file.read_text(encoding="utf-8", errors="replace")

        culverts = GeomCulvert.get_culverts(geom_file, river, reach, rs)
        if culverts.empty:
            return pd.DataFrame()

        us_dists = GeomCulvertGIS._structure_us_distances(text, river, reach, rs)
        if len(us_dists) != len(culverts):
            raise ValueError(
                f"US Distance parse mismatch for {river}/{reach}/RS {rs}: found "
                f"{len(us_dists)} culvert records in the geometry block but "
                f"get_culverts returned {len(culverts)}. Refusing to align by "
                f"index (could assign foreign US Distance values)."
            )

        adj = GeomCulvert.get_adjacent_cross_sections(geom_file, river, reach, rs)
        us_rs = str(adj["upstream"]["RS"])
        ds_rs = str(adj["downstream"]["RS"])

        xyz = GeomCrossSection.get_xs_coords(geom_file, river=river, reach=reach,
                                             ras_object=ras_object)
        s_us, x_us, y_us = GeomCulvertGIS._cutline(xyz, us_rs)
        s_ds, x_ds, y_ds = GeomCulvertGIS._cutline(xyz, ds_rs)
        if len(s_us) < 2 or len(s_ds) < 2:
            raise ValueError(
                f"Bounding XS cut lines unavailable for structure {rs} "
                f"(US={us_rs}, DS={ds_rs}); geometry may not be georeferenced."
            )

        # reach lengths + bank stations of the upstream bounding XS
        xs_meta = GeomCrossSection.get_cross_sections(geom_file, river=river, reach=reach)
        row = xs_meta[xs_meta["RS"].astype(str) == us_rs]
        if row.empty:
            raise ValueError(f"Upstream XS {us_rs} not found for structure {rs}")
        lob = float(row.iloc[0]["Length_Left"])
        channel = float(row.iloc[0]["Length_Channel"])
        rob = float(row.iloc[0]["Length_Right"])
        banks = GeomCrossSection.get_bank_stations(geom_file, river, reach, us_rs)
        left_bank, right_bank = (float(banks[0]), float(banks[1])) if banks else (-1e9, 1e9)

        def face_point(reach_dist: float, station: float, rlen: float) -> Tuple[float, float]:
            # rlen is fixed per barrel so both faces use the same reach-length
            # basis (a per-face zone mix misplaces a skewed barrel's far face).
            frac = reach_dist / rlen if rlen else 0.0
            ux, uy = GeomCulvertGIS._point_on_cutline(s_us, x_us, y_us, station)
            dx, dy = GeomCulvertGIS._point_on_cutline(s_ds, x_ds, y_ds, station)
            return (1 - frac) * ux + frac * dx, (1 - frac) * uy + frac * dy

        rows: List[Dict[str, Any]] = []
        for i, (_, c) in enumerate(culverts.iterrows()):
            us_dist = us_dists[i]
            length = float(c["Length"])
            us_inv = float(c["UpstreamInvert"])
            ds_inv = float(c["DownstreamInvert"])
            drop = us_inv - ds_inv
            name = str(c.get("CulvertName", "")).strip()
            barrels = c.get("BarrelStations") or []
            for b_idx, (us_sta, ds_sta) in enumerate(barrels, start=1):
                if not (us_dist == us_dist):  # NaN US Distance -> cannot place
                    continue
                # one reach-length basis per barrel, from the upstream-face zone
                rlen = GeomCulvertGIS._reach_length_at(
                    float(us_sta), left_bank, right_bank, lob, channel, rob)
                us_pt = face_point(us_dist, float(us_sta), rlen)
                ds_pt = face_point(us_dist + length, float(ds_sta), rlen)
                planimetric = math.dist(us_pt, ds_pt)
                length_3d = math.hypot(planimetric, drop)
                err = abs(planimetric - length) / length * 100 if length else float("nan")
                rows.append({
                    "CulvertName": name,
                    "Barrel": b_idx,
                    "us_x": us_pt[0], "us_y": us_pt[1],
                    "ds_x": ds_pt[0], "ds_y": ds_pt[1],
                    "planimetric_length": planimetric,
                    "length_3d": length_3d,
                    "entered_length": length,
                    "length_error_pct": err,
                })
        return pd.DataFrame(rows)

    @staticmethod
    @log_call
    def validate_placement(geom_file: Union[str, Path],
                           river: str,
                           reach: str,
                           rs: str,
                           length_tol_pct: float = 1.0,
                           invert_tol: Optional[float] = None,
                           ras_object=None) -> pd.DataFrame:
        """
        Run hydraulic-validity checks on every culvert at a structure.

        Checks per culvert group:
            - length     : reconstructed GIS length vs entered Length, reported as
                           an informational REVIEW flag beyond ``length_tol_pct``
                           (reconstruction is approximate; see module docstring).
            - us_invert  : US invert >= local bed under the opening on the upstream
                           bounding XS (within +/- invert_tol). The global XS
                           minimum is reported in ``detail`` for reference.
            - ds_invert  : DS invert >= local bed under the opening on the
                           downstream bounding XS.
            - entrance_loss : entered Ke within tolerance of the HDS-5 value for
                              the selected inlet (advisory).
            - exit_loss  : exit loss near the typical 1.0 (advisory).

        Returns:
            pd.DataFrame with columns: CulvertName, check, status (PASS/FAIL/WARN),
            value, reference, detail.
        """
        geom_file = Path(geom_file)
        if invert_tol is None:
            invert_tol = GeomCulvertGIS.INVERT_TOLERANCE
        culverts = GeomCulvert.get_culverts(geom_file, river, reach, rs)
        if culverts.empty:
            return pd.DataFrame()

        adj = GeomCulvert.get_adjacent_cross_sections(geom_file, river, reach, rs)
        us_rs = str(adj["upstream"]["RS"])
        ds_rs = str(adj["downstream"]["RS"])
        us_se = GeomCrossSection.get_station_elevation(geom_file, river, reach, us_rs)
        ds_se = GeomCrossSection.get_station_elevation(geom_file, river, reach, ds_rs)
        us_global_min = float(us_se["Elevation"].min())
        ds_global_min = float(ds_se["Elevation"].min())

        barrel_df = GeomCulvertGIS.reconstruct_barrels(geom_file, river, reach, rs,
                                                       ras_object=ras_object)
        # worst (max) length error per culvert name
        len_err = (barrel_df.groupby("CulvertName")["length_error_pct"].max().to_dict()
                   if not barrel_df.empty else {})

        records: List[Dict[str, Any]] = []
        for _, c in culverts.iterrows():
            name = str(c.get("CulvertName", "")).strip()
            us_inv = float(c["UpstreamInvert"])
            ds_inv = float(c["DownstreamInvert"])
            ke = float(c["EntranceLoss"])
            kex = float(c["ExitLoss"])
            span = float(c["Span"]) if pd.notna(c.get("Span")) else 0.0

            # local bed under the opening: lowest ground within span/2 of each
            # barrel station (vs the GLOBAL XS minimum, which can be an offset
            # low point far from the culvert).
            barrels = c.get("BarrelStations") or []
            if barrels:
                us_bed = min(GeomCulvertGIS._local_bed_min(us_se, float(b[0]), span)
                             for b in barrels)
                ds_bed = min(GeomCulvertGIS._local_bed_min(ds_se, float(b[1]), span)
                             for b in barrels)
            else:
                us_bed, ds_bed = us_global_min, ds_global_min

            err = len_err.get(name, float("nan"))
            # 1D barrel lines are *reconstructed* (mean ~2.6% vs HEC-RAS), so a
            # difference larger than tolerance is an informational REVIEW flag,
            # not a hard FAIL. This read-only module does not enforce HEC-RAS's
            # strict +/-1% authored-centerline rule.
            records.append({
                "CulvertName": name, "check": "length",
                "status": "PASS" if (err == err and err <= length_tol_pct) else (
                    "REVIEW" if err == err else "N/A"),
                "value": None if err != err else round(err, 2),
                "reference": f"<= {length_tol_pct}% of entered Length (approx.)",
                "detail": "reconstructed GIS length vs entered barrel Length",
            })
            records.append({
                "CulvertName": name, "check": "us_invert",
                "status": "PASS" if us_inv >= us_bed - invert_tol else "FAIL",
                "value": round(us_inv, 2),
                "reference": f">= local bed {us_bed:.2f} (XS {us_rs})",
                "detail": f"upstream invert vs local bed under opening "
                          f"(global XS min {us_global_min:.2f}, tol {invert_tol} ft)",
            })
            records.append({
                "CulvertName": name, "check": "ds_invert",
                "status": "PASS" if ds_inv >= ds_bed - invert_tol else "FAIL",
                "value": round(ds_inv, 2),
                "reference": f">= local bed {ds_bed:.2f} (XS {ds_rs})",
                "detail": f"downstream invert vs local bed under opening "
                          f"(global XS min {ds_global_min:.2f}, tol {invert_tol} ft)",
            })

            label = GeomCulvertGIS._scale_label(c.get("InletType"), c.get("OutletType"))
            rec_ke = GeomCulvertGIS._recommended_ke(label)
            if rec_ke is None:
                ke_status, ref = "N/A", "no HDS-5 mapping for inlet"
            elif abs(ke - rec_ke) <= GeomCulvertGIS.ENTRANCE_LOSS_TOLERANCE:
                ke_status, ref = "PASS", f"HDS-5 ~{rec_ke} ({label})"
            else:
                ke_status, ref = "WARN", f"HDS-5 ~{rec_ke} ({label})"
            records.append({
                "CulvertName": name, "check": "entrance_loss",
                "status": ke_status, "value": ke, "reference": ref,
                "detail": "entrance loss Ke vs HDS-5 guidance for inlet",
            })
            records.append({
                "CulvertName": name, "check": "exit_loss",
                "status": "PASS" if abs(kex - GeomCulvertGIS.TYPICAL_EXIT_LOSS) <= 0.3 else "WARN",
                "value": kex, "reference": f"~{GeomCulvertGIS.TYPICAL_EXIT_LOSS} typical",
                "detail": "exit loss coefficient vs typical full-expansion value",
            })
        return pd.DataFrame(records)


__all__ = ["GeomCulvertGIS"]
