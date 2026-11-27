
#!/usr/bin/env python3

import argparse
import base64
import binascii
import csv
import hashlib
import io
import json
import re
import resource
import sys
import time
from pathlib import Path

from modules.ingestion import ingest_file
from modules.pii_detection import detect_in_text
from modules.header_classification import classify_csv_column


SUPPORTED = {".csv", ".tsv", ".json", ".txt"}
REDACTED = "[REDACTED]"

# Deliberately broad: inspect candidate Base64 tokens even when adjacent
# to punctuation or other text. Binary payloads are preserved unchanged.
BASE64_PATTERN = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")


def get_sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def get_peak_rss_mb():
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return round(usage / (1024 * 1024), 2)
    return round(usage / 1024, 2)


def redact_text(text, field_name=None):
    if not isinstance(text, str) or not text:
        return text, 0

    detections = detect_in_text(
        text,
        path="doc",
        source_type="text",
        field_name=field_name,
    )

    valid = []
    for item in detections:
        start = item.get("start")
        end = item.get("end")
        if (
            isinstance(start, int)
            and isinstance(end, int)
            and 0 <= start < end <= len(text)
        ):
            valid.append(item)

    valid.sort(key=lambda item: (item["start"], item["end"]), reverse=True)

    cleaned = text
    count = 0
    last_start = len(text)

    for item in valid:
        start = item["start"]
        end = item["end"]

        if end > last_start:
            continue

        cleaned = cleaned[:start] + REDACTED + cleaned[end:]
        last_start = start
        count += 1

    return cleaned, count


def clean_embedded_base64(text, field_name=None):
    if not isinstance(text, str) or not text:
        return text, 0

    total = 0

    def replace_match(match):
        nonlocal total

        token = match.group(0)

        # Avoid decoding arbitrary fragments of longer tokens.
        if len(token) % 4 == 1:
            return token

        try:
            padded = token + "=" * (-len(token) % 4)
            decoded = base64.b64decode(padded, validate=True)

            # Only inspect text-like payloads. Preserve binary payloads.
            decoded_text = decoded.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return token

        cleaned, count = redact_text(decoded_text, field_name)

        if count == 0:
            return token

        total += count
        return base64.b64encode(cleaned.encode("utf-8")).decode("ascii")

    return BASE64_PATTERN.sub(replace_match, text), total


def clean_base64(value, field_name=None):
    return clean_embedded_base64(value, field_name)


def safe_field_name(field_name):
    if field_name is None:
        return None

    category = classify_csv_column(str(field_name))
    return category if category else str(field_name)


def clean_value(value, field_name=None):
    if isinstance(value, str):
        field = safe_field_name(field_name)

        cleaned, count = clean_embedded_base64(value, field)
        cleaned, found = redact_text(cleaned, field)

        return cleaned, count + found

    if isinstance(value, list):
        cleaned = []
        count = 0

        for item in value:
            result, found = clean_value(item, field_name)
            cleaned.append(result)
            count += found

        return cleaned, count

    if isinstance(value, dict):
        cleaned = {}
        count = 0
        protected_number = 1

        for key, item in value.items():
            original_key = str(key)
            category = classify_csv_column(original_key)

            # Do not expose potentially identifying field names.
            if category:
                clean_key = f"protected_field_{protected_number}"
                protected_number += 1
            else:
                clean_key, found_key = redact_text(original_key)
                count += found_key

                if clean_key != original_key:
                    clean_key = f"protected_field_{protected_number}"
                    protected_number += 1

            clean_item, found_item = clean_value(item, original_key)

            if clean_key in cleaned:
                clean_key = f"protected_field_{protected_number}"
                protected_number += 1

            cleaned[clean_key] = clean_item
            count += found_item

        return cleaned, count

    return value, 0


def clean_csv(text, delimiter):
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))

    if not rows:
        return "", 0

    headers = rows[0]
    sensitive_columns = set()
    safe_headers = []
    total = 0

    for index, header in enumerate(headers):
        category = classify_csv_column(header)

        if category:
            sensitive_columns.add(index)
            safe_headers.append(f"protected_field_{index + 1}")
        else:
            cleaned, found = redact_text(header)
            safe_headers.append(cleaned)
            total += found

    output = io.StringIO()
    writer = csv.writer(output, delimiter=delimiter, lineterminator="\n")
    writer.writerow(safe_headers)

    for row in rows[1:]:
        cleaned_row = []

        for index, value in enumerate(row):
            field_name = headers[index] if index < len(headers) else None

            if index in sensitive_columns:
                cleaned_row.append(REDACTED)
                total += 1
                continue

            cleaned, found = clean_embedded_base64(value, field_name)
            cleaned, extra = redact_text(cleaned, safe_field_name(field_name))

            cleaned_row.append(cleaned)
            total += found + extra

        writer.writerow(cleaned_row)

    return output.getvalue(), total


