from ras_commander.hdf.HdfResultsQuery import _resolve_geometry_hdf


def test_resolve_geometry_hdf_uses_sibling_plan_text_when_prj_metadata_unavailable(
    tmp_path,
):
    plan_hdf = tmp_path / "Project.p07.hdf"
    plan_hdf.write_bytes(b"not a real hdf")
    (tmp_path / "Project.p07").write_text(
        "Plan Title=Generated\nGeom File=g09\n",
        encoding="utf-8",
    )
    geom_hdf = tmp_path / "Project.g09.hdf"
    geom_hdf.write_bytes(b"geometry")

    assert _resolve_geometry_hdf(plan_hdf) == geom_hdf
