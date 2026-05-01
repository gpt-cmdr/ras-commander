"""
Tests for RasUnsteady.update_restart_settings().

Verifies:
1. Enabling restart replaces an existing Restart Filename= line (no duplicates)
2. Enabling restart inserts exactly one Restart Filename= when none exists
3. Disabling restart removes an existing Restart Filename= line
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock


SAMPLE_UNSTEADY = """\
Flow Title=Test Flow
Use Restart=-1
Restart Filename=old_restart.rst
Boundary Location=
"""

SAMPLE_UNSTEADY_NO_RESTART_FILENAME = """\
Flow Title=Test Flow
Use Restart=0
Boundary Location=
"""


@pytest.fixture
def ras_object():
    obj = MagicMock()
    obj.check_initialized = MagicMock()
    obj.get_unsteady_entries = MagicMock(return_value=None)
    return obj


@pytest.fixture
def unsteady_file_with_restart(tmp_path):
    p = tmp_path / "test.u01"
    p.write_text(SAMPLE_UNSTEADY)
    return p


@pytest.fixture
def unsteady_file_without_restart(tmp_path):
    p = tmp_path / "test.u01"
    p.write_text(SAMPLE_UNSTEADY_NO_RESTART_FILENAME)
    return p


class TestUpdateRestartSettings:

    def test_replace_existing_restart_filename(self, unsteady_file_with_restart, ras_object):
        """Enabling restart when a Restart Filename= line already exists should replace it, not duplicate."""
        from ras_commander.RasUnsteady import RasUnsteady

        RasUnsteady.update_restart_settings(
            str(unsteady_file_with_restart),
            use_restart=True,
            restart_filename="new_restart.rst",
            ras_object=ras_object,
        )

        content = unsteady_file_with_restart.read_text()
        lines = content.splitlines()

        restart_filename_lines = [l for l in lines if l.startswith("Restart Filename=")]
        assert len(restart_filename_lines) == 1, f"Expected 1 Restart Filename line, got {len(restart_filename_lines)}: {restart_filename_lines}"
        assert restart_filename_lines[0] == "Restart Filename=new_restart.rst"

        use_restart_lines = [l for l in lines if l.startswith("Use Restart=")]
        assert len(use_restart_lines) == 1
        assert use_restart_lines[0] == "Use Restart=-1"

    def test_insert_restart_filename_when_none_exists(self, unsteady_file_without_restart, ras_object):
        """Enabling restart when no Restart Filename= line exists should insert exactly one."""
        from ras_commander.RasUnsteady import RasUnsteady

        RasUnsteady.update_restart_settings(
            str(unsteady_file_without_restart),
            use_restart=True,
            restart_filename="brand_new.rst",
            ras_object=ras_object,
        )

        content = unsteady_file_without_restart.read_text()
        lines = content.splitlines()

        restart_filename_lines = [l for l in lines if l.startswith("Restart Filename=")]
        assert len(restart_filename_lines) == 1
        assert restart_filename_lines[0] == "Restart Filename=brand_new.rst"

    def test_disable_restart_removes_filename(self, unsteady_file_with_restart, ras_object):
        """Disabling restart should remove any existing Restart Filename= line."""
        from ras_commander.RasUnsteady import RasUnsteady

        RasUnsteady.update_restart_settings(
            str(unsteady_file_with_restart),
            use_restart=False,
            ras_object=ras_object,
        )

        content = unsteady_file_with_restart.read_text()
        lines = content.splitlines()

        restart_filename_lines = [l for l in lines if l.startswith("Restart Filename=")]
        assert len(restart_filename_lines) == 0, f"Expected 0 Restart Filename lines after disabling, got: {restart_filename_lines}"

        use_restart_lines = [l for l in lines if l.startswith("Use Restart=")]
        assert use_restart_lines[0] == "Use Restart=0"
