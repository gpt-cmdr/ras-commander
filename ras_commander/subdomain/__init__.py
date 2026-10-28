"""Hydraulic subdomains of a 2D parent model.

Split a large 2D (often rain-on-grid) parent into breakout subdomains whose
boundaries sit where normal depth holds, found from the parent's own native
face flow along TauDEM stream links (see :class:`RasSubdomain`).

Example:
    >>> from ras_commander.terrain import RasTauDem
    >>> from ras_commander.subdomain import RasSubdomain
    >>> taudem = RasTauDem.delineate("dem.tif", "work/taudem", cell_size=100.0)  # doctest: +SKIP
    >>> search = RasSubdomain.find_split_lines(["parent.p01.hdf", "parent.p02.hdf"],
    ...                                        taudem.streams, taudem.catchments)  # doctest: +SKIP
    >>> partition = RasSubdomain.build_subdomains(search)                         # doctest: +SKIP

Requires geopandas, shapely 2 and pyproj (``pip install ras-commander[full]``).
"""

_EXPORTS = {
    "RasSubdomain": ".RasSubdomain",
    "SplitLineCriteria": ".RasSubdomain",
    "SplitLineSearch": ".RasSubdomain",
    "SubdomainPartition": ".RasSubdomain",
    "SubdomainBreakout": "._breakouts",
    "SubdomainBreakoutPlan": "._breakouts",
    "SubdomainBreakoutSet": "._breakouts",
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    """Load the subdomain API (and geopandas) only when it is requested."""
    if name in _EXPORTS:
        from importlib import import_module

        value = getattr(import_module(_EXPORTS[name], __name__), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
