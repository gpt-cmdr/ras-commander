# .claude/ Component Manifest

Central registry mapping all skills, agents, rules, and commands by domain.
Update this file when adding, removing, or renaming any `.claude/` component.

This file is the Claude-side component registry only. Shared repository behavior lives in the `AGENTS.md` hierarchy, not in `.claude/`.

Some provider-invocation entries still exist here during the migration. `dev_invoke_codex-cli`
is the supported Claude-to-Codex handoff. Gemini, Kimi, and provider-mixed review entries
are legacy Claude-only compatibility components, explicit-request-only, and not part of the
long-term shared multi-harness contract.

When looking for a component related to a domain, scan the relevant domain group below.
When adding a new component, add it to the appropriate domain group AND the relationship map.

---

## Domain Groups

### HEC-RAS Execution

| Component | Type | Path |
|-----------|------|------|
| `hecras_compute_plans` | skill | `.claude/skills/hecras_compute_plans/SKILL.md` |
| `hecras_compute_remote` | skill | `.claude/skills/hecras_compute_remote/SKILL.md` |
| `hecras_compute_rascontrol` | skill | `.claude/skills/hecras_compute_rascontrol/SKILL.md` |
| `hecras_plan_execution` | skill | `.claude/skills/hecras_plan_execution/SKILL.md` |
| `execution.md` | rule | `.claude/rules/hec-ras/execution.md` |
| `remote.md` | rule | `.claude/rules/hec-ras/remote.md` |
| `hecras-general-agent` | agent | `.claude/agents/hecras-general-agent.md` |
| `remote-executor` | agent | `.claude/agents/remote-executor.md` + `.claude/agents/remote-executor/SUBAGENT.md` |

### HDF Results

| Component | Type | Path |
|-----------|------|------|
| `hecras_extract_results` | skill | `.claude/skills/hecras_extract_results/SKILL.md` |
| `hecras_parse_compute-messages` | skill | `.claude/skills/hecras_parse_compute-messages/SKILL.md` |
| `hdf-files.md` | rule | `.claude/rules/hec-ras/hdf-files.md` |
| `hdf-analyst` | agent | `.claude/agents/hdf-analyst/SUBAGENT.md` |
| `hecras-results-analyst` | agent | `.claude/agents/hecras-results-analyst.md` |

### Geometry

| Component | Type | Path |
|-----------|------|------|
| `hecras_parse_geometry` | skill | `.claude/skills/hecras_parse_geometry/SKILL.md` |
| `geometry.md` | rule | `.claude/rules/hec-ras/geometry.md` |
| `geometry-parser` | agent | `.claude/agents/geometry-parser/SUBAGENT.md` |

### USGS Integration

| Component | Type | Path |
|-----------|------|------|
| `usgs_integrate_gauges` | skill | `.claude/skills/usgs_integrate_gauges/SKILL.md` |
| `usgs.md` | rule | `.claude/rules/hec-ras/usgs.md` |
| `usgs-integrator` | agent | `.claude/agents/usgs-integrator/SUBAGENT.md` |

### DSS Operations

| Component | Type | Path |
|-----------|------|------|
| `dss_read_boundary-data` | skill | `.claude/skills/dss_read_boundary-data/SKILL.md` |
| `dss-files.md` | rule | `.claude/rules/hec-ras/dss-files.md` |

### Precipitation

| Component | Type | Path |
|-----------|------|------|
| `precip_analyze_aorc` | skill | `.claude/skills/precip_analyze_aorc/SKILL.md` |
| `precip_analyze_atlas14-variance` | skill | `.claude/skills/precip_analyze_atlas14-variance/SKILL.md` |
| `precipitation.md` | rule | `.claude/rules/hec-ras/precipitation.md` |
| `precipitation-method-validation.md` | rule | `.claude/rules/testing/precipitation-method-validation.md` |
| `precipitation-notebook-debugging-patterns.md` | rule | `.claude/rules/documentation/precipitation-notebook-debugging-patterns.md` |
| `precipitation-specialist` | agent | `.claude/agents/precipitation-specialist/SUBAGENT.md` |

### Terrain & Land Cover

| Component | Type | Path |
|-----------|------|------|
| `terrain.md` | rule | `.claude/rules/hec-ras/terrain.md` |
| `terrain-modification.md` | rule | `.claude/rules/hec-ras/terrain-modification.md` |
| `RasTerrainMod` | module | `ras_commander/terrain/RasTerrainMod.py` |
| `HdfLandCover` | module | `ras_commander/hdf/HdfLandCover.py` |
| `930_terrain_modification_analysis` | notebook | `examples/930_terrain_modification_analysis.ipynb` |
| `211_final_mannings_and_infiltration` | notebook | `examples/211_final_mannings_and_infiltration.ipynb` |

