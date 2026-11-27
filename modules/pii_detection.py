
import re
import unicodedata

from modules.identity import normalize_name


FIELD_CATEGORIES = {
    "patient_name": "PATIENT_NAME",
    "name": "PATIENT_NAME",
    "full_name": "PATIENT_NAME",
    "relative_name": "RELATIVE_NAME",
    "guardian_name": "RELATIVE_NAME",
    "father_name": "RELATIVE_NAME",
    "mother_name": "RELATIVE_NAME",
    "mobile": "PHONE",
    "phone": "PHONE",
    "phone_number": "PHONE",
    "contact": "PHONE",
    "aadhaar": "AADHAAR",
    "aadhaar_no": "AADHAAR",
    "aadhar": "AADHAAR",
    "abha": "ABHA",
    "abha_no": "ABHA",
    "uhid": "UHID",
    "mrn": "MRN",
    "patient_id": "MRN",
    "pan": "PAN",
    "address": "ADDRESS",
    "pin": "PIN_CODE",
    "pincode": "PIN_CODE",
    "policy_no": "INSURANCE_ID",
    "insurance_id": "INSURANCE_ID",
    "dob": "DOB",
    "date_of_birth": "DOB",
    "email": "EMAIL",
    "village": "VILLAGE",
    "locality": "LOCALITY",
    "house_no": "HOUSE",
    "landmark": "LANDMARK",
}


PATTERNS = {
    "AADHAAR": re.compile(
        r"(?<!\d)(?:\d{4}[ -]?){2}\d{4}(?!\d)"
    ),
    "PHONE": re.compile(
        r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"
    ),
    "PAN": re.compile(
        r"(?<![A-Z0-9])[A-Z]{5}\d{4}[A-Z](?![A-Z0-9])",
        re.IGNORECASE,
    ),
    "EMAIL": re.compile(
        r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
        re.IGNORECASE,
    ),
}


LABELLED_PATTERNS = {
    "ABHA": re.compile(
        r"\bABHA(?:\s*(?:ID|NO\.?|NUMBER))?"
        r"\s*[:#-]?\s*(\d{2}(?:[ -]?\d){12})\b",
        re.IGNORECASE,
    ),
    "UHID": re.compile(
        r"\bUHID\s*[:#-]?\s*([A-Z0-9][A-Z0-9/-]{3,})\b",
        re.IGNORECASE,
    ),
    "MRN": re.compile(
        r"\b(?:MRN|PATIENT\s*ID|REGISTRATION\s*(?:NO\.?|NUMBER))"
        r"\s*[:#-]?\s*([A-Z0-9][A-Z0-9/-]{3,})\b",
        re.IGNORECASE,
    ),
    "PIN_CODE": re.compile(
        r"\b(?:PIN(?:\s*CODE)?|PINCODE|POSTAL\s*CODE)"
        r"\s*[:#-]?\s*(\d{6})\b",
        re.IGNORECASE,
    ),
    "INSURANCE_ID": re.compile(
        r"\b(?:POLICY\s*(?:NO\.?|NUMBER)|INSURANCE\s*(?:ID|NO\.?|NUMBER))"
        r"\s*[:#-]?\s*([A-Z0-9][A-Z0-9/-]{3,})\b",
        re.IGNORECASE,
    ),
    "DOB": re.compile(
        r"\b(?:DOB|D\.O\.B|DATE\s*OF\s*BIRTH)"
        r"\s*[:#-]?\s*(\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4})\b",
        re.IGNORECASE,
    ),
}


PATIENT_LABELS = re.compile(
    r"(?:patient\s*(?:full\s*)?name|name\s*of\s*patient|"
    r"रोगी\s*का\s*नाम|मरीज\s*का\s*नाम|मरीज़\s*का\s*नाम)"
    r"\s*[:=#-]\s*([^\n,;|]{2,80})",
    re.IGNORECASE,
)


REPORT_PATTERN = re.compile(
    r"\bReport\s+of\s+"
    r"([A-Za-z][A-Za-z.'-]*(?:\s+[A-Za-z][A-Za-z.'-]*){1,3}?)"
    r"(?=\s+(?:behenji|bhai|sir|madam)\b|\s+\d+\s*[Yy]\b)",
    re.IGNORECASE,
)


RELATIVE_LABELS = re.compile(
    r"(?:C/O|S/O|D/O|W/O|F/O|relative\s*name|guardian\s*name|"
    r"father(?:'s)?\s*name|mother(?:'s)?\s*name|"
    r"पिता|माता|पति|पत्नी|अभिभावक)"
    r"\s*[:=#-]?\s*"
    r"([A-Za-z\u0900-\u097F][A-Za-z\u0900-\u097F.'-]*"
    r"(?:\s+[A-Za-z\u0900-\u097F][A-Za-z\u0900-\u097F.'-]*){1,3})",
    re.IGNORECASE,
)


