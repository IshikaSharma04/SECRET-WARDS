#!/usr/bin/env python3
"""Independent security checks for a Secret Wards output directory.

This supplements (and does not replace) validate_output.py and check_dev.py.
It reports check names and counts only; it never prints paths or PII surfaces.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import unicodedata
from collections import Counter
from pathlib import Path


class CheckResults:
    """Keep pass, fail and skip results and print a non-sensitive summary."""

    def __init__(self) -> None:
        self.results: list[tuple[str, str, str]] = []

    def add(self, name: str, status: str, detail: str) -> None:
        self.results.append((name, status, detail))
        print(f"{status.upper():7} {name}: {detail}")

    def finish(self) -> int:
        counts = Counter(status for _, status, _ in self.results)
        print(
            "SUMMARY "
            f"passed={counts['pass']} failed={counts['fail']} skipped={counts['skip']}"
        )
        return 1 if counts["fail"] else 0


def list_files(root: Path) -> list[Path]:
    """Return regular files below root in a stable order, without following links."""
    found: list[Path] = []
    if not root.is_dir():
        return found
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs.sort()
        names.sort()
        base = Path(current)
        found.extend(base / name for name in names if (base / name).is_file())
    return found


def list_output_paths(root: Path) -> list[Path]:
    """Return every directory and file below output for full-path inspection."""
    found: list[Path] = []
    if not root.is_dir():
        return found
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs.sort()
        names.sort()
        base = Path(current)
        found.extend(base / name for name in dirs)
        found.extend(base / name for name in names)
    return found


def normalize(text: str) -> str:
    """Use the same basic Unicode/case/whitespace normalization as check_dev.py."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def load_truth_surfaces(truth_path: Path) -> tuple[list[str] | None, str]:
    """Read entity surfaces only when the existing practice truth schema supports it."""
    if not truth_path.is_file():
        return None, "practice truth file is unavailable"
    try:
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "practice truth file could not be read as JSON"
    files = truth.get("files") if isinstance(truth, dict) else None
    if not isinstance(files, dict):
        return None, "practice truth has no supported files mapping"

    surfaces: set[str] = set()
    for entry in files.values():
        if not isinstance(entry, dict) or not isinstance(entry.get("units"), dict):
            return None, "practice truth file entries do not have the expected units mapping"
        for unit in entry["units"].values():
            if not isinstance(unit, dict) or not isinstance(unit.get("entities"), list):
                return None, "practice truth units do not have the expected entities list"
            for entity in unit["entities"]:
                if isinstance(entity, dict) and isinstance(entity.get("surface"), str):
                    value = normalize(entity["surface"])
                    if value:
                        surfaces.add(value)
    return sorted(surfaces), ""


def read_text_safely(path: Path) -> str | None:
    """Read output text as UTF-8, returning None if unavailable or not UTF-8."""
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return None


def check_paths(
    output: Path,
    all_paths: list[Path],
    surfaces: list[str] | None,
    results: CheckResults,
) -> None:
    """Search complete relative output paths, including directory components."""
    if surfaces is None:
        results.add(
            "output paths contain no known PII",
            "skip",
            "practice truth surfaces unavailable",
        )
        return

    hits = 0
    candidates = [output, *all_paths]
    for path in candidates:
        try:
            relative = "." if path == output else path.relative_to(output).as_posix()
        except ValueError:
            continue
        normalized_path = normalize(relative)
        hits += sum(1 for surface in surfaces if surface in normalized_path)

    if hits:
        results.add(
            "output paths contain no known PII",
            "fail",
            f"known-surface matches={hits}",
        )
    else:
        results.add(
            "output paths contain no known PII",
            "pass",
            "no practice-truth surfaces found",
        )


