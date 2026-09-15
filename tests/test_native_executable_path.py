"""Explicit native paths must not fall through to Windows version discovery."""
from pathlib import Path

import pytest

from ras_commander import get_ras_exe


@pytest.mark.parametrize('name', ['RasUnsteady', 'rasUnsteady', 'rasUnsteady64', 'Ras.exe'])
def test_explicit_engine_file_is_resolved_without_version_discovery(tmp_path, name):
    engine = tmp_path / 'HEC RAS' / name
    engine.parent.mkdir()
    engine.write_bytes(b'path resolution fixture')
    assert Path(get_ras_exe(engine)) == engine