### eBFE/BLE Models

| Component | Type | Path |
|-----------|------|------|
| `ebfe_crawl_s3-catalog` | skill | `.claude/skills/ebfe_crawl_s3-catalog/SKILL.md` |
| `ebfe_organize_models` | skill | `.claude/skills/ebfe_organize_models/SKILL.md` |
| `ebfe_validate_models` | skill | `.claude/skills/ebfe_validate_models/SKILL.md` |
| `ebfe-organizer` | agent | `.claude/agents/ebfe-organizer/SUBAGENT.md` |

### Quality Assurance

| Component | Type | Path |
|-----------|------|------|
| `qa_repair_geometry` | skill | `.claude/skills/qa_repair_geometry/SKILL.md` |
| `qa_rasmapper_spatial-review` | skill | `.claude/skills/qa_rasmapper_spatial-review/SKILL.md` |
| `qa_review_triple-model` | skill | `.claude/skills/qa_review_triple-model/SKILL.md` |
| `quality-assurance` | agent | `.claude/agents/quality-assurance/SUBAGENT.md` |
| `rasmapper-spatial-reviewer` | agent | `.claude/agents/rasmapper-spatial-reviewer.md` |
| `validation-patterns.md` | rule | `.claude/rules/validation/validation-patterns.md` |

### HEC-RAS GUI & COM Automation

| Component | Type | Path |
|-----------|------|------|
| `hecras_explore_gui` | skill | `.claude/skills/hecras_explore_gui/SKILL.md` |
| `hecras_screenshot` | skill | `.claude/skills/hecras_screenshot/SKILL.md` |
| `hecras_export_cloud-native` | skill | `.claude/skills/hecras_export_cloud-native/SKILL.md` |
| `win32com-automation-expert` | agent | `.claude/agents/win32com-automation-expert.md` |
| `hecras-code-archaeologist` | agent | `.claude/agents/hecras-code-archaeologist.md` |

### HEC-RAS Project Operations

| Component | Type | Path |
|-----------|------|------|
| `hecras-project-inspector` | agent | `.claude/agents/hecras-project-inspector.md` |
| `hecras-notebook-qaqc` | agent | `.claude/agents/hecras-notebook-qaqc.md` |

### Calibration

| Component | Type | Path |
|-----------|------|------|
| `calibration.md` | rule | `.claude/rules/hec-ras/calibration.md` |
| `RasCalibrate` | module | `ras_commander/RasCalibrate.py` |
| `ras-commander-first.md` | rule | `.claude/rules/hec-ras/ras-commander-first.md` |

### Python Patterns

| Component | Type | Path |
|-----------|------|------|
| `static-classes.md` | rule | `.claude/rules/python/static-classes.md` |
| `decorators.md` | rule | `.claude/rules/python/decorators.md` |
| `path-handling.md` | rule | `.claude/rules/python/path-handling.md` |
| `error-handling.md` | rule | `.claude/rules/python/error-handling.md` |
| `naming-conventions.md` | rule | `.claude/rules/python/naming-conventions.md` |
| `import-patterns.md` | rule | `.claude/rules/python/import-patterns.md` |
| `ras-commander-patterns.md` | rule | `.claude/rules/python/ras-commander-patterns.md` |
| `api-first-principle.md` | rule | `.claude/rules/python/api-first-principle.md` |
| `dataframe-first-principle.md` | rule | `.claude/rules/python/dataframe-first-principle.md` |
| `hdf-attribute-mapping-pattern.md` | rule | `.claude/rules/python/hdf-attribute-mapping-pattern.md` |
| `htab-optimization-learnings.md` | rule | `.claude/rules/python/htab-optimization-learnings.md` |
| `state-machine-empty-line-handling.md` | rule | `.claude/rules/python/state-machine-empty-line-handling.md` |
| `windows-reserved-names.md` | rule | `.claude/rules/python/windows-reserved-names.md` |
| `pyright-lsp-usage.md` | rule | `.claude/rules/python/pyright-lsp-usage.md` |
| `api-consistency-auditor` | agent | `.claude/agents/api-consistency-auditor.md` |
| `ras-commander-api-expert` | agent | `.claude/agents/ras-commander-api-expert.md` |

### Documentation & Testing

