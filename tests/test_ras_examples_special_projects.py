import pandas as pd

from ras_commander import RasExamples


def test_klawitter_registered_as_special_project():
    url = RasExamples.SPECIAL_PROJECTS["Klawitter"]

    assert "Klawitter_2D_Tutorial.zip" in url
    assert url.startswith("https://www.hec.usace.army.mil/confluence/")


def test_list_projects_includes_klawitter_special_project(monkeypatch):
    project_df = pd.DataFrame(
        [
            {
                "Category": "Sample",
                "Project": "Muncie",
            }
        ]
    )
    monkeypatch.setattr(RasExamples, "_folder_df", project_df)

    projects = RasExamples.list_projects()

    assert "Klawitter" in projects