def get_language(text):
    if not isinstance(text, str):
        return "unknown"

    hindi = any("\u0900" <= char <= "\u097f" for char in text)
    english = any(char.isascii() and char.isalpha() for char in text)

    if hindi and english:
        return "hinglish"
    if hindi:
        return "hi"
    if english:
        return "en"
    return "unknown"


def normalize_field(field):
    field = unicodedata.normalize("NFKC", str(field)).casefold()
    return re.sub(r"[^\w]+", "_", field).strip("_")


def make_detection(
    category,
    path,
    start,
    end,
    target,
    source_type,
    method,
    confidence,
    language,
    record_id=None,
    source_file=None,
):
    result = {
        "category": category,
        "path": path,
        "start": start,
        "end": end,
        "target": target,
        "source_type": source_type,
        "method": method,
        "confidence": confidence,
        "language": language,
        "action": "REDACT",
    }

    if record_id is not None:
        result["record_id"] = record_id

    if source_file is not None:
        result["source_file"] = source_file

    return result


def detect_in_text(
    text,
    path,
    source_type,
    field_name=None,
    known_names=None,
    record_id=None,
    source_file=None,
    target="value",
):
    if not isinstance(text, str) or not text:
        return []

    detections = []
    language = get_language(text)
    field = normalize_field(field_name or "")

    def add(category, start, end, method, confidence):
        if start < 0 or end > len(text) or start >= end:
            return

        for item in detections:
            if start < item["end"] and end > item["start"]:
                return

        detected_target = (
            "filename" if source_type == "filename" else text[start:end]
        )

        detections.append(
            make_detection(
                category,
                path,
                start,
                end,
                detected_target,
                source_type,
                method,
                confidence,
                language,
                record_id,
                source_file,
            )
        )

    category = FIELD_CATEGORIES.get(field)

    if category:
        add(category, 0, len(text), "field_match", 0.99)

    for category, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            add(category, match.start(), match.end(), "regex", 0.95)

    for category, pattern in LABELLED_PATTERNS.items():
        for match in pattern.finditer(text):
            start, end = match.span(1)
            add(category, start, end, "labelled_regex", 0.96)

    for pattern, category, method in (
        (PATIENT_LABELS, "PATIENT_NAME", "patient_context"),
        (REPORT_PATTERN, "PATIENT_NAME", "whatsapp_report_rule"),
        (RELATIVE_LABELS, "RELATIVE_NAME", "relative_context"),
    ):
        for match in pattern.finditer(text):
            start, end = match.span(1)
            add(category, start, end, method, 0.90)

    if known_names:
        groups = (
            known_names.items()
            if isinstance(known_names, dict)
            else [("PATIENT_NAME", known_names)]
        )

        for category, names in groups:
            if category not in ("PATIENT_NAME", "RELATIVE_NAME"):
                continue

            if isinstance(names, str):
                names = [names]

            for name in names:
                if not isinstance(name, str):
                    continue

                normalized = normalize_name(name)

                if not normalized:
                    continue

                pattern_text = r"[\W_]+".join(
                    re.escape(part) for part in normalized.split()
                )

                pattern = re.compile(
                    r"(?<!\w)" + pattern_text + r"(?!\w)",
                    re.IGNORECASE,
                )

                for match in pattern.finditer(text):
                    previous = text[:match.start()].rstrip()

                    if re.search(
                        r"(?:\bdr\.?|\bdoctor|डॉ\.?)\s*$",
                        previous,
                        re.IGNORECASE,
                    ):
                        continue

                    add(
                        category,
                        match.start(),
                        match.end(),
                        "known_name",
                        0.90,
                    )

    return detections


def join_path(parent, child):
    child = str(child).replace("~", "~0").replace("/", "~1")
    return parent.rstrip("/") + "/" + child


def detect_pii(
    data,
    source_type="text",
    base_path="doc",
    known_names=None,
    record_id=None,
    source_file=None,
):
    detections = []

    def check(value, path, field_name=None):
        if isinstance(value, str):
            detections.extend(
                detect_in_text(
                    value,
                    path,
                    source_type,
                    field_name,
                    known_names,
                    record_id,
                    source_file,
                )
            )

        elif isinstance(value, dict):
            for key, item in value.items():
                child_path = join_path(path, key)

                detections.extend(
                    detect_in_text(
                        str(key),
                        child_path,
                        source_type,
                        known_names=known_names,
                        record_id=record_id,
                        source_file=source_file,
                        target="key",
                    )
                )

                check(item, child_path, key)

        elif isinstance(value, list):
            for index, item in enumerate(value):
                check(item, join_path(path, index), field_name)

    check(data, base_path)

    detections.sort(
        key=lambda item: (item["path"], -item["start"])
    )

    return detections


def detect_filename_pii(
    relative_path,
    known_names=None,
    record_id=None,
    source_file=None,
):
    return detect_in_text(
        str(relative_path),
        str(relative_path),
        "filename",
        known_names=known_names,
        record_id=record_id,
        source_file=source_file,
        target="filename",
    )
