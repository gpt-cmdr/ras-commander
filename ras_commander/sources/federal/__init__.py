"""Federal model sources (USGS, FEMA eBFE, NOAA ras2fim, etc.)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ras_commander.sources.federal.usgs_sciencebase import (
        ScienceBaseInteractiveDownloadRequired,
        UsgsScienceBase,
    )

from .ebfe_models import RasEbfeModels
from .noaa_ras2fim import NoaaRas2fimModels

def __getattr__(name: str):
    """Lazily expose the optional ScienceBase source implementation."""
    if name in {"UsgsScienceBase", "ScienceBaseInteractiveDownloadRequired"}:
        from ras_commander.sources.federal.usgs_sciencebase import (
            ScienceBaseInteractiveDownloadRequired,
            UsgsScienceBase,
        )

        return {
            "UsgsScienceBase": UsgsScienceBase,
            "ScienceBaseInteractiveDownloadRequired": (
                ScienceBaseInteractiveDownloadRequired
            ),
        }[name]
    raise AttributeError(name)


__all__ = [
    'UsgsScienceBase',
    'ScienceBaseInteractiveDownloadRequired',
    'RasEbfeModels',
    'NoaaRas2fimModels',
]
