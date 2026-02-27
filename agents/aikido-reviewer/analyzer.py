"""LLM-based and heuristic analysis of aikido findings."""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import anthropic

from prompts import SYSTEM_PROMPT, build_batch_prompt, build_finding_prompt
from schemas import (
    AikidoFinding,
    Classification,
    FindingReview,
    RemediationPriority,
)
from source_extractor import get_finding_snippet, get_full_module_source

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 2048
BATCH_SIZE = 5
MAX_CONCURRENT = 5


# ---------------------------------------------------------------------------
# Heuristic classifier (no LLM, instant)
# ---------------------------------------------------------------------------

SEVERITY_TO_PRIORITY = {
    "critical": RemediationPriority.CRITICAL,
    "high": RemediationPriority.HIGH,
    "medium": RemediationPriority.MEDIUM,
    "low": RemediationPriority.LOW,
    "info": RemediationPriority.INFORMATIONAL,
}

# Detectors that are almost always FP at PatternMatch level
HIGH_FP_DETECTORS = {
    "missing-min-ada-check",
    "unused-import",
    "dead-code-path",
}

# Detectors where simulation rejection is strong counter-evidence
SIMULATION_SENSITIVE = {
    "missing-datum-in-script-output",
    "arbitrary-datum-in-output",
    "value-not-preserved",
    "unrestricted-minting",
}


def heuristic_classify(finding: AikidoFinding) -> FindingReview:
    """Classify a finding using heuristics only (no LLM)."""
    evidence = finding.evidence
    severity = finding.severity.lower()
    confidence = finding.confidence.lower()
    tier = finding.reliability_tier.lower()
    detector = finding.detector

    classification = Classification.NEEDS_REVIEW
    reviewer_confidence = 0.5
    reasoning_parts: List[str] = []
    mitigating: List[str] = []

    # Info severity findings are almost always FP or informational
    if severity == "info":
        classification = Classification.LIKELY_FP
        reviewer_confidence = 0.7
        reasoning_parts.append("Info severity findings are typically informational, not exploitable.")

    # Known high-FP detectors
    if detector in HIGH_FP_DETECTORS:
        classification = Classification.CONFIRMED_FP
        reviewer_confidence = 0.85
        reasoning_parts.append(f"Detector '{detector}' is a known high-FP pattern.")
        if detector == "missing-min-ada-check":
            mitigating.append("Cardano ledger enforces minimum ADA at protocol level")

    # Evidence-based classification
    if evidence:
        level = evidence.level

        # Corroborated = strongest
        if level == "Corroborated" and confidence == "definite":
            if severity in ("critical", "high"):
                classification = Classification.CONFIRMED_TP
                reviewer_confidence = 0.9
                reasoning_parts.append("Corroborated evidence with definite confidence — multiple analysis lanes agree.")

        # Simulation rejection = counter-evidence
        if evidence.witness and isinstance(evidence.witness, dict):
            rejection = evidence.witness.get("rejection_error")
            if rejection:
                classification = Classification.LIKELY_FP
                reviewer_confidence = 0.75
                reasoning_parts.append(
                    f"Simulation rejected the exploit: {rejection[:120]}. "
                    "The validator appears to catch this scenario."
                )
                mitigating.append("Transaction simulation rejected exploit attempt")

        # PatternMatch + Possible = weakest
        if level == "PatternMatch" and confidence == "possible":
            if classification == Classification.NEEDS_REVIEW:
                classification = Classification.LIKELY_FP
                reviewer_confidence = 0.6
                reasoning_parts.append("PatternMatch with 'possible' confidence is the weakest evidence tier.")

        # SMT inconclusive
        if evidence.details and "inconclusive" in evidence.details.lower():
            reasoning_parts.append("SMT solver was inconclusive — cannot prove or disprove.")

    # Experimental tier
    if tier == "experimental" and classification == Classification.NEEDS_REVIEW:
        classification = Classification.LIKELY_FP
        reviewer_confidence = 0.55
        reasoning_parts.append("Experimental detector tier has higher expected FP rate.")

    if not reasoning_parts:
        reasoning_parts.append(
            f"Heuristic classification based on {severity} severity, "
            f"{confidence} confidence, {tier} tier."
        )

    return FindingReview(
        finding_index=0,  # set by caller
        detector=finding.detector,
        title=finding.title,
        original_severity=finding.severity,
        original_confidence=finding.confidence,
        classification=classification,
        reviewer_confidence=reviewer_confidence,
        reasoning=" ".join(reasoning_parts),
        mitigating_patterns=mitigating,
        exploitation_scenario=None,
        remediation_priority=SEVERITY_TO_PRIORITY.get(severity, RemediationPriority.INFORMATIONAL),
    )


