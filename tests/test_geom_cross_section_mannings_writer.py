import pandas as pd
import pytest

from ras_commander.geom.GeomCrossSection import GeomCrossSection
from ras_commander.geom.GeomParser import GeomParser

SAMPLE_GEOMETRY = "\n".join(
    [
        "Geom Title=Sample",
        "River Reach=Test River,Test Reach",
        "Type RM Length L Ch R = 1,100,0,0,0",
        "#Sta/Elev= 2",
        "    0.00   10.00  100.00   10.00",
        "#Mann= 3 ,0 ,0",
        "    0.00    0.06    0.00   30.00    0.04    0.00   70.00    0.06    0.00",
        "Bank Sta=30,70",
        "Exp/Cntr=0.1,0.3",
        "Type RM Length L Ch R = 1,90,0,0,0",
        "#Sta/Elev= 2",
        "    0.00   10.00  100.00   10.00",
        "#Mann= 3 ,0 ,0",
        "    0.00    0.06    0.00   30.00    0.04    0.00   70.00    0.06    0.00",
        "Bank Sta=30,70",
        "Exp/Cntr=0.1,0.3",
        "",
    ]
)


def test_set_mannings_n_inserts_extra_lines_without_overwriting_following_records(tmp_path):
    geom_path = tmp_path / "sample.g01"
    geom_path.write_text(SAMPLE_GEOMETRY, encoding="utf-8")

    updated = pd.DataFrame(
        {
            "Station": [float(i) for i in range(20)],
            "n_value": [0.04 if i % 2 else 0.08 for i in range(20)],
        }
    )

    GeomCrossSection.set_mannings_n(
        geom_path,
        "Test River",
        "Test Reach",
        "100",
        updated,
        format_flag=-1,
        change_flag=0,
    )

    lines = geom_path.read_text(encoding="utf-8").splitlines()
    mann_line = lines.index("#Mann= 20 ,-1 ,0 ")
    expected_data_lines = len(
        GeomParser.format_fixed_width(
            [0.0] * 20 * 3,
            values_per_line=GeomCrossSection.MANNINGS_VALUES_PER_LINE,
        )
    )

    assert lines[mann_line + 1 + expected_data_lines] == "Bank Sta=30,70"
    assert len(lines[mann_line + 1]) == 72
    assert "Type RM Length L Ch R = 1,90,0,0,0" in lines
    assert "Exp/Cntr=0.1,0.3" in lines

    roundtrip = GeomCrossSection.get_mannings_n(
        geom_path,
        "Test River",
        "Test Reach",
        "100",
    )
    assert len(roundtrip) == 20


def test_set_mannings_n_rejects_over_20_blocks(tmp_path):
    geom_path = tmp_path / "sample.g01"
    geom_path.write_text(SAMPLE_GEOMETRY, encoding="utf-8")

    too_many = pd.DataFrame(
        {
            "Station": [float(i) for i in range(21)],
            "n_value": [0.04] * 21,
        }
    )

    with pytest.raises(ValueError, match="exceeds HEC-RAS limit"):
        GeomCrossSection.set_mannings_n(
            geom_path,
            "Test River",
            "Test Reach",
            "100",
            too_many,
        )
