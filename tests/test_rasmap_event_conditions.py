from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from ras_commander import RasMap


def _write_rasmap(path: Path) -> Path:
    path.write_text(
        """<RASMapper>
  <EventConditions>
    <Layer Name="Current" Type="RASEventConditions" Filename=".\\Model.u09.hdf" />
    <Layer Name="Stale" Type="RASEventConditions" Filename="%LocalAppData%\\old\\Model.u01.hdf" />
  </EventConditions>
  <Results>
    <Layer Name="Old plan" Type="RASResults" Filename=".\\Model.p01.hdf">
      <Layer Name="Event Conditions" Type="RASEventConditions" Filename=".\\Model.p01.hdf" />
    </Layer>
  </Results>
</RASMapper>
""",
        encoding="utf-8",
    )
    return path


def _event_filenames(path: Path) -> list[str]:
    root = ET.parse(path).getroot()
    return [
        layer.get("Filename") or ""
        for layer in root.iter("Layer")
        if layer.get("Type") == "RASEventConditions"
    ]


def test_prune_event_conditions_is_recursive_atomic_and_backed_up(tmp_path):
    rasmap = _write_rasmap(tmp_path / "Model.rasmap")
    current = tmp_path / "Model.u09.hdf"
    current.touch()

    evidence = RasMap.prune_event_condition_layers(
        [current],
        rasmap_path=rasmap,
    )

    assert evidence["before_count"] == 3
    assert evidence["removed_count"] == 2
    assert evidence["retained_count"] == 1
    assert evidence["readback_count"] == 1
    assert evidence["changed"] is True
    assert _event_filenames(rasmap) == [r".\Model.u09.hdf"]
    backup = tmp_path / "Model.event-conditions.bak.rasmap"
    assert backup.is_file()
    assert len(_event_filenames(backup)) == 3
    assert not (tmp_path / ".Model.rasmap.event-conditions.tmp").exists()


def test_prune_event_conditions_missing_requested_filename_is_non_mutating(tmp_path):
    rasmap = _write_rasmap(tmp_path / "Model.rasmap")
    before = rasmap.read_bytes()

    with pytest.raises(ValueError, match=r"filename\(s\) are absent"):
        RasMap.prune_event_condition_layers(
            [r".\Model.u77.hdf"],
            rasmap_path=rasmap,
        )

    assert rasmap.read_bytes() == before
    assert not (tmp_path / "Model.event-conditions.bak.rasmap").exists()


def test_prune_event_conditions_refuses_existing_backup(tmp_path):
    rasmap = _write_rasmap(tmp_path / "Model.rasmap")
    backup = tmp_path / "Model.event-conditions.bak.rasmap"
    backup.write_text("existing", encoding="utf-8")
    before = rasmap.read_bytes()

    with pytest.raises(FileExistsError, match="backup already exists"):
        RasMap.prune_event_condition_layers(
            [r".\Model.u09.hdf"],
            rasmap_path=rasmap,
        )

    assert rasmap.read_bytes() == before
    assert backup.read_text(encoding="utf-8") == "existing"
