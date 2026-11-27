
import re

from modules.identity import normalize_name


# Fields that directly contain personal information.
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


# General identifier patterns.
# These patterns can identify values without needing a label.
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


# These identifiers require a label before their value.
# The captured group contains only the identifier, not its label.
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


# Labels that can introduce a relative's name.
RELATIVE_LABELS = re.compile(
    r"(?:C/O|S/O|D/O|W/O|F/O|"
    r"relative name|guardian name|father name|mother name|"
    r"पिता|माता|पति|पत्नी|अभिभावक)"
    r"\s*[:\-]?\s*([^\n,;]{2,60})",
    re.IGNORECASE
)


# Labels that can introduce a patient's name.
PATIENT_LABELS = re.compile(
    r"(?:patient name|patient|नाम|रोगी का नाम)"
    r"\s*[:\-]\s*([^\n,;]{2,60})",
    re.IGNORECASE
)
REPORT_OF_PATTERN = re.compile(
    r"\bReport\s+of\s+([^\n,;]{2,60}?)\s+behenji\b",
    re.IGNORECASE
)


# Common medical words that should not be treated as names.
MEDICAL_WORDS = {
    "fever", "cough", "cold", "pain", "vomiting",
    "diabetes", "hypertension", "dengue", "malaria",
    "headache", "weakness", "breathlessness",
    "बुखार", "खांसी", "दर्द", "उल्टी"
}


def get_language(text):
    """Identify the script used in the text."""

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
    """Make field names easier to compare."""

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


def detect_in_text(
    text,
    path,
    source_type,
    field_name=None,
    known_names=None,
    record_id=None,
    source_file=None,
    target="value"
):
    """Find personal information inside one text value."""

    detections = []
    language = get_language(text)
    field = normalize_field(field_name or "")

    def add_detection(category, start, end, method, confidence):
        # Avoid reporting the same characters twice.
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

    # Check whether the field itself identifies PII.
    category = FIELD_CATEGORIES.get(field)

    if category:
        add_detection(
            category, 0, len(text), "field_match", 0.99
        )

    # Detect Aadhaar, phone numbers and PAN.
    for category, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            add_detection(
                category,
                match.start(),
                match.end(),
                "regex",
                0.95
            )

    # Detect identifiers that require a label.
    for category, pattern in LABELLED_PATTERNS.items():
        for match in pattern.finditer(text):
            # Capture only the identifier value.
            start, end = match.span(1)

            add_detection(
                category,
                start,
                end,
                "labelled_regex",
                0.95
            )

    # Detect relative names after labels such as C/O or S/O.
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
            "RELATIVE_NAME", start, end, "context_rule", 0.85
        )
        
   
    for match in REPORT_OF_PATTERN.finditer(text):
        name = match.group(1)
        start = match.start(1)
        end = match.end(1)

        
        while name and name[0].isspace():
            name = name[1:]
            start += 1

        while name and name[-1].isspace():
            name = name[:-1]
            end -= 1

        if name:
            add_detection(
                "PATIENT_NAME",
                start,
                end,
                "whatsapp_report_rule",
                0.95
            )
    # Detect patient names after patient-related labels.
    for match in PATIENT_LABELS.finditer(text):
        name = match.group(1)
        start = match.start(1)
        end = match.end(1)

        while name and name[-1].isspace():
            name = name[:-1]
            end -= 1

        if name:
            add_detection(
                "PATIENT_NAME", start, end, "context_rule", 0.90
            )

    # Compare names collected from structured patient records.
    if known_names:
        if isinstance(known_names, dict):
            name_groups = known_names.items()
        else:
            name_groups = [("PATIENT_NAME", known_names)]

        for category, names in name_groups:
            if isinstance(names, str):
                names = [names]

            for name in names:
                if not isinstance(name, str):
                    continue

                # Normalize the known name before comparing it.
                normalized_name = normalize_name(name)

                if not normalized_name:
                    continue

                if category not in ("PATIENT_NAME", "RELATIVE_NAME"):
                    continue

                # Allow different spaces and punctuation between words.
                name_parts = normalized_name.split()
                name_pattern = r"[\W_]+".join(
                    re.escape(part) for part in name_parts
                )

                pattern = re.compile(
                    r"(?<!\w)" + name_pattern + r"(?!\w)",
                    re.IGNORECASE
                )

                for match in pattern.finditer(text):
                    previous_text = text[:match.start()].rstrip().lower()

                    # Avoid automatically marking a doctor's name
                    # as a patient name.
                    if re.search(
                        r"(?:dr\.?|doctor|डॉ\.?)$",
                        previous_text
                    ):
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
    """Build a path for nested JSON data."""

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
    """
    Detect PII in text, dictionaries and lists.

    Character positions start at zero.
    The end position is exclusive.
    Positions always refer to the original text.
    """

    detections = []

    def check_value(value, path, field_name=None):
        if isinstance(value, str):
            found = detect_in_text(
                value,
                path,
                source_type,
                field_name,
                known_names,
                record_id,
                source_file
            )
            detections.extend(found)

        elif isinstance(value, dict):
            for key, item in value.items():
                child_path = join_path(path, key)

                # Check keys as well as values.
                detections.extend(
                    detect_in_text(
                        str(key),
                        child_path,
                        source_type,
                        known_names=known_names,
                        record_id=record_id,
                        source_file=source_file,
                        target="key"
                    )
                )

                check_value(item, child_path, key)

        elif isinstance(value, list):
            for index, item in enumerate(value):
                child_path = join_path(path, index)
                check_value(item, child_path, field_name)

    check_value(data, base_path)

    # Sort detections so replacements can happen from right to left.
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
    """Check whether a filename or folder path contains PII."""

    return detect_in_text(
        relative_path,
        relative_path,
        "filename",
        known_names=known_names,
        record_id=record_id,
        source_file=source_file,
        target="filename"
    )
