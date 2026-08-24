import logging
from pathlib import Path

import pytest

from ras_commander.RasBreach import RasBreach


BREACH_LOGGER = "ras_commander.RasBreach"


def _breach_records(caplog):
    return [record for record in caplog.records if record.name == BREACH_LOGGER]


def _write_plan_with_breach(tmp_path: Path) -> Path:
    plan_path = tmp_path / "BreachProject.p01"
    plan_lines = [
        "Plan Title=Breach Logging Test",
        "Breach Loc=           River,           Reach,  1000.0,True,Dam             ",
        "Breach Method= 0",
        "Breach Geom=5700,200,595,0.5,0.5,True,0.5,630,1,2.6",
        "Breach Start= 0,",
        "Breach Progression= 0",
        "Breach Calculator Data= 0,0,0,0,0,0,0",
        "",
        "Simulation Date=01JAN2000,0000,02JAN2000,0000",
    ]
    plan_path.write_text("\r\n".join(plan_lines) + "\r\n", encoding="utf-8", newline="")
    return plan_path


def test_list_breach_structures_is_quiet_at_info_and_detailed_at_debug(tmp_path, caplog):
    plan_path = _write_plan_with_breach(tmp_path)
    caplog.set_level(logging.INFO, logger=BREACH_LOGGER)

    structures = RasBreach.list_breach_structures_plan(plan_path)

    assert [item["structure"] for item in structures] == ["Dam"]
    assert _breach_records(caplog) == []

    caplog.clear()
    caplog.set_level(logging.DEBUG, logger=BREACH_LOGGER)

    structures = RasBreach.list_breach_structures_plan(plan_path)

    assert len(structures) == 1
    messages = [record.getMessage() for record in _breach_records(caplog)]
    assert any("Found 1 breach structures in BreachProject.p01" in message for message in messages)


def test_list_breach_structures_accepts_legacy_four_field_1d_location(tmp_path):
    plan_path = tmp_path / "LegacyBreach.p03"
    plan_path.write_text(
        "Plan Title=Legacy Breach\r\n"
        "Breach Loc=Bald Eagle Cr.  ,Lock Haven      ,81454   ,True\r\n"
        "Breach Method= 0\r\n",
        encoding="utf-8",
        newline="",
    )

    structures = RasBreach.list_breach_structures_plan(plan_path)

    assert structures == [
        {
            "structure": "",
            "river": "Bald Eagle Cr.",
            "reach": "Lock Haven",
            "station": "81454",
            "is_active": True,
        }
    ]


def test_list_breach_structures_uses_project_encoding_fallback(tmp_path):
    plan_path = tmp_path / "EncodedBreach.p01"
    plan_path.write_bytes(
        (
            "Plan Title=Encoded Breach\r\n"
            "Breach Loc=Río,Reach,1000,True,Dam\r\n"
            "Breach Method= 0\r\n"
        ).encode("cp1252")
    )

    [breach] = RasBreach.list_breach_structures_plan(plan_path)

    assert breach["river"] == "Río"
    assert breach["structure"] == "Dam"


@pytest.mark.parametrize("activation", ["enabled", "maybe", "-1", "2", ""])
def test_list_breach_structures_rejects_unknown_activation_tokens(
    tmp_path,
    activation,
):
    plan_path = tmp_path / "UnknownActivation.p01"
    plan_path.write_text(
        "Plan Title=Unknown Activation\r\n"
        f"Breach Loc=River,Reach,1000,{activation},Dam\r\n"
        "Breach Method= 0\r\n",
        encoding="utf-8",
        newline="",
    )

    with pytest.raises(ValueError, match="Unexpected Breach Loc activation token"):
        RasBreach.list_breach_structures_plan(plan_path)


@pytest.mark.parametrize(
    ("activation", "expected"),
    [
        ("True", True),
        ("true", True),
        ("1", True),
        ("yes", True),
        ("False", False),
        ("false", False),
        ("0", False),
        ("no", False),
    ],
)
def test_list_breach_structures_parses_explicit_compatibility_tokens(
    tmp_path,
    activation,
    expected,
):
    plan_path = tmp_path / f"Activation-{activation}.p01"
    plan_path.write_text(
        "Plan Title=Activation\r\n"
        f"Breach Loc=River,Reach,1000,{activation},Dam, North\r\n"
        "Breach Method= 0\r\n",
        encoding="utf-8",
        newline="",
    )

    [breach] = RasBreach.list_breach_structures_plan(plan_path)

    assert breach["is_active"] is expected
    assert breach["structure"] == "Dam, North"


