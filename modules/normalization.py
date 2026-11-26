
from copy import deepcopy

from modules.identity import normalize_name
from modules.pii_detection import detect_pii, detect_filename_pii
from modules.hospital_identification import identify_hospital


PATIENT_NAME_FIELDS = [
    "patient_name",
    "patient_full_name"
]

RELATIVE_NAME_FIELDS = {
    "relative_name": "relative",
    "guardian_name": "guardian",
    "father_name": "father",
    "mother_name": "mother"
}

IDENTIFIER_FIELDS = {
    "uhid": "UHID",
    "mrn": "UHID",
    "aadhaar": "AADHAAR",
    "aadhaar_no": "AADHAAR",
    "abha": "ABHA",
    "abha_no": "ABHA",
    "pan": "PAN",
    "payer_pan": "PAN",
    "policy_no": "INSURANCE_ID",
    "insurance_id": "INSURANCE_ID"
}


def extract_identity_candidates(data):

    candidates = {
        "patient_names": [],
        "relative_names": [],
        "identifiers": []
    }

    if not isinstance(data, dict):
        return candidates

    for field in PATIENT_NAME_FIELDS:
        value = data.get(field)

        if isinstance(value, str) and value.strip():
            normalized = normalize_name(value)

            if normalized:
                candidates["patient_names"].append({
                    "value": value.strip(),
                    "normalized_value": normalized,
                    "confidence": 0.99
                })

    for field, relation in RELATIVE_NAME_FIELDS.items():
        value = data.get(field)

        if isinstance(value, str) and value.strip():
            normalized = normalize_name(value)

            if normalized:
                candidates["relative_names"].append({
                    "value": value.strip(),
                    "normalized_value": normalized,
                    "relation": relation,
                    "confidence": 0.95
                })

    for field, identifier_type in IDENTIFIER_FIELDS.items():
        value = data.get(field)

        if isinstance(value, str) and value.strip():
            identifier = {
                "type": identifier_type,
                "value": value.strip(),
                "confidence": 0.99 if identifier_type == "UHID" else 0.95
            }

            if identifier_type in ("AADHAAR", "ABHA"):
                identifier["verified"] = False

            candidates["identifiers"].append(identifier)

    return candidates


def get_hospital_information(data, document_metadata, all_records):

    hospital_evidence = []

    hospital_input = {
        "document_metadata": document_metadata
    }

    if isinstance(data, dict):
        hospital_input.update(data)

    hospital = identify_hospital(hospital_input)

    if hospital["hospital_name"] is not None:
        hospital_evidence.append(hospital)

    for item in all_records:
        if not isinstance(item, dict):
            continue

        record_data = item.get("data")

        if not isinstance(record_data, dict):
            continue

        if record_data.get("resourceType") == "Organization":
            organization_hospital = identify_hospital(record_data)

            if organization_hospital["hospital_name"] is not None:
                hospital_evidence.append(organization_hospital)

    if not hospital_evidence:
        return {
            "hospital_name": None,
            "evidence_source": None,
            "confidence": "unknown"
        }

    hospital_names = {
        evidence["hospital_name"].strip().casefold()
        for evidence in hospital_evidence
        if isinstance(evidence.get("hospital_name"), str)
        and evidence["hospital_name"].strip()
    }

    if len(hospital_names) != 1:
        return {
            "hospital_name": None,
            "evidence_source": None,
            "confidence": "unknown"
        }

    return hospital_evidence[0]


def build_normalized_records(ingestion_result, known_names=None):

    if not isinstance(ingestion_result, dict):
        return []

    if ingestion_result.get("status") != "SUCCESS":
        return []

    records = ingestion_result.get("records", [])

    if not isinstance(records, list):
        return []

    metadata = ingestion_result.get("metadata", {})

    if not isinstance(metadata, dict):
        metadata = {}

    source_file = ingestion_result.get("source_file")
    file_format = ingestion_result.get("format")
    hospital_id = metadata.get("hospital_id")

    document_metadata = metadata.get("document_metadata", {})

    if not isinstance(document_metadata, dict):
        document_metadata = {}

    normalized_records = []

    for index, item in enumerate(records):

        if not isinstance(item, dict):
            continue

        data = item.get("data", {})

        if not isinstance(data, (dict, list, str)):
            continue

        locator = item.get("locator", f"record:{index}")
        record_id = f"REC_{len(normalized_records) + 1:03d}"

        hospital = get_hospital_information(
            data,
            document_metadata,
            records
        )

        candidates = extract_identity_candidates(data)

        source_type = (
            file_format.lower()
            if isinstance(file_format, str)
            else "unknown"
        )

        detections = detect_pii(
            data,
            source_type=source_type,
            base_path="data",
            known_names=known_names,
            record_id=record_id,
            source_file=source_file
        )

        metadata_detections = detect_pii(
            document_metadata,
            source_type=source_type,
            base_path="metadata.document_metadata",
            known_names=known_names,
            record_id=record_id,
            source_file=source_file
        )

        detections.extend(metadata_detections)

        if isinstance(source_file, str) and source_file:
            filename_detections = detect_filename_pii(
                source_file,
                known_names=known_names,
                record_id=record_id,
                source_file=source_file
            )

            detections.extend(filename_detections)

        normalized_records.append({
            "record_id": record_id,
            "source": {
                "hospital_id": hospital_id,
                "file": source_file,
                "locator": locator
            },
            "hospital": hospital,
            "identity_candidates": candidates,
            "detections": detections,
            "original_data": deepcopy(data)
        })

    return normalized_records
