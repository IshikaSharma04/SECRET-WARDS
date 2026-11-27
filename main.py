
#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import sys
import time
import unicodedata

from pathlib import Path

from modules.ingestion import ingest_file
from modules.normalization import build_normalized_records
from modules.hospital_identification import identify_hospital
from modules.identity_resolver import resolve_records
from modules.pii_detection import detect_pii, detect_filename_pii


class Stats:
    identifiers = 0
    generalized = 0
    suppressed = 0


def decode(raw):
    """Decode supported text encodings without silently replacing characters."""

    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="strict")

    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="strict")

    for encoding in ("utf-8", "cp1252"):
        try:
            return raw.decode(encoding, errors="strict")
        except UnicodeDecodeError:
            continue

    return None


def safe_hospital_id(hospital_name):
    """Create a stable, non-sensitive Unicode-safe hospital identifier."""

    if not isinstance(hospital_name, str) or not hospital_name.strip():
        return None

    value = unicodedata.normalize("NFKC", hospital_name)
    value = value.casefold().strip()

    cleaned = []

    for char in value:
        category = unicodedata.category(char)

        if category[0] in ("L", "M", "N"):
            cleaned.append(char)
        else:
            cleaned.append("_")

    value = "".join(cleaned)
    value = re.sub(r"_+", "_", value).strip("_")

    return value or None


def get_hospital_id(ingestion_result):
    """Identify a hospital only when all available evidence agrees."""

    if not isinstance(ingestion_result, dict):
        return None

    metadata = ingestion_result.get("metadata") or {}

    if not isinstance(metadata, dict):
        metadata = {}

    records = ingestion_result.get("records") or []

    if not isinstance(records, list):
        records = []

    evidence = []

    document_metadata = metadata.get("document_metadata")

    if isinstance(document_metadata, dict):
        result = identify_hospital({
            "document_metadata": document_metadata
        })

        if isinstance(result, dict) and result.get("hospital_name"):
            evidence.append(result["hospital_name"])

    explicit_fields = [
        "hospital_name",
        "hospital",
        "facility_name",
        "facility"
    ]

    for field in explicit_fields:
        hospital_name = metadata.get(field)

        if isinstance(hospital_name, str) and hospital_name.strip():
            result = identify_hospital({
                field: hospital_name
            })

            if isinstance(result, dict) and result.get("hospital_name"):
                evidence.append(result["hospital_name"])

    for item in records:
        if not isinstance(item, dict):
            continue

        data = item.get("data")

        if not isinstance(data, dict):
            continue

        if data.get("resourceType") != "Organization":
            continue

        result = identify_hospital(data)

        if isinstance(result, dict) and result.get("hospital_name"):
            evidence.append(result["hospital_name"])

    if not evidence:
        return None

    normalized_names = {
        " ".join(
            unicodedata.normalize("NFKC", name).casefold().split()
        )
        for name in evidence
    }

    if len(normalized_names) != 1:
        return None

    return safe_hospital_id(evidence[0])


def collect_known_names(normalized_records):
    """Build a dataset-wide name collection for narrative redaction."""

    known_names = {
        "PATIENT_NAME": set(),
        "RELATIVE_NAME": set(),
    }

    for record in normalized_records:
        candidates = record.get("identity_candidates") or {}

        for item in candidates.get("patient_names") or []:
            if isinstance(item, dict):
                value = item.get("value")

                if isinstance(value, str) and value.strip():
                    known_names["PATIENT_NAME"].add(value.strip())

        for item in candidates.get("relative_names") or []:
            if isinstance(item, dict):
                value = item.get("value")

                if isinstance(value, str) and value.strip():
                    known_names["RELATIVE_NAME"].add(value.strip())

    return {
        category: sorted(names, key=len, reverse=True)
        for category, names in known_names.items()
    }


def redact_string(value, path, detections, target="value"):
    """Apply detections to the original string, from right to left."""

    matching = [
        item for item in detections
        if item.get("path") == path
        and item.get("target") == target
    ]

    matching.sort(
        key=lambda item: item.get("start", 0),
        reverse=True
    )

    result = value

    for item in matching:
        start = item.get("start")
        end = item.get("end")
        category = item.get("category", "PII")

        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end > len(result)
            or start >= end
        ):
            continue

        result = result[:start] + f"[{category}]" + result[end:]

    return result


