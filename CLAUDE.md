@AGENTS.md

## Claude Adapter Notes

- Claude auto-loads `.claude/rules/`. Treat those files as Claude-specific preload helpers, not the shared source of truth.
- If a rule matters to Codex too, move it into the `AGENTS.md` hierarchy or a shared skill before keeping a Claude-specific accelerator copy.
- Use `.claude/MANIFEST.md` to discover relevant Claude-native rules, skills, agents, and commands.
- Use `.claude/agents/` for Claude-native delegation. Shared repository behavior still comes from `AGENTS.md`.
