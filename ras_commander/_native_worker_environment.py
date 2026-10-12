"""Environment for bounded managed native workers; no caller-state mutation."""

import os


def worker_environment(worker_threads: int | None) -> dict[str, str]:
    environment = dict(os.environ)
    if worker_threads is None:
        return environment
    names = (
        "COMPlus_ThreadPool_ForceMinWorkerThreads",
        "COMPlus_ThreadPool_ForceMaxWorkerThreads",
    )
    # Windows treats environment names case-insensitively. A copied dictionary
    # must remove inherited spellings before adding the controlled value.
    for key in list(environment):
        if key.casefold() in {name.casefold() for name in names}:
            del environment[key]
    value = format(worker_threads, "x")
    for name in names:
        environment[name] = value
    return environment