def test_set_breach_geom_logs_concise_info_and_debug_details(tmp_path, caplog):
    plan_path = _write_plan_with_breach(tmp_path)
    caplog.set_level(logging.DEBUG, logger=BREACH_LOGGER)

    updated = RasBreach.set_breach_geom(
        plan_path,
        "Dam",
        final_bottom_width=300,
        formation_time=1.5,
    )

    assert updated["values"]["Breach Geom"] == "5700,300,595,0.5,0.5,True,0.5,630,1.5,2.6"
    records = _breach_records(caplog)
    info_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.DEBUG
    ]

    assert info_messages == ["Updating breach geometry for 'Dam' (2 field changes)"]
    assert any("final_bottom_width: 200 -> 300" in message for message in debug_messages)
    assert any("formation_time: 1 -> 1.5" in message for message in debug_messages)
    assert any("Created backup: BreachProject_backup_" in message for message in debug_messages)
    assert all("Created backup" not in message for message in info_messages)


def test_set_breach_geom_maps_canonical_parameters_to_exact_fields(tmp_path):
    plan_path = _write_plan_with_breach(tmp_path)

    updated = RasBreach.set_breach_geom(
        plan_path,
        "Dam",
        centerline=5800,
        final_bottom_width=300,
        final_bottom_elev=590,
        left_slope=1,
        right_slope=1.5,
        failure_mode="overtopping",
        piping_coefficient=0.8,
        initial_piping_elevation=625,
        formation_time=1.5,
        weir_coefficient=3,
    )

    assert updated["values"]["Breach Geom"].split(",") == [
        "5800",
        "300",
        "590",
        "1",
        "1.5",
        "False",
        "0.8",
        "625",
        "1.5",
        "3",
    ]


def test_set_breach_geom_accepts_deprecated_intent_preserving_aliases(tmp_path):
    plan_path = _write_plan_with_breach(tmp_path)

    with pytest.warns(FutureWarning) as caught:
        updated = RasBreach.set_breach_geom(
            plan_path,
            "Dam",
            initial_width=300,
            weir_coef=3,
        )

    assert len(caught) == 2
    assert updated["values"]["Breach Geom"].split(",") == [
        "5700",
        "300",
        "595",
        "0.5",
        "0.5",
        "True",
        "0.5",
        "630",
        "1",
        "3",
    ]


@pytest.mark.parametrize(
    ("keyword", "value", "message"),
    [
        ("active", True, "activation is stored in Breach Loc"),
        ("top_elev", 630, "no top-elevation field"),
        ("formation_method", 1, "no formation-method field"),
    ],
)
def test_set_breach_geom_rejects_unsafe_legacy_arguments_without_writing(
    tmp_path,
    keyword,
    value,
    message,
):
    plan_path = _write_plan_with_breach(tmp_path)
    source_bytes = plan_path.read_bytes()

    with pytest.raises(ValueError, match=message):
        RasBreach.set_breach_geom(plan_path, "Dam", **{keyword: value})

    assert plan_path.read_bytes() == source_bytes
    assert list(tmp_path.glob("BreachProject_backup_*")) == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"final_bottom_width": 300, "initial_width": 250},
        {"weir_coefficient": 3, "weir_coef": 2.6},
    ],
)
def test_set_breach_geom_rejects_canonical_alias_conflicts_without_writing(
    tmp_path,
    kwargs,
):
    plan_path = _write_plan_with_breach(tmp_path)
    source_bytes = plan_path.read_bytes()

    with pytest.raises(ValueError, match="Specify only one"):
        RasBreach.set_breach_geom(plan_path, "Dam", **kwargs)

    assert plan_path.read_bytes() == source_bytes
    assert list(tmp_path.glob("BreachProject_backup_*")) == []


def test_set_breach_geom_rejects_unknown_failure_mode_without_writing(tmp_path):
    plan_path = _write_plan_with_breach(tmp_path)
    source_bytes = plan_path.read_bytes()

    with pytest.raises(ValueError, match="failure_mode must be"):
        RasBreach.set_breach_geom(plan_path, "Dam", failure_mode="instantaneous")

    assert plan_path.read_bytes() == source_bytes
    assert list(tmp_path.glob("BreachProject_backup_*")) == []


def test_set_breach_geom_preserves_legacy_nine_field_arity(tmp_path):
    plan_path = _write_plan_with_breach(tmp_path)
    plan_path.write_bytes(
        plan_path.read_bytes().replace(
            b"Breach Geom=5700,200,595,0.5,0.5,True,0.5,630,1,2.6",
            b"Breach Geom=5700,200,595,0.5,0.5,True,0.5,630,1",
        )
    )

    updated = RasBreach.set_breach_geom(plan_path, "Dam", formation_time=1.5)

    fields = updated["values"]["Breach Geom"].split(",")
    assert len(fields) == 9
    assert fields[8] == "1.5"


