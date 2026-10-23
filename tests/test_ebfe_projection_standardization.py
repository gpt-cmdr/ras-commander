from pathlib import Path

from ras_commander.sources.federal.ebfe_models import RasEbfeModels


def _project(tmp_path: Path, projection_value: str) -> Path:
    project = tmp_path / "ExampleModel"
    project.mkdir()
    (project / "Example Model.prj").write_text(
        "Proj Title=Example Model\nPlan File=p01\n", encoding="utf-8"
    )
    (project / "Example Model.rasmap").write_text(
        '<RASMapper>\n'
        f'  <RASProjectionFilename Filename="{projection_value}" />\n'
        '</RASMapper>\n',
        encoding="utf-8",
    )
    return project


def test_empty_projection_reference_does_not_copy_project_directory(tmp_path):
    project = _project(tmp_path, "")

    result = RasEbfeModels._standardize_projection(project)

    assert result == {
        "projection_files_created": 0,
        "rasmap_projection_updates": 0,
    }
    assert not (project / "Projection").exists()


def test_directory_projection_reference_is_ignored(tmp_path):
    project = _project(tmp_path, "Projection")
    (project / "Projection").mkdir()

    result = RasEbfeModels._standardize_projection(project)

    assert result == {
        "projection_files_created": 0,
        "rasmap_projection_updates": 0,
    }
    assert not list((project / "Projection").iterdir())


def test_regular_projection_file_still_copies_and_repoints(tmp_path):
    project = _project(tmp_path, "source_projection.prj")
    source = project / "source_projection.prj"
    source.write_text('PROJCS["synthetic"]\n', encoding="utf-8")

    result = RasEbfeModels._standardize_projection(project)

    assert result == {
        "projection_files_created": 1,
        "rasmap_projection_updates": 1,
    }
    copied = project / "Projection" / "source_projection.prj"
    assert copied.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert r'Filename=".\Projection\source_projection.prj"' in (
        project / "Example Model.rasmap"
    ).read_text(encoding="utf-8")