| Component | Type | Path |
|-----------|------|------|
| `hierarchical-knowledge-best-practices.md` | rule | `.claude/rules/documentation/hierarchical-knowledge-best-practices.md` |
| `mkdocs-config.md` | rule | `.claude/rules/documentation/mkdocs-config.md` |
| `notebook-standards.md` | rule | `.claude/rules/documentation/notebook-standards.md` |
| `notebook-to-agent-conversion.md` | rule | `.claude/rules/documentation/notebook-to-agent-conversion.md` |
| `tdd-approach.md` | rule | `.claude/rules/testing/tdd-approach.md` |
| `environment-management.md` | rule | `.claude/rules/testing/environment-management.md` |
| `agent-integration-testing.md` | rule | `.claude/rules/testing/agent-integration-testing.md` |
| `documentation-generator` | agent | `.claude/agents/documentation-generator/SUBAGENT.md` |
| `example-notebook-librarian` | agent | `.claude/agents/example-notebook-librarian.md` |
| `python-environment-manager` | agent | `.claude/agents/python-environment-manager.md` |

### Notebook Operations

| Component | Type | Path |
|-----------|------|------|
| `notebook-runner` | agent | `.claude/agents/notebook-runner.md` |
| `notebook-output-auditor` | agent | `.claude/agents/notebook-output-auditor.md` |
| `notebook-anomaly-spotter` | agent | `.claude/agents/notebook-anomaly-spotter.md` |
| `test-notebook` | command | `.claude/commands/test-notebook.md` |

### Dev Tooling

Note: `dev_invoke_codex-cli` is the supported Claude-to-Codex handoff. Gemini/Kimi
provider invocations are legacy, explicit-request-only Claude helpers and are excluded from
the shared multi-harness skill corpus.

| Component | Type | Path |
|-----------|------|------|
| `dev_invoke_codex-cli` | skill | `.claude/skills/dev_invoke_codex-cli/SKILL.md` |
| `dev_invoke_gemini-cli` | skill | `.claude/skills/dev_invoke_gemini-cli/SKILL.md` |
| `dev_invoke_kimi-cli` | skill | `.claude/skills/dev_invoke_kimi-cli/SKILL.md` |
| `dev_manage_git-worktrees` | skill | `.claude/skills/dev_manage_git-worktrees/SKILL.md` |
| `dev_gate_merge-to-main` | skill | `.claude/skills/dev_gate_merge-to-main/SKILL.md` |
| `dev_human-in-loop` | skill | `.claude/skills/dev_human-in-loop/SKILL.md` |
| `code-oracle-codex` | agent | `.claude/agents/code-oracle-codex.md` |
| `code-oracle-gemini` | agent | `.claude/agents/code-oracle-gemini.md` |
| `git-operations` | agent | `.claude/agents/git-operations/SUBAGENT.md` |

### Agent Infrastructure & Knowledge

| Component | Type | Path |
|-----------|------|------|
| `hierarchical-knowledge-agent-skill-memory-curator` | agent | `.claude/agents/hierarchical-knowledge-agent-skill-memory-curator.md` |
| `subagent-output-pattern.md` | rule | `.claude/rules/subagent-output-pattern.md` |
| `primitive-extraction-workflow.md` | rule | `.claude/rules/workflow/primitive-extraction-workflow.md` |
| `clb-engineering-recommendation.md` | rule | `.claude/rules/clb-engineering-recommendation.md` |
| `agents-md-bridge.md` | rule | `.claude/rules/agents-md-bridge.md` |
| `hec-hms-documentation-scout` | agent | `.claude/agents/hec-hms-documentation-scout.md` |
| `claude-code-guide` | agent | `.claude/agents/claude-code-guide.md` |

### Conversation Analysis

| Component | Type | Path |
|-----------|------|------|
| `conversation-deep-researcher` | agent | `.claude/agents/conversation-deep-researcher.md` |
| `conversation-index-scanner` | agent | `.claude/agents/conversation-index-scanner.md` |
| `conversation-insights-orchestrator` | agent | `.claude/agents/conversation-insights-orchestrator.md` |
| `best-practice-extractor` | agent | `.claude/agents/best-practice-extractor.md` |
| `blocker-detector` | agent | `.claude/agents/blocker-detector.md` |
| `slash-command-finder` | agent | `.claude/agents/slash-command-finder.md` |

### Task Management Commands

| Component | Type | Path |
|-----------|------|------|
| `agent-taskclose` | command | `.claude/commands/agent-taskclose.md` |
| `agent-taskupdate` | command | `.claude/commands/agent-taskupdate.md` |
| `agent-cleanfiles` | command | `.claude/commands/agent-cleanfiles.md` |
| `agent-engagesubagents` | command | `.claude/commands/agent-engagesubagents.md` |
| `agent-crossrepo` | command | `.claude/commands/agent-crossrepo.md` |
| `agents-start-gitworktree` | command | `.claude/commands/agents-start-gitworktree.md` |
| `agents-close-gitworktree` | command | `.claude/commands/agents-close-gitworktree.md` |

