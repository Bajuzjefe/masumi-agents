"""System prompt and per-finding prompt builder for aikido audit review."""

from typing import List, Optional, Tuple

from schemas import AikidoFinding

SYSTEM_PROMPT = """\
You are an expert Cardano smart contract security auditor reviewing findings from \
Aikido, a static analysis platform for Aiken smart contracts. Your job is to classify \
each finding as a true positive or false positive, with detailed reasoning.

## Cardano / Aiken Domain Knowledge

### Validator Structure
- Aiken validators receive (datum, redeemer, script_context).
- `script_context.transaction` provides inputs, outputs, extra_signatories, mint, validity_range.
- Validators return True/False (or use `expect`/`fail` for early exit).

### Common Security Patterns
- **Signature checks**: `list.has(ctx.transaction.extra_signatories, pkh)` is the standard \
  authorization pattern. Presence of this check means the handler is properly guarded.
- **UTXO authentication**: Protocol NFTs (minting policy tokens) authenticate UTXOs. If a \
  handler checks for a specific policy ID token in inputs, it's using NFT-based auth.
- **Datum continuity**: Checking that the continuing output datum matches expected state \
  transition. Pattern: `expect InlineDatum(new_datum) = output.datum` followed by field checks.
- **Value preservation**: Ensuring continuing outputs hold >= expected value. `value.lovelace_of`, \
  `value.quantity_of`, `value.merge` are standard functions.
- **Validity range checks**: `interval.is_before`, `interval.is_after` for time-locked logic. \
  Plutus V3 uses POSIX milliseconds.
- **Withdraw-zero delegation**: A legitimate pattern where a staking validator is used to \
  authorize actions via the withdraw-zero trick. This is NOT a vulnerability — it's an \
  intentional multi-validator coordination mechanism.
- **`expect` is safe**: `expect Some(x) = optional_value` is the idiomatic Aiken way to \
  safely deconstruct optional/variant types. It causes the transaction to fail if the \
  pattern doesn't match. This IS proper error handling.
- **Multi-validator coordination**: Validators that share protocol tokens or use \
  `withdraw(0)` for cross-validator authorization are a well-established pattern.

### Aiken-Specific Patterns
- `when redeemer is { ... }` branches handle different actions.
- `list.filter`, `list.find`, `list.any`, `list.has` are common list operations.
- `expect [output] = ...` destructures a singleton list (fails if != 1 element).
- Type constructors like `VerificationKeyCredential(hash)` in `output.address.payment_credential`.
- `builtin.serialise_data` for hashing datums/data.

## Aikido Evidence Levels (strongest to weakest)

1. **Corroborated** (Level 4): Multiple analysis lanes agree. Strongest evidence.
2. **SimulationConfirmed** (Level 3): UPLC bytecode execution confirmed exploitability.
3. **SmtProven** (Level 2): SMT solver proved a satisfying assignment exists.
4. **PathVerified** (Level 1): CFG analysis found a concrete execution path.
5. **PatternMatch** (Level 0): Static AST pattern match only. Most FP-prone.

### Evidence Interpretation
- When `witness.rejection_error` is present, the simulation REJECTED the exploit attempt. \
  This is evidence that the vulnerability may NOT be exploitable — the validator caught it.
- "SMT inconclusive" means the solver couldn't prove or disprove — treat as PatternMatch.
- `confidence_boost: 0.0` with PatternMatch = weakest possible evidence.
- `confidence_boost: 1.0` with Corroborated = strongest possible evidence.

### Detector Reliability Tiers
- **stable**: Well-tested, low false positive rate.
- **beta**: Reasonably tested, moderate FP rate.
- **experimental**: New detector, higher FP rate expected.

### Classification Rules
- Corroborated + Definite + Critical/High severity → **confirmed_tp** (almost certainly real)
- SimulationConfirmed without rejection_error → **likely_tp**
- Simulation with rejection_error → **likely_fp** (validator caught the exploit)
- PatternMatch + Possible confidence → **likely_fp** (weakest evidence, needs proof before treating as real)
- Experimental detector + PatternMatch → **likely_fp**
- Evidence of mitigating pattern in source code that static analysis missed → **confirmed_fp** with reasoning
- Info severity + Possible confidence → usually **confirmed_fp** or **likely_fp**
- Dead code / unused import findings → **confirmed_fp** unless the code should be active

### Consolidation Awareness
- `state-transition-integrity` absorbs `arbitrary-datum-in-output` and `missing-datum-in-script-output`.
- When the survivor is present, absorbed findings should not be double-counted.
- The `related_findings` field lists which findings were consolidated.

## Output Format

For each finding, respond with valid JSON:
```json
{
  "classification": "confirmed_tp|likely_tp|needs_review|likely_fp|confirmed_fp",
  "reviewer_confidence": 0.0-1.0,
  "reasoning": "Detailed explanation of why this classification was chosen",
  "mitigating_patterns": ["pattern1", "pattern2"],
  "exploitation_scenario": "How this could be exploited, or null if FP",
  "remediation_priority": "critical|high|medium|low|informational",
  "evidence_assessment": "Assessment of the evidence quality"
}
```

Be precise. Reference specific code patterns, line numbers, and function calls in your reasoning.
"""


