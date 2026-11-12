"""Lossless binary64 JSON values for mapping manifests and comparison rows."""
from collections.abc import Mapping
import math

import numpy as np
import pandas as pd


def json_value(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, np.ndarray):
        return json_value(value.tolist())
    if isinstance(value, np.generic):
        scalar = value.item()
        if isinstance(scalar, np.generic):
            raise TypeError("mapping JSON requires native scalars or binary64 values")
        return json_value(scalar)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def records(frame):
    """Keep Python float round trips; pandas' JSON formatter rounds transforms.

    Row access deep-copies ``DataFrame.attrs`` (pandas ``__finalize__``); a large
    receipt there made every row cost a full copy. The rows never read attrs, so
    they are detached for the conversion and restored afterwards.
    """
    attrs = frame.attrs
    frame.attrs = {}
    try:
        return json_value(frame.to_dict(orient="records"))
    finally:
        frame.attrs = attrs
