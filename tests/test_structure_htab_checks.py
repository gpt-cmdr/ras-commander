"""
Regression tests for structure HTAB QA coverage.

These tests use real HEC-RAS example projects and verify that the structure
HTAB checker:
- evaluates bridge/culvert HTAB settings instead of silently returning zero
- includes inline weirs in the structure HTAB review surface
"""

import re
import sys
from pathlib import Path


# Ensure we're using local source, not installed package
repo_root = Path(__file__).parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))


from ras_commander import RasExamples
from ras_commander.check import CheckNt
from ras_commander.geom import GeomBridge, GeomInlineWeir


def _get_geom_file(project_path: Path) -> Path:
    """Return the first plain-text geometry file in an extracted project."""
    geom_files = sorted(
        path for path in project_path.iterdir()
        if path.is_file() and re.search(r"\.g\d\d$", path.name.lower())
    )
    assert geom_files, f"No geometry files found in {project_path}"
    return geom_files[0]


def _insert_inline_weir_htab_lines(
    geom_file: Path,
    hw_max: float = 20.0,
    tw_max: float = 15.0,
    max_flow: float = 1000.0,
    free_flow_points: int = 10,
    submerged_curves: int = 12,
    points_per_curve: int = 14,
) -> None:
    """Insert explicit HTAB lines into the first inline weir block."""
    lines = geom_file.read_text(encoding='utf-8', errors='replace').splitlines(True)

    insert_idx = None
    for idx, line in enumerate(lines):
        if line.startswith("IW Pilot Flow="):
            insert_idx = idx + 1
            break

    assert insert_idx is not None, f"No inline weir block found in {geom_file}"

    htab_lines = [
        f"BC HTab HWMax=  {hw_max:.1f}\n",
        f"BC HTab TWMax=  {tw_max:.1f}\n",
        f"BC HTab MaxFlow= {max_flow:.1f}\n",
        "BC Use User HTab Curves= -1\n",
        f"BC User HTab FreeFlow(D)= {free_flow_points}\n",
        f"BC User HTab Sub Curve(D)= {submerged_curves}\n",
        f"BC User HTab Pts/SubCrv(D)= {points_per_curve}\n",
    ]

    lines[insert_idx:insert_idx] = htab_lines
    geom_file.write_text("".join(lines), encoding='utf-8')


def test_bridge_structure_htab_check_reports_suboptimal_free_flow_points():
    """Bridge HTAB QA should flag the real bridge example's free-flow setting."""
    project_path = RasExamples.extract_project(
        "Bridge Hydraulics",
        suffix="test_structure_htab_bridge",
    )
    geom_file = _get_geom_file(project_path)

    results = CheckNt.check_structure_htab_params(geom_file)

    assert results.messages, "Expected bridge HTAB QA messages, found none"
    assert any(msg.message_id == "HTAB_STR_FF_01" for msg in results.messages)
    assert any(msg.structure == "Beaver Creek/Kentwood/RS 5.4" for msg in results.messages)


def test_geombridge_get_htab_dict_reads_inline_weir_htab_lines():
    """GeomBridge HTAB reader should support inline weirs as well as bridges."""
    project_path = RasExamples.extract_project(
        "Example 12 - Inline Structure",
        suffix="test_structure_htab_weir_reader",
    )
    geom_file = _get_geom_file(project_path)
    weirs_df = GeomInlineWeir.get_weirs(geom_file)

    assert not weirs_df.empty, "Expected at least one inline weir in the example project"

    row = weirs_df.iloc[0]
    _insert_inline_weir_htab_lines(geom_file)

    htab = GeomBridge.get_htab_dict(
        geom_file,
        row['River'],
        row['Reach'],
        str(row['RS']),
        include_invert=False,
    )

    assert htab['has_htab_lines'] is True
    assert htab['hw_max'] == 20.0
    assert htab['tw_max'] == 15.0
    assert htab['max_flow'] == 1000.0
    assert htab['free_flow_points'] == 10
    assert htab['submerged_curves'] == 12
    assert htab['points_per_curve'] == 14


def test_inline_weir_structure_htab_check_reports_suboptimal_curve_counts():
    """Structure HTAB QA should include inline weirs once HTAB lines are present."""
    project_path = RasExamples.extract_project(
        "Example 12 - Inline Structure",
        suffix="test_structure_htab_weir_check",
    )
    geom_file = _get_geom_file(project_path)
    weirs_df = GeomInlineWeir.get_weirs(geom_file)

    assert not weirs_df.empty, "Expected at least one inline weir in the example project"

    row = weirs_df.iloc[0]
    _insert_inline_weir_htab_lines(geom_file)

    results = CheckNt.check_structure_htab_params(geom_file)
    weir_messages = [
        msg for msg in results.messages
        if msg.structure == f"{row['River']}/{row['Reach']}/RS {row['RS']}"
    ]

    assert weir_messages, "Expected inline weir HTAB QA messages, found none"
    assert {msg.message_id for msg in weir_messages} == {
        "HTAB_STR_FF_01",
        "HTAB_STR_RC_01",
        "HTAB_STR_PRC_01",
    }
