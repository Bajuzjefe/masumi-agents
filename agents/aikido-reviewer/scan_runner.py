"""Aikido CLI execution helpers for auto-scan workflow."""

from __future__ import annotations

import json
import os
import posixpath
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Tuple
from urllib.parse import urlparse


def _safe_relative_path(path: str) -> str:
    """Normalize and validate a relative project path."""
    normalized = posixpath.normpath(path).lstrip("/")
    if normalized in ("", "."):
        raise ValueError("source_files contains an empty path")
    if normalized == ".." or normalized.startswith("../"):
        raise ValueError(f"source_files path escapes project root: {path}")
    return normalized


def _safe_relative_subpath(path: str | None) -> str:
    """Validate optional repo subpath."""
    if not path:
        return "."
    normalized = _safe_relative_path(path)
    if normalized == ".":
        return "."
    return normalized


def _allowed_repo_hosts() -> set[str]:
    raw = os.getenv("ALLOWED_REPO_HOSTS", "github.com,gitlab.com,bitbucket.org")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _validate_repo_url(repo_url: str) -> None:
    if not repo_url:
        raise ValueError("repo_url is required")
    if len(repo_url) > 2048:
        raise ValueError("repo_url is too long")

    parsed = urlparse(repo_url)
    if parsed.scheme != "https":
        raise ValueError("repo_url must use https://")

    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("repo_url missing hostname")

    if host not in _allowed_repo_hosts():
        raise ValueError(f"repo_url host '{host}' is not allowed")


def contains_aiken_toml(source_files: Dict[str, str]) -> bool:
    """Return True if source_files includes an aiken.toml file anywhere."""
    for key in source_files:
        try:
            normalized = _safe_relative_path(key).lower()
        except ValueError:
            continue
        if normalized == "aiken.toml" or normalized.endswith("/aiken.toml"):
            return True
    return False


def _write_project_tree(source_files: Dict[str, str], project_dir: Path) -> Dict[str, str]:
    """Write provided source files into a temporary project directory."""
    normalized_sources: Dict[str, str] = {}
    for raw_path, content in source_files.items():
        rel_path = _safe_relative_path(raw_path)
        target = project_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        normalized_sources[rel_path] = content
    return normalized_sources


def _run_aikido_cli(project_dir: Path) -> Dict:
    """Execute Aikido and parse JSON report."""
    aikido_bin = os.getenv("AIKIDO_BIN", "aikido")
    timeout_seconds = int(os.getenv("AIKIDO_TIMEOUT_SECONDS", "600"))

    cmd = [
        aikido_bin,
        str(project_dir),
        "--format",
        "json",
        "--quiet",
        "--min-severity",
        "info",
        "--fail-on",
        "critical",
    ]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    if not stdout:
        raise RuntimeError(
            "Aikido scan produced no JSON output. "
            f"exit_code={proc.returncode}, stderr={stderr[:300]}"
        )

    try:
        report = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Aikido JSON output parse failed. "
            f"exit_code={proc.returncode}, stderr={stderr[:300]}"
        ) from exc

    if not isinstance(report, dict) or "findings" not in report:
        raise RuntimeError(
            "Aikido output missing findings payload. "
            f"exit_code={proc.returncode}, stderr={stderr[:300]}"
        )
    return report


def _collect_source_files(project_dir: Path) -> Dict[str, str]:
    """Collect source files for downstream snippet extraction."""
    max_files = int(os.getenv("MAX_SCAN_SOURCE_FILES", "500"))
    max_file_bytes = int(os.getenv("MAX_SCAN_SOURCE_FILE_BYTES", "200000"))
    max_total_bytes = int(os.getenv("MAX_SCAN_TOTAL_SOURCE_BYTES", "5000000"))

    include_suffixes = {".ak", ".toml"}

    collected: Dict[str, str] = {}
    total_bytes = 0

    for path in sorted(project_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in include_suffixes:
            continue
        rel = path.relative_to(project_dir).as_posix()
        if rel.startswith(".git/"):
            continue
        size = path.stat().st_size
        if size > max_file_bytes:
            continue
        if len(collected) >= max_files:
            break
        if total_bytes + size > max_total_bytes:
            break
        content = path.read_text(encoding="utf-8", errors="ignore")
        collected[rel] = content
        total_bytes += size

    return collected


def run_aikido_scan_from_source_files(source_files: Dict[str, str]) -> Tuple[Dict, Dict[str, str]]:
    """Run Aikido CLI against provided source files and return findings JSON + normalized sources."""
    if not isinstance(source_files, dict) or len(source_files) == 0:
        raise ValueError("source_files must be a non-empty JSON object")
    if not contains_aiken_toml(source_files):
        raise ValueError(
            "source_files must include aiken.toml for auto scan mode. "
            "Provide a full Aiken project snapshot."
        )

    with tempfile.TemporaryDirectory(prefix="aikido-scan-") as tmpdir:
        project_dir = Path(tmpdir) / "project"
        project_dir.mkdir(parents=True, exist_ok=True)

        normalized_sources = _write_project_tree(source_files, project_dir)
        report = _run_aikido_cli(project_dir)

        return report, normalized_sources


def run_aikido_scan_from_repo(
    repo_url: str,
    repo_ref: str | None = None,
    repo_subpath: str | None = None,
) -> Tuple[Dict, Dict[str, str]]:
    """Clone repository and run Aikido scan."""
    _validate_repo_url(repo_url)
    clone_timeout = int(os.getenv("AIKIDO_GIT_CLONE_TIMEOUT_SECONDS", "180"))
    safe_subpath = _safe_relative_subpath(repo_subpath)

    with tempfile.TemporaryDirectory(prefix="aikido-repo-scan-") as tmpdir:
        repo_dir = Path(tmpdir) / "repo"

        clone_cmd = ["git", "clone", "--depth", "1"]
        if repo_ref:
            clone_cmd.extend(["--branch", repo_ref])
        clone_cmd.extend([repo_url, str(repo_dir)])

        proc = subprocess.run(
            clone_cmd,
            capture_output=True,
            text=True,
            timeout=clone_timeout,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to clone repo_url: {(proc.stderr or '').strip()[:300]}")

        project_dir = repo_dir if safe_subpath == "." else repo_dir / safe_subpath
        if not project_dir.exists() or not project_dir.is_dir():
            raise ValueError(f"repo_subpath not found in repository: {safe_subpath}")

        if not (project_dir / "aiken.toml").exists():
            raise ValueError(f"aiken.toml not found at repo_subpath: {safe_subpath}")

        report = _run_aikido_cli(project_dir)
        source_files = _collect_source_files(project_dir)
        return report, source_files
