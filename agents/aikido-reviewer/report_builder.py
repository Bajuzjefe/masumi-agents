"""Assemble the aikido.review.v1 output report."""

from typing import List

from schemas import (
    Classification,
    ClassificationSummary,
    FindingReview,
    ReviewReport,
)

SEVERITY_WEIGHT = {
    "critical": 10,
    "high": 7,
    "medium": 4,
    "low": 2,
    "info": 1,
}


def build_classification_summary(reviews: List[FindingReview]) -> ClassificationSummary:
    """Count findings by classification."""
    summary = ClassificationSummary()
    for review in reviews:
        c = review.classification
        if c == Classification.CONFIRMED_TP:
            summary.confirmed_tp += 1
        elif c == Classification.LIKELY_TP:
            summary.likely_tp += 1
        elif c == Classification.NEEDS_REVIEW:
            summary.needs_review += 1
        elif c == Classification.LIKELY_FP:
            summary.likely_fp += 1
        elif c == Classification.CONFIRMED_FP:
            summary.confirmed_fp += 1
    return summary


def compute_risk_score(reviews: List[FindingReview]) -> float:
    """Compute a 0-10 risk score weighted by severity and classification.

    Only confirmed/likely TPs and needs_review contribute to risk.
    """
    if not reviews:
        return 0.0

    max_possible = sum(
        SEVERITY_WEIGHT.get(r.original_severity.lower(), 1)
        for r in reviews
    )
    if max_possible == 0:
        return 0.0

    actual = 0.0
    for review in reviews:
        weight = SEVERITY_WEIGHT.get(review.original_severity.lower(), 1)
        c = review.classification
        if c == Classification.CONFIRMED_TP:
            actual += weight * 1.0
        elif c == Classification.LIKELY_TP:
            actual += weight * 0.7
        elif c == Classification.NEEDS_REVIEW:
            actual += weight * 0.4
        # LIKELY_FP and CONFIRMED_FP contribute nothing

    return round(min(10.0, (actual / max_possible) * 10.0), 1)


def risk_level(score: float) -> str:
    """Map risk score to a human-readable level."""
    if score >= 8.0:
        return "critical"
    if score >= 6.0:
        return "high"
    if score >= 4.0:
        return "medium"
    if score >= 2.0:
        return "low"
    return "minimal"


def build_executive_summary(
    summary: ClassificationSummary,
    risk_score: float,
    total: int,
) -> str:
    """Generate a human-readable executive summary."""
    parts = [f"Reviewed {total} findings from Aikido static analysis."]

    tp_count = summary.confirmed_tp + summary.likely_tp
    fp_count = summary.confirmed_fp + summary.likely_fp

    if tp_count > 0:
        parts.append(
            f"{tp_count} finding(s) classified as true or likely true positives "
            f"requiring attention."
        )
    if summary.needs_review > 0:
        parts.append(f"{summary.needs_review} finding(s) require manual review.")
    if fp_count > 0:
        parts.append(f"{fp_count} finding(s) classified as false or likely false positives.")

    level = risk_level(risk_score)
    parts.append(f"Overall risk level: {level} (score: {risk_score}/10.0).")

    return " ".join(parts)


def build_recommendations(reviews: List[FindingReview]) -> List[str]:
    """Generate actionable recommendations sorted by priority."""
    recs: List[str] = []
    priority_order = ["critical", "high", "medium", "low", "informational"]

    # Group confirmed/likely TPs by priority
    actionable = [
        r for r in reviews
        if r.classification in (Classification.CONFIRMED_TP, Classification.LIKELY_TP)
    ]
    actionable.sort(key=lambda r: priority_order.index(r.remediation_priority.value))

    for review in actionable:
        recs.append(
            f"[{review.remediation_priority.value.upper()}] "
            f"Address {review.detector} in {review.title}: {review.reasoning[:150]}"
        )

    if not recs:
        recs.append("No critical issues found. Continue monitoring with regular Aikido scans.")

    return recs


def build_report(
    project: str,
    reviews: List[FindingReview],
    depth: str,
) -> ReviewReport:
    """Assemble the full review report."""
    summary = build_classification_summary(reviews)
    score = compute_risk_score(reviews)
    executive = build_executive_summary(summary, score, len(reviews))
    recommendations = build_recommendations(reviews)

    return ReviewReport(
        project=project,
        review_depth=depth,
        total_findings=len(reviews),
        classification_summary=summary,
        risk_score=score,
        risk_level=risk_level(score),
        executive_summary=executive,
        finding_reviews=reviews,
        recommendations=recommendations,
    )
