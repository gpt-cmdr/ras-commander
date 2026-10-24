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

__all__ = ["RasSubdomain", "SplitLineCriteria", "SplitLineSearch", "SubdomainPartition"]


def __getattr__(name):
    """Load the subdomain API (and geopandas) only when it is requested."""
    if name in __all__:
        from importlib import import_module

        module = import_module(".RasSubdomain", __name__)
        for public in __all__:
            globals()[public] = getattr(module, public)
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
