"""No undefined names in the package (pyflakes), including in annotations."""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ras_commander.RasUnsteady import RasUnsteady

PACKAGE = Path(__file__).resolve().parents[1] / "ras_commander"


def test_package_has_no_undefined_names():
    pyflakes_api = pytest.importorskip("pyflakes.api")
    from pyflakes import messages, reporter

    class Collect(reporter.Reporter):
        def __init__(self):
            super().__init__(sys.stdout, sys.stderr)
            self.found = []

        def flake(self, message):
            if isinstance(message, (messages.UndefinedName, messages.UndefinedLocal)):
                self.found.append(f"{Path(message.filename).relative_to(PACKAGE)}:{message.lineno} {message.message_args[0]}")

    collector = Collect()
    for path in sorted(PACKAGE.rglob("*.py")):
        if ".claude" not in path.parts:
            pyflakes_api.check(path.read_text(encoding="utf-8"), str(path), collector)
    assert collector.found == []


def test_boundary_tables_are_kept_per_boundary(tmp_path):
    # Tables are saved when the next table, the next boundary or the file ends.
    unsteady = tmp_path / "probe.u01"
    unsteady.write_text(
        "Flow Title=probe\n"
        "Boundary Location=River,Reach,100,,,,,,\n"
        "Flow Hydrograph= 3\n     1.0     2.0     3.0\n"
        "Boundary Location=River,Reach,50,,,,,,\n"
        "Stage Hydrograph= 2\n     4.0     5.0\n"
        "Boundary Location=River,Reach,10,,,,,,\n"
        "Flow Hydrograph= 2\n     6.0     7.0\n"
        "Gate Openings= 2\n     8.0     9.0\n",
        encoding="utf-8",
    )
    frame = RasUnsteady.extract_boundary_and_tables(
        unsteady, ras_object=SimpleNamespace(check_initialized=lambda: None)
    )
    tables = {
        station: {name: table["Value"].tolist() for name, table in tables.items()}
        for station, tables in zip(frame["River Station"], frame["Tables"])
    }
    assert tables == {
        "100": {"Flow Hydrograph": [1.0, 2.0, 3.0]},
        "50": {"Stage Hydrograph": [4.0, 5.0]},
        "10": {"Flow Hydrograph": [6.0, 7.0], "Gate Openings": [8.0, 9.0]},
    }
