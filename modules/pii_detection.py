
import re

from modules.identity import normalize_name


FIELD_CATEGORIES = {
    "patient_name": "PATIENT_NAME",
    "relative_name": "RELATIVE_NAME",
    "guardian_name": "RELATIVE_NAME",
    "father_name": "RELATIVE_NAME",
    "mother_name": "RELATIVE_NAME",
    "mobile": "PHONE",
    "phone": "PHONE",
    "phone_number": "PHONE",
    "aadhaar": "AADHAAR",
    "aadhaar_no": "AADHAAR",
    "abha": "ABHA",
    "abha_no": "ABHA",
    "uhid": "UHID",
    "mrn": "UHID",
    "pan": "PAN",
    "payer_pan": "PAN",
    "address": "ADDRESS",
    "pin": "PIN_CODE",
    "pincode": "PIN_CODE",
    "policy_no": "INSURANCE_ID",
    "insurance_id": "INSURANCE_ID",
}

PATTERNS = {
    "AADHAAR": re.compile(
        r"(?<!\d)(?:\d{4}[ -]?){2}\d{4}(?!\d)"
    ),
    "PHONE": re.compile(
        r"(?<!\d)(?:\+91[ \t-]?)?[6-9]\d{4}[ \t-]?\d{5}(?!\d)"
    ),
    "PAN": re.compile(
        r"\b[A-Z]{5}\d{4}[A-Z]\b",
        re.IGNORECASE
    ),
}

REPORT_OF_PATTERN = re.compile(
    r"\bReport\s+of\s+([^\n,;]{2,60}?)\s+behenji\b",
    re.IGNORECASE
)

LABELLED_PATTERNS = {
    "ABHA": re.compile(
        r"\bABHA(?:\s*(?:ID|NO\.?|NUMBER))?"
        r"\s*[:#-]?\s*(\d{2}(?:[ -]?\d){12})\b",
        re.IGNORECASE
    ),
    "UHID": re.compile(
        r"\b(?:UHID|MRN)\s*[:#-]?\s*"
        r"([A-Z0-9][A-Z0-9/-]{3,})\b",
        re.IGNORECASE
    ),
    "PIN_CODE": re.compile(
        r"\b(?:PIN(?:\s*CODE)?|PINCODE|POSTAL\s*CODE)"
        r"\s*[:#-]?\s*(\d{6})\b",
        re.IGNORECASE
    ),
    "INSURANCE_ID": re.compile(
        r"\b(?:POLICY\s*(?:NO\.?|NUMBER)|"
        r"INSURANCE\s*(?:ID|NO\.?|NUMBER))"
        r"\s*[:#-]?\s*([A-Z0-9][A-Z0-9/-]{3,})\b",
        re.IGNORECASE
    ),
}

RELATIVE_LABELS = re.compile(
    r"(?:"
    r"C/O|S/O|D/O|W/O|F/O|"
    r"relative\s+name|guardian\s+name|"
    r"father\s+name|mother\s+name|"
    r"पिता(?:\s+का\s+नाम)?|"
    r"माता(?:\s+का\s+नाम)?|"
    r"पति(?:\s+का\s+नाम)?|"
    r"पत्नी(?:\s+का\s+नाम)?|"
    r"अभिभावक(?:\s+का\s+नाम)?"
    r")"
    r"\s*[:\-]?\s*([^\n,;]{2,60})",
    re.IGNORECASE
)

PATIENT_LABELS = re.compile(
    r"(?:"
    r"patient\s+name|patient|"
    r"नाम|रोगी\s+का\s+नाम|मरीज\s+का\s+नाम"
    r")"
    r"\s*[:\-]\s*([^\n,;]{2,60})",
    re.IGNORECASE
)

MEDICAL_WORDS = {
    "fever", "cough", "cold", "pain", "vomiting",
    "diabetes", "hypertension", "dengue", "malaria",
    "headache", "weakness", "breathlessness",
    "बुखार", "खांसी", "खाँसी", "दर्द", "उल्टी",
}

DOCTOR_PREFIX = re.compile(
    r"(?:dr\.?|doctor|डॉ\.?|डॉक्टर)$",
    re.IGNORECASE
)


def get_language(text):
    has_hindi = any("\u0900" <= char <= "\u097f" for char in text)
    has_english = any(char.isascii() and char.isalpha() for char in text)

    if has_hindi and has_english:
        return "hinglish"
    if has_hindi:
        return "hi"
    if has_english:
        return "en"
    return "unknown"


def normalize_field(field):
    field = str(field).lower().strip()
    return re.sub(r"[^a-z0-9]+", "_", field).strip("_")


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
    source_file=None
):
    detection = {
        "category": category,
        "path": path,
        "start": start,
        "end": end,
        "target": target,
        "source_type": source_type,
        "method": method,
        "confidence": confidence,
        "language": language,
        "action": "REDACT"
    }

    if record_id is not None:
        detection["record_id"] = record_id
    if source_file is not None:
        detection["source_file"] = source_file

    return detection


