from importlib import import_module
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest


ras_process_module = import_module("ras_commander.RasProcess")
RasProcess = ras_process_module.RasProcess


@pytest.fixture
def rasmap_project(tmp_path):
    (tmp_path / "Demo.rasmap").write_text(
        "<RASMapper><Units>English</Units></RASMapper>", encoding="utf-8"
    )
    return SimpleNamespace(
        project_folder=tmp_path,
        project_name="Demo",
        check_initialized=lambda: None,
    )


def _rasmap(project):
    root = ET.parse(project.project_folder / "Demo.rasmap").getroot()
    return {
        tag: (root.findtext(tag) or None)
        for tag in ("RenderMode", "ReduceShallowToHorizontal", "UseDepthWeightedFaces")
    }


@pytest.mark.parametrize(
    "render_mode, expected",
    [
        ("horizontal", ("horizontal", None, None)),
        ("sloping", ("sloping", None, None)),
        ("slopingPretty", ("slopingPretty", "true", None)),
        ("slopingPretty:true:true", ("slopingPretty", "true", "true")),
        ("slopingPretty:false:true", ("slopingPretty", None, "true")),
        ("SLOPINGPRETTY:TRUE:FALSE", ("slopingPretty", "true", None)),
        (
            {"mode": "slopingPretty", "use_depth_weighted_faces": True},
            ("slopingPretty", "true", "true"),
        ),
        ({"mode": "sloping"}, ("sloping", None, None)),
    ],
)
def test_store_maps_render_mode_forms_are_written_to_rasmap(
    rasmap_project, render_mode, expected
):
    RasProcess._set_rasmap_render_mode(render_mode, rasmap_project)

    assert tuple(_rasmap(rasmap_project).values()) == expected


@pytest.mark.parametrize(
    "render_mode",
    ["slopingPretty:true", "sloping:true:true", "slopingPretty:yes:no", "bogus"],
)
def test_invalid_render_mode_raises_before_rasmap_changes(rasmap_project, render_mode):
    before = (rasmap_project.project_folder / "Demo.rasmap").read_text(encoding="utf-8")

    with pytest.raises(ValueError):
        RasProcess._set_rasmap_render_mode(render_mode, rasmap_project)

    after = (rasmap_project.project_folder / "Demo.rasmap").read_text(encoding="utf-8")
    assert after == before