# ---------------------------------------------------------------------------
# LLM-based classifier
# ---------------------------------------------------------------------------

def _parse_review_json(text: str, finding: AikidoFinding) -> Dict[str, Any]:
    """Parse LLM response JSON, with fallback extraction."""
    # Try direct parse
    text = text.strip()
    if text.startswith("```"):
        # Strip markdown code fences
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        )

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in response
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    # Fallback: return needs_review
    logger.warning("Failed to parse LLM response for %s, falling back to heuristic", finding.detector)
    return {}


def _json_to_review(data: Dict[str, Any], finding: AikidoFinding, index: int) -> FindingReview:
    """Convert parsed JSON dict to FindingReview, with defaults."""
    if not data:
        review = heuristic_classify(finding)
        review.finding_index = index
        review.reasoning = "[LLM parse failed, heuristic fallback] " + review.reasoning
        return review

    try:
        classification = Classification(data.get("classification", "needs_review"))
    except ValueError:
        classification = Classification.NEEDS_REVIEW

    try:
        priority = RemediationPriority(data.get("remediation_priority", "informational"))
    except ValueError:
        priority = SEVERITY_TO_PRIORITY.get(finding.severity.lower(), RemediationPriority.INFORMATIONAL)

    return FindingReview(
        finding_index=index,
        detector=finding.detector,
        title=finding.title,
        original_severity=finding.severity,
        original_confidence=finding.confidence,
        classification=classification,
        reviewer_confidence=min(1.0, max(0.0, float(data.get("reviewer_confidence", 0.5)))),
        reasoning=data.get("reasoning", "No reasoning provided."),
        mitigating_patterns=data.get("mitigating_patterns", []),
        exploitation_scenario=data.get("exploitation_scenario"),
        remediation_priority=priority,
        evidence_assessment=data.get("evidence_assessment"),
    )


async def _review_single(
    client: anthropic.AsyncAnthropic,
    finding: AikidoFinding,
    index: int,
    source_files: Dict[str, str],
    all_findings: List[AikidoFinding],
    semaphore: asyncio.Semaphore,
) -> FindingReview:
    """Review a single finding via LLM."""
    snippet = get_finding_snippet(finding, source_files)
    full_source = get_full_module_source(finding, source_files)

    # Related findings in same module
    related = [f for f in all_findings if f.module == finding.module and f is not finding]

    prompt = build_finding_prompt(finding, index, snippet, full_source, related or None)

    async with semaphore:
        try:
            response = await client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            data = _parse_review_json(text, finding)
            return _json_to_review(data, finding, index)
        except Exception as e:
            logger.error("LLM call failed for finding #%d: %s", index, e)
            review = heuristic_classify(finding)
            review.finding_index = index
            review.reasoning = f"[LLM error: {e}, heuristic fallback] " + review.reasoning
            return review


