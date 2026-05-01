"""Tests for restart usage settings in unsteady flow files."""

from ras_commander import RasUnsteady


class _DummyRas:
    def check_initialized(self):
        return None


def _write_unsteady_file(tmp_path, lines):
    unsteady_file = tmp_path / "model.u01"
    unsteady_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return unsteady_file


def _read_lines(unsteady_file):
    return unsteady_file.read_text(encoding="utf-8").splitlines()


def _restart_filename_lines(unsteady_file):
    return [
        line for line in _read_lines(unsteady_file)
        if line.startswith("Restart Filename=")
    ]


def test_set_restart_settings_replaces_existing_restart_filename(tmp_path):
    unsteady_file = _write_unsteady_file(
        tmp_path,
        [
            "Flow Title=Test Flow",
            "Program Version=6.60",
            "Use Restart=0",
            "Restart Filename=old_restart.rst",
            "Boundary Location=TestBoundary",
        ],
    )

    RasUnsteady.set_restart_settings(
        unsteady_file,
        use_restart=True,
        restart_filename="new_restart.rst",
        ras_object=_DummyRas(),
    )

    lines = _read_lines(unsteady_file)
    assert "Use Restart=-1" in lines
    assert _restart_filename_lines(unsteady_file) == [
        "Restart Filename=new_restart.rst"
    ]

    settings = RasUnsteady.get_restart_settings(
        unsteady_file,
        ras_object=_DummyRas(),
    )
    assert settings["use_restart"] is True
    assert settings["restart_filename"] == "new_restart.rst"


def test_set_restart_settings_inserts_one_restart_filename_when_missing(tmp_path):
    unsteady_file = _write_unsteady_file(
        tmp_path,
        [
            "Flow Title=Test Flow",
            "Program Version=6.60",
            "Use Restart=0",
            "Boundary Location=TestBoundary",
        ],
    )

    RasUnsteady.update_restart_settings(
        unsteady_file,
        use_restart=True,
        restart_filename="new_restart.rst",
        ras_object=_DummyRas(),
    )

    lines = _read_lines(unsteady_file)
    assert lines[lines.index("Use Restart=-1") + 1] == (
        "Restart Filename=new_restart.rst"
    )
    assert _restart_filename_lines(unsteady_file) == [
        "Restart Filename=new_restart.rst"
    ]


def test_set_restart_settings_disable_removes_restart_filenames(tmp_path):
    unsteady_file = _write_unsteady_file(
        tmp_path,
        [
            "Flow Title=Test Flow",
            "Program Version=6.60",
            "Use Restart=-1",
            "Restart Filename=old_restart.rst",
            "Restart Filename=duplicate_restart.rst",
            "Boundary Location=TestBoundary",
        ],
    )

    RasUnsteady.set_restart_settings(
        unsteady_file,
        use_restart=False,
        ras_object=_DummyRas(),
    )

    lines = _read_lines(unsteady_file)
    assert "Use Restart=0" in lines
    assert _restart_filename_lines(unsteady_file) == []

    settings = RasUnsteady.get_restart_settings(
        unsteady_file,
        ras_object=_DummyRas(),
    )
    assert settings["use_restart"] is False
    assert settings["restart_filename"] is None


def test_set_restart_settings_inserts_use_restart_when_missing(tmp_path):
    unsteady_file = _write_unsteady_file(
        tmp_path,
        [
            "Flow Title=Test Flow",
            "Program Version=6.60",
            "Boundary Location=TestBoundary",
        ],
    )

    RasUnsteady.set_restart_settings(
        unsteady_file,
        use_restart=True,
        restart_filename="new_restart.rst",
        ras_object=_DummyRas(),
    )

    lines = _read_lines(unsteady_file)
    assert lines[lines.index("Program Version=6.60") + 1] == "Use Restart=-1"
    assert lines[lines.index("Use Restart=-1") + 1] == (
        "Restart Filename=new_restart.rst"
    )