def clean_json(text):
    data = json.loads(text)
    cleaned, count = clean_value(data)

    return (
        json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n",
        count,
    )


def clean_txt(text):
    cleaned, count = clean_embedded_base64(text)
    cleaned, found = redact_text(cleaned)
    return cleaned, count + found


def get_safe_path(relative_path, used_paths):
    suffix = Path(relative_path).suffix.lower()

    if suffix not in SUPPORTED:
        raise ValueError("unsupported_format")

    number = len(used_paths) + 1
    safe_name = f"record_{number:06d}{suffix}"

    while safe_name in used_paths:
        number += 1
        safe_name = f"record_{number:06d}{suffix}"

    used_paths.add(safe_name)
    return safe_name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    start = time.monotonic()
    input_root = Path(args.input).resolve()
    output_root = Path(args.output).resolve()
    sanitized_root = output_root / "sanitized"

    if not input_root.is_dir():
        raise SystemExit("Input directory not found")

    sanitized_root.mkdir(parents=True, exist_ok=True)

    files = []
    records = []
    used_paths = set()
    identifiers_detected = 0

    input_files = sorted(
        path for path in input_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )

    for path in input_files:
        file_hash = None

        try:
            raw = path.read_bytes()
            file_hash = get_sha256(raw)
            extension = path.suffix.lower()

            if extension not in SUPPORTED:
                raise ValueError("unsupported_format")

            result = ingest_file(
                path,
                hospital_id=None,
                input_root=input_root,
            )

            if result.get("status") != "SUCCESS":
                raise ValueError("ingestion_failed")

            encoding = result.get("metadata", {}).get(
                "encoding", "utf-8-sig"
            )

            text = raw.decode(encoding)
            safe_path = get_safe_path(
                path.relative_to(input_root).as_posix(),
                used_paths,
            )

            if extension in (".csv", ".tsv"):
                delimiter = "\t" if extension == ".tsv" else ","
                cleaned, count = clean_csv(text, delimiter)

                row_count = max(
                    0,
                    sum(
                        1 for _ in csv.reader(
                            io.StringIO(text),
                            delimiter=delimiter,
                        )
                    ) - 1,
                )

                for row in range(row_count):
                    records.append({
                        "file": f"sanitized/{safe_path}",
                        "loc": f"row:{row}",
                        "patient": None,
                    })

            elif extension == ".json":
                cleaned, count = clean_json(text)

                records.append({
                    "file": f"sanitized/{safe_path}",
                    "loc": "doc",
                    "patient": None,
                })

            else:
                cleaned, count = clean_txt(text)

                records.append({
                    "file": f"sanitized/{safe_path}",
                    "loc": "doc",
                    "patient": None,
                })

            destination = sanitized_root / safe_path
            destination.write_text(cleaned, encoding="utf-8")

            identifiers_detected += count

            files.append({
                "input_sha256": file_hash,
                "output": f"sanitized/{safe_path}",
                "status": "sanitized",
            })

        except Exception as exc:
            # Do not put source paths, values or exception messages in reports.
            files.append({
                "input_sha256": file_hash,
                "output": None,
                "status": "quarantined",
                "reason": type(exc).__name__,
            })

    valid_outputs = {
        item["output"]
        for item in files
        if item["status"] == "sanitized"
    }

    records = [
        item for item in records
        if item["file"] in valid_outputs
    ]

    output_root.mkdir(parents=True, exist_ok=True)

    with (output_root / "records.jsonl").open(
        "w", encoding="utf-8"
    ) as file:
        for record in records:
            file.write(
                json.dumps(record, ensure_ascii=False) + "\n"
            )

    sanitized_count = sum(
        item["status"] == "sanitized" for item in files
    )

    report = {
        "schema": "raksha-report/1",
        "files": files,
        "counts": {
            "files_total": len(files),
            "files_sanitized": sanitized_count,
            "files_quarantined": len(files) - sanitized_count,
            "records_processed": len(records),
            "identifiers_detected": identifiers_detected,
            "records_linked": 0,
            "records_generalized": 0,
            "records_suppressed": 0,
            "records_quarantined": 0,
        },
        "timing": {
            "seconds": round(time.monotonic() - start, 2),
        },
        "resources": {
            "peak_rss_mb": get_peak_rss_mb(),
        },
    }

    (output_root / "report.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print(
        f"files {len(files)} "
        f"sanitized {sanitized_count} "
        f"quarantined {len(files) - sanitized_count} "
        f"records {len(records)}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