### Cross-Validation & QAQC

Note: `qa_review_triple-model` and `code-oracle-gemini` are legacy provider-mixed
Claude-only compatibility components. Generic QAQC should use Claude/Codex production paths;
use these only when the user explicitly requests the legacy provider-mixed workflow or Gemini.

| Component | Type | Path |
|-----------|------|------|
| `dual-qaqc` | command | `.claude/commands/dual-qaqc.md` |
| `qa_review_triple-model` | skill | `.claude/skills/qa_review_triple-model/SKILL.md` |
| `code-oracle-codex` | agent | `.claude/agents/code-oracle-codex.md` |
| `code-oracle-gemini` | agent | `.claude/agents/code-oracle-gemini.md` |

---

## Relationship Map

### HEC-RAS Execution Domain

**`hecras_plan_execution`** (skill) -- execution mode selection
- Upstream: `hecras-project-inspector` agent (provides project intelligence)
- Downstream: `hecras_compute_plans`, `hecras_compute_remote`, `hecras_compute_rascontrol` skills
- Rules: `execution.md`, `static-classes.md`

**`hecras_compute_plans`** (skill) -- plan execution
- Upstream: `hecras_plan_execution` skill (mode decision)
- Downstream: `hecras_extract_results` skill, `hecras_parse_compute-messages` skill
- Agents: `hecras-general-agent` (coordinator)
- Rules: `execution.md`, `static-classes.md`, `decorators.md`

**`hecras_compute_remote`** (skill) -- distributed execution
- Upstream: `hecras_plan_execution` skill
- Downstream: `hecras_extract_results` skill
- Agents: `remote-executor`
- Rules: `remote.md`, `execution.md`

**`hecras_compute_rascontrol`** (skill) -- legacy COM execution
- Agents: `win32com-automation-expert`
- Rules: `execution.md`

**`hecras-general-agent`** (agent) -- workflow coordinator
- Uses skills: `hecras_plan_execution`, `hecras_compute_plans`, `hecras_extract_results`, `hecras_parse_compute-messages`
- Coordinates agents: `hecras-project-inspector`, `hecras-results-analyst`

### HDF Results Domain

**`hecras_extract_results`** (skill) -- results extraction
- Upstream: `hecras_compute_plans` skill (produces HDF)
- Agents: `hdf-analyst`, `hecras-results-analyst`
- Rules: `hdf-files.md`, `hdf-attribute-mapping-pattern.md`

**`hecras_parse_compute-messages`** (skill) -- execution diagnostics
- Upstream: `hecras_compute_plans` skill
- Agents: `hecras-results-analyst`

**`hdf-analyst`** (agent) -- HDF specialist
- Uses skills: `hecras_extract_results`
- Rules: `hdf-files.md`, `api-first-principle.md`
- Related agents: `hecras-results-analyst`

**`hecras-results-analyst`** (agent) -- results interpretation
- Uses skills: `hecras_extract_results`, `hecras_parse_compute-messages`
- Rules: `hdf-files.md`, `validation-patterns.md`
- Related agents: `hdf-analyst`, `hecras-project-inspector`

### Geometry Domain

**`hecras_parse_geometry`** (skill) -- geometry parsing
- Agents: `geometry-parser`
- Rules: `geometry.md`, `state-machine-empty-line-handling.md`
- Related skills: `qa_repair_geometry`

**`geometry-parser`** (agent) -- geometry specialist
- Uses skills: `hecras_parse_geometry`
- Rules: `geometry.md`, `api-first-principle.md`

### Data Integration Domain

**`usgs_integrate_gauges`** (skill) -- USGS gauge workflow
- Agents: `usgs-integrator`
- Rules: `usgs.md`
- Related skills: `dss_read_boundary-data`

**`dss_read_boundary-data`** (skill) -- DSS file operations
- Rules: `dss-files.md`
- Related skills: `usgs_integrate_gauges`, `hecras_compute_plans`

**`precip_analyze_aorc`** (skill) -- historical precipitation
- Agents: `precipitation-specialist`
- Rules: `precipitation.md`
- Related skills: `precip_analyze_atlas14-variance`, `dss_read_boundary-data`

**`precip_analyze_atlas14-variance`** (skill) -- design storms
- Agents: `precipitation-specialist`
- Rules: `precipitation.md`, `precipitation-method-validation.md`

