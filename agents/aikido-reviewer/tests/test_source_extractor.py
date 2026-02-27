"""Tests for source_extractor module."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas import AikidoFinding, FindingLocation
from source_extractor import (
    extract_snippet,
    get_finding_snippet,
    get_full_module_source,
    match_source_file,
    normalize_path,
)


SAMPLE_SOURCE = """\
use aiken/collection/list
use aiken/crypto.{VerificationKeyHash}

validator collateral {
  spend(datum: Option<CollateralDatum>, redeemer: CollateralAction, ctx: ScriptContext) {
    let tx = ctx.transaction
    expect Some(d) = datum
    when redeemer is {
      Deposit -> {
        let signer = list.at(tx.extra_signatories, 0)
        signer == d.owner
      }
      Withdraw -> {
        list.has(tx.extra_signatories, d.owner)
      }
    }
  }
}"""

SOURCE_FILES = {
    "validators/collateral.ak": SAMPLE_SOURCE,
    "lib/strike/forwards/types.ak": "type ForwardDatum { owner: ByteArray }",
}


def test_normalize_path_strips_tmp_prefix():
    path = "/tmp/strike/forwards/validators/collateral.ak"
    assert normalize_path(path) == "validators/collateral.ak"


def test_normalize_path_strips_lib_prefix():
    path = "/tmp/strike/forwards/lib/strike/forwards/types.ak"
    assert normalize_path(path) == "lib/strike/forwards/types.ak"


def test_normalize_path_filename_fallback():
    path = "/some/random/path/foo.ak"
    assert normalize_path(path) == "foo.ak"


def test_match_source_file_exact():
    assert match_source_file("validators/collateral.ak", SOURCE_FILES) == "validators/collateral.ak"


def test_match_source_file_normalized():
    path = "/tmp/strike/forwards/validators/collateral.ak"
    assert match_source_file(path, SOURCE_FILES) == "validators/collateral.ak"


def test_match_source_file_suffix():
    # Source files keyed with project prefix
    files = {"project/validators/collateral.ak": "code"}
    path = "/tmp/strike/forwards/validators/collateral.ak"
    assert match_source_file(path, files) == "project/validators/collateral.ak"


def test_match_source_file_not_found():
    assert match_source_file("/tmp/unknown.ak", SOURCE_FILES) is None


def test_extract_snippet_marks_finding_lines():
    snippet = extract_snippet(SAMPLE_SOURCE, 7, 7, context=2)
    lines = snippet.splitlines()
    # Line 7 should be marked
    assert any(line.startswith(">") and "expect" in line for line in lines)
    # Context lines should not be marked
    assert any(line.startswith(" ") for line in lines)


def test_extract_snippet_handles_start_of_file():
    snippet = extract_snippet(SAMPLE_SOURCE, 1, 2, context=3)
    lines = snippet.splitlines()
    assert lines[0].startswith(">")
    assert "   1" in lines[0]


def test_extract_snippet_handles_end_of_file():
    total_lines = len(SAMPLE_SOURCE.splitlines())
    snippet = extract_snippet(SAMPLE_SOURCE, total_lines, total_lines, context=3)
    lines = snippet.splitlines()
    assert any(line.startswith(">") for line in lines)


def test_get_finding_snippet():
    finding = AikidoFinding(
        detector="test",
        severity="high",
        confidence="likely",
        title="Test finding",
        description="Test",
        module="collateral",
        location=FindingLocation(
            path="/tmp/strike/forwards/validators/collateral.ak",
            byte_start=100,
            byte_end=200,
            line_start=5,
            line_end=8,
        ),
    )
    snippet = get_finding_snippet(finding, SOURCE_FILES)
    assert snippet is not None
    assert ">" in snippet
    assert "spend" in snippet


def test_get_finding_snippet_no_location():
    finding = AikidoFinding(
        detector="test",
        severity="info",
        confidence="possible",
        title="No location",
        description="Test",
        module="utils",
    )
    assert get_finding_snippet(finding, SOURCE_FILES) is None


def test_get_full_module_source_short():
    finding = AikidoFinding(
        detector="test",
        severity="info",
        confidence="possible",
        title="Test",
        description="Test",
        module="collateral",
        location=FindingLocation(
            path="/tmp/strike/forwards/validators/collateral.ak",
            byte_start=0,
            byte_end=100,
            line_start=1,
        ),
    )
    source = get_full_module_source(finding, SOURCE_FILES)
    assert source is not None
    assert "validator collateral" in source


def test_get_full_module_source_too_long():
    big_files = {"validators/big.ak": "\n".join(f"line {i}" for i in range(300))}
    finding = AikidoFinding(
        detector="test",
        severity="info",
        confidence="possible",
        title="Test",
        description="Test",
        module="big",
        location=FindingLocation(
            path="validators/big.ak",
            byte_start=0,
            byte_end=100,
            line_start=1,
        ),
    )
    assert get_full_module_source(finding, big_files) is None
