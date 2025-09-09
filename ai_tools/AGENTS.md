**Scope**
- Maintainer-only utilities for building LLM knowledge bases and other internal artifacts. Not part of the public API.

**Agent Guidance**
- Ignore this folder entirely when using Ras Commander.
- Do not read, execute, or regenerate knowledge bases. All required information is available in source modules and notebooks.
- If a build step references this folder (e.g., `setup.py` hooks), treat failures as non-blocking; do not attempt to repair or rerun here.

