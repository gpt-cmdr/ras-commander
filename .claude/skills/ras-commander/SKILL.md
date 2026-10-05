---
name: ras-commander
description: "Coordinate HEC-RAS tasks through RAS Commander: identify the task, inspect project readiness, route to execution, results, geometry, GIS, or HMS specialists, and consolidate evidence. Use for requests to ask RAS Commander or handle a complete RAS workflow."
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
---

# RAS Commander

Serve as the task entry point for “Just Ask for RAS Commander.” Translate the request into a scoped workflow using the installed public library. This skill is a coordinator, not a new modeling engine or a guarantee that every operation is available.

## Intake and routing

Identify the project, requested result, engine/library versions, and whether the work is read-only, modifies inputs, or runs a model. Use existing authorization; ask only for missing consequential choices. Read the applicable repository/project guidance without applying repository editorial rules to external user deliverables.

Read [runtime and MCP boundaries](references/runtime-and-mcp.md) before choosing tooling. Inspect the installed package contracts; do not copy stale signatures from an agent definition.

| Task | Route |
|---|---|
| Project inventory/readiness | `hecras-project-inspector` where available; otherwise the installed RasPrj API |
| API discovery/integration | [RAS API Discovery](../ras-api-discovery/SKILL.md); current signatures and schemas |
| Plan execution | `hecras_plan_execution`, then the appropriate local/remote execution skill |
| Result interpretation | Results analyst or HDF specialist through public APIs |
| Geometry/QA | Geometry or QA specialist with explicit input-change scope |
| GIS/archive/map delivery | Shared `cloud-native-gis` skill |
| HMS or watershed-to-RAS work | Canonical `hms-commander` skill in the HMS repository if available; otherwise identify the missing integration before execution |
| Suspected Commander or MCP defect, feature gap, or contribution | [RAS Commander contributing](../ras-commander-contributing/SKILL.md); protect the user's task first |
| Repository writing review | Requested auditor; do not impose repository rules on user-created work |

Use native specialist/subagent mechanisms available in the current harness. Claude roles are adapters; Codex should use these shared instructions and available native workers, not assume Claude's Task syntax exists. Direct Python work is appropriate for a small task; delegate domains when useful. MCP calls always require the bounded subagent flow below.

Named repository roles and specialist skills are optional accelerators. A portable package includes only its selected workflows. If a named helper is absent, use the installed public Python API with the same authorization and dependency limits, or report the missing runtime capability. Do not assume a tool or role exists because it appears in a routing table.

## Coordinate and report

Give each worker a specific question, authorized project root, relevant versions, allowed operations, and expected output. Assign exclusive files when workers write, and tell them to preserve others' changes. Do not launch all specialists for every request.

Use RAS Commander APIs for RAS execution, preprocessing, project inspection, and extraction. Preserve source inputs unless the requested operation authorizes edits. Do not run models merely to answer an inventory question. Return the result, supporting versions/conditions, created or changed artifacts, and unresolved issues. Separate execution completion from model adequacy.

The brand phrase identifies this routing experience. It does not install dependencies, supply an HEC executable, or authorize project edits, uploads, publication, or deployment.
