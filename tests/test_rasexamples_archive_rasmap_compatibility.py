"""Optional compatibility sweep over an installed RasExamples archive."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from ras_commander import RasExamples, RasMap


@pytest.mark.integration
def test_installed_rasexamples_archive_parses_diverse_rasmap_corpus(
    tmp_path: Path,
):
    archives = sorted(
        RasExamples._user_data_dir.glob("Example_Projects_*.zip")
    )
    if not archives:
        pytest.skip("No locally installed RasExamples archive")

    archive = archives[-1]
    failed = []
    statuses = []
    feature_counts = {
        "modern_landcover": 0,
        "terrain": 0,
        "basemap": 0,
        "results": 0,
    }

    with zipfile.ZipFile(archive) as source:
        members = sorted(
            name for name in source.namelist() if name.lower().endswith(".rasmap")
        )
        if not members:
            pytest.skip(f"No .rasmap members in {archive.name}")

        for index, member in enumerate(members):
            contents = source.read(member)
            feature_counts["modern_landcover"] += b'Type="LandCoverLayer"' in contents
            feature_counts["terrain"] += b'Type="TerrainLayer"' in contents
            feature_counts["basemap"] += b'Type="WMSLayer"' in contents
            feature_counts["results"] += b"<Results" in contents

            rasmap_path = tmp_path / str(index) / Path(member).name
            rasmap_path.parent.mkdir()
            rasmap_path.write_bytes(contents)
            rasmap_df = RasMap.parse_rasmap(rasmap_path)
            status = rasmap_df.at[0, "rasmap_status"]
            statuses.append(status)
            if status == "failed":
                failed.append((member, rasmap_df.at[0, "rasmap_error"]))

    assert len(members) >= 20
    assert failed == []
    assert set(statuses) <= {"parsed", "parsed_with_errors"}
    assert all(count > 0 for count in feature_counts.values())
