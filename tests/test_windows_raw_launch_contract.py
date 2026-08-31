"""Windows regression for the raw command contract used by ``compute_plan``."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows CreateProcess contract")
def test_raw_quoted_command_preserves_spaced_paths_and_shell_metacharacter(
    tmp_path,
):
    """A direct raw command must not route ``A&B`` through a command shell."""
    working_directory = tmp_path / "spaced script directory"
    working_directory.mkdir()
    script_path = working_directory / "capture arguments.py"
    script_path.write_text(
        "import json\n"
        "import sys\n"
        "print(json.dumps(sys.argv))\n",
        encoding="utf-8",
    )
    executable = Path(sys.executable).resolve(strict=True)
    argument = "A&B"
    command = f'"{executable}" "{script_path}" "{argument}"'

    process = subprocess.Popen(
        command,
        executable=str(executable),
        shell=False,
        cwd=str(working_directory),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    stdout, stderr = process.communicate(timeout=30)

    assert process.returncode == 0, stderr
    observed_argv = json.loads(stdout)
    assert Path(observed_argv[0]).resolve(strict=True) == script_path.resolve(
        strict=True
    )
    assert observed_argv[1:] == [argument]

