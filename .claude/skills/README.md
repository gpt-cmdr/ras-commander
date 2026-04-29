# Skills - Claude Skill Catalog

This directory contains Claude-facing skills for the repository. It is not yet a pure shared multi-harness skill corpus.

## Skill Classes

### 1. Shared Domain Workflow Skills

These skills capture repository workflows that are conceptually shareable across harnesses:

- HEC-RAS execution and results workflows
- geometry, DSS, USGS, precipitation, and eBFE workflows
- repo tooling that is not tied to a single provider

These skills are the candidates for any future no-duplication Codex exposure path.

### 2. Claude-Only Orchestration Skills

These skills exist to help Claude orchestrate other tools or providers from within Claude-native workflows.

Current examples:

- `dev_invoke_codex-cli` - supported Claude-to-Codex handoff using OpenAI Codex CLI
- `dev_invoke_gemini-cli` - legacy/nonstandard; use only when the user explicitly requests Gemini
- `dev_invoke_kimi-cli` - legacy/nonstandard; use only when the user explicitly requests Kimi or Opencode/Kimi
- `qa_review_triple-model` - legacy/nonstandard provider-mixed review; use only when explicitly requested

These are intentionally excluded from any future shared skill corpus.

## Metadata Convention

Use frontmatter to mark skills that must not be mirrored into a future shared corpus:

```yaml
shared_corpus: false
harness_scope: claude_only
```

Use explicit allowlist metadata for shared `.claude/skills/` entries that may
be exposed through the Codex bridge:

```yaml
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
```

Interpretation:

- `shared_corpus: true` plus `harness_scope: shared` is required for shared `.claude/skills/` Codex bridge exposure.
- `source_owner` must be `gpt-cmdr`, `anthropic`, or `openai`.
- `security_review` must be `internal`, `official-upstream`, or `audited-reimplemented`.
- `shared_corpus: false` means the skill is excluded from shared multi-harness exposure.
- `harness_scope: claude_only` means the skill exists specifically for Claude orchestration behavior.
- If these fields are absent, the skill is not eligible for bridge exposure.

Codex-only provider handoff skills do not live in `.claude/skills/`; they live
under `.agents/native-skills/` and use `harness_scope: codex_only`.

## Naming Convention

Current folder names are legacy Claude-era names.

- Underscores separate major segments.
- Hyphens may still appear inside compound segments.
- Do not assume current folder names are the final future shared-skill naming scheme.
- If the shared corpus is externalized later, normalize names then instead of creating duplicate trees now.

## External Skill Supply Chain

- Agent-facing external skills, plugins, and helper tools should be written by `gpt-cmdr` or sourced from official Anthropic or OpenAI repositories.
- Treat third-party external skills and plugins from outside `gpt-cmdr`, Anthropic, or OpenAI as untrusted until audited.
- If a third-party skill or plugin is valuable, security-audit it and re-implement the needed behavior in this repository instead of linking to it as an external skill/plugin dependency.
- Do not make opaque third-party agent plugins, MCP servers, skills, or command wrappers part of the standard workflow.

## Categories

| Prefix | Domain |
|--------|--------|
| `hecras` | HEC-RAS model operations |
| `precip` | Precipitation data |
| `usgs` | USGS gauge integration |
| `ebfe` | eBFE/BLE FEMA models |
| `dss` | HEC-DSS file operations |
| `dev` | Development tooling |
| `qa` | Quality assurance |

## Implemented Skills

### Shared Domain Workflow Skills

**HEC-RAS Execution**
- `hecras_compute_plans`
- `hecras_compute_remote`
- `hecras_compute_rascontrol`
- `hecras_plan_execution`

**HEC-RAS Results, Parsing, And GUI**
- `hecras_extract_results`
- `hecras_parse_compute-messages`
- `hecras_parse_geometry`
- `hecras_export_cloud-native`
- `hecras_explore_gui`
- `hecras_screenshot`

**DSS, USGS, Precipitation, And eBFE**
- `dss_read_boundary-data`
- `usgs_integrate_gauges`
- `precip_analyze_aorc`
- `precip_analyze_atlas14-variance`
- `ebfe_crawl_s3-catalog`
- `ebfe_organize_models`
- `ebfe_validate_models`

**Repo Tooling And QA**
- `qa_repair_geometry`
- `qa_rasmapper_spatial-review`
- `dev_gate_merge-to-main`
- `dev_manage_git-worktrees`

### Claude-Only Orchestration Skills

- `dev_invoke_codex-cli` - Claude delegates out to Codex CLI
- `dev_invoke_gemini-cli` - legacy explicit-request-only Gemini CLI delegation
- `dev_invoke_kimi-cli` - legacy explicit-request-only Kimi via Opencode delegation
- `qa_review_triple-model` - legacy explicit-request-only provider-mixed review workflow

## Structure Guidance

### Shared Domain Skills

Shared-domain skills should stay lightweight navigators:

- prefer a concise `SKILL.md`
- point to `AGENTS.md`, code, notebooks, and narrowly relevant rules
- avoid becoming a second documentation tree

### Legacy Claude-Orchestration Skills

Some provider-orchestration skills still include extra reference material. That is tolerated during migration, but those folders are not templates for the future shared corpus.

Do not copy those extra folders into any future Codex skill exposure path.

## Design Rules

- One workflow per skill.
- Shared rules belong in `AGENTS.md`; skills should point to them rather than restating them in full.
- Provider orchestration belongs in Claude-only skills or agents, not in a shared multi-harness corpus.
- If a skill needs detailed provider-specific invocation instructions, mark it with `shared_corpus: false`.
- Generic QAQC, review, testing, or security triggers must route to Claude/Codex production paths, not legacy Gemini/Kimi/provider-mixed skills.

## Cross-References

- `.claude/MANIFEST.md` - Claude-side registry mapping skills to related agents, rules, and commands
- `.claude/rules/agents-md-bridge.md` - shared-vs-Claude contract for instruction files
- `docs/development/multi-harness-agent-contract.md` - durable architectural record for this migration