async def _review_batch(
    client: anthropic.AsyncAnthropic,
    batch: List[Tuple[int, AikidoFinding]],
    source_files: Dict[str, str],
    semaphore: asyncio.Semaphore,
) -> List[FindingReview]:
    """Review a batch of findings in a single LLM call."""
    items = []
    for index, finding in batch:
        snippet = get_finding_snippet(finding, source_files)
        items.append((index, finding, snippet))

    prompt = build_batch_prompt(items)

    async with semaphore:
        try:
            response = await client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS * 2,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()

            # Parse JSON array
            if text.startswith("```"):
                lines = text.splitlines()
                text = "\n".join(l for l in lines if not l.strip().startswith("```"))

            try:
                results = json.loads(text)
            except json.JSONDecodeError:
                start = text.find("[")
                end = text.rfind("]") + 1
                if start >= 0 and end > start:
                    results = json.loads(text[start:end])
                else:
                    results = []

            reviews = []
            for i, (index, finding, _snippet) in enumerate(items):
                if i < len(results) and isinstance(results[i], dict):
                    reviews.append(_json_to_review(results[i], finding, index))
                else:
                    review = heuristic_classify(finding)
                    review.finding_index = index
                    reviews.append(review)
            return reviews

        except Exception as e:
            logger.error("Batch LLM call failed: %s", e)
            reviews = []
            for index, finding in batch:
                review = heuristic_classify(finding)
                review.finding_index = index
                review.reasoning = f"[Batch LLM error: {e}, heuristic fallback] " + review.reasoning
                reviews.append(review)
            return reviews


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def analyze_findings(
    findings: List[AikidoFinding],
    source_files: Dict[str, str],
    depth: str = "standard",
    anthropic_credential: Optional[str] = None,
) -> List[FindingReview]:
    """Analyze all findings and return reviews.

    depth:
        - "quick": Heuristic only, no LLM calls.
        - "standard": Critical/High get individual LLM calls; Medium/Low/Info batched.
        - "deep": Standard + second correlation pass.
    """
    if depth == "quick":
        reviews = []
        for i, finding in enumerate(findings):
            review = heuristic_classify(finding)
            review.finding_index = i
            reviews.append(review)
        return reviews

    # Standard and deep modes use LLM
    client = anthropic.AsyncAnthropic(api_key=anthropic_credential)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    critical_high: List[Tuple[int, AikidoFinding]] = []
    rest: List[Tuple[int, AikidoFinding]] = []

    for i, finding in enumerate(findings):
        if finding.severity.lower() in ("critical", "high"):
            critical_high.append((i, finding))
        else:
            rest.append((i, finding))

    # Individual reviews for critical/high
    tasks = [
        _review_single(client, finding, index, source_files, findings, semaphore)
        for index, finding in critical_high
    ]

    # Batch reviews for medium/low/info
    for batch_start in range(0, len(rest), BATCH_SIZE):
        batch = rest[batch_start:batch_start + BATCH_SIZE]
        tasks.append(_review_batch(client, batch, source_files, semaphore))

    raw_results = await asyncio.gather(*tasks)

    # Flatten results (batches return lists)
    reviews: List[FindingReview] = []
    for result in raw_results:
        if isinstance(result, list):
            reviews.extend(result)
        else:
            reviews.append(result)

    # Sort by finding index
    reviews.sort(key=lambda r: r.finding_index)

    # Deep mode: second correlation pass
    if depth == "deep":
        reviews = await _correlation_pass(client, reviews, findings, source_files, semaphore)

    return reviews


async def _correlation_pass(
    client: anthropic.AsyncAnthropic,
    reviews: List[FindingReview],
    findings: List[AikidoFinding],
    source_files: Dict[str, str],
    semaphore: asyncio.Semaphore,
) -> List[FindingReview]:
    """Second pass: look for cross-finding patterns that individual reviews might miss."""
    # Build summary of all reviews for context
    summary_parts = ["## Review Summary So Far\n"]
    for review in reviews:
        summary_parts.append(
            f"#{review.finding_index} [{review.detector}] {review.classification.value} "
            f"(confidence: {review.reviewer_confidence:.2f}): {review.reasoning[:100]}..."
        )

    # Only re-review needs_review findings
    needs_review = [r for r in reviews if r.classification == Classification.NEEDS_REVIEW]
    if not needs_review:
        return reviews

    correlation_prompt = "\n".join(summary_parts) + (
        "\n\n## Correlation Task\n"
        "Given the full context of all findings above, re-evaluate the 'needs_review' findings. "
        "Consider: Are multiple findings pointing at the same root cause? Does a mitigating "
        "pattern found for one finding also apply to others in the same module? "
        "Respond with a JSON array of updated review objects for ONLY the needs_review findings."
    )

    for review in needs_review:
        finding = findings[review.finding_index]
        snippet = get_finding_snippet(finding, source_files)
        if snippet:
            correlation_prompt += f"\n\n### Finding #{review.finding_index}\n```aiken\n{snippet}\n```"

    async with semaphore:
        try:
            response = await client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS * 2,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": correlation_prompt}],
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                lines = text.splitlines()
                text = "\n".join(l for l in lines if not l.strip().startswith("```"))

            updated = json.loads(text) if text.startswith("[") else []

            # Merge updated reviews
            review_map = {r.finding_index: r for r in reviews}
            for i, nr in enumerate(needs_review):
                if i < len(updated) and isinstance(updated[i], dict):
                    review_map[nr.finding_index] = _json_to_review(
                        updated[i], findings[nr.finding_index], nr.finding_index
                    )

            return sorted(review_map.values(), key=lambda r: r.finding_index)
        except Exception as e:
            logger.warning("Correlation pass failed: %s", e)
            return reviews
