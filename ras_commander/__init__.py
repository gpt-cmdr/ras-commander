from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("ras_commander")
except PackageNotFoundError:
    # package is not installed
    __version__ = "unknown"