def check_identical_copies(
    input_files: list[Path],
    sanitized_files: list[Path],
    results: CheckResults,
) -> None:
    """Fail on identical input copies except the exact verified static README."""
    approved_relative_path = Path("misc") / "README_export.txt"

    input_hashes: set[bytes] = set()
    approved_readme_hashes: set[bytes] = set()

    # Input paths are rooted at the supplied input directory. Identify the
    # README by its exact trailing relative path, not by its content alone.
    for input_path in input_files:
        try:
            digest = hashlib.sha256(input_path.read_bytes()).digest()
        except OSError:
            results.add(
                "sanitized output has no byte-identical input copies",
                "fail",
                "one or more input files could not be read for comparison",
            )
            return

        input_hashes.add(digest)
        if input_path.parts[-2:] == approved_relative_path.parts:
            approved_readme_hashes.add(digest)

    copies = 0
    approved = 0

    for output_path in sanitized_files:
        try:
            digest = hashlib.sha256(output_path.read_bytes()).digest()
        except OSError:
            copies += 1
            continue

        # The exception requires BOTH the exact relative path and matching
        # content from the corresponding approved input README.
        is_approved_readme = (
            output_path.parts[-2:] == approved_relative_path.parts
            and digest in approved_readme_hashes
        )

        if digest in input_hashes and not is_approved_readme:
            copies += 1
        elif is_approved_readme:
            approved += 1

    if copies:
        results.add(
            "sanitized output has no byte-identical input copies",
            "fail",
            f"unapproved matching sanitized files={copies}",
        )
    else:
        results.add(
            "sanitized output has no byte-identical input copies",
            "pass",
            f"no unapproved copies; approved static README files={approved}",
        )


def safe_sanitized_reference(
    value: object, output: Path, sanitized: Path
) -> Path | None:
    """Resolve a contract path only if it stays inside sanitized/."""
    if not isinstance(value, str) or not value.startswith("sanitized/"):
        return None
    relative = value[len("sanitized/"):]
    if not relative:
        return None
    candidate = (output / value).resolve()
    try:
        candidate.relative_to(sanitized.resolve())
    except ValueError:
        return None
    return candidate


def check_report(
    output: Path,
    input_files: list[Path],
    sanitized: Path,
    sanitized_files: list[Path],
    results: CheckResults,
) -> dict | None:
    """Parse report.json and compare its file hashes/statuses/counts with disk."""
    report_path = output / "report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        results.add(
            "report.json is valid JSON",
            "fail",
            "missing, unreadable or invalid JSON",
        )
        results.add(
            "report file accounting matches input",
            "skip",
            "report could not be parsed",
        )
        return None

    results.add("report.json is valid JSON", "pass", "parsed successfully")

    if not isinstance(report, dict):
        results.add(
            "report file accounting matches input",
            "fail",
            "top-level value is not an object",
        )
        return report

    entries = report.get("files")
    if not isinstance(entries, list):
        results.add(
            "report file accounting matches input",
            "fail",
            "files is not a list",
        )
        return report

    input_hashes = Counter(
        hashlib.sha256(path.read_bytes()).hexdigest() for path in input_files
    )
    report_hashes: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    declared_sanitized: set[str] = set()
    problems = 0
    valid_statuses = {"sanitized", "quarantined", "suppressed"}

    for entry in entries:
        if not isinstance(entry, dict):
            problems += 1
            continue

        sha = entry.get("input_sha256")
        status = entry.get("status")

        if not isinstance(sha, str) or len(sha) != 64:
            problems += 1
        else:
            report_hashes[sha.lower()] += 1

        if status not in valid_statuses:
            problems += 1
        else:
            statuses[status] += 1

        target = entry.get("output")
        if status == "sanitized":
            resolved = safe_sanitized_reference(target, output, sanitized)
            if resolved is None or not resolved.is_file():
                problems += 1
            else:
                declared_sanitized.add(
                    resolved.relative_to(sanitized.resolve()).as_posix()
                )
        elif target is not None:
            problems += 1

    actual_sanitized = (
        {path.relative_to(sanitized).as_posix() for path in sanitized_files}
        if sanitized.is_dir()
        else set()
    )

    if report_hashes != input_hashes:
        problems += 1
    if declared_sanitized != actual_sanitized:
        problems += 1

    counts = report.get("counts")
    if not isinstance(counts, dict):
        problems += 1
    else:
        expected_counts = {
            "files_total": len(input_files),
            "files_sanitized": statuses["sanitized"],
            "files_quarantined": statuses["quarantined"],
        }
        for key, expected in expected_counts.items():
            actual = counts.get(key)
            if (
                isinstance(actual, bool)
                or not isinstance(actual, int)
                or actual != expected
            ):
                problems += 1

    if problems:
        results.add(
            "report file accounting matches input",
            "fail",
            f"accounting inconsistencies={problems}",
        )
    else:
        results.add(
            "report file accounting matches input",
            "pass",
            f"input files={len(input_files)} sanitized files={len(actual_sanitized)}",
        )

    return report


