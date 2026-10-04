---
name: ras-api-discovery
description: Find current RAS Commander public APIs, signatures, schemas, examples, and integration gaps. Use for API discovery and integration questions; this workflow does not extract model data.
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
---

# RAS API Discovery

Identify the requested capability and installed `ras-commander` version. Read [release and runtime boundaries](../ras-commander/references/runtime-and-mcp.md). Distinguish installed behavior, current published behavior, and repository development work.

Use public exports, signatures, docstrings, canonical schemas, and examples from the matching package/release. Search source when these do not establish an answer. Source inspection is appropriate for API discovery; it does not authorize copying parsers or bypassing public APIs to extract project data. Treat website/main examples as potentially newer than the installed release.

For DataFrames, consult the installed `schemas` module and the actual return contract rather than repeating a cached column table. Check whether the selected method is static or instance-based, its required extras/runtime, input semantics, return type, and side effects. Do not invoke a setter, initializer, compute method, download, or export merely to inspect its signature.

Split large investigations into focused source, example, or contract reviews using the harness's native worker mechanism when useful. Select workers based on the task and available capabilities; do not hardcode provider models or import a fictitious Task module. Give each reviewer the package version, question, scope, and concise evidence format. Preserve notebook outputs; read source cells without execution for discovery.

Return the supported method and verified signature, canonical schema/return fields, a version-matched usage example when available, required dependencies, source locators, and any unresolved API gap. Label an unexecuted example as unexecuted. Keep large research artifacts in the caller's authorized workspace only when needed. No fixed drive, repository location, or global project object is assumed.

Use the fuller Python workflow for project data. Any project MCP query requires a bounded informational subagent under the linked runtime contract. A discovered API is not evidence that its output or side effects satisfy that boundary.