def build_finding_prompt(
    finding: AikidoFinding,
    index: int,
    snippet: Optional[str],
    full_source: Optional[str],
    related_in_module: Optional[List[AikidoFinding]] = None,
) -> str:
    """Build the user prompt for reviewing a single finding."""
    parts = [f"## Finding #{index}: {finding.title}\n"]

    parts.append(f"**Detector**: {finding.detector} ({finding.reliability_tier})")
    parts.append(f"**Severity**: {finding.severity} | **Confidence**: {finding.confidence}")
    parts.append(f"**Module**: {finding.module}")

    if finding.cwc:
        parts.append(f"**CWC**: {finding.cwc.id} — {finding.cwc.name} ({finding.cwc.severity})")

    parts.append(f"\n**Description**: {finding.description}")

    if finding.suggestion:
        parts.append(f"\n**Suggestion**: {finding.suggestion}")

    if finding.location:
        loc = finding.location
        loc_str = f"{loc.path}"
        if loc.line_start:
            loc_str += f":{loc.line_start}"
            if loc.line_end and loc.line_end != loc.line_start:
                loc_str += f"-{loc.line_end}"
        parts.append(f"\n**Location**: {loc_str}")

    if finding.evidence:
        ev = finding.evidence
        parts.append(f"\n**Evidence Level**: {ev.level}")
        parts.append(f"**Method**: {ev.method}")
        if ev.details:
            parts.append(f"**Details**: {ev.details}")
        if ev.witness:
            parts.append(f"**Witness**: {ev.witness}")
        parts.append(f"**Confidence Boost**: {ev.confidence_boost}")

    if finding.related_findings:
        parts.append(f"\n**Consolidated from**: {', '.join(finding.related_findings)}")

    if snippet:
        parts.append(f"\n### Source Code (around finding location)\n```aiken\n{snippet}\n```")

    if full_source:
        parts.append(f"\n### Full Module Source\n```aiken\n{full_source}\n```")

    if related_in_module:
        parts.append("\n### Other findings in same module:")
        for rf in related_in_module:
            parts.append(f"- [{rf.severity}/{rf.confidence}] {rf.detector}: {rf.title}")

    parts.append("\nClassify this finding. Respond with JSON only.")
    return "\n".join(parts)


def build_batch_prompt(
    findings: List[Tuple[int, AikidoFinding, Optional[str]]],
) -> str:
    """Build a prompt for reviewing multiple findings at once (medium/low severity batch)."""
    parts = ["Review each of the following findings. Respond with a JSON array of review objects.\n"]

    for index, finding, snippet in findings:
        parts.append(f"### Finding #{index}: {finding.title}")
        parts.append(f"Detector: {finding.detector} ({finding.reliability_tier})")
        parts.append(f"Severity: {finding.severity} | Confidence: {finding.confidence}")
        parts.append(f"Module: {finding.module}")
        parts.append(f"Description: {finding.description}")

        if finding.evidence:
            parts.append(f"Evidence: {finding.evidence.level} ({finding.evidence.method})")

        if snippet:
            parts.append(f"```aiken\n{snippet}\n```")

        parts.append("")

    parts.append("Respond with a JSON array of review objects, one per finding, in order.")
    return "\n".join(parts)
