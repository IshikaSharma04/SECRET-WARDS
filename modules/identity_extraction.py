import re
from datetime import datetime


PATIENT_FIELDS = {
    "patient_name",
    "patient_full_name",
    "name_of_patient",
    "patient",
    "naam",
}

RELATIVE_FIELDS = {
    "father_name": "father",
    "mother_name": "mother",
    "guardian_name": "guardian",
    "relative_name": "relative",
    "spouse_name": "spouse",
    "husband_name": "spouse",
    "wife_name": "spouse",
    "pita_ka_naam": "father",
    "pati_ka_naam": "spouse",
}

ID_FIELDS = {
    "uhid": "UHID",
    "uhid_no": "UHID",
    "mrn": "MRN",
    "medical_record_number": "MRN",
    "hospital_patient_id": "HOSPITAL_ID",
    "hospital_patient_no": "HOSPITAL_ID",
    "patient_id": "HOSPITAL_ID",
    "patient_ref": "HOSPITAL_ID",
    "reg_no": "HOSPITAL_ID",
    "registration_no": "HOSPITAL_ID",
    "abha": "ABHA",
    "abha_id": "ABHA",
    "abha_no": "ABHA",
    "aadhaar": "AADHAAR",
    "aadhaar_no": "AADHAAR",
    "aadhar": "AADHAAR",
    "aadhar_no": "AADHAAR",
    "policy_no": "INSURANCE_ID",
    "policy_number": "INSURANCE_ID",
    "insurance_id": "INSURANCE_ID",
    "insurance_no": "INSURANCE_ID",
    "phone": "PHONE",
    "mobile": "PHONE",
    "mobile_no": "PHONE",
    "phone_no": "PHONE",
    "email": "EMAIL",
    "email_id": "EMAIL",
    "pan": "PAN",
    "pan_no": "PAN",
    "ipd_no": "IPD",
    "ipd_number": "IPD",
}

INSURANCE_FIELDS = {
    "insurance_provider",
    "insurance_company",
    "insurer",
}

DOB_FIELDS = {
    "dob",
    "dob_mm_dd_yyyy",
    "date_of_birth",
    "birth_date",
    "birthdate",
    "janm_tithi",
}

AGE_FIELDS = {
    "age",
    "umar",
}

VILLAGE_FIELDS = {
    "village",
    "village_mohalla",
    "gaon",
}

LOCALITY_FIELDS = {
    "city",
}

RELATION_FIELDS = {
    "relation",
    "relationship",
    "guardian_relation",
}


def normalize_field(field):
    field = re.sub(
        r"([a-z0-9])([A-Z])",
        r"\1_\2",
        str(field)
    )

    return re.sub(
        r"[^a-zA-Z0-9]+",
        "_",
        field
    ).lower().strip("_")


def clean_value(value):
    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return str(value)

    if not isinstance(value, str):
        return None

    value = value.strip()

    return value if value else None


def normalize_date(value, field=None):
    value = clean_value(value)

    if not value:
        return None

    field = normalize_field(field) if field else None

    # ISO dates are unambiguous and are used by FHIR and DHH.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        formats = ("%Y-%m-%d",)

    elif re.match(r"^\d{4}-\d{2}-\d{2}T", value):
        value = value[:10]
        formats = ("%Y-%m-%d",)

    # Arogya explicitly labels its DOB as MM/DD/YYYY.
    elif field == "dob_mm_dd_yyyy":
        formats = ("%m/%d/%Y",)

    # Sanjeevani DOB and Jeevan Jyoti Janm Tithi use DD/MM/YYYY
    # and DD-MM-YYYY respectively.
    elif field in ("dob", "janm_tithi"):
        formats = (
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%d.%m.%Y",
            "%d/%m/%y",
            "%d-%m-%y",
        )

    else:
        # Do not guess the format of an unknown date field.
        return None

    for date_format in formats:
        try:
            parsed = datetime.strptime(value, date_format)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


def get_relation(value):
    if not isinstance(value, str):
        return None

    value = value.strip().casefold()
    value = re.sub(r"\s+", "", value)
    value = value.replace(".", "")

    relations = {
        "s/o": "father",
        "d/o": "father",
        "f/o": "father",
        "father": "father",
        "son": "father",
        "daughter": "father",
        "mother": "mother",
        "w/o": "spouse",
        "husband": "spouse",
        "wife": "spouse",
        "c/o": "guardian",
        "guardian": "guardian",
    }

    return relations.get(value)


def add_name(result, value, relation=None):
    value = clean_value(value)

    if not value:
        return

    item = {
        "value": value,
        "confidence": 0.99,
    }

    if relation:
        item["relation"] = relation
        target = "relative_names"
    else:
        target = "patient_names"

    if item not in result[target]:
        result[target].append(item)


def add_identifier(result, field, value, scope=None):
    value = clean_value(value)
    kind = ID_FIELDS.get(field)

    if not value or not kind:
        return

    item = {
        "type": kind,
        "value": value,
        "confidence": 0.99,
    }

    if kind in ("ABHA", "AADHAAR"):
        item["verified"] = False

    if kind == "INSURANCE_ID" and scope:
        item["scope"] = scope.casefold()

    if item not in result["identifiers"]:
        result["identifiers"].append(item)


