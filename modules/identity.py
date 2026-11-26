
import unicodedata


_TITLE_WORDS = {
    # English
    "mr", "mrs", "ms", "miss", "dr",
    "doctor",

    # Hindi
    "श्री", "श्रीमती", "सुश्री",
    "श्रीमान", "कुमारी", "कु",
    "डॉ", "डॉक्टर"
}


def _clean_name_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.casefold()

    cleaned = []

    for char in value:
        category = unicodedata.category(char)

        if category[0] in ("L", "M", "N"):
            cleaned.append(char)
        else:
            cleaned.append(" ")

    return " ".join("".join(cleaned).split())


def normalize_name(name: str | None) -> str | None:
    if not isinstance(name, str):
        return None

    cleaned_name = _clean_name_text(name)

    if not cleaned_name:
        return None

    name_parts = cleaned_name.split()

    while name_parts and name_parts[0] in _TITLE_WORDS:
        name_parts.pop(0)

    if not name_parts:
        return None

    return " ".join(name_parts)
