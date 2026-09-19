"""Feature-table reload suppression for in-process RASGeometry edits and saves."""

from __future__ import annotations

from contextlib import contextmanager


@contextmanager
def suppress_feature_table_reloads(geom):
    """Hold RASMapper's ``MultiLayerReloadSuppressor`` over ``geom``'s feature layers.

    Each RasMapperLib feature layer watches its source HDF and, once the file
    changes, reloads its feature table from disk the next time the table is
    read, discarding in-memory edits. ``RASGeometry.Save()`` does not guard
    against this: it writes one layer, then reads the next layer's table, so a
    reload can replace computed data partway through the save and the save
    skips it without an error. RASMapper's own save paths
    (``RASGeometry.StopEditing`` / ``LoadSaveAllLayers``) hold this suppressor
    for that reason. Under Wine the watcher fires on the first write, so
    unguarded saves are lost every time (#361).

    Wrap both the in-memory edits and the ``Save()`` call.
    """
    from RasMapperLib import FeatureLayer, MultiLayerReloadSuppressor  # type: ignore
    from System.Collections.Generic import List as NetList  # type: ignore

    layers = NetList[FeatureLayer]()
    for layer in geom.Layers:
        if isinstance(layer, FeatureLayer):
            layers.Add(layer)

    suppressor = MultiLayerReloadSuppressor(layers)
    try:
        yield
    finally:
        suppressor.Dispose()
