"""Resolve DSS boundaries on the native backend with Java made impossible.

Used by ``test_rasdss_hecras_acceptance.py``. ``jnius`` and ``jnius_config`` cannot be
imported here and ``JAVA_HOME`` is removed, so any fallback to the Java bridge fails.

argv: project_folder ras_version out.pkl
Writes ``{"result": DataFrame, "jnius_loaded": bool}``.
"""

import os
import pickle
import sys

sys.modules["jnius"] = None
sys.modules["jnius_config"] = None
os.environ.pop("JAVA_HOME", None)
os.environ["RAS_COMMANDER_DSS_BACKEND"] = "native"

from ras_commander import RasDss, init_ras_project  # noqa: E402


def main():
    project, version, out_path = sys.argv[1:4]
    ras = init_ras_project(project, version, load_results_summary=False, hide_intro=True)
    result = RasDss.extract_boundary_timeseries(ras.boundaries_df, ras_object=ras)
    with open(out_path, "wb") as fh:
        pickle.dump(
            {"result": result, "jnius_loaded": sys.modules.get("jnius") is not None}, fh
        )


if __name__ == "__main__":
    main()
