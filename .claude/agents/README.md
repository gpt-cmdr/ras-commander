# Claude agent adapters

This directory contains Claude-native delegation roles. Shared workflow contracts live in the
`AGENTS.md` hierarchy and approved shared skills. Codex uses those contracts and its native worker
mechanisms; it does not assume these Claude agent definitions are automatically registered.

## Entry points

| Role | Canonical workflow | Purpose |
|---|---|---|
| [ras-commander](ras-commander.md) | [RAS Commander skill](../skills/ras-commander/SKILL.md) | “Just Ask for RAS Commander” task intake and routing |
| [cloud-native-gis](cloud-native-gis.md) | [Cloud Native GIS skill](../skills/cloud-native-gis/SKILL.md) | RAS/HMS GIS/archive/export using current package contracts |

HMS intake lives in the HMS repository's shared `hms-commander` skill. Cross-model tasks load that
repository's actual guidance when available; the RAS entry point does not duplicate HMS policy.

## Discover specialists

Use [.claude/MANIFEST.md](../MANIFEST.md) for the component registry and relationships. Read the
selected role's definition and the applicable shared contract. Do not infer available tools or
supported APIs from a historical example or a model-name category.

Specialists include project inspection, results/HDF analysis, geometry, precipitation, USGS,
remote execution, QA, API discovery, documentation, and knowledge maintenance. Load only the
roles needed for the task. Existing specialists are not all migrated thin adapters; audit their
references and tool declarations when maintaining them.

## Delegate bounded work

Give a worker a focused question, authorized project root, versions, allowed operations, relevant
shared guidance, and expected evidence/artifacts. Assign exclusive files for concurrent edits and
preserve others' work. Use the configured model appropriate to the task; this directory imposes
no universal model hierarchy, cost ratio, or automatic provider escalation.

RAS/HMS project MCP tools belong only to bounded read-only informational subagents with
non-spatial/non-gridded outputs. The main coordinator receives a concise answer with provenance,
limits, and blockers. Heavy or modifying workflows use the full Python libraries. If subagent MCP
tool exposure is unavailable, follow the shared workflow's Python handoff or report the limitation.

## Maintain adapters

Keep native wrappers thin and place behavior that both harnesses need in shared skills or AGENTS.
Update active callers and registry references when changing role names. Record the current routing
in the manifest. Agent files
can be root-level Markdown definitions or existing folder-based roles; consult the current harness
requirements before introducing a new layout. Do not copy a workflow policy into a second role.

The entry point definitions establish routing instructions. Demonstrate actual discovery and
activation in each supported harness before claiming a packaged plugin experience.
