"""Run only the library preprocessor in the task's Windows/Wine interpreter."""

import dataclasses, json, sys
from pathlib import Path
from ras_commander import RasPrj, RasPreprocess, init_ras_project

request = json.loads(Path(sys.argv[1]).read_text())
ras = init_ras_project(
    request["project"],
    request["executable"],
    ras_object=RasPrj(),
    load_results_summary=False,
    load_hdf_metadata=False,
    hide_intro=True,
)
result = RasPreprocess.preprocess_plan(
    request["plan"],
    ras_object=ras,
    max_wait=300,
    clear_existing=True,
    require_linux_solver_ready=False,
)
Path(request["response"]).write_text(
    json.dumps(dataclasses.asdict(result), default=str, indent=2)
)
raise SystemExit(0 if result else 1)
