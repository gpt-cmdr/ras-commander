"""Private Water Data adapter for the existing single-site retrieval contracts."""

import re

import pandas as pd


def _backend():
    try:
        from dataretrieval import waterdata
        for name in ("get_continuous", "get_daily", "get_monitoring_locations", "get_time_series_metadata"):
            if not callable(getattr(waterdata, name, None)):
                raise ImportError(name)
        return waterdata
    except ImportError as exc:
        raise ImportError(
            "Modern USGS retrieval requires dataretrieval>=1.4. "
            "Install with: pip install 'dataretrieval>=1.4'"
        ) from exc


def _location(site):
    number = str(site).strip()
    if number.upper().startswith("USGS-"):
        number = number[5:]
    if not re.fullmatch(r"\d{8,15}", number):
        raise ValueError("site_id must be an 8-15 digit USGS station number")
    return number, f"USGS-{number}"


def _wait():
    from .core import _apply_rate_limit
    _apply_rate_limit()


def _utc(value):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError("USGS query dates must not be missing")
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _normalize(frame, site, code, statistic):
    """Keep sorted UTC observations; refuse conflicting series or units."""
    column = f"{site}_{code}"
    if frame is None or frame.empty:
        return pd.DataFrame(columns=[column, column + "_cd"], index=pd.DatetimeIndex([], tz="UTC", name="datetime"))
    required = {"time", "value", "parameter_code", "monitoring_location_id", "statistic_id", "unit_of_measure", "approval_status"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Water Data response is missing fields: {', '.join(sorted(missing))}")
    frame = frame.copy()
    expected_location = f"USGS-{site}"
    for field, expected in [("monitoring_location_id", expected_location), ("parameter_code", code), ("statistic_id", statistic)]:
        if not frame[field].eq(expected).all():
            raise ValueError(f"Water Data response contains unexpected {field}")
    expected_units = {"00060": {"ft^3/s", "ft3/s", "cfs", "ft³/s"}, "00065": {"ft", "feet"}}
    if code in expected_units and not frame["unit_of_measure"].isin(expected_units[code]).all():
        raise ValueError(f"Water Data units do not match parameter {code}: {frame['unit_of_measure'].unique().tolist()}")
    if not frame["approval_status"].isin(["Approved", "Provisional"]).all():
        raise ValueError("Water Data approval_status must explicitly be Approved or Provisional")
    result = pd.DataFrame({
        "datetime": pd.to_datetime(frame["time"], utc=True, errors="raise"),
        column: pd.to_numeric(frame["value"], errors="raise"),
        column + "_cd": frame["approval_status"].map({"Approved": "A", "Provisional": "P"}),
    })
    if result["datetime"].isna().any():
        raise ValueError("Water Data observation time must not be missing")
    # Approval and other qualifiers remain separate, preserving exact P/A checks.
    if "qualifier" in frame:
        result[column + "_qualifier_cd"] = frame["qualifier"].map(
            lambda value: ",".join(map(str, value)) if isinstance(value, (list, tuple)) else value
        )
    result = result.drop_duplicates().sort_values("datetime", kind="stable")
    if result["datetime"].duplicated().any():
        raise ValueError("Water Data returned conflicting observations at the same timestamp; select an unambiguous series")
    return result.set_index("datetime")


def _retrieve(*, sites, parameterCd, start, end, daily=False):
    site, location = _location(sites)
    code = str(parameterCd)
    if not re.fullmatch(r"\d{5}", code):
        raise ValueError("parameterCd must be a five-digit USGS parameter code")
    lower, upper = _utc(start), _utc(end)
    date_end = re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(end)) is not None
    if date_end:
        upper += pd.Timedelta(days=1)
    if (date_end and upper <= lower) or (not date_end and upper < lower):
        raise ValueError("USGS end date must not precede start date")
    statistic = "00003" if daily else "00011"
    api = _backend()
    fetch = api.get_daily if daily else api.get_continuous
    frames, requests = [], 0
    current = lower
    # Year-sized intervals stay below the provider's continuous-query limit.
    while current <= upper:
        stop = min(current + pd.DateOffset(years=1), upper)
        _wait()
        frame, _ = fetch(
            monitoring_location_id=location, parameter_code=code, statistic_id=statistic,
            time=f"{current.isoformat()}/{stop.isoformat()}",
        )
        frames.append(_normalize(frame, site, code, statistic))
        requests += 1
        if stop == upper:
            break
        current = stop
    result = pd.concat(frames)
    result = result.reset_index().drop_duplicates().set_index("datetime").sort_index()
    if result.index.duplicated().any():
        raise ValueError("Water Data returned conflicting observations across query intervals")
    result = result[(result.index >= lower) & ((result.index < upper) if date_end else (result.index <= upper))]
    return result, {"source": "dataretrieval.waterdata", "monitoring_location_id": location,
                    "parameter_code": code, "statistic_id": statistic, "request_count": requests}


class _WaterDataAdapter:
    """Translate only the single-site calls used by Commander retrieval."""

    get_iv = staticmethod(_retrieve)

    @staticmethod
    def get_dv(**kwargs):
        return _retrieve(**kwargs, daily=True)

    @staticmethod
    def get_info(*, sites):
        site, location = _location(sites)
        _wait()
        frame, _ = _backend().get_monitoring_locations(monitoring_location_id=location)
        if frame is None or frame.empty:
            return pd.DataFrame(), {}
        if len(frame) != 1 or not frame["monitoring_location_id"].eq(location).all():
            raise ValueError("Water Data returned ambiguous monitoring location metadata")
        row = frame.iloc[0]
        geometry = row.get("geometry")
        if isinstance(geometry, dict):
            longitude, latitude = geometry["coordinates"][:2]
        elif geometry is not None and not geometry.is_empty:
            longitude, latitude = geometry.x, geometry.y
        else:
            raise ValueError("Monitoring location has no geographic point")
        mapping = {"station_nm": "monitoring_location_name", "drain_area_va": "drainage_area",
                   "alt_va": "altitude", "state_cd": "state_code", "county_nm": "county_name",
                   "huc_cd": "hydrologic_unit_code", "site_tp_cd": "site_type_code"}
        result = {old: row.get(new) for old, new in mapping.items()}
        result.update(site_no=site, dec_lat_va=latitude, dec_long_va=longitude)
        return pd.DataFrame([result]), {"source": "dataretrieval.waterdata"}

    @staticmethod
    def what_sites(*, sites, service="iv"):
        if service != "iv":
            raise ValueError("Only instantaneous metadata queries are supported here")
        _, location = _location(sites)
        _wait()
        frame, _ = _backend().get_time_series_metadata(monitoring_location_id=location, statistic_id="00011")
        if frame is None or frame.empty:
            return pd.DataFrame(columns=["parm_cd"])
        return frame.rename(columns={"parameter_code": "parm_cd"})
