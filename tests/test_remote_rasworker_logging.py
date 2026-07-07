import importlib
import json
import logging
from types import SimpleNamespace


rasworker_module = importlib.import_module("ras_commander.remote.RasWorker")


def _rasworker_messages(caplog, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == level
        and record.name == "ras_commander.remote.RasWorker"
    ]


def test_init_ras_worker_factory_message_is_debug(monkeypatch, caplog):
    local_worker_module = importlib.import_module("ras_commander.remote.LocalWorker")

    monkeypatch.setattr(
        local_worker_module,
        "init_local_worker",
        lambda **kwargs: SimpleNamespace(
            worker_id=kwargs["worker_id"],
            worker_type="local",
        ),
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.remote.RasWorker"):
        worker = rasworker_module.init_ras_worker(
            "local",
            worker_id="local-test",
            ras_exe_path=r"C:\HEC-RAS\6.6\Ras.exe",
        )

    assert worker.worker_id == "local-test"
    assert _rasworker_messages(caplog, logging.INFO) == []
    assert "Initializing local worker" in "\n".join(
        _rasworker_messages(caplog, logging.DEBUG)
    )


def test_load_workers_from_json_info_is_path_concise(monkeypatch, tmp_path, caplog):
    config_path = tmp_path / "nested" / "RemoteWorkers.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps(
            {
                "workers": [
                    {
                        "name": "Local Test",
                        "worker_type": "local",
                        "enabled": True,
                    },
                    {
                        "name": "Remote Test",
                        "worker_type": "psexec",
                        "enabled": True,
                        "hostname": "test-host",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_init_ras_worker(worker_type, ras_object=None, **kwargs):
        return SimpleNamespace(
            worker_id=kwargs["worker_id"],
            worker_type=worker_type,
        )

    monkeypatch.setattr(
        rasworker_module,
        "init_ras_worker",
        fake_init_ras_worker,
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.remote.RasWorker"):
        workers = rasworker_module.load_workers_from_json(config_path)

    info_messages = _rasworker_messages(caplog, logging.INFO)
    debug_text = "\n".join(_rasworker_messages(caplog, logging.DEBUG))

    assert [worker.worker_id for worker in workers] == ["Local Test", "Remote Test"]
    assert info_messages == ["Loaded 2 workers from RemoteWorkers.json"]
    assert str(config_path.parent) not in info_messages[0]
    assert "Loaded worker: Local Test (local)" in debug_text
    assert "Loaded worker: Remote Test (psexec)" in debug_text
    assert str(config_path.resolve()) in debug_text
