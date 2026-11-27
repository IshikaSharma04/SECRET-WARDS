"""Classify hospital CSV headers without changing clinical field names."""

import re
import unicodedata


def _normalize_header(header):
    """Normalize spacing, punctuation and Unicode for comparison."""
    if not isinstance(header, str):
        return ""

    value = unicodedata.normalize("NFKC", header).casefold().strip()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


_HEADER_CATEGORIES = {
    "UHID": {
        "uhid", "uhid no", "uhid number",
        "mrn", "mrn no", "medical record number",
        "patient id", "patientid", "reg no", "registration no",
    },
    "PATIENT_NAME": {
        "name", "patient", "patient name", "patient full name",
        "name of patient", "naam", "patient naam",
        "firstname", "first name", "lastname", "last name",
    },
    "RELATIVE_NAME": {
        "relative name", "guardian", "guardian name",
        "father name", "mother name", "husband name",
        "pita pati ka naam", "pita ka naam", "pati ka naam",
    },
    "ADDRESS": {
        "address", "patient address", "pata",
        "village", "gaon", "village mohalla", "mohalla",
        "street", "city", "district", "jila", "tehsil",
        "state", "locality",
    },
    "PIN": {
        "pin", "pin code", "pincode", "postal code", "zip", "zip code",
    },
    "PHONE": {
        "mobile", "mobile no", "mobile number",
        "phone", "phone no", "phone number",
        "contact number", "contact no",
    },
    "AADHAAR": {
        "aadhaar", "aadhaar no", "aadhaar number",
        "aadhar", "aadhar no", "aadhar number",
    },
    "ABHA": {
        "abha", "abha no", "abha number", "abha id",
    },
    "DOB": {
        "dob", "date of birth", "birth date",
        "dob mm dd yyyy", "janm tithi",
    },
    "DATE": {
        "date", "reg date", "registration date",
        "registered", "registered mm dd yyyy",
        "admission date", "visit date",
    },
    "AGE": {
        "age", "patient age", "umar",
    },
}


def classify_csv_column(header):
    """
    Return the privacy category for a recognized sensitive column.

    Return None for headers that should not be classified by this function.
    Clinical headers such as Medicine, Dosage and Diagnosis remain untouched.
    """
    normalized = _normalize_header(header)

    if not normalized:
        return None

    # Exact aliases are safest: avoid classifying unrelated columns.
    for category, aliases in _HEADER_CATEGORIES.items():
        if normalized in aliases:
            return category

    return None
