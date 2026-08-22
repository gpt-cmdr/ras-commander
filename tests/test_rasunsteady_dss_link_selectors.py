"""Regression tests for exact, ambiguity-safe DSS boundary mutation."""

from pathlib import Path

import pytest

from ras_commander.RasUnsteady import RasUnsteady

DSS_PATH = "//TARGET/FLOW/DATE/1HOUR/RUN:TEST/"


def _block(
    location: str,
    bc_type: str = "Flow Hydrograph",
    value: str = "1",
) -> list[str]:
    return [
        f"Boundary Location={location}",
        "Interval=5MIN",
        f"{bc_type}= 1 ",
        f"{value:>8}",
        "DSS File=old.dss",
        "DSS Path=//OLD/FLOW/DATE/5MIN/RUN:OLD/",
        "Use DSS=False",
    ]


def _write_file(
    path: Path,
    records: list[str],
    newline: str = "\n",
    terminal_newline: bool = True,
) -> bytes:
    content = newline.join(records)
    if terminal_newline:
        content += newline
    raw = content.encode("utf-8")
    path.write_bytes(raw)
    return raw


def _set_link(path: Path, **selectors: object) -> bool:
    return RasUnsteady.set_boundary_dss_link(
        path,
        None,
        None,
        None,
        r"hydrology/scenario.dss",
        DSS_PATH,
        interval="1HOUR",
        **selectors,
    )


def _assert_only_newline(raw: bytes, newline: bytes) -> None:
    remaining = raw.replace(newline, b"")
    assert b"\r" not in remaining
    assert b"\n" not in remaining


def test_legacy_unique_1d_selector_remains_positional(tmp_path: Path) -> None:
    unsteady = tmp_path / "model.u01"
    records = _block("River A,Reach A,1000,,,,,,")
    records += _block("River B,Reach B,2000,,,,,,", value="9")
    _write_file(unsteady, records)

    changed = RasUnsteady.set_boundary_dss_link(
        unsteady,
        "River A",
        "Reach A",
        "1000",
        "forcing.dss",
        DSS_PATH,
    )

    assert changed is True
    text = unsteady.read_text(encoding="utf-8")
    assert "Flow Hydrograph= 0 " in text
    assert "DSS File=.\\forcing.dss" in text
    assert "Boundary Location=River B,Reach B,2000" in text
    assert f"{'9':>8}" in text


def test_exact_2d_selector_leaves_other_block_unchanged(tmp_path: Path) -> None:
    unsteady = tmp_path / "model.u01"
    untouched = _block(",,,,,Area2D,,Line A,", value="7")
    target = _block(",,,,,Area2D,,Line B,", value="8")
    untouched_bytes = ("\r\n".join(untouched) + "\r\n").encode()
    _write_file(unsteady, untouched + target, newline="\r\n")

    assert _set_link(
        unsteady,
        sa_2d_name="Area2D",
        bc_line="Line B",
        expected_bc_type="Flow Hydrograph",
    )

    after = unsteady.read_bytes()
    assert untouched_bytes in after
    assert b"DSS File=.\\hydrology\\scenario.dss\r\n" in after
    assert f"{'8':>8}".encode() not in after


def test_ambiguous_partial_selector_rejected_without_write(tmp_path: Path) -> None:
    unsteady = tmp_path / "model.u01"
    before = _write_file(
        unsteady,
        _block(",,,,,Area2D,,Line A,")
        + _block(",,,,,Area2D,,Line B,"),
    )

    with pytest.raises(ValueError, match="ambiguous"):
        _set_link(unsteady, sa_2d_name="Area2D")

    assert unsteady.read_bytes() == before


def test_mixed_1d_and_2d_selectors_rejected_without_write(tmp_path: Path) -> None:
    unsteady = tmp_path / "model.u01"
    before = _write_file(unsteady, _block("River,Reach,1000,,,,,,"))

    with pytest.raises(ValueError, match="either 1D selectors"):
        RasUnsteady.set_boundary_dss_link(
            unsteady,
            "River",
            "Reach",
            "1000",
            "forcing.dss",
            DSS_PATH,
            sa_2d_name="Area2D",
        )

    assert unsteady.read_bytes() == before


