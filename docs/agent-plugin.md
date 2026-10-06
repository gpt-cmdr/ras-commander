# Agent Plugin and MCPs

RAS Commander is distributed to coding agents in three layers. Each layer has a deliberately different capability profile:

- The **RAS Commander and HMS Commander Python libraries** do the engineering work.
- The **RAS Commander agent plugin** teaches a local agent how to use those libraries and routes its work.
- Two small **MCP servers** answer quick, read-only questions about project text.

The plugin is intended for **local agents on Windows**, such as Claude Code or Codex running on the engineer's own workstation. That is the platform where HEC-RAS and HEC-HMS run, and where the project files and Python environment live.

RAS Commander is an independent open source project that complements and builds upon HEC's work by providing Python tools for HEC-RAS workflows. HEC-RAS is developed by the U.S. Army Corps of Engineers Hydrologic Engineering Center (HEC). RAS Commander is not affiliated with, endorsed by, or supported by HEC or USACE.

## Design philosophy

**The library does the work.** Every operation that runs a plan, reads HDF or DSS results, edits geometry, or produces GIS output goes through the public Python APIs of `ras-commander` and `hms-commander`. The plugin and the MCP servers do not reimplement these parsers or workflows.

**The MCP servers are a quick lookup, not a second API.** They read approved project text and return bounded, non-spatial answers, such as units, plan settings, and HMS control times. They never change a project, run an engine, or read binary, spatial, or gridded data. A question that outgrows them moves to Python; the MCP tools are not widened to answer it.

**MCP calls stay out of the main conversation.** Project text is large and is untrusted input. The plugin gives each MCP server its own read-only subagent. A guard hook rejects any call that comes from the main conversation, so raw project text stays in a disposable subagent context.

**Stay current with released packages.** The plugin installs the MCP servers from PyPI and checks for newer releases in the background. It notifies the user and never upgrades an environment during a task or overrides a pinned version.

**Fix problems where they occur.** The plugin includes a contribution workflow:

- When an agent run by a maintainer finds a defect, it reproduces the problem with public or synthetic data, fixes it in a separate clone, adds a regression test, and opens a pull request. A maintainer is a user whose GitHub account can push to the affected repository.
- Other users get a drafted issue or pull request. Feature requests are first checked against the API consistency criteria.
- Nothing is submitted publicly without the user's approval, and private project data stays out of issues, pull requests, and tests.

## Capability profiles

