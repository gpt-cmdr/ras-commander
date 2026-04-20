# /dual-qaqc — Dual-Oracle Cross-Validation

**Trigger**: `/dual-qaqc [topic or target]`

Run the same analysis through two independent AI oracles (Codex CLI at xhigh thinking + Claude Opus) and reconcile findings. Items where both agree are high-confidence. Divergences require human review.

**Use for**: API consistency audits, algorithmic correctness checks, security reviews, QAQC of complex outputs, design decisions with non-obvious tradeoffs.

---

## Workflow

### Step 1: Frame the Question

Formulate a precise, answerable question. Vague questions produce useless divergence.

```
Good: "Does HdfResultsPlan.get_compute_messages() handle the case where the HDF 
       exists but the compute messages group is missing? Check lines 720-830."

Bad: "Is this code good?"
```

### Step 2: Write Context to a File

Save the code/question to a temp file so both oracles get identical input:

```bash
cat > /tmp/dual-qaqc-context.md << 'EOF'
# Dual-QAQC Context — [topic]

## Question
[Precise question]

## Code Under Review
[Paste relevant code or file path]

## What to Check
- [Specific concern 1]
- [Specific concern 2]
EOF
```

### Step 3: Invoke Codex Oracle

Dispatch to `code-oracle-codex` agent (see `.claude/agents/code-oracle-codex.md`):

```
@code-oracle-codex: Review /tmp/dual-qaqc-context.md
- Answer the question in the context file
- Flag any issues you find that weren't asked about
- Assign confidence: High / Medium / Low to each finding
- Write findings to: .claude/outputs/dual-qaqc/{date}-codex.md
```

### Step 4: Invoke Opus Oracle

Run the same context through Claude Opus (max thinking if available):

```
@opus: Review /tmp/dual-qaqc-context.md
- Same instructions as Codex oracle above
- Write findings to: .claude/outputs/dual-qaqc/{date}-opus.md
```

### Step 5: Reconcile

Compare the two outputs:

```
Agreement     → High confidence finding → act on it
Disagreement  → Flag for human review → do NOT resolve automatically
One found, one missed → Medium confidence → investigate further
```

### Step 6: Write Reconciled Report

```markdown
# Dual-QAQC: [Topic] — {date}

## High-Confidence Findings (Both Agree)
- [Finding]: [Action required]

## Divergences (Human Review Required)
- [Topic]: Codex says X, Opus says Y — [why this matters]

## One-Sided Findings (Investigate Further)
- [Finding from Codex only]: [Codex confidence]
- [Finding from Opus only]: [Opus confidence]

## Verdict
[Overall assessment and recommended action]
```

Save to: `.claude/outputs/dual-qaqc/{date}-{topic}-reconciled.md`

---

## Model Guidance

| Oracle | Strengths | Run when |
|--------|-----------|----------|
| Codex CLI (xhigh) | Code logic, security, edge cases | Always |
| Claude Opus (extended thinking) | Architecture, tradeoffs, broader context | Always |
| Claude Sonnet | Speed, iteration | Skip for dual-qaqc (use for drafts) |

**xhigh thinking** = Codex CLI's maximum reasoning budget. Use `--thinking xhigh` flag.

---

## Output Location

`.claude/outputs/dual-qaqc/`

```
{date}-{topic}-codex.md      ← Codex oracle findings
{date}-{topic}-opus.md       ← Opus oracle findings
{date}-{topic}-reconciled.md ← Final reconciled report
```

---

*Cross-references*: `code-oracle-codex` agent, `code-oracle-gemini` agent, `/agent-oracle-codex` command
