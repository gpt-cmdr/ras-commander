# Error Handling and Examples

Reference material for multi-model code review — graceful degradation, example sessions, and per-model troubleshooting.

## Graceful Degradation & Error Handling

Not all users have access to all four models. The skill handles failures gracefully.

### Common Failure Scenarios

1. **API Key Not Set**: Model provider requires authentication
2. **Rate Limit Exceeded**: Free tier limits reached
3. **Model Unavailable**: Service temporarily down
4. **Subagent Timeout**: Analysis took too long
5. **Permission Denied**: Insufficient access rights

### Failure Response Protocol

When a subagent fails:

```
1. Log the failure with specific error reason
2. Create placeholder report: workspace/{task}QAQC/{model}-analysis/qaqc-report.md
3. Content: "ANALYSIS FAILED: [specific reason]"
4. Continue with remaining successful models
5. Notify user which models succeeded/failed
```

### Minimum Viable Review

The skill works with as few as **1 successful model**:
- **1 model**: Single perspective (still valuable)
- **2 models**: Cross-validation possible
- **3 models**: Good consensus building
- **4 models**: Optimal coverage

### User Notification Template

```
Multi-Model Code Review Complete

Successful Models:
   - Opus: Analysis complete
   - Gemini: Analysis complete
   - Codex: Analysis complete

Failed Models:
   - Kimi K2.5: API key not configured (TOGETHER_API_KEY missing)

Proceeding with synthesis of 3/4 models...
```

### Fallback Strategy by Model Count

| Available Models | Strategy | Confidence Level |
|-----------------|-----------|------------------|
| 4/4 (all) | Full consensus analysis | Highest |
| 3/4 | Strong consensus with gap noted | High |
| 2/4 | Cross-validation sufficient | Good |
| 1/4 | Single expert opinion | Moderate |
| 0/4 | **Abort** - No models available | Failed |

### Handling Partial Results

**If Kimi K2.5 fails** (edge case expert):
- Note: "Edge case analysis incomplete - consider manual edge case review"
- Still proceed with Opus/Gemini/Codex consensus

**If Gemini fails** (large context expert):
- Note: "Multi-file pattern analysis may be incomplete"
- Other models may miss cross-file issues

**If Codex fails** (implementation expert):
- Note: "API contract analysis incomplete"
- Focus on Opus architecture + Gemini patterns

**If Opus fails** (reasoning expert):
- Note: "Deep reasoning analysis unavailable"
- Weight Codex implementation findings higher

### Recommended Model Priority

If you can only configure some models, prioritize:

1. **Opus** - Best overall reasoning (if available)
2. **Gemini** - Best for large/multi-file analysis
3. **Kimi K2.5** - Best for testing/edge cases
4. **Codex** - Best for implementation details

### Configuration Check

Before running, verify model availability:

```bash
# Check which models are available
opencode models | grep -E "(opus|gemini|codex|kimi)"

# Check API keys
echo $TOGETHER_API_KEY
echo $OPENAI_API_KEY
echo $GEMINI_API_KEY
```

## Example Sessions

### Example 1: All Models Available (Optimal)

```
User: /triple_model_code_review examples/720_precipitation_methods_comprehensive.ipynb "incremental vs cumulative confusion"

Claude: Creating workspace and launching 4 independent reviewers...

[Launches Opus, Gemini, Codex, Kimi K2.5 in parallel]

All four reviewers completed successfully

All four reviewers identified the same bugs:
- Line 810: DataFrame passed instead of column (All 4 found)
- Line 1396: DataFrame passed instead of column (All 4 found)
- Lines 1777-1789: np.cumsum on DataFrame (All 4 found)

Kimi K2.5 additionally identified:
- Missing test for empty DataFrame input
- Edge case: single-row DataFrame handling
- No validation for NaN values in precipitation data

Reports saved to workspace/notebook720QAQC/
```

### Example 2: Graceful Degradation (1 Model Fails)

```
User: /triple_model_code_review src/auth/login.py "security vulnerabilities"

Claude: Creating workspace and launching 4 independent reviewers...

[Launches Opus, Gemini, Codex, Kimi K2.5 in parallel]

Results:
Opus: Analysis complete
Gemini: Analysis complete
Codex: Analysis complete
Kimi K2.5: Failed - API key not configured

Note: Kimi K2.5 (edge case expert) unavailable. Edge case coverage may be incomplete.

3/4 models found these security issues:
- Line 45: SQL injection vulnerability (All 3 found)
- Line 78: Missing input validation (All 3 found)
- Line 23: Weak password hashing (Opus + Codex found)

Missing: Edge case analysis for malformed inputs (usually Kimi's strength)

Reports saved to workspace/loginQAQC/
```

### Example 3: Minimal Viable Review (2 Models)

```
User: /triple_model_code_review ras_commander/core.py "performance bottleneck"

Claude: Creating workspace and launching 4 independent reviewers...

Results:
Opus: Analysis complete
Gemini: Failed - Rate limit exceeded
Codex: Failed - Service unavailable
Kimi K2.5: Analysis complete

Proceeding with 2/4 models (Opus + Kimi)

Consensus findings:
- Line 234: O(n^2) loop identified by both
- Line 567: Memory leak in caching (Kimi found with test case)

Opus unique insight: Architectural recommendation to use generators
Kimi unique insight: Specific benchmark test showing 10x slowdown

Note: 2-model review sufficient for this scope. Consider re-running with all models for critical code.

Reports saved to workspace/coreQAQC/
```

## When to Weight Kimi's Findings Higher

Kimi K2.5 findings should be given extra weight when:
- **Edge cases are critical** (financial calculations, safety systems)
- **Testing is insufficient** (new codebase, legacy code)
- **Security matters** (user input handling, authentication)
- **Error handling is crucial** (production systems, data pipelines)

## Troubleshooting Model Failures

### Opus Failures

**Symptom**: "Model not available" or "Rate limit exceeded"

**Solutions**:
```bash
# Check Opus availability
opencode models | grep opus

# Alternative: Use Sonnet if Opus unavailable
opencode run -m claude-sonnet-4.5 "..."
```

### Gemini Failures

**Symptom**: "Gemini API error" or "Context length exceeded"

**Solutions**:
```bash
# Check Gemini API key
export GEMINI_API_KEY=your_key_here

# Try smaller context window model
opencode run -m gemini-1.5-flash "..."
```

### Codex Failures

**Symptom**: "Codex service unavailable" or "OpenAI error"

**Solutions**:
```bash
# Check OpenAI API key
export OPENAI_API_KEY=your_key_here

# Alternative: Use GPT-4o
opencode run -m gpt-4o "..."
```

### Kimi K2.5 Failures

**Symptom**: "Together.ai error" or "API key not found"

**Solutions**:
```bash
# Set Together.ai API key
export TOGETHER_API_KEY=your_key_here

# Alternative: Use Opencode's free Kimi
opencode run -m opencode/kimi-k2.5-free "..."

# Check Together.ai credits
curl -H "Authorization: Bearer $TOGETHER_API_KEY" \
  https://api.together.xyz/v1/models
```

### General Troubleshooting

**All models failing?**
1. Check internet connection
2. Verify opencode CLI: `opencode --version`
3. Check auth status: `opencode auth status`
4. Review logs: `opencode debug`

**Intermittent failures?**
- Retry with backoff: Wait 30 seconds and re-run
- Check rate limits: May need to upgrade tier
- Use fewer models: Start with 2-3 instead of 4

**Permission denied?**
- Check workspace directory permissions
- Ensure write access to `workspace/` folder
- Run from project root with proper access
