"""Minimal plan-HDF doubles for launcher control-flow tests.

``RasCmdr.compute_plan`` opens the plan HDF after HEC-RAS exits and fails the
run when the file is unreadable or partial. Launcher doubles that stand in for
a finished run must therefore write a real HDF5 file, not placeholder bytes.
"""

from pathlib import Path

import h5py
import numpy as np


def write_minimal_plan_hdf(path, *, marker: str = "computed") -> Path:
    """Write the smallest plan HDF that ``compute_plan`` accepts as finished.

    The file holds ``Plan Data/Plan Information`` and a compute-message
    record that ends with ``Complete Process``. It has no output clock, so
    the completion gate records the simulation window as not judged.
    ``marker`` changes the bytes, for tests that compare result identity
    before and after a run.
    """
    path = Path(path)
    with h5py.File(path, "w") as hdf:
        info = hdf.require_group("Plan Data/Plan Information")
        info.attrs["Test Marker"] = marker
        hdf.require_group("Results/Summary").create_dataset(
            "Compute Messages (text)",
            data=np.array([b"Computations finished\r\nComplete Process\t1\r\n"]),
        )
    return path