def check_records(
    output: Path, sanitized: Path, results: CheckResults
) -> list[dict] | None:
    """Parse JSONL, check required fields, then validate each file reference."""
    records_path = output / "records.jsonl"
    try:
        lines = records_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        results.add(
            "records.jsonl lines have required fields",
            "fail",
            "missing or unreadable file",
        )
        results.add(
            "records.jsonl file references exist",
            "skip",
            "records file could not be read",
        )
        return None

    records: list[dict] = []
    malformed = 0
    missing_fields = 0

    for line in lines:
        if not line.strip():
            malformed += 1
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue

        if not isinstance(record, dict):
            missing_fields += 1
            continue
        if not all(key in record for key in ("file", "loc", "patient")):
            missing_fields += 1
            continue
        if not isinstance(record["file"], str) or not record["file"]:
            missing_fields += 1
            continue
        if not isinstance(record["loc"], str) or not record["loc"]:
            missing_fields += 1
            continue
        if record["patient"] is not None and not isinstance(record["patient"], str):
            missing_fields += 1
            continue

        records.append(record)

    if malformed or missing_fields:
        results.add(
            "records.jsonl lines have required fields",
            "fail",
            f"invalid lines={malformed} invalid records={missing_fields}",
        )
    else:
        results.add(
            "records.jsonl lines have required fields",
            "pass",
            f"valid records={len(records)} (null patient links allowed)",
        )

    bad_references = 0
    for record in records:
        resolved = safe_sanitized_reference(
            record.get("file"), output, sanitized
        )
        if resolved is None or not resolved.is_file():
            bad_references += 1

    if bad_references:
        results.add(
            "records.jsonl references existing sanitized files",
            "fail",
            f"invalid file references={bad_references}",
        )
    elif malformed or missing_fields:
        results.add(
            "records.jsonl references existing sanitized files",
            "skip",
            "some records could not be checked because their structure was invalid",
        )
    else:
        results.add(
            "records.jsonl references existing sanitized files",
            "pass",
            f"checked references={len(records)}",
        )

    return records


def check_known_surfaces(
    label: str,
    path: Path,
    surfaces: list[str] | None,
    results: CheckResults,
) -> None:
    """Search one side-channel file for practice-truth entity surfaces."""
    if surfaces is None:
        results.add(label, "skip", "practice truth surfaces unavailable")
        return

    content = read_text_safely(path)
    if content is None:
        results.add(label, "fail", "file is missing or unreadable")
        return

    normalized = normalize(content)
    hits = sum(1 for surface in surfaces if surface in normalized)

    if hits:
        results.add(label, "fail", f"known-surface matches={hits}")
    else:
        results.add(label, "pass", "no practice-truth surfaces found")


def main() -> int:
    """Run all independent checks and return non-zero if any check failed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    input_root = args.input.resolve()
    output_root = args.output.resolve()
    sanitized = output_root / "sanitized"
    results = CheckResults()

    if not input_root.is_dir():
        results.add(
            "input directory is available",
            "fail",
            "input directory is missing",
        )
        return results.finish()

    input_files = list_files(input_root)
    sanitized_files = list_files(sanitized)
    output_paths = list_output_paths(output_root)
    surfaces, _reason = load_truth_surfaces(
        Path(__file__).resolve().parent / "dev" / "truth" / "truth.json"
    )

    if not sanitized.is_dir():
        results.add(
            "sanitized directory exists",
            "fail",
            "required directory is missing",
        )
    else:
        results.add(
            "sanitized directory exists",
            "pass",
            "directory is present",
        )

    check_paths(output_root, output_paths, surfaces, results)
    check_identical_copies(input_files, sanitized_files, results)
    check_report(output_root, input_files, sanitized, sanitized_files, results)
    records = check_records(output_root, sanitized, results)
    check_known_surfaces(
        "report.json has no known PII surfaces",
        output_root / "report.json",
        surfaces,
        results,
    )
    check_known_surfaces(
        "records.jsonl has no known PII surfaces",
        output_root / "records.jsonl",
        surfaces,
        results,
    )

    # Linkage is optional; this checker validates structure and file references.
    _ = records
    return results.finish()


if __name__ == "__main__":
    sys.exit(main())
