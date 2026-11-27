
def identify_hospital(metadata):
    if not isinstance(metadata, dict):
        metadata = {}

    evidence = []

    # 1. Check JSON document metadata.
    document_metadata = metadata.get("document_metadata", {})

    if isinstance(document_metadata, dict):
        export_metadata = document_metadata.get("_export_meta", {})

        if isinstance(export_metadata, dict):
            hospital_name = export_metadata.get("hospital")

            if isinstance(hospital_name, str) and hospital_name.strip():
                evidence.append({
                    "hospital_name": hospital_name.strip(),
                    "evidence_source": "json_metadata"
                })

    # 2. Check explicit hospital fields.
    explicit_fields = [
        "hospital_name",
        "hospital",
        "facility_name",
        "facility"
    ]

    for field in explicit_fields:
        hospital_name = metadata.get(field)

        if isinstance(hospital_name, str) and hospital_name.strip():
            evidence.append({
                "hospital_name": hospital_name.strip(),
                "evidence_source": "explicit_field"
            })

    # 3. Check FHIR Organization resource.
    if metadata.get("resourceType") == "Organization":
        hospital_name = metadata.get("name")

        if isinstance(hospital_name, str) and hospital_name.strip():
            evidence.append({
                "hospital_name": hospital_name.strip(),
                "evidence_source": "fhir_organization"
            })

    # 4. No reliable hospital evidence found.
    if not evidence:
        return {
            "hospital_name": None,
            "evidence_source": None,
            "confidence": "unknown"
        }

    # 5. Reject conflicting hospital evidence.
    unique_names = {
        item["hospital_name"].casefold()
        for item in evidence
    }

    if len(unique_names) > 1:
        return {
            "hospital_name": None,
            "evidence_source": None,
            "confidence": "unknown"
        }

    # 6. Return the first available evidence when consistent.
    return {
        "hospital_name": evidence[0]["hospital_name"],
        "evidence_source": evidence[0]["evidence_source"],
        "confidence": "high"
    }
