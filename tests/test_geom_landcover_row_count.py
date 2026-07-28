"""Regression tests for plain-text land-cover base-table row counts."""

from pathlib import Path

import pandas as pd
import pytest

from ras_commander.geom import GeomLandCover


def _write_geometry(path: Path, table_lines: list[str]) -> None:
    path.write_text(
        "".join(
            [
                "Geom Title=Land Cover Test\n",
                "LCMann Time=Dec/30/1899 00:00:00\n",
                "LCMann Region Time=Dec/30/1899 00:00:00\n",
                *table_lines,
                "Chan Stop Cuts=0\n",
            ]
        ),
        encoding="utf-8",
    )


def test_replace_base_table_updates_disabled_header_to_emitted_row_count(
    tmp_path,
):
    geom_path = tmp_path / "test.g01"
    _write_geometry(geom_path, ["LCMann Table=0\n"])

    GeomLandCover.replace_base_mannings_n(
        geom_path,
        pd.DataFrame(
            {
                "class_name": ["Open Water", "Developed, Open Space"],
                "mannings_n": [0.03, 0.04],
            }
        ),
        backup=False,
    )

    text = geom_path.read_text(encoding="utf-8")
    assert text.count("LCMann Table=") == 1
    assert "LCMann Table=2\n" in text
    assert "Developed, Open Space,0.04\n" in text
    assert "Chan Stop Cuts=0\n" in text

    result = GeomLandCover.get_base_mannings_n(geom_path)
    assert result["Table Number"].tolist() == ["2", "2"]
    assert result["Land Cover Name"].tolist() == [
        "Open Water",
        "Developed, Open Space",
    ]


def test_replace_base_table_recounts_after_filtering_and_size_change(tmp_path):
    geom_path = tmp_path / "test.g01"
    _write_geometry(
        geom_path,
        [
            "LCMann Table=2\n",
            "Old A,0.03\n",
            "Old B,0.04\n",
        ],
    )

    GeomLandCover.replace_base_mannings_n(
        geom_path,
        pd.DataFrame(
            {
                "Land Cover Name": ["New A", "New B", "New C", ""],
                "Base Mannings n Value": [0.05, 0.06, 0.07, float("nan")],
                "Table Number": ["2", "2", "2", "2"],
            }
        ),
        backup=False,
    )

    text = geom_path.read_text(encoding="utf-8")
    assert "LCMann Table=3\n" in text
    assert "LCMann Table=2\n" not in text
    assert text.count("LCMann Table=") == 1
    assert text.index("New C,0.07") < text.index("Chan Stop Cuts=0")


def test_replace_base_table_rejects_explicit_count_mismatch(tmp_path):
    geom_path = tmp_path / "test.g01"
    _write_geometry(geom_path, ["LCMann Table=0\n"])

    with pytest.raises(ValueError, match="must equal.*2.*got 21"):
        GeomLandCover.replace_base_mannings_n(
            geom_path,
            [
                {"class_name": "A", "mannings_n": 0.03},
                {"class_name": "B", "mannings_n": 0.04},
            ],
            table_number=21,
            backup=False,
        )

    assert "LCMann Table=0\n" in geom_path.read_text(encoding="utf-8")
