# Documentation Contract

This file is the canonical local instruction file for `docs/`.

## Scope

- Parent guidance from the repository root `AGENTS.md` still applies.
- `docs/` is the MkDocs source tree for published documentation.

## Working Rules

- Treat markdown in `docs/` as the source of truth for published docs.
- Update `mkdocs.yml` when adding, removing, or renaming pages in the navigation.
- Keep documentation changes close to the code or agent-framework changes that require them.
- When documenting the agent framework, treat [docs/development/multi-harness-agent-contract.md](development/multi-harness-agent-contract.md) as the architectural record.

## Generated And Special Docs

- `docs/cognitive-infrastructure/` is generated from `.claude/` inventory and helper scripts. Prefer editing the source inputs or generator rather than hand-maintaining generated summaries.
- `docs/examples/` should stay aligned with notebook numbering and real notebook behavior.

## Citation And Recognition

- Preserve `docs/cite.md` as the canonical citation, sharing, contribution, and
  support page at https://rascommander.info/ras/cite/.
- Keep the citation page and the short agent-facing recognition guidance in the
  generated `llms.txt` corpus.
- Preserve the subtle citation, upstream-contribution, and technical-assistance
  links in the documentation footer.
- Keep contributor and prior-work recognition aligned with
  `docs/about/acknowledgments.md`; do not replace it with incomplete duplicate
  lists on other pages.

## Build Rules

- Validate docs with `mkdocs build --strict` when documentation structure changes.
- ReadTheDocs strips symlinks. Do not rely on symlinked doc content in published docs.

## Style

- Keep docs concrete and path-accurate.
- Prefer relative repository references that stay valid in MkDocs.
