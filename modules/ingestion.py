
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

    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):

        text = raw.decode("utf-16")

        if "\x00" in text:
            raise ValueError("binary_content")

        return text, "utf-16"

    try:

        text = raw.decode("utf-8-sig")

        if "\x00" in text:
            raise ValueError("binary_content")

        return text, "utf-8-sig"

    except UnicodeDecodeError:
        pass

    if b"\x00" in raw:

        try:

            text = raw.decode("utf-16")

            if "\x00" not in text:
                return text, "utf-16"

        except UnicodeDecodeError:
            pass

        raise ValueError("binary_content")

    try:

        text = raw.decode("cp1252")

        if "\x00" in text:
            raise ValueError("binary_content")

        return text, "cp1252"

    except UnicodeDecodeError:
        raise ValueError("undecodable_text")


def read_csv(text, delimiter):

    reader = csv.DictReader(
        io.StringIO(text),
        delimiter=delimiter
    )

    if not reader.fieldnames:
        raise ValueError("missing_header")

    headers = [
        header.strip() if header else ""
        for header in reader.fieldnames
    ]

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
    document_metadata = {}

    # FHIR Bundle
    if isinstance(data, dict) and data.get("resourceType") == "Bundle":

        file_format = "FHIR"

        document_metadata = {
            key: value
            for key, value in data.items()
            if key != "entry"
        }

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

    # JSON array
    elif isinstance(data, list):

        for index, item in enumerate(data):

            records.append({
                "locator": f"/{index}",
                "data": item
            })

    # JSON object
    elif isinstance(data, dict):

        collection_keys = (
            "visits",
            "patients",
            "results",
            "tickets"
        )

        selected_key = None

        for key in collection_keys:

            if isinstance(data.get(key), list):

                if selected_key is not None:

                    warnings.append(
                        "Multiple record collections found; "
                        "entire JSON object kept as one record"
                    )

                    selected_key = None
                    break

                selected_key = key

        if selected_key is not None:

            # Preserve all document-level information
            # outside the selected record collection.
            document_metadata = {
                key: value
                for key, value in data.items()
                if key != selected_key
            }

            for index, item in enumerate(data[selected_key]):

                if not isinstance(item, dict):

                    warnings.append(
                        f"Invalid record skipped at {selected_key}/{index}"
                    )
                    continue

                records.append({
                    "locator": f"/{selected_key}/{index}",
                    "data": item
                })

        else:

            records.append({
                "locator": "/",
                "data": data
            })

    # Primitive JSON value
    else:

        records.append({
            "locator": "/",
            "data": data
        })

    return records, file_format, warnings, document_metadata


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
        document_metadata = {}

        if file_format == "CSV":

            records = read_csv(text, ",")

        elif file_format == "TSV":

            records = read_csv(text, "\t")

        elif file_format == "JSON":

            records, file_format, warnings, document_metadata = read_json(text)

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
                "record_count": len(records),
                "document_metadata": document_metadata
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
