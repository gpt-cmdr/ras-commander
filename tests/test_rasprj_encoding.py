"""Regression coverage for HEC-RAS project-file encoding fallbacks."""

from ras_commander.RasPrj import RasPrj


def test_project_entries_use_fallback_encoding_for_cp1252_project_file(tmp_path):
    project_file = tmp_path / "NewOrleansLike.prj"
    project_file.write_bytes(
        b"Proj Title=New Orleans Like\r\n"
        b"Current Plan=p01\r\n"
        b"Geom File=g02\r\n"
        b"Plot Driver Conduit Layer List Feature=Base\x95Fairmont 2\r\n"
    )

    ras_project = RasPrj()
    ras_project.project_folder = tmp_path
    ras_project.project_name = "NewOrleansLike"
    ras_project.prj_file = project_file

    geom_df = ras_project._get_prj_entries("Geom")

    assert geom_df.loc[0, "geom_number"] == "02"
    assert geom_df.loc[0, "full_path"].endswith("NewOrleansLike.g02")
