"""Federal model sources (USGS, FEMA eBFE, etc.)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ras_commander.sources.federal.usgs_sciencebase import UsgsScienceBase

from .ebfe_models import RasEbfeModels

__all__ = ['UsgsScienceBase', 'RasEbfeModels']