def sanitize_tree(data, detections, path="data"):
    """Redact detected values and dictionary keys recursively."""

    if isinstance(data, str):
        return redact_string(data, path, detections)

    if isinstance(data, list):
        return [
            sanitize_tree(
                item,
                detections,
                f"{path}/{index}"
            )
            for index, item in enumerate(data)
        ]

    if isinstance(data, dict):
        result = {}

        for key, value in data.items():
            child_path = (
                path.rstrip("/") + "/" +
                str(key).replace("~", "~0").replace("/", "~1")
            )

            clean_key = redact_string(
                str(key),
                child_path,
                detections,
                target="key"
            )

            # Correct argument order:
            # sanitize_tree(data, detections, path)
            clean_value = sanitize_tree(
                value,
                detections,
                child_path
            )

            original_clean_key = clean_key
            suffix = 2

            while clean_key in result:
                clean_key = f"{original_clean_key}_{suffix}"
                suffix += 1

            result[clean_key] = clean_value

        return result

    return data


def add_patient_pseudonym(data, locator, pseudonym):
    """Insert a pseudonym into the corresponding JSON record."""

    if not isinstance(data, (dict, list)):
        return

    if locator == "/":
        target = data

    else:
        parts = locator.strip("/").split("/")
        target = data

        try:
            for part in parts:
                part = part.replace("~1", "/").replace("~0", "~")

                if isinstance(target, list):
                    target = target[int(part)]
                elif isinstance(target, dict):
                    target = target[part]
                else:
                    return
        except (KeyError, IndexError, ValueError, TypeError):
            return

    if not isinstance(target, dict):
        return

    if target.get("resourceType"):
        extensions = target.setdefault("extension", [])

        if not isinstance(extensions, list):
            return

        extensions.append({
            "url": "https://raksha.example/fhir/StructureDefinition/patient-pseudonym",
            "valueIdentifier": {
                "value": pseudonym
            }
        })

    else:
        target["patient_pseudonym"] = pseudonym


def has_patient_identity(record):
    candidates = record.get("identity_candidates") or {}

    return bool(
        candidates.get("patient_names")
        or candidates.get("relative_names")
        or candidates.get("identifiers")
    )


def get_resolution_by_key(resolution):
    """Index resolver results using their source file and local record ID."""

    return {
        (item.get("source_file"), item.get("record_id")): item
        for item in resolution
    }


def process_csv_file(text, delimiter, rel, normalized, resolution, known_names):
    reader = csv.DictReader(io.StringIO(text, newline=""))

    if not reader.fieldnames:
        raise ValueError("missing_csv_header")

    fieldnames = list(reader.fieldnames)

    if "patient_pseudonym" not in fieldnames:
        fieldnames.append("patient_pseudonym")

    by_locator = {
        item.get("source", {}).get("locator"): item
        for item in normalized
    }

    resolution_by_key = get_resolution_by_key(resolution)

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
        delimiter=delimiter,
        lineterminator="\n",
        extrasaction="ignore"
    )
    writer.writeheader()

    records_jsonl = []
    row_index = 0

    for row in reader:
        locator = f"row:{row_index}"
        row_index += 1

        normalized_record = by_locator.get(locator)
        pseudonym = None

        if normalized_record:
            source_file = normalized_record.get("source", {}).get("file")
            record_id = normalized_record.get("record_id")

            result = resolution_by_key.get(
                (source_file, record_id)
            )

            if result:
                pseudonym = result.get("pseudonym")

        detections = detect_pii(
            row,
            source_type="csv",
            base_path="data",
            known_names=known_names
        )

        Stats.identifiers += len(detections)

        clean_row = sanitize_tree(row, detections)
        clean_row["patient_pseudonym"] = pseudonym or ""

        writer.writerow(clean_row)

        if normalized_record and has_patient_identity(normalized_record):
            records_jsonl.append({
                "file": f"sanitized/{rel}",
                "loc": locator,
                "patient": pseudonym
            })

    return output.getvalue(), records_jsonl


def process_json_file(text, rel, normalized, resolution, known_names):
    data = json.loads(text)

    detections = detect_pii(
        data,
        source_type="json",
        base_path="data",
        known_names=known_names
    )

    Stats.identifiers += len(detections)

    clean_data = sanitize_tree(data, detections)

    resolution_by_key = get_resolution_by_key(resolution)

    records_jsonl = []

    for record in normalized:
        if not has_patient_identity(record):
            continue

        source_file = record.get("source", {}).get("file")
        record_id = record.get("record_id")

        result = resolution_by_key.get(
            (source_file, record_id)
        )

        if not result:
            continue

        pseudonym = result.get("pseudonym")

        if pseudonym:
            locator = record.get("source", {}).get("locator")
            add_patient_pseudonym(clean_data, locator, pseudonym)

        records_jsonl.append({
            "file": f"sanitized/{rel}",
            "loc": record.get("source", {}).get("locator"),
            "patient": pseudonym
        })

    return (
        json.dumps(clean_data, ensure_ascii=False, indent=2) + "\n",
        records_jsonl
    )


