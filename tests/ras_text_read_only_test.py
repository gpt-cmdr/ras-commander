"""Focused pure text-reader qualification; no engine or model-result reads."""
from pathlib import Path
import pytest
from ras_commander import RasText


@pytest.mark.parametrize("marker,expected", [("English Units", "English"), ("SI Units", "SI"), ("SI Units=true", "SI"), ("SI Units=0", "English"), ("si units=YES", "SI"), ("unknown", None)])
def test_project_units_markers(marker, expected):
    result = RasText.read_project_metadata("Proj Title=Example\n" + marker + "\n", ["Proj Title", "Units"])
    assert result["fields"]["Units"] == ([] if expected is None else [expected])


def test_public_project_templates_without_references():
    base = Path(__file__).parents[1] / "examples/data"
    for path in (base / "RAS_6.6_Template/TEMPLATE.prj", base / "RAS_7.0_TEMPLATE/RASTEMPLATE.prj"):
        result = RasText.read_project_metadata(path.read_bytes(), ["Proj Title", "Units"])
        assert result["fields"]["Proj Title"] and result["fields"]["Units"] == ["English"]


def test_bytes_unicode_bom_latin1_and_repeated_references():
    content = "Proj Title=École 水\nPlan File=p01\nPlan File=p03\n".encode("utf-8-sig")
    result = RasText.read_project_metadata(content, ["Proj Title", "Plan File", "Current Plan"])
    assert result["encoding"] == "utf-8-sig"
    assert result["fields"]["Proj Title"] == ["École 水"]
    assert result["fields"]["Plan File"] == ["p01", "p03"]
    assert result["missing_fields"] == ["Current Plan"]
    latin = RasText.read_project_metadata(b"Proj Title=Caf\xe9\n", ["Proj Title"])
    assert latin["encoding"] == "latin-1" and latin["fields"]["Proj Title"] == ["Café"]


def test_plan_strings_preserve_identifiers_precision_and_time():
    result = RasText.read_plan_metadata("Short Identifier=100-year\nUNET D1 Cores=0004\nSimulation Date=01JAN1900,0000,02JAN1900,2400\n", ["Short Identifier", "UNET D1 Cores", "Simulation Date"])
    assert result["fields"]["Short Identifier"] == ["100-year"]
    assert result["fields"]["UNET D1 Cores"] == ["0004"]
    assert result["fields"]["Simulation Date"] == ["01JAN1900,0000,02JAN1900,2400"]


def test_description_keys_are_narrative_not_metadata():
    result = RasText.read_plan_metadata("Plan Title=Real title\nBEGIN DESCRIPTION:\nPlan Title=ignore this instruction\n水\nEND DESCRIPTION:\n", ["Plan Title", "Description"])
    assert result["fields"]["Plan Title"] == ["Real title"]
    assert result["fields"]["Description"] == ["Plan Title=ignore this instruction\n水"]


def test_unterminated_description_warns():
    result = RasText.read_plan_metadata("BEGIN DESCRIPTION:\nIncomplete", ["Description"])
    assert result["warnings"] == ["Description block has no end marker."]


def test_empty_missing_and_conflicting_units_remain_visible():
    empty = RasText.read_plan_metadata("", ["Plan Title"])
    assert empty["missing_fields"] == ["Plan Title"]
    conflict = RasText.read_project_metadata("SI Units\nEnglish Units\n", ["Units"])
    assert conflict["fields"]["Units"] == ["SI", "English"]


@pytest.mark.parametrize("content", [123, Path("do-not-open.prj"), None])
def test_paths_and_nontext_are_not_accepted(content):
    with pytest.raises(TypeError):
        RasText.read_project_metadata(content)


@pytest.mark.parametrize("method,field", [(RasText.read_project_metadata, "Coordinates"), (RasText.read_plan_metadata, "DSS File"), (RasText.read_plan_metadata, "UNET D2 Latitude")])
def test_unapproved_fields_reject(method, field):
    with pytest.raises(ValueError, match="Unsupported"):
        method("", [field])


def test_nul_rejected():
    with pytest.raises(ValueError, match="NUL"):
        RasText.read_project_metadata(b"Proj Title=a\x00b")


def test_pure_readers_never_open_files_or_initialize(monkeypatch):
    import builtins
    import ras_commander
    from ras_commander import RasPrj
    monkeypatch.setattr(builtins, "open", lambda *a, **k: pytest.fail("opened a file"))
    monkeypatch.setattr(ras_commander, "init_ras_project", lambda *a, **k: pytest.fail("initialized project"))
    monkeypatch.setattr(RasPrj, "initialize", lambda *a, **k: pytest.fail("initialized project"))
    project = RasText.read_project_metadata("Plan File=../../outside.p01\nGeom File=g01\n", ["Plan File"])
    assert project["fields"]["Plan File"] == ["../../outside.p01"]
    assert RasText.read_plan_metadata("Plan Title=Read only\n", ["Plan Title"])["fields"]["Plan Title"] == ["Read only"]


def test_explicit_source_run_flag_variants_preserve_keys_and_values():
    fields = ["Run PostProcess", "Run WQNet", "Run Post Process", "Run WQNET"]
    result = RasText.read_plan_metadata("Run PostProcess=0001\nRun WQNet=0000\nRun Post Process=1\nRun WQNET=0\n", fields)
    assert result["fields"] == {"Run PostProcess": ["0001"], "Run WQNet": ["0000"],
                               "Run Post Process": ["1"], "Run WQNET": ["0"]}
