# Portable Commander plugin

Canonical skills remain under `.claude/skills/`. The portable package is generated from the selected sources in `package.json`; it is not a manually maintained copied skill corpus. The generator follows local inline and reference-style Markdown links (including angle-bracket targets), bundles supporting files, rebases links, checks containment, and records source and packaged SHA-256 hashes. Generated distributions belong in ignored scratch or CI artifacts.

## Assemble and discover

From the repository root, choose a new disposable destination:

```sh
python scripts/agent_framework/build_plugin.py --output /tmp/commander-plugin-candidate
```

Local HTML links are rejected; directory/escaping targets fail assembly. Use supported Markdown links for bundled resource references.

The output has root `plugin.json`, `skills/`, supporting resources when needed, and `source-provenance.json`. Its plugin version is independent of the Python package, protocol, and MCP server versions. Change the plugin version when releasing updated instructions; regenerate rather than editing the bundle. Instructions use current installed contracts instead of copied API catalogs.

Use the current host's supported local plugin/marketplace import or submission flow. For Codex local marketplace setup, consult [official packaging guidance](https://developers.openai.com/plugins/build/plugins); select this generated folder as the plugin source. In a repository checkout, the existing `sync_codex_skill_bridge.py` remains the direct skill discovery route. Claude-native role files remain thin repository adapters; this portable artifact does not bundle a second set of role policies.

This first distribution is skills-only: no MCP manifest, hooks, automatic install, remote execution, or publication. A hosted ChatGPT installation has only the tools and runtime actually exposed to that host. Importing instructions does not grant Python, local filesystem access, an HEC executable, or a local coding-agent environment. Local agent workflows also require authorized project access, current public packages, appropriate extras, and engine installation when execution is requested.

## Tool boundary and activation evidence

RAS/HMS project MCP calls are bounded read-only informational subagent tasks. The client must isolate MCP exposure to the child; a skill cannot enforce that tool configuration, and a server cannot reliably attest caller identity. Do not add MCP wiring until the server contracts and client isolation have been qualified. A host without subagent tool routing uses scoped Python with its actual runtime or reports the missing capability. The main coordinator never calls project MCP as a fallback.

The fuller experience comes from public Python APIs with the dependencies and authorization required for that task. Geometry, GIS, gridded/binary data, execution, edits, exports, and publication do not become MCP operations. Repository writing standards apply to repository contributions only; external user reports/maps/notebooks follow the user's requirements.

Before claiming “Just Ask” activation on a host, demonstrate discovery, direct/indirect invocation, version discovery, relevant domain routing, bounded delegation, Python handoff, missing-tool behavior, and scoped output on that host. Packaging alone is not an activation demonstration. Installed/imported skills are snapshots; updates require regeneration and host refresh or rescan/republication as applicable. See [official skill guidance](https://developers.openai.com/plugins/build/skills).

## Release maintenance

`release-watch.json` lists distributions whose current stable PyPI metadata informs maintenance. `refresh_release_snapshot.py` records released versions, dependency metadata, archive identity/hashes, and missing/unavailable sources. It never installs packages, edits dependency pins, widens compatibility bounds, accepts HEC terms, or publishes anything. Metadata discovery is not evidence of tested compatibility.

The GitHub workflow assembles the portable distribution as an artifact and opens an update PR when release metadata changes. It runs on repository release publication, weekly, or manually; it does not depend on a workflow from another repo. Library/MCP maintainers must review drift, run their minimum/latest contract and packaging checks, and publish exact qualified versions before declaring compatibility. Preserve offline/user-pinned environments; report updates rather than changing them during an agent query.

Update PR creation requires GitHub Actions write/PR permissions and the repository setting allowing Actions to create pull requests. The workflow declares requested permissions; administrators may still prohibit this capability. No repository setting is changed by the workflow. If denied, retain the generated artifact/log and make the update PR through an authorized maintainer. No workflow auto-merges, publishes to PyPI, installs into user environments, or submits a plugin to a directory.

For current Claude Code client isolation, the official [subagent guide](https://code.claude.com/docs/en/sub-agents#scope-mcp-servers-to-a-subagent) documents inline `mcpServers` on the informational child definition, instead of connecting the project server globally. Trust/host version and available server configuration still need qualification. Updated repository adapters use Claude's current `Agent` delegation tool name; portable skills do not prescribe that name for other hosts. No server configuration is activated by this package.
