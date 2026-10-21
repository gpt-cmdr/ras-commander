"""A batch whose plans all fail is summarized per permutation, not a KeyError.

When ``RasCmdr.compute_parallel`` refuses or fails every plan,
``RasPrj.update_results_df`` can return a frame without a ``plan_number``
column. ``execute_and_summarize`` filtered on that column and raised
``KeyError: 'plan_number'`` instead of reporting the failed permutations.
"""
import pandas as pd

from ras_commander.RasPermutation import RasPermutation


def test_rows_for_plans_tolerates_a_frame_without_plan_numbers():
    assert RasPermutation._rows_for_plans(pd.DataFrame(), ["02", "05"]).empty
    assert RasPermutation._rows_for_plans(None, ["02"]).empty


def test_rows_for_plans_filters_to_requested_plans():
    frame = pd.DataFrame({"plan_number": ["01", "02", "05"], "value": [1, 2, 3]})
    rows = RasPermutation._rows_for_plans(frame, ["02", "05"])
    assert rows["plan_number"].tolist() == ["02", "05"]
