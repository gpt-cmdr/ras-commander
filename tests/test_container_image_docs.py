"""Keep the public current-image table consistent with the shipped catalog."""

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_current_image_table_matches_packaged_oci_and_sif_references():
    """Readers must be able to select every published payload from the guide."""
    catalog = json.loads(
        (ROOT / "ras_commander/resources/container_images.json").read_text(encoding="utf-8")
    )
    guide = (ROOT / "docs/user-guide/container-images.md").read_text(encoding="utf-8")
    current = guide.split("## Historical Docker Hub images", 1)[0]
    rows = [line for line in current.splitlines() if line.startswith("| `")]
    documented = {}
    for row in rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        if len(cells) != 4:
            continue
        version, role = (cell.strip("`") for cell in cells[:2])
        documented[(version, role)] = tuple(re.findall(r"`([^`]+)`", " ".join(cells[2:])))

    expected = {
        (image["hec_ras_version"], image["role"]): tuple(
            value for value in (image.get("ghcr"), image.get("sif")) if value
        )
        for image in catalog["images"]
        if image.get("ghcr")
    }
    assert documented == expected
