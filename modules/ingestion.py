
import csv
import io
import json
from pathlib import Path


SUPPORTED_FORMATS = {
    ".csv": "CSV",
    ".tsv": "TSV",
    ".json": "JSON",
    ".txt": "TXT"
}


def make_result(source_file, file_format, status, error_code=None,
                records=None, metadata=None, warnings=None):
    return {
        "source_file": source_file,
        "format": file_format,
        "status": status,
        "error_code": error_code,
        "records": records if records is not None else [],
        "metadata": metadata if metadata is not None else {},
        "warnings": warnings if warnings is not None else []
    }


def decode_file(raw):
    encodings = ["utf-8-sig", "utf-16", "cp1252"]

    for encoding in encodings:
        try:
            text = raw.decode(encoding)

            if "\x00" in text:
                raise ValueError("binary_content")

            return text, encoding

        except UnicodeDecodeError:
            continue

    raise ValueError("undecodable_text")


def read_csv(text, delimiter):
    reader = csv.DictReader(
        io.StringIO(text),
        delimiter=delimiter
    )

    if not reader.fieldnames:
        raise ValueError("missing_header")

    headers = [header.strip() if header else "" for header in reader.fieldnames]

    if any(not header for header in headers):
        raise ValueError("empty_header")

    if len(headers) != len(set(headers)):
        raise ValueError("duplicate_header")

    reader.fieldnames = headers

    records = []

    for index, row in enumerate(reader):
        if None in row:
            raise ValueError("extra_columns")

        if all(value is None or value == "" for value in row.values()):
            continue

        records.append({
            "locator": f"row:{index}",
            "data": row
        })

    return records


def read_json(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("invalid_json") from error

    records = []
    warnings = []
    file_format = "JSON"

    if isinstance(data, dict) and data.get("resourceType") == "Bundle":
        file_format = "FHIR"

        entries = data.get("entry", [])

        if not isinstance(entries, list):
            raise ValueError("invalid_fhir_entries")

        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                warnings.append("Invalid FHIR entry skipped")
                continue

            resource = entry.get("resource")

            if not isinstance(resource, dict):
                warnings.append("FHIR entry without a resource skipped")
                continue

            records.append({
                "locator": f"/entry/{index}/resource",
                "data": resource
            })

    elif isinstance(data, list):
        for index, item in enumerate(data):
            records.append({
                "locator": f"/{index}",
                "data": item
            })

    else:
        records.append({
            "locator": "/",
            "data": data
        })

    return records, file_format, warnings


def read_text(text):
    return [{
        "locator": "doc",
        "data": {"text": text}
    }]


def ingest_file(file_path, hospital_id, input_root):
    path = Path(file_path)
    root = Path(input_root)
    file_format = SUPPORTED_FORMATS.get(path.suffix.lower())

    try:
        if path.is_symlink():
            return make_result(
                path.name, file_format, "UNSAFE", "symbolic_link"
            )

        resolved_path = path.resolve()
        resolved_root = root.resolve()

        if not resolved_path.is_relative_to(resolved_root):
            return make_result(
                path.name, file_format, "UNSAFE", "outside_input_folder"
            )

        if not resolved_path.is_file():
            return make_result(
                path.name, file_format, "MALFORMED", "not_a_file"
            )

        if file_format is None:
            return make_result(
                path.name, None, "UNSUPPORTED", "unsupported_format"
            )

        source_file = resolved_path.relative_to(resolved_root).as_posix()
        raw = resolved_path.read_bytes()

        if not raw.strip():
            return make_result(
                source_file, file_format, "MALFORMED", "empty_file"
            )

        text, encoding = decode_file(raw)

        warnings = []

        if file_format == "CSV":
            records = read_csv(text, ",")

        elif file_format == "TSV":
            records = read_csv(text, "\t")

        elif file_format == "JSON":
            records, file_format, warnings = read_json(text)

        else:
            records = read_text(text)

        return make_result(
            source_file,
            file_format,
            "SUCCESS",
            records=records,
            metadata={
                "hospital_id": hospital_id,
                "encoding": encoding,
                "record_count": len(records)
            },
            warnings=warnings
        )

    except ValueError as error:
        error_code = str(error)

        status = "UNSAFE" if error_code == "binary_content" else "MALFORMED"

        return make_result(
            path.name, file_format, status, error_code
        )

    except PermissionError:
        return make_result(
            path.name, file_format, "UNSAFE", "read_permission_denied"
        )

    except (OSError, csv.Error, RecursionError):
        return make_result(
            path.name, file_format, "MALFORMED", "file_read_error"
        )
