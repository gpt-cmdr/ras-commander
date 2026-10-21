"""Independent delivered rainfall is comparison evidence, not presumed canonical truth."""
import json
from pathlib import Path

import numpy as np
import pytest

from ras_commander.precip import FrequencyStormDdf

REFERENCE = json.loads((Path(__file__).parent / 'data/hms410_frequency_storm.json').read_text())
DURATIONS = REFERENCE['durations_minutes']
DEPTHS = REFERENCE['events']['01']['depths_inches']


@pytest.mark.parametrize('event', REFERENCE['events'])
def test_all_delivered_intervals_and_control_window(event):
    source = REFERENCE['events'][event]
    actual = FrequencyStormDdf.generate_hyetograph(
        source['depths_inches'], DURATIONS, simulation_duration_hours=240)
    values = actual.incremental_depth.to_numpy()
    expected = np.asarray(source['expected_incremental_inches'])
    assert len(actual) == 2881
    assert values[0] == 0 and actual.hour.iloc[0] == 0
    np.testing.assert_allclose(values[1:289], expected, rtol=0, atol=1e-12)
    np.testing.assert_allclose(actual.cumulative_depth.iloc[1:289], np.cumsum(expected), rtol=0, atol=2e-12)
    assert np.all(values[289:] == 0)
    assert actual.hour.iloc[-1] == 240
    assert values[1:].argmax() == 144
    assert actual.hour.iloc[values.argmax()] == pytest.approx(12 + 5/60)
    assert values.sum() == pytest.approx(source['depths_inches'][-1], abs=1e-12)
    assert actual.attrs['units'] == 'inches'


def test_default_window_and_depth_information_used():
    first = FrequencyStormDdf.generate_hyetograph(DEPTHS, DURATIONS)
    changed = list(DEPTHS)
    changed[0] = 1.2
    second = FrequencyStormDdf.generate_hyetograph(changed, DURATIONS)
    assert len(first) == 289 and first.hour.iloc[-1] == 24
    assert not np.allclose(first.incremental_depth, second.incremental_depth)
    assert first.incremental_depth.sum() == pytest.approx(second.incremental_depth.sum())


def test_public_dataframe_schema_matches_output():
    from ras_commander.schemas import DATAFRAME_SCHEMAS
    actual = FrequencyStormDdf.generate_hyetograph(DEPTHS, DURATIONS)
    columns = DATAFRAME_SCHEMAS['frequency_storm_ddf']['columns']
    assert list(actual.columns) == [column['name'] for column in columns]
    assert [str(dtype) for dtype in actual.dtypes] == [column['dtype'] for column in columns]


@pytest.mark.parametrize('depths', [DEPTHS[:-1], [0]*8, [-1]*8, [np.nan]*8,
    [np.inf]*8, [1.3, 1.2, 5.02, 7.17, 8.74, 11.4, 13.9, 16.4]])
def test_invalid_depths(depths):
    with pytest.raises(ValueError, match='depths_inches'):
        FrequencyStormDdf.generate_hyetograph(depths, DURATIONS)


@pytest.mark.parametrize('durations', [[5,15,30,60,120,180,360,1440],
    DURATIONS[:-1], DURATIONS[::-1], [np.nan]*8])
def test_duration_labels_are_not_inferred(durations):
    with pytest.raises(ValueError, match='durations_minutes'):
        FrequencyStormDdf.generate_hyetograph(DEPTHS, durations)


@pytest.mark.parametrize('hours', [0, 23, 24.01, np.nan, np.inf])
def test_invalid_control_window(hours):
    with pytest.raises(ValueError, match='simulation_duration_hours'):
        FrequencyStormDdf.generate_hyetograph(DEPTHS, DURATIONS, simulation_duration_hours=hours)