def test_set_breach_geom_adds_weir_field_to_legacy_nine_field_record(tmp_path):
    plan_path = _write_plan_with_breach(tmp_path)
    plan_path.write_bytes(
        plan_path.read_bytes().replace(
            b"Breach Geom=5700,200,595,0.5,0.5,True,0.5,630,1,2.6",
            b"Breach Geom=5700,200,595,0.5,0.5,True,0.5,630,1",
        )
    )

    updated = RasBreach.set_breach_geom(plan_path, "Dam", weir_coefficient=3)

    fields = updated["values"]["Breach Geom"].split(",")
    assert len(fields) == 10
    assert fields[8:] == ["1", "3"]


def test_set_breach_geom_rejects_unknown_arity_without_writing(tmp_path):
    plan_path = _write_plan_with_breach(tmp_path)
    plan_path.write_bytes(
        plan_path.read_bytes().replace(
            b"Breach Geom=5700,200,595,0.5,0.5,True,0.5,630,1,2.6",
            b"Breach Geom=5700,200,595,0.5,0.5,True,0.5,630,1,2.6,extra",
        )
    )
    source_bytes = plan_path.read_bytes()

    with pytest.raises(ValueError, match="expected 9 or 10"):
        RasBreach.set_breach_geom(plan_path, "Dam", formation_time=1.5)

    assert plan_path.read_bytes() == source_bytes
    assert list(tmp_path.glob("BreachProject_backup_*")) == []


def test_update_breach_block_backup_is_debug_only(tmp_path, caplog):
    plan_path = _write_plan_with_breach(tmp_path)
    caplog.set_level(logging.DEBUG, logger=BREACH_LOGGER)

    updated = RasBreach.update_breach_block(
        plan_path,
        "Dam",
        method=9,
    )

    assert updated["values"]["Breach Method"] == " 9"
    records = _breach_records(caplog)
    info_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.DEBUG
    ]

    assert info_messages == []
    assert any("Created backup: BreachProject_backup_" in message for message in debug_messages)
    assert any("Updated breach block for Dam in BreachProject.p01" in message for message in debug_messages)


def test_update_breach_block_does_not_rewrite_trailing_plan_settings(tmp_path):
    plan_path = tmp_path / "TrailingSettings.p03"
    trailing_settings = (
        "WQ ULTIMATE=-1\r\n"
        "WQ Max Comp Step=1HOUR\r\n"
        "Calibration Method= 0 \r\n"
    )
    plan_path.write_text(
        "Plan Title=Trailing Settings\r\n"
        "Breach Loc=River,Reach,1000,True\r\n"
        "Breach Method= 0\r\n"
        "Breach Geom=5250,745,585,0.5,0.5,True,0.5,620,2.5,2.6\r\n"
        "Breach Progression= 2\r\n"
        "       0       0       1       1\r\n"
        + trailing_settings,
        encoding="utf-8",
        newline="",
    )

    RasBreach.update_breach_block(
        plan_path,
        "",
        method=1,
        is_active=False,
        create_backup=False,
    )

    updated = plan_path.read_bytes().decode("utf-8")
    assert updated.endswith(trailing_settings)
    assert "Breach Method= 1\r\n" in updated
    breach_location = next(
        line for line in updated.splitlines() if line.startswith("Breach Loc=")
    )
    assert breach_location.count(",") == 3
    assert breach_location.endswith(",False")


def test_create_breach_block_backup_is_debug_only(tmp_path, caplog):
    plan_path = tmp_path / "CreateBreach.p01"
    plan_path.write_text(
        "Plan Title=Create Breach Test\r\nSimulation Date=01JAN2000,0000,02JAN2000,0000\r\n",
        encoding="utf-8",
        newline="",
    )
    caplog.set_level(logging.DEBUG, logger=BREACH_LOGGER)

    created = RasBreach.create_breach_block(
        plan_path,
        "NewDam",
        river="River",
        reach="Reach",
        station="1000.0",
    )

    assert created["structure_name"] == "NewDam"
    assert created["values"]["Breach Geom"] == "0,0,0,0,0,False,0.5,,1,2.6"
    records = _breach_records(caplog)
    info_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.DEBUG
    ]

    assert info_messages == []
    assert any("Created backup: CreateBreach_backup_" in message for message in debug_messages)
    assert any("Created breach block for NewDam in CreateBreach.p01" in message for message in debug_messages)


def test_failure_paths_raise_without_extra_error_log(tmp_path, caplog):
    plan_path = _write_plan_with_breach(tmp_path)
    caplog.set_level(logging.DEBUG, logger=BREACH_LOGGER)

    with pytest.raises(ValueError, match="Structure 'MissingDam' not found"):
        RasBreach.read_breach_block(plan_path, "MissingDam")

    records = _breach_records(caplog)
    assert all(record.levelno < logging.ERROR for record in records)
    assert any(
        record.levelno == logging.DEBUG
        and record.getMessage() == "Error reading breach block"
        and record.exc_info
        for record in records
    )