| Component | Install | What it can do | What it does not do |
|---|---|---|---|
| [ras-commander](https://github.com/gpt-cmdr/ras-commander) library | `pip install ras-commander` | The full HEC-RAS workflow: project initialization, plan execution, HDF and DSS results, geometry, boundary conditions, quality checks, GIS export, and project edits when authorized | Nothing is withheld. Engine execution requires a local HEC-RAS installation |
| [hms-commander](https://github.com/gpt-cmdr/hms-commander) library | `pip install hms-commander` | The HEC-HMS workflow: basin, meteorology, control, and run files; DSS results; Atlas 14 and frequency storms; GIS; HMS-to-RAS handoff | Engine execution requires a local HEC-HMS installation |
| [RAS Commander agent plugin](https://github.com/gpt-cmdr/ras-commander-plugin) | Claude Code or Codex plugin (below) | Skills that route RAS, HMS, GIS, HMS-to-RAS, and contribution tasks to the libraries. On Claude Code it also bundles both MCP servers, one read-only subagent per server, the guard hook, and the update check | It does not install HEC software or Python extras, and grants no file access the host agent does not already have |
| [ras-commander-mcp](https://github.com/gpt-cmdr/ras-commander-mcp) | `uvx ras-commander-mcp` | Five read-only tools: `server_information`, `project_units`, `plan_description`, `project_metadata`, and `plan_configuration`. They read `.prj` and `.p01`–`.p99` text within approved roots | No geometry, HDF, DSS, grids, execution, edits, or exports |
| [hms-commander-mcp](https://github.com/gpt-cmdr/hms-commander-mcp) | `uvx hms-commander-mcp` | Two read-only tools: `server_info` and `read_hms_sections`. The second returns named sections and approved scalar fields from `.hms`, `.basin`, `.met`, `.control`, `.run`, and `.gage` text within approved roots | No DSS, SQLite, spatial, or gridded data, execution, or edits |

**MCP bounds.** Both servers limit each request to 100 rows and 16,000 characters, and each read to 30 seconds. The file-size limit is 1 MiB for the RAS server and 2 MiB for the HMS server. Every answer reports the source file's SHA-256 hash and size, and the installed package versions.

**Library requirements.** ras-commander-mcp 0.4.0 needs ras-commander 0.104.0 or later for the metadata and configuration tools. hms-commander-mcp 0.1.1 needs hms-commander 0.4.0.

### Host support

| Host | Skills | MCP through subagents |
|---|---|---|
| Claude Code, local, on Windows or Linux | Yes | Yes |
| Codex, local | Yes | No: subagent-only MCP access has not been demonstrated on Codex, so its distribution contains the skills only. Project reads on Codex use the Python libraries |
| claude.ai and other hosted chat | Skills only, where the host supports them | No: hosted sessions cannot reach local project files |

## Why local agents on Windows

The plugin assumes an agent working on the engineer's workstation, with access to the project folders, a Python environment with the libraries, and, for execution, HEC-RAS or HEC-HMS. HEC-RAS and HEC-HMS are Windows desktop applications, and RAS Commander's execution workflows run them locally. The text MCP servers also run on Linux, but most project work assumes a Windows workstation.

The MCP servers read files through Windows extended-length paths, so deep project folders work even when a path exceeds 260 characters. Other tools on the workstation can still fail on long paths. Enabling Windows long paths from an elevated prompt avoids those failures; no reboot is required for newly started programs:

```powershell
reg add HKLM\SYSTEM\CurrentControlSet\Control\FileSystem /v LongPathsEnabled /t REG_DWORD /d 1 /f
```

## Qualification evidence

The MCP servers were tested with a corpus of real and official example project text: 983 HEC-RAS project and plan files, and 586 HEC-HMS files. The corpus spans RAS plan versions 3.10 through 6.60 and HMS versions 3.5 through 4.12. Tests ran on Linux and through a network-share root on Windows.

- **Answers:** every response was checked against its JSON schema, the source hash and size, and an independent line-based reading of the same file. Windows and Linux returned the same content for every file both could reach; for 16 HMS files only the page boundaries differed, because the longer network root used more of each response's size budget.
- **Long paths:** after the long-path fix, all 69 RAS and 44 HMS files whose network path reached 260 characters were also read correctly on Windows.
- **Source files:** no source file changed during any run.
- **Published packages:** the PyPI packages reproduced the results of the source checkout.

These checks establish text-reading behavior and compatibility. They do not establish hydraulic or hydrologic results.

The plugin was tested in Claude Code 2.1.287 on October 5 and 6, 2026:

- A direct MCP call from the main conversation was rejected with an instruction to delegate.
- The same question asked through the subagent returned the expected values and source hash.

## Install

Claude Code:

```sh
claude plugin marketplace add gpt-cmdr/ras-commander-plugin
claude plugin install ras-commander@ras-commander-plugin
```

The MCP servers start through `uvx`, so install [uv](https://docs.astral.sh/uv/) first. By default each server may read only the current project folder; the plugin's `extra_roots` option adds other folders.

For Codex installation, see the [plugin repository](https://github.com/gpt-cmdr/ras-commander-plugin).

## Updates

- **Plugin:** run `claude plugin marketplace update ras-commander-plugin`, then `claude plugin update ras-commander@ras-commander-plugin`, and restart Claude Code.
- **MCP servers:** `uvx` reuses its cached copy, and picks up a new PyPI release once uv's package index cache is more than 10 minutes old. To refresh immediately, clear both the server and its library:

  ```sh
  uv cache clean ras-commander-mcp ras-commander
  uv cache clean hms-commander-mcp hms-commander
  ```

- **Notifications:** the plugin's session-start check reports available updates and never installs them.

## Repositories

| Repository | Contents |
|---|---|
| [gpt-cmdr/ras-commander](https://github.com/gpt-cmdr/ras-commander) | RAS Commander library and its canonical agent skills |
| [gpt-cmdr/hms-commander](https://github.com/gpt-cmdr/hms-commander) | HMS Commander library and its canonical agent skills |
| [gpt-cmdr/ras-commander-plugin](https://github.com/gpt-cmdr/ras-commander-plugin) | Agent plugin and marketplace, generated from the libraries' released skills |
| [gpt-cmdr/ras-commander-mcp](https://github.com/gpt-cmdr/ras-commander-mcp) | Read-only HEC-RAS text MCP server |
| [gpt-cmdr/hms-commander-mcp](https://github.com/gpt-cmdr/hms-commander-mcp) | Read-only HEC-HMS text MCP server |

Report problems or request features as issues in the repository that owns the behavior.