def process_text_file(text, rel, known_names):
    data = {"text": text}

    detections = detect_pii(
        data,
        source_type="text",
        base_path="data",
        known_names=known_names
    )

    Stats.identifiers += len(detections)

    clean_data = sanitize_tree(data, detections)

    return clean_data["text"], []


def get_safe_output_path(relative_path, raw, known_names):
    """Avoid exposing names contained in filenames or directory names."""

    detections = detect_filename_pii(
        relative_path,
        known_names=known_names
    )

    if not detections:
        return relative_path

    digest = hashlib.sha256(raw).hexdigest()[:12]
    extension = Path(relative_path).suffix.lower()

    return f"redacted/{digest}{extension}"


def peak_rss_mb():
    try:
        import resource

        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

        if sys.platform == "darwin":
            return round(value / 1048576, 1)

        return round(value / 1024, 1)

    except Exception:
        return 0.0


def prepare_output_directory(input_root, output_root, sanitized_root):
    """Safely remove only the previous generated sanitized output."""

    resolved_sanitized = sanitized_root.resolve()

    if output_root == input_root or input_root in output_root.parents:
        raise SystemExit(
            "Output directory must not be inside the input directory"
        )

    if (
        resolved_sanitized == input_root
        or input_root in resolved_sanitized.parents
    ):
        raise SystemExit(
            "Sanitized output directory must not contain the input directory"
        )

    if sanitized_root.is_symlink():
        raise SystemExit(
            "Sanitized output directory must not be a symbolic link"
        )

    output_root.mkdir(parents=True, exist_ok=True)

    if sanitized_root.exists():
        shutil.rmtree(sanitized_root)

    sanitized_root.mkdir(parents=True, exist_ok=True)


def write_debug_error(debug_file, relative_path, stage, error):
    """Write exception metadata without recording patient data or filenames."""

    path_hash = hashlib.sha256(
        relative_path.encode("utf-8", errors="replace")
    ).hexdigest()[:12]

    error_name = getattr(error, "name", None)
    error_object = getattr(error, "obj", None)

    debug_entry = {
        "file_hash": path_hash,
        "stage": stage,
        "exception": type(error).__name__,
        "attribute": error_name,
        "object_type": (
            type(error_object).__name__
            if error_object is not None
            else None
        )
    }

    debug_file.write(
        json.dumps(debug_entry, ensure_ascii=True) + "\n"
    )
    debug_file.flush()