def test_boundary_index_alone_selects_exact_block(tmp_path: Path) -> None:
    unsteady = tmp_path / "model.u01"
    _write_file(
        unsteady,
        _block(",,,,,Area2D,,Line A,", value="3")
        + _block(",,,,,Area2D,,Line B,", value="4"),
    )

    assert _set_link(unsteady, boundary_index=1)

    text = unsteady.read_text(encoding="utf-8")
    first_block, second_block = text.split("Boundary Location=")[1:]
    assert f"{'3':>8}" in first_block
    assert "DSS File=.\\hydrology\\scenario.dss" in second_block
    assert f"{'4':>8}" not in second_block


def test_boundary_index_cross_checks_semantic_selector(tmp_path: Path) -> None:
    unsteady = tmp_path / "model.u01"
    _write_file(
        unsteady,
        _block(",,,,,Area2D,,Line A,")
        + _block(",,,,,Area2D,,Line B,"),
    )

    assert _set_link(
        unsteady,
        sa_2d_name="Area2D",
        bc_line="Line B",
        boundary_index=1,
    )


def test_boundary_index_mismatch_and_out_of_range_rejected(tmp_path: Path) -> None:
    unsteady = tmp_path / "model.u01"
    before = _write_file(
        unsteady,
        _block(",,,,,Area2D,,Line A,")
        + _block(",,,,,Area2D,,Line B,"),
    )

    with pytest.raises(ValueError, match="does not match"):
        _set_link(
            unsteady,
            sa_2d_name="Area2D",
            bc_line="Line B",
            boundary_index=0,
        )
    with pytest.raises(ValueError, match="out of range"):
        _set_link(unsteady, boundary_index=2)

    assert unsteady.read_bytes() == before


def test_expected_boundary_type_rejected_without_write(tmp_path: Path) -> None:
    unsteady = tmp_path / "model.u01"
    before = _write_file(
        unsteady,
        _block(",,,,,Area2D,,Stage Line,", bc_type="Stage Hydrograph"),
    )

    with pytest.raises(ValueError, match="not the expected"):
        _set_link(
            unsteady,
            sa_2d_name="Area2D",
            bc_line="Stage Line",
            expected_bc_type="Flow Hydrograph",
        )

    assert unsteady.read_bytes() == before


def test_bare_relative_dss_filename_gets_explicit_prefix(tmp_path: Path) -> None:
    unsteady = tmp_path / "model.u01"
    _write_file(unsteady, _block("River,Reach,1000,,,,,,"))

    assert RasUnsteady.set_boundary_dss_link(
        unsteady,
        "River",
        "Reach",
        "1000",
        "hydrology/scenario.dss",
        DSS_PATH,
    )

    assert "DSS File=.\\hydrology\\scenario.dss" in unsteady.read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_preserves_consistent_newline_convention(
    tmp_path: Path,
    newline: str,
) -> None:
    unsteady = tmp_path / "model.u01"
    _write_file(
        unsteady,
        _block(",,,,,Area2D,,Line A,"),
        newline=newline,
    )

    assert _set_link(unsteady, sa_2d_name="Area2D", bc_line="Line A")

    _assert_only_newline(unsteady.read_bytes(), newline.encode())


@pytest.mark.parametrize("terminal_newline", [True, False])
def test_preserves_terminal_newline_state(
    tmp_path: Path,
    terminal_newline: bool,
) -> None:
    unsteady = tmp_path / "model.u01"
    _write_file(
        unsteady,
        _block(",,,,,Area2D,,Line A,"),
        newline="\r\n",
        terminal_newline=terminal_newline,
    )

    assert _set_link(unsteady, sa_2d_name="Area2D", bc_line="Line A")

    assert unsteady.read_bytes().endswith(b"\r\n") is terminal_newline


def test_mixed_newlines_rejected_with_original_bytes_unchanged(
    tmp_path: Path,
) -> None:
    unsteady = tmp_path / "model.u01"
    before = (
        b"Boundary Location=,,,,,Area2D,,Line A,\r\n"
        b"Flow Hydrograph= 1 \n"
        b"       1\r\n"
        b"Use DSS=False\r\n"
    )
    unsteady.write_bytes(before)

    with pytest.raises(ValueError, match="Mixed newline"):
        _set_link(unsteady, sa_2d_name="Area2D", bc_line="Line A")

    assert unsteady.read_bytes() == before


def test_unmatched_semantic_selector_returns_false_without_write(
    tmp_path: Path,
) -> None:
    unsteady = tmp_path / "model.u01"
    before = _write_file(unsteady, _block(",,,,,Area2D,,Line A,"))

    assert _set_link(
        unsteady,
        sa_2d_name="Area2D",
        bc_line="Missing",
    ) is False
    assert unsteady.read_bytes() == before
