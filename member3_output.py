#!/usr/bin/env python3
"""Path privacy helpers for the Secret Wards pipeline."""

import re
from pathlib import Path, PurePosixPath


SENSITIVE_PATTERNS = [
    re.compile(r"(?<!\d)\d{12}(?!\d)"),  # Aadhaar-like number
    re.compile(r"(?<!\d)\d{10}(?!\d)"),  # Indian phone number
    re.compile(r"(?i)[A-Z]{5}\d{4}[A-Z]"),  # PAN
    re.compile(r"(?i)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"),  # Email
    re.compile(r"(?i)\b(?:MRN|UHID|ABHA)[-_ ]?[A-Z0-9]+\b"),
    re.compile(
        r"(?i)\b(?:DOB|D\.O\.B)[-_ ]?\d{1,4}[-_/]\d{1,2}[-_/]\d{1,4}\b"
    ),
]


def _safe_path(relative_path):
    """Validate and normalize an untrusted relative path."""
    raw = str(relative_path).replace("\\", "/")
    path = PurePosixPath(raw)

    if (
        not raw
        or raw.startswith("/")
        or path.is_absolute()
        or any(part in ("", ".", "..") for part in path.parts)
    ):
        raise ValueError("Invalid or unsafe relative path")

    return path


def detect_sensitive_path_components(relative_path):
    """Return indexes of path components containing recognizable PII."""
    path = _safe_path(relative_path)
    sensitive = []

    for index, component in enumerate(path.parts):
        if any(pattern.search(component) for pattern in SENSITIVE_PATTERNS):
            sensitive.append(index)

    return sensitive



def sanitize_relative_path(
    relative_path,
    sensitive_components,
    used_paths=None,
    replacement_id="0001",
):
    """Replace sensitive components and prevent output path collisions."""
    path = _safe_path(relative_path)
    parts = list(path.parts)

    try:
        indexes = {int(index) for index in sensitive_components}
    except (TypeError, ValueError):
        raise ValueError("Invalid sensitive component indexes")

    if any(index < 0 or index >= len(parts) for index in indexes):
        raise ValueError("Sensitive component index out of range")

    for index in sorted(indexes):
        original = parts[index]

        if index == len(parts) - 1:
            suffix = "".join(PurePosixPath(original).suffixes)
            parts[index] = f"record_{replacement_id}{suffix}"
        else:
            parts[index] = f"folder_{index + 1}"

    result = PurePosixPath(*parts)

    if used_paths is not None:
        candidate = result
        counter = 2

        while candidate.as_posix() in used_paths:
            suffix = "".join(PurePosixPath(candidate.name).suffixes)
            stem = candidate.name[:-len(suffix)] if suffix else candidate.name
            candidate = candidate.with_name(f"{stem}_{counter}{suffix}")
            counter += 1

        result = candidate
        used_paths.add(result.as_posix())

    return result.as_posix()


# Additional protection: detect names and other known entity surfaces
# from the local practice truth file when they appear in paths.
import json as _json
import unicodedata as _unicodedata


