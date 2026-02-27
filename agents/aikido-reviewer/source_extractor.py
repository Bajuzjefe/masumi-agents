"""Extract source code snippets around finding locations."""

from typing import Dict, Optional

from schemas import AikidoFinding

CONTEXT_LINES = 8
MAX_MODULE_LINES = 200


def normalize_path(finding_path: str) -> str:
    """Strip /tmp/... prefix to get relative path like validators/foo.ak."""
    parts = finding_path.split("/")
    # Aikido paths look like /tmp/strike/forwards/validators/collateral.ak
    # We want to match against source_files keys which are relative
    # Try to find validators/ or lib/ segment as anchor
    for i, part in enumerate(parts):
        if part in ("validators", "lib"):
            return "/".join(parts[i:])
    # Fallback: just the filename
    return parts[-1] if parts else finding_path


def match_source_file(finding_path: str, source_files: Dict[str, str]) -> Optional[str]:
    """Find the matching source file key for a finding path.

    Tries exact match, normalized match, then suffix match.
    """
    if finding_path in source_files:
        return finding_path

    normalized = normalize_path(finding_path)
    if normalized in source_files:
        return normalized

    # Suffix match: find a key that ends with the normalized path
    for key in source_files:
        if key.endswith(normalized) or normalized.endswith(key):
            return key

    # Last resort: filename match
    filename = finding_path.rsplit("/", 1)[-1]
    for key in source_files:
        if key.endswith(filename):
            return key

    return None


def extract_snippet(
    source: str,
    line_start: int,
    line_end: Optional[int] = None,
    context: int = CONTEXT_LINES,
) -> str:
    """Extract a code snippet with line numbers and markers around finding lines."""
    lines = source.splitlines()
    if not lines or line_start < 1:
        return ""

    end = line_end or line_start
    # 0-indexed
    start_idx = max(0, line_start - 1 - context)
    end_idx = min(len(lines), end + context)

    result = []
    for i in range(start_idx, end_idx):
        line_num = i + 1
        is_finding = line_start <= line_num <= end
        marker = ">" if is_finding else " "
        result.append(f"{marker} {line_num:4} | {lines[i]}")

    return "\n".join(result)


def get_finding_snippet(
    finding: AikidoFinding,
    source_files: Dict[str, str],
) -> Optional[str]:
    """Get the code snippet for a finding, or None if source not available."""
    if not finding.location:
        return None

    key = match_source_file(finding.location.path, source_files)
    if key is None:
        return None

    source = source_files[key]
    if not finding.location.line_start:
        return None

    return extract_snippet(
        source,
        finding.location.line_start,
        finding.location.line_end,
    )


def get_full_module_source(
    finding: AikidoFinding,
    source_files: Dict[str, str],
) -> Optional[str]:
    """Get full module source if it's short enough to include."""
    if not finding.location:
        return None

    key = match_source_file(finding.location.path, source_files)
    if key is None:
        return None

    source = source_files[key]
    if source.count("\n") + 1 > MAX_MODULE_LINES:
        return None

    return source
