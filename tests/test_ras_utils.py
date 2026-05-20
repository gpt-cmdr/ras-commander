from pathlib import Path

import pytest

from ras_commander import RasCmdr, RasUtils


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (1, "01"),
        ("1", "01"),
        ("01", "01"),
        ("001", "01"),
        ("p01", "01"),
        ("P01", "01"),
        (".p01", "01"),
        ("g02", "02"),
        ("project.p03", "03"),
        (Path("project.p04"), "04"),
    ],
)
def test_normalize_ras_number_accepts_prefixed_and_path_forms(raw, expected):
    assert RasUtils.normalize_ras_number(raw) == expected


@pytest.mark.parametrize("raw", ["p00", "p100", "plan01", "foo", "p"])
def test_normalize_ras_number_rejects_invalid_prefixed_forms(raw):
    with pytest.raises(ValueError):
        RasUtils.normalize_ras_number(raw)


def test_compute_hdf_path_uses_normalized_plan_number(tmp_path):
    ras_obj = type(
        "FakeRas",
        (),
        {"project_folder": tmp_path, "project_name": "Demo"},
    )()

    assert RasCmdr._get_hdf_path("p01", ras_obj) == tmp_path / "Demo.p01.hdf"
