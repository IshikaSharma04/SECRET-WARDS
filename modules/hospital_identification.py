
def identify_hospital(metadata):
    if not isinstance(metadata, dict):
        metadata = {}

    # 1. Check JSON document metadata
    document_metadata = metadata.get("document_metadata", {})

    if not isinstance(document_metadata, dict):
        document_metadata = {}

    export_metadata = document_metadata.get("_export_meta", {})

    if not isinstance(export_metadata, dict):
        export_metadata = {}

    hospital_name = export_metadata.get("hospital")

    if isinstance(hospital_name, str) and hospital_name.strip():
        return {
            "hospital_name": hospital_name.strip(),
            "evidence_source": "json_metadata",
            "confidence": "high"
        }

    # 2. Check explicit hospital fields
    explicit_fields = [
        "hospital_name",
        "hospital",
        "facility_name",
        "facility"
    ]

    for field in explicit_fields:
        hospital_name = metadata.get(field)

        if isinstance(hospital_name, str) and hospital_name.strip():
            return {
                "hospital_name": hospital_name.strip(),
                "evidence_source": "explicit_field",
                "confidence": "high"
            }

    # 3. Check FHIR Organization resource
    if metadata.get("resourceType") == "Organization":
        hospital_name = metadata.get("name")

        if isinstance(hospital_name, str) and hospital_name.strip():
            return {
                "hospital_name": hospital_name.strip(),
                "evidence_source": "fhir_organization",
                "confidence": "high"
            }

    # 4. No reliable hospital evidence found
    return {
        "hospital_name": None,
        "evidence_source": None,
        "confidence": "unknown"
    }
