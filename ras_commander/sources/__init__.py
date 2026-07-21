"""Model source downloaders and unified catalog (federal, state, county, etc.)."""

from typing import TYPE_CHECKING

from .federal import RasEbfeModels
from .county import M3Model

if TYPE_CHECKING:
    from .federal import ScienceBaseInteractiveDownloadRequired, UsgsScienceBase


def __getattr__(name: str):
    """Lazily expose ScienceBase without increasing base import cost."""
    if name in {"UsgsScienceBase", "ScienceBaseInteractiveDownloadRequired"}:
        from .federal import (
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
    # Federal sources
    'RasEbfeModels',
    'UsgsScienceBase',
    'ScienceBaseInteractiveDownloadRequired',
    # County sources
    'M3Model',
]