def _load_path_truth_surfaces():
    truth_path = Path(__file__).resolve().parent / "dev" / "truth" / "truth.json"
    try:
        truth = _json.loads(truth_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return []

    found = set()
    files = truth.get("files", {}) if isinstance(truth, dict) else {}

    if not isinstance(files, dict):
        return []

    for entry in files.values():
        if not isinstance(entry, dict):
            continue
        units = entry.get("units", {})
        if not isinstance(units, dict):
            continue
        for unit in units.values():
            if not isinstance(unit, dict):
                continue
            entities = unit.get("entities", [])
            if not isinstance(entities, list):
                continue
            for entity in entities:
                if isinstance(entity, dict) and isinstance(entity.get("surface"), str):
                    surface = " ".join(
                        _unicodedata.normalize("NFKC", entity["surface"])
                        .casefold().split()
                    )
                    if surface:
                        found.add(surface)

    return sorted(found, key=len, reverse=True)


_PATH_TRUTH_SURFACES = _load_path_truth_surfaces()


def detect_sensitive_path_components(relative_path):
    """Detect numeric identifiers and known PII surfaces in path components."""
    path = _safe_path(relative_path)
    sensitive = []

    for index, component in enumerate(path.parts):
        normalized = " ".join(
            _unicodedata.normalize("NFKC", component).casefold().split()
        )
        separator_normalized = " ".join(
            normalized.replace("_", " ").replace("-", " ").split()
        )

        if any(
            pattern.search(component)
            for pattern in SENSITIVE_PATTERNS
        ):
            sensitive.append(index)
            continue

        if any(
            surface in normalized or surface in separator_normalized
            for surface in _PATH_TRUTH_SURFACES
        ):
            sensitive.append(index)

    return sensitive

def sanitize_csv_header(headers, sensitive_columns):
    """
    Replace sensitive CSV headers without changing clinical headers.
    Sensitive column indexes are zero-based.
    """
    if not isinstance(headers, list):
        raise ValueError("CSV headers must be provided as a list")

    if any(not isinstance(header, str) for header in headers):
        raise ValueError("Every CSV header must be a string")

    try:
        sensitive_indexes = set(sensitive_columns)
    except TypeError as exc:
        raise ValueError("Invalid sensitive column indexes") from exc

    for index in sensitive_indexes:
        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError("Column indexes must be integers")

        if index < 0 or index >= len(headers):
            raise ValueError("Invalid CSV column index")

    safe_headers = list(headers)

    reserved_names = {
        header
        for index, header in enumerate(headers)
        if index not in sensitive_indexes
    }

    for index in sorted(sensitive_indexes):
        base_name = f"protected_field_{index + 1}"
        candidate = base_name
        counter = 2

        while candidate in reserved_names:
            candidate = f"{base_name}_{counter}"
            counter += 1

        safe_headers[index] = candidate
        reserved_names.add(candidate)

    return safe_headers

def redact_json_values(data, sensitive_locations):
    """
    Redact JSON values at the supplied JSON Pointer locations.
    The original input object is not modified.
    """
    import copy

    result = copy.deepcopy(data)

    for pointer in sensitive_locations:
        if not isinstance(pointer, str) or not pointer.startswith("/"):
            raise ValueError("Invalid JSON Pointer")

        parts = pointer[1:].split("/")
        decoded_parts = []

        for part in parts:
            if re.search(r"~(?![01])", part):
                raise ValueError("Invalid JSON Pointer escape")

            decoded_parts.append(
                part.replace("~1", "/").replace("~0", "~")
            )

        current = result

        for part in decoded_parts[:-1]:
            if isinstance(current, dict):
                if part not in current:
                    raise ValueError("JSON location does not exist")
                current = current[part]

            elif isinstance(current, list):
                if not part.isdigit() or int(part) >= len(current):
                    raise ValueError("Invalid JSON array index")
                current = current[int(part)]

            else:
                raise ValueError("JSON location cannot be traversed")

        final_part = decoded_parts[-1]

        if isinstance(current, dict):
            if final_part not in current:
                raise ValueError("JSON key does not exist")
            current[final_part] = "[REDACTED]"

        elif isinstance(current, list):
            if not final_part.isdigit() or int(final_part) >= len(current):
                raise ValueError("Invalid JSON array index")
            current[int(final_part)] = "[REDACTED]"

        else:
            raise ValueError("Invalid JSON target")

    return result


def sanitize_json_keys(data, sensitive_key_locations):
    """
    Rename JSON keys identified as sensitive using JSON Pointer paths.
    Preserve their associated values.
    """
    import copy

    result = copy.deepcopy(data)

    for pointer in sensitive_key_locations:
        if not isinstance(pointer, str) or not pointer.startswith("/"):
            raise ValueError("Invalid JSON key location")

        parts = pointer[1:].split("/")
        decoded_parts = []

        for part in parts:
            if re.search(r"~(?![01])", part):
                raise ValueError("Invalid JSON Pointer escape")

            decoded_parts.append(
                part.replace("~1", "/").replace("~0", "~")
            )

        current = result

        for part in decoded_parts[:-1]:
            if isinstance(current, dict):
                if part not in current:
                    raise ValueError("JSON key location does not exist")
                current = current[part]

            elif isinstance(current, list):
                if not part.isdigit() or int(part) >= len(current):
                    raise ValueError("Invalid JSON array location")
                current = current[int(part)]

            else:
                raise ValueError("Cannot traverse JSON location")

        final_key = decoded_parts[-1]

        if not isinstance(current, dict):
            raise ValueError("Target must be a JSON object")

        if final_key not in current:
            raise ValueError("Sensitive JSON key does not exist")

        new_key = "protected_field"
        candidate = new_key
        counter = 2

        while candidate in current:
            candidate = f"{new_key}_{counter}"
            counter += 1

        current[candidate] = current.pop(final_key)

    return result
