# .agents

This directory is the Codex-facing adapter layer for agent framework content.

The shared source of truth remains the `AGENTS.md` hierarchy. Shared skill
sources currently live under `.claude/skills/`; Codex-only adapter skill sources
live under `.agents/native-skills/`.

Do not edit generated skill bridge entries under `.agents/skills/` directly.
Regenerate them with:

```bash
python scripts/agent_framework/sync_codex_skill_bridge.py
```

Generated `.agents/skills/` entries may point to:

- approved shared-domain skills in `.claude/skills/`
- approved Codex-native adapter skills in `.agents/native-skills/`

Codex hook configuration does not live here. Project hooks live in `.codex/`
and call shared hook code in `scripts/agent_hooks/`.

External agent-facing plugins and skills should come from `gpt-cmdr` or official Anthropic/OpenAI repositories. Third-party plugins or skills from outside those sources must be security-audited and re-implemented in this repository before they become part of the standard workflow.
