"""
StormGenerator ARI column labels against NOAA's own labelled export.

The NOAA PFDS endpoint used by ``download_from_coordinates`` returns unlabelled
quantile arrays. NOAA's CSV export for the same point carries the column
headers. Both responses were captured on 2026-10-02 for 30.05 N, -99.14 W
(Kerrville, TX; Atlas 14 Volume 11) and are stored as fixtures, so these
tests run offline.
"""

from pathlib import Path

import pandas as pd
import pytest

from ras_commander.precip import StormGenerator

FIXTURES = Path(__file__).parent / "fixtures" / "precipitation" / "noaa_atlas14"
POINT = "30.05_-99.14_depth_english"


def _raw_dataframe(series: str) -> pd.DataFrame:
    content = (FIXTURES / f"pfds_{POINT}_{series}.txt").read_text()
    data_dict = StormGenerator._parse_noaa_response(content)
    return StormGenerator._api_data_to_dataframe(data_dict, "english")


def _labelled_csv(series: str) -> dict:
    """Return {duration_label: {ari_label: depth}} from NOAA's labelled CSV."""
    lines = (FIXTURES / f"fe_text_mean_{POINT}_{series}.csv").read_text().splitlines()
    header = next(line for line in lines if line.startswith("by duration for"))
    labels = []
    for token in header.split(":,", 1)[1].split(","):
        token = token.strip().lstrip("'")
        labels.append(token.split("/")[1] if "/" in token else token)
    rows = {}
    for line in lines:
        name, _, values = line.partition(":,")
        if name.endswith(("-min", "-hr", "-day")) and values:
            rows[name] = dict(zip(labels, (float(v) for v in values.split(","))))
    return rows


DURATION_HOURS = {"60-min": 1, "3-hr": 3, "6-hr": 6, "24-hr": 24, "2-day": 48}


@pytest.mark.parametrize("series", ["pds", "ams"])
def test_column_labels_match_noaa_headers(series):
    df = _raw_dataframe(series)
    expected = list(next(iter(_labelled_csv(series).values())).keys())
    assert [c for c in df.columns if c != "duration_hours"] == expected


@pytest.mark.parametrize("series", ["pds", "ams"])
@pytest.mark.parametrize("duration_label", sorted(DURATION_HOURS))
def test_depths_match_noaa_labelled_values(series, duration_label):
    df = _raw_dataframe(series)
    row = df[df["duration_hours"] == DURATION_HOURS[duration_label]].iloc[0]
    for ari, depth in _labelled_csv(series)[duration_label].items():
        assert row[ari] == pytest.approx(depth), (series, duration_label, ari)


def test_100_year_24_hour_depth():
    """NOAA lists 12.1 in for the 100-year (1/100 AEP) 24-hour depth here."""
    for series in ("pds", "ams"):
        df = _raw_dataframe(series)
        depth = df.loc[df["duration_hours"] == 24, "100"].iloc[0]
        assert depth == pytest.approx(12.1)
        depths, _ = StormGenerator.interpolate_depths(df, 100, 24)
        assert depths[-1] == pytest.approx(12.1)


def test_no_unpublished_return_periods():
    assert StormGenerator.STANDARD_ARI_VALUES_PDS[0] == "1"
    assert StormGenerator.STANDARD_ARI_VALUES_AMS[0] == "2"
    assert "2000" not in StormGenerator.STANDARD_ARI_VALUES_PDS
    assert "2000" not in StormGenerator.STANDARD_ARI_VALUES_AMS
