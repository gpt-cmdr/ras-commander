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


# .NET Framework 4.x selects legacy behavior from the host's target framework
# (BinaryCompatibility). python.exe has no TargetFrameworkAttribute, so a
# pythonnet host runs RasMapperLib with pre-4.5 quirks: Array.Sort and
# List<T>.Sort use the legacy depth-limited quicksort instead of introsort.
# The two sorts order equal keys differently, which changes stored face
# profiles at equal-station samples. RasMapperLib.dll in HEC-RAS 6.x and 7.x
# targets 4.7.2, as do RasProcess.exe and RasMapper.exe in 7.0.1, so a worker
# that hosts RasMapperLib declares that target through the runtime's
# TargetFrameworkMoniker override (any 4.5+ target selects introsort).
RASMAPPER_TARGET_FRAMEWORK = ".NETFramework,Version=v4.7.2"
_TARGET_FRAMEWORK_VARIABLE = "COMPlus_TargetFrameworkMoniker"


def rasmapper_host_environment(worker_threads: int | None) -> dict[str, str]:
    """Return a worker environment for a Python process that hosts RasMapperLib."""
    environment = worker_environment(worker_threads)
    for key in list(environment):
        if key.casefold() == _TARGET_FRAMEWORK_VARIABLE.casefold():
            del environment[key]
    environment[_TARGET_FRAMEWORK_VARIABLE] = RASMAPPER_TARGET_FRAMEWORK
    return environment