def main():
    parser = argparse.ArgumentParser(
        description="RAKSHA privacy and identity pipeline"
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    started = time.monotonic()

    input_root = Path(args.input).resolve()
    output_root = Path(args.output).resolve()
    sanitized_root = output_root / "sanitized"

    if not input_root.is_dir():
        raise SystemExit("Input directory does not exist")

    prepare_output_directory(
        input_root,
        output_root,
        sanitized_root
    )

    Stats.identifiers = 0
    Stats.generalized = 0
    Stats.suppressed = 0

    sys.setrecursionlimit(5000)

    files = []
    all_normalized = []
    file_data = {}

    debug_path = output_root / "debug_errors.txt"

    with open(debug_path, "w", encoding="utf-8") as debug_file:

        # -----------------------------------------------------------
        # Pass 1: ingest and normalize every supported file.
        # -----------------------------------------------------------

        for path in sorted(p for p in input_root.rglob("*") if p.is_file()):
            relative_path = path.relative_to(input_root).as_posix()
            raw = path.read_bytes()

            entry = {
                "input_sha256": hashlib.sha256(raw).hexdigest()
            }

            extension = path.suffix.lower()
            stage = "format_validation"

            try:
                if extension not in (".csv", ".tsv", ".json", ".txt"):
                    raise ValueError("unsupported_format")

                if not raw.strip():
                    raise ValueError("empty_file")

                stage = "decoding"
                text = decode(raw)

                if text is None:
                    raise ValueError("undecodable_text")

                stage = "ingestion"
                ingestion = ingest_file(
                    path,
                    hospital_id=None,
                    input_root=input_root
                )

                if not isinstance(ingestion, dict):
                    raise TypeError("ingestion_result_not_dict")

                if ingestion.get("status") != "SUCCESS":
                    raise ValueError(
                        ingestion.get("error_code") or "ingestion_failed"
                    )

                stage = "hospital_identification"
                hospital_id = get_hospital_id(ingestion)

                stage = "metadata_update"
                metadata = ingestion.get("metadata")

                if not isinstance(metadata, dict):
                    metadata = {}
                    ingestion["metadata"] = metadata

                metadata["hospital_id"] = hospital_id

                stage = "normalization"
                normalized = build_normalized_records(ingestion)

                if not isinstance(normalized, list):
                    raise TypeError("normalized_records_not_list")

                all_normalized.extend(normalized)

                file_data[relative_path] = {
                    "text": text,
                    "raw": raw,
                    "extension": extension,
                    "normalized": normalized
                }

                entry["_relative_path"] = relative_path
                entry["status"] = "pending"

            except Exception as error:
                entry["status"] = "quarantined"
                entry["output"] = None
                entry["reason"] = (
                    str(error)
                    if isinstance(error, ValueError)
                    and str(error).isidentifier()
                    else type(error).__name__
                )

                write_debug_error(
                    debug_file,
                    relative_path,
                    stage,
                    error
                )

            files.append(entry)

        # -----------------------------------------------------------
        # Pass 2: resolve identities across the complete dataset.
        # -----------------------------------------------------------

        known_names = collect_known_names(all_normalized)

        resolution = resolve_records(all_normalized)

        resolution_by_key = get_resolution_by_key(resolution)

        # -----------------------------------------------------------
        # Pass 3: sanitize and write files.
        # -----------------------------------------------------------

        records_jsonl = []

        for entry in files:
            relative_path = entry.get("_relative_path")

            if not relative_path:
                continue

            item = file_data.get(relative_path)

            if not item:
                continue

            text = item["text"]
            raw = item["raw"]
            extension = item["extension"]
            normalized = item["normalized"]

            safe_path = get_safe_output_path(
                relative_path,
                raw,
                known_names
            )

            stage = "sanitization"

            try:
                if extension == ".csv":
                    result, record_lines = process_csv_file(
                        text,
                        ",",
                        safe_path,
                        normalized,
                        resolution,
                        known_names
                    )

                elif extension == ".tsv":
                    result, record_lines = process_csv_file(
                        text,
                        "\t",
                        safe_path,
                        normalized,
                        resolution,
                        known_names
                    )

                elif extension == ".json":
                    result, record_lines = process_json_file(
                        text,
                        safe_path,
                        normalized,
                        resolution,
                        known_names
                    )

                else:
                    result, record_lines = process_text_file(
                        text,
                        safe_path,
                        known_names
                    )

                stage = "output_writing"

                destination = sanitized_root / safe_path
                destination.parent.mkdir(parents=True, exist_ok=True)

                destination.write_text(
                    result,
                    encoding="utf-8",
                    newline=""
                )

                entry["output"] = f"sanitized/{safe_path}"
                entry["status"] = "sanitized"

                records_jsonl.extend(record_lines)

            except Exception as error:
                entry["output"] = None
                entry["status"] = "quarantined"
                entry["reason"] = type(error).__name__

                write_debug_error(
                    debug_file,
                    relative_path,
                    stage,
                    error
                )

    # Remove internal processing fields from the report.
    for entry in files:
        entry.pop("_relative_path", None)

    # Only records from successfully written files may be exported.
    exported = {
        entry["output"]
        for entry in files
        if entry.get("output")
    }

    records_jsonl = [
        record for record in records_jsonl
        if record["file"] in exported
    ]

    with open(
        output_root / "records.jsonl",
        "w",
        encoding="utf-8"
    ) as output_file:
        for record in records_jsonl:
            output_file.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True
                ) + "\n"
            )

    # ---------------------------------------------------------------
    # Report
    # ---------------------------------------------------------------

    sanitized_count = sum(
        entry["status"] == "sanitized"
        for entry in files
    )

    quarantined_count = sum(
        entry["status"] == "quarantined"
        for entry in files
    )

    report = {
        "schema": "raksha-report/1",
        "files": files,
        "counts": {
            "files_total": len(files),
            "files_sanitized": sanitized_count,
            "files_quarantined": quarantined_count,
            "records_processed": len(records_jsonl),
            "identifiers_detected": Stats.identifiers,
            "records_linked": sum(
                record["patient"] is not None
                for record in records_jsonl
            ),
            "records_generalized": Stats.generalized,
            "records_suppressed": Stats.suppressed,
            "records_quarantined": 0
        },
        "timing": {
            "seconds": round(time.monotonic() - started, 2)
        },
        "resources": {
            "peak_rss_mb": peak_rss_mb()
        }
    }

    (output_root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )

    print(
        f"files {len(files)} "
        f"sanitized {sanitized_count} "
        f"quarantined {quarantined_count} "
        f"records {len(records_jsonl)}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
