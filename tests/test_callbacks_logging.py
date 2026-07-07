import logging

from ras_commander.callbacks import ConsoleCallback, FileLoggerCallback


LOGGER_NAME = "ras_commander.callbacks"


def _records(caplog):
    return [record for record in caplog.records if record.name == LOGGER_NAME]


def test_file_logger_callback_initialization_is_debug_only(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        FileLoggerCallback(tmp_path / "logs_info")

    assert not any(
        "FileLoggerCallback initialized" in record.getMessage()
        for record in _records(caplog)
    )

    caplog.clear()

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        log_dir = tmp_path / "logs_debug"
        FileLoggerCallback(log_dir)

    messages = [record.getMessage() for record in _records(caplog)]
    assert any("FileLoggerCallback initialized" in message for message in messages)
    assert any(str(log_dir) in message for message in messages)


def test_console_callback_verbose_does_not_print_command_by_default(capsys):
    command = r'C:\Program Files\HEC\HEC-RAS\7.0\Ras.exe -c C:\Models\Project.prj C:\Models\Project.p01'
    callback = ConsoleCallback(verbose=True)

    callback.on_exec_start("01", command)
    callback.on_exec_message("01", "Geometry Preprocessor Version 7.0")

    output = capsys.readouterr().out
    assert "[Plan 01] Starting execution..." in output
    assert "[Plan 01] Geometry Preprocessor Version 7.0" in output
    assert "Command:" not in output
    assert command not in output


def test_console_callback_prints_command_when_explicitly_requested(capsys):
    command = r'C:\Program Files\HEC\HEC-RAS\7.0\Ras.exe -c C:\Models\Project.prj C:\Models\Project.p01'
    callback = ConsoleCallback(verbose=True, show_command=True)

    callback.on_exec_start("01", command)

    output = capsys.readouterr().out
    assert f"[Plan 01] Command: {command}" in output