### eBFE/BLE Domain

**`ebfe_crawl_s3-catalog`** (skill) -- public BLE/eBFE catalog discovery
- Downstream: `ebfe_organize_models` skill
- Agents: `ebfe-organizer`

**`ebfe_organize_models`** (skill) -- model organization
- Upstream: `ebfe_crawl_s3-catalog` skill
- Downstream: `ebfe_validate_models` skill
- Agents: `ebfe-organizer`

**`ebfe_validate_models`** (skill) -- model validation
- Upstream: `ebfe_organize_models` skill
- Rules: `validation-patterns.md`, `dataframe-first-principle.md`

### Quality Assurance Domain

**`qa_repair_geometry`** (skill) -- geometry repair
- Agents: `quality-assurance`
- Rules: `validation-patterns.md`, `geometry.md`
- Related skills: `hecras_parse_geometry`, `qa_rasmapper_spatial-review`

**`qa_rasmapper_spatial-review`** (skill) -- RASMapper spatial QA snapshots
- Agents: `rasmapper-spatial-reviewer`
- Rules: `validation-patterns.md`, `hdf-files.md`
- Related skills: `hecras_screenshot`, `hecras_extract_results`, `hecras_parse_geometry`, `qa_repair_geometry`

**`rasmapper-spatial-reviewer`** (agent) -- terrain-backed RASMapper review
- Uses skills: `qa_rasmapper_spatial-review`
- Related agents: `quality-assurance`, `hdf-analyst`, `hecras-project-inspector`, `hecras-results-analyst`

**`qa_review_triple-model`** (skill) -- legacy explicit-request-only provider-mixed review
- Agents: `code-oracle-codex`, `code-oracle-gemini`
- Related skills: `dev_invoke_codex-cli`, `dev_invoke_gemini-cli`, `dev_invoke_kimi-cli`

### Dev Tooling Domain

**`dev_gate_merge-to-main`** (skill) -- feature-branch guardrail
- Agents: `git-operations`
- Commands: `agent-taskupdate`, `agent-engagesubagents`

**`dev_human-in-loop`** (skill) -- human approval gate for high-risk agent actions

**`dev_invoke_codex-cli`** (skill) -- Codex CLI delegation
- Agents: `code-oracle-codex`

**`dev_invoke_gemini-cli`** (skill) -- legacy explicit-request-only Gemini CLI delegation
- Agents: `code-oracle-gemini`

**`dev_invoke_kimi-cli`** (skill) -- legacy explicit-request-only Kimi CLI delegation

**`dev_manage_git-worktrees`** (skill) -- worktree management
- Agents: `git-operations`
- Commands: `agents-start-gitworktree`, `agents-close-gitworktree`

### HEC-RAS GUI & Documentation Domain

**`hecras_explore_gui`** (skill) -- GUI exploration
- Agents: `win32com-automation-expert`, `hecras-code-archaeologist`
- Related skills: `hecras_screenshot`

**`hecras_screenshot`** (skill) -- GUI screenshot capture
- Agents: `win32com-automation-expert`, `hecras-code-archaeologist`
- Related skills: `hecras_explore_gui`, `qa_rasmapper_spatial-review`

### Notebook Operations Domain

**`notebook-runner`** (agent) -- execution
- Related agents: `notebook-output-auditor`, `notebook-anomaly-spotter`
- Commands: `test-notebook`
- Rules: `notebook-standards.md`

**`example-notebook-librarian`** (agent) -- management
- Uses agents: `notebook-runner`, `notebook-output-auditor`
- Rules: `notebook-standards.md`, `notebook-to-agent-conversion.md`

---

## Index Files

| File | Purpose |
|------|---------|
| `.claude/README.md` | Framework overview |
| `.claude/agents/README.md` | Agent registry, model assignments, delegation tree |
| `.claude/skills/README.md` | Skill catalog |
| `.claude/rules/README.md` | Rule organization, path scoping |
| `.claude/MANIFEST.md` | This file -- cross-domain relationship map |

---

## Conventions

**Voice**: All skills, agents, rules, and commands use imperative agent-instructable voice. Write "When the user asks X, use Y" not "This module provides Y."

**Cross-References**: Every file includes a `## Cross-References` section mapping related components in other directories. Use the relationship map above as the source of truth.

**Line Budget**: 200-400 lines per file. Documented exceptions: `code-oracle-codex.md`, `code-oracle-gemini.md`, `win32com-automation-expert.md`, `hecras-code-archaeologist.md`.

**Updates**: When adding a new component, update this manifest AND add cross-references to related existing components.
