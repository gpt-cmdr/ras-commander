# Comparison, Tips, and Troubleshooting

Reference material for Kimi CLI — model comparison guide, usage tips, troubleshooting, and integration patterns.

## Comparison: When to Use Kimi vs Gemini vs Codex

| Task | Kimi K2.5 | Gemini | Codex |
|------|:---------:|:------:|:-----:|
| Test generation | Excellent | Excellent | Excellent |
| Edge case detection | Excellent | Excellent | Viable |
| Code coverage analysis | Excellent | Excellent | Viable |
| QA verification | Excellent | Excellent | Viable |
| Security-focused code review | Excellent | Excellent | Viable |
| General code review | Excellent | Excellent | Viable |
| Test maintenance | Excellent | Excellent | Excellent |
| Implementation | Viable | Viable | Excellent |
| Refactoring | Viable | Viable | Excellent |
| Large codebase analysis | Excellent | Excellent | Viable |
| Documentation review | Excellent | Excellent | Viable |

### Decision Guide

**Use Kimi K2.5 (via Opencode/Together.ai) when:**
- Primary goal is generating comprehensive test suites
- You need thorough edge case identification
- QA verification of existing implementations
- Security-focused code reviews
- Testing TypeScript/JavaScript/Python code
- Free tier with generous limits (2,000 req/day via Opencode)

**Use Gemini (via Gemini CLI) when:**
- Code review is the primary goal (not test generation)
- You need 1M+ token context for large codebase analysis
- Documentation review and knowledge extraction
- Security audits without test generation
- Maximum context window needed

**Use Codex (via Codex CLI) when:**
- Primary goal is implementation or refactoring
- Test generation is secondary to code changes
- Complex multi-file modifications needed
- Heavy reasoning tasks beyond testing

## Integration with Other Skills

**Works well with:**
- `dev_invoke_gemini-cli` - Cross-verify test coverage with Gemini
- `dev_invoke_codex-cli` - Implement fixes after Kimi identifies issues
- `using-git-worktrees` - Create isolated workspace for test development
- `triple-model-code-review` - Multi-model validation

**Sequence example:**
```
1. Kimi K2.5: Generate tests -> Identify uncovered edge cases
2. Codex: Implement missing edge case handling
3. Kimi K2.5: Verify fixes and regenerate tests
4. Gemini: Review final implementation
```

## Tips

1. **Include full code** - Paste actual code in TASK.md, don't just reference files
2. **Specify test framework** - Tell Opencode exactly which framework to use
3. **Define coverage targets** - Set clear coverage expectations
4. **List edge cases explicitly** - Ask Kimi K2.5 to identify additional edge cases
5. **Request specific output** - Define exactly what OUTPUT.md should contain
6. **Use full model path** - Use `opencode/kimi-k2.5-free` not just `kimi-k2.5`
7. **Mock external dependencies** - Remind Opencode to mock databases, APIs, etc.
8. **Test data examples** - Provide sample inputs/outputs for clarity
9. **Try piping input** - If `run` command fails, use `cat prompt.txt | opencode run ...`
10. **Use interactive mode** - Start with `opencode . -m <model>` for complex tasks

## Troubleshooting

### Issue: "Session not found" error
**Solution:** Use interactive mode instead:
```bash
opencode . -m opencode/kimi-k2.5-free
```

### Issue: "DecimalError" with Together.ai
**Solution:** This is cosmetic - the output is still generated. Use the interactive mode or piping method.

### Issue: API key errors
**Solution:** Set the appropriate environment variable:
```bash
export TOGETHER_API_KEY=your_key_here
# or
export MOONSHOT_API_KEY=your_key_here
```

## Session Management

- Use `opencode --continue` to resume last session
- Use `opencode -s <session_id>` to resume specific session
- Sessions are stored locally by Opencode
- Session IDs appear in OUTPUT.md for reference