def compile_known_names(known_names):
    if not known_names:
        return {}

    if isinstance(known_names, dict):
        name_groups = known_names.items()
    else:
        name_groups = [("PATIENT_NAME", known_names)]

    compiled = {}

    for category, names in name_groups:
        if category not in ("PATIENT_NAME", "RELATIVE_NAME"):
            continue

        if isinstance(names, str):
            names = [names]

        alternatives = set()

        for name in names:
            if not isinstance(name, str):
                continue

            normalized_name = normalize_name(name)
            if not normalized_name:
                continue

            parts = normalized_name.split()
            if not parts:
                continue

            name_pattern = r"[\W_]+".join(
                re.escape(part) for part in parts
            )
            alternatives.add(name_pattern)

        if not alternatives:
            continue

        ordered_alternatives = sorted(
            alternatives,
            key=len,
            reverse=True
        )

        combined_pattern = (
            r"(?<!\w)(?:"
            + "|".join(ordered_alternatives)
            + r")(?!\w)"
        )

        compiled[category] = re.compile(
            combined_pattern,
            re.IGNORECASE
        )

    return compiled


def detect_in_text(
    text,
    path,
    source_type,
    field_name=None,
    known_names=None,
    record_id=None,
    source_file=None,
    target="value",
    compiled_known_names=None
):
    detections = []
    language = get_language(text)
    field = normalize_field(field_name or "")

    def add_detection(category, start, end, method, confidence):
        for item in detections:
            if start < item["end"] and end > item["start"]:
                return

        detections.append(
            make_detection(
                category,
                path,
                start,
                end,
                target,
                source_type,
                method,
                confidence,
                language,
                record_id,
                source_file
            )
        )

    category = FIELD_CATEGORIES.get(field)

    if category:
        add_detection(
            category, 0, len(text), "field_match", 0.99
        )

    for category, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            add_detection(
                category,
                match.start(),
                match.end(),
                "regex",
                0.95
            )

    for category, pattern in LABELLED_PATTERNS.items():
        for match in pattern.finditer(text):
            start, end = match.span(1)
            add_detection(
                category,
                start,
                end,
                "labelled_regex",
                0.95
            )

    for match in RELATIVE_LABELS.finditer(text):
        name = match.group(1)
        start = match.start(1)
        end = match.end(1)

        while name and name[-1].isspace():
            name = name[:-1]
            end -= 1

        if not name:
            continue

        words = set(
            re.findall(r"[a-z]+|[\u0900-\u097f]+", name.lower())
        )

        if words.intersection(MEDICAL_WORDS):
            continue

        add_detection(
            "RELATIVE_NAME",
            start,
            end,
            "context_rule",
            0.85
        )

    for match in PATIENT_LABELS.finditer(text):
        name = match.group(1)
        start = match.start(1)
        end = match.end(1)

        while name and name[-1].isspace():
            name = name[:-1]
            end -= 1

        if name:
            add_detection(
                "PATIENT_NAME",
                start,
                end,
                "context_rule",
                0.90
            )

    for match in REPORT_OF_PATTERN.finditer(text):
        start, end = match.span(1)
        add_detection(
            "PATIENT_NAME",
            start,
            end,
            "whatsapp_report_rule",
            0.95
        )

    if compiled_known_names is None:
        compiled_known_names = compile_known_names(known_names)

    for category, pattern in compiled_known_names.items():
        for match in pattern.finditer(text):
            previous_text = text[:match.start()].rstrip()

            if DOCTOR_PREFIX.search(previous_text):
                continue

            add_detection(
                category,
                match.start(),
                match.end(),
                "known_name",
                0.90
            )

    return detections


def join_path(parent, child):
    child = str(child).replace("~", "~0").replace("/", "~1")

    if parent == "/":
        return "/" + child

    return parent.rstrip("/") + "/" + child


def detect_pii(
    data,
    source_type="text",
    base_path="doc",
    known_names=None,
    record_id=None,
    source_file=None
):
    detections = []
    compiled_known_names = compile_known_names(known_names)

    def check_value(value, path, field_name=None):
        if isinstance(value, str):
            found = detect_in_text(
                value,
                path,
                source_type,
                field_name,
                known_names,
                record_id,
                source_file,
                compiled_known_names=compiled_known_names
            )
            detections.extend(found)

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
                        compiled_known_names=compiled_known_names
                    )
                )

                check_value(item, child_path, key)

        elif isinstance(value, list):
            for index, item in enumerate(value):
                child_path = join_path(path, index)
                check_value(item, child_path, field_name)

    check_value(data, base_path)

    detections.sort(
        key=lambda item: (item["path"], -item["start"])
    )

    return detections


def detect_filename_pii(
    relative_path,
    known_names=None,
    record_id=None,
    source_file=None
):
    """Detect PII in filenames even when labels use filename separators."""

    # Filenames commonly use underscores or hyphens instead of spaces.
    # Convert those separators so labelled patterns such as MRN and UHID
    # can recognize identifiers embedded in filenames.
    searchable_path = re.sub(
        r"[\W_]+",
        " ",
        str(relative_path),
        flags=re.UNICODE
    )

    return detect_in_text(
        searchable_path,
        str(relative_path),
        "filename",
        known_names=known_names,
        record_id=record_id,
        source_file=source_file,
        target="filename"
    )