def add_secondary_clue(result, field, value):
    if field in DOB_FIELDS:
        clue = "dob"

    elif field in AGE_FIELDS:
        clue = "age"

    elif field in VILLAGE_FIELDS:
        clue = "village"

    elif field in LOCALITY_FIELDS:
        clue = "locality"

    else:
        return

    value = clean_value(value)

    if not value:
        return

    if clue == "dob":
        value = normalize_date(value, field)

        if not value:
            return

    elif clue == "age":
        match = re.fullmatch(
            r"\s*(\d{1,3})\s*(?:years?|yrs?|y)?\s*",
            value,
            re.IGNORECASE
        )

        if not match:
            return

        age = int(match.group(1))

        if not 0 <= age <= 120:
            return

        value = age

    elif clue in ("village", "locality"):
        # Preserve original capitalization for output and debugging.
        # Normalize case later when comparing identity clues.
        value = re.sub(r"\s+", " ", value).strip()

    if result["secondary_clues"][clue] is None:
        result["secondary_clues"][clue] = value


def split_guardian(value):
    value = clean_value(value)

    if not value:
        return None, None

    match = re.match(
        r"^\s*(s/o|d/o|w/o|f/o|c/o)\s+(.+)$",
        value,
        flags=re.IGNORECASE
    )

    if not match:
        return None, value

    relation = get_relation(match.group(1))

    return relation, match.group(2).strip()


def extract_fhir_patient(data, result):
    names = data.get("name", [])

    if isinstance(names, dict):
        names = [names]

    if isinstance(names, list):
        for name in names:
            if not isinstance(name, dict):
                continue

            full_name = clean_value(name.get("text"))

            if not full_name:
                given = name.get("given", [])

                if isinstance(given, str):
                    given = [given]

                if not isinstance(given, list):
                    given = []

                parts = [
                    part.strip()
                    for part in given
                    if isinstance(part, str) and part.strip()
                ]

                family = clean_value(name.get("family"))

                if family:
                    parts.append(family)

                full_name = " ".join(parts)

            add_name(result, full_name)

    identifiers = data.get("identifier", [])

    if isinstance(identifiers, dict):
        identifiers = [identifiers]

    if isinstance(identifiers, list):
        for identifier in identifiers:
            if not isinstance(identifier, dict):
                continue

            system = str(
                identifier.get("system") or ""
            ).casefold()

            field = None

            if "aadhaar" in system or "aadhar" in system:
                field = "aadhaar"

            elif "abha" in system or "healthid" in system:
                field = "abha"

            elif "uhid" in system:
                field = "uhid"

            elif "mrn" in system:
                field = "mrn"

            if field:
                add_identifier(
                    result,
                    field,
                    identifier.get("value")
                )

    add_secondary_clue(
        result,
        "birth_date",
        data.get("birthDate")
    )

    addresses = data.get("address", [])

    if isinstance(addresses, dict):
        addresses = [addresses]

    if isinstance(addresses, list):
        for address in addresses:
            if not isinstance(address, dict):
                continue

            add_secondary_clue(
                result,
                "city",
                address.get("city")
            )

            lines = address.get("line", [])

            if isinstance(lines, str):
                lines = [lines]

            if isinstance(lines, list):
                for line in lines:
                    add_secondary_clue(
                        result,
                        "village",
                        line
                    )


def extract_identity_candidates(data):
    result = {
        "patient_names": [],
        "relative_names": [],
        "identifiers": [],
        "secondary_clues": {
            "dob": None,
            "age": None,
            "village": None,
            "locality": None,
        },
    }

    if not isinstance(data, (dict, list)):
        return result

    def visit(value):
        if isinstance(value, list):
            for item in value:
                if isinstance(item, (dict, list)):
                    visit(item)

            return

        if not isinstance(value, dict):
            return

        resource_type = value.get("resourceType")

        if resource_type == "Patient":
            extract_fhir_patient(value, result)
            return

        if resource_type and resource_type != "Bundle":
            return

        scope = None

        for key, item in value.items():
            if normalize_field(key) in INSURANCE_FIELDS:
                scope = clean_value(item)
                break

        first_name = None
        last_name = None
        relation = None

        for key, item in value.items():
            if normalize_field(key) in RELATION_FIELDS:
                relation = clean_value(item)
                break

        for key, item in value.items():
            field = normalize_field(key)

            if field in ("first_name", "first"):
                first_name = clean_value(item)

            elif field in ("last_name", "last"):
                last_name = clean_value(item)

            elif field in PATIENT_FIELDS:
                if isinstance(item, str):
                    add_name(result, item)

                elif isinstance(item, dict):
                    name = clean_value(item.get("text"))

                    if not name:
                        given = clean_value(item.get("given"))
                        family = clean_value(item.get("family"))

                        name = " ".join(
                            part for part in (given, family) if part
                        )

                    add_name(result, name)

            elif field in RELATIVE_FIELDS:
                relative_type = RELATIVE_FIELDS[field]

                if field == "relative_name":
                    relative_type = (
                        get_relation(relation) or "relative"
                    )

                add_name(
                    result,
                    item,
                    relative_type
                )

            elif field in ID_FIELDS:
                add_identifier(
                    result,
                    field,
                    item,
                    scope
                )

            elif (
                field in DOB_FIELDS
                or field in AGE_FIELDS
                or field in VILLAGE_FIELDS
                or field in LOCALITY_FIELDS
            ):
                add_secondary_clue(
                    result,
                    field,
                    item
                )

        if first_name or last_name:
            full_name = " ".join(
                part
                for part in (first_name, last_name)
                if part
            )

            add_name(result, full_name)

        for key, item in value.items():
            field = normalize_field(key)

            if field in ("guardian", "pita_pati_ka_naam"):
                if isinstance(item, dict):
                    relative_name = clean_value(item.get("name"))

                    relation_type = get_relation(
                        item.get("relation")
                    )

                else:
                    relation_type, relative_name = split_guardian(item)

                if relative_name:
                    add_name(
                        result,
                        relative_name,
                        relation_type
                        or get_relation(relation)
                        or "relative"
                    )

            if isinstance(item, (dict, list)):
                visit(item)

    visit(data)

    return result