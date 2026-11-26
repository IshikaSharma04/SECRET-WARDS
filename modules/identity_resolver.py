
from modules.identity import normalize_name
from modules.pseudonym import generate_pseudonym, load_secret
from modules.identity_registry import (
    IdentityRegistry,
    RegistryConflictError
)


def _get_confidence(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0

    if value < 0 or value > 1:
        return 0

    return value


def _get_identity_data(record):
    source = record.get("source") or {}
    candidates = record.get("identity_candidates") or {}

    if not isinstance(source, dict):
        source = {}

    if not isinstance(candidates, dict):
        candidates = {}

    hospital = str(source.get("hospital_id") or "").strip().casefold()

    names = set()
    relatives = set()
    identifiers = set()

    for item in candidates.get("patient_names") or []:
        if not isinstance(item, dict):
            continue

        name = normalize_name(item.get("value"))
        confidence = _get_confidence(item.get("confidence"))

        if name and confidence >= 0.90:
            names.add(name)

    for item in candidates.get("relative_names") or []:
        if not isinstance(item, dict):
            continue

        name = normalize_name(item.get("value"))
        relation = str(item.get("relation") or "").strip().casefold()
        confidence = _get_confidence(item.get("confidence"))

        if name and relation and confidence >= 0.90:
            relatives.add((relation, name))

    for item in candidates.get("identifiers") or []:
        if not isinstance(item, dict):
            continue

        kind = str(item.get("type") or "").strip().upper()
        value = str(item.get("value") or "").strip().casefold()
        confidence = _get_confidence(item.get("confidence"))

        if not kind or not value:
            continue

        if kind in ("UHID", "MRN", "HOSPITAL_ID"):
            if hospital and confidence >= 0.90:
                identifiers.add((hospital, kind, value))

        elif kind in ("ABHA", "AADHAAR", "AADHAR"):
            if item.get("verified") is True and confidence >= 0.95:
                identifiers.add(("GLOBAL", kind, value))

        elif kind in ("INSURANCE", "INSURANCE_ID", "POLICY_ID"):
            scope = str(item.get("scope") or "").strip().casefold()

            if scope and item.get("verified") is True and confidence >= 0.95:
                identifiers.add(("INSURANCE", scope, kind, value))

    return {
        "names": names,
        "relatives": relatives,
        "identifiers": identifiers
    }


def _compare_records(first, second):
    first_ids = first["identifiers"]
    second_ids = second["identifiers"]

    shared_ids = first_ids & second_ids

    if shared_ids:
        if first["names"] and second["names"]:
            if first["names"].isdisjoint(second["names"]):
                return "conflict"

        return "match"

    different_ids = False

    for id1 in first_ids:
        for id2 in second_ids:
            if id1[:-1] == id2[:-1] and id1[-1] != id2[-1]:
                different_ids = True

    shared_names = first["names"] & second["names"]
    shared_relatives = first["relatives"] & second["relatives"]

    if shared_names and shared_relatives:
        if different_ids:
            return "conflict"

        return "match"

    if shared_names:
        return "uncertain"

    return "no_match"


def _get_group_identifiers(group, details):
    identifiers = set()

    for index in group:
        identifiers.update(details[index]["identifiers"])

    return sorted(identifiers)


def resolve_records(records, registry_path=None):
    if not isinstance(records, list):
        raise TypeError("records must be a list")

    secret = load_secret()

    registry = IdentityRegistry(
        path=registry_path,
    )

    details = []

    for record in records:
        if not isinstance(record, dict):
            record = {}

        details.append(_get_identity_data(record))

    groups = [[i] for i in range(len(records))]
    review = set()
    reasons = {}
    matches = []

    # First identify possible matches and records that need review.
    for i in range(len(details)):
        for j in range(i + 1, len(details)):
            result = _compare_records(details[i], details[j])

            if result == "match":
                matches.append((i, j))

            elif result == "conflict":
                review.update((i, j))
                reasons[i] = "conflicting_identity_evidence"
                reasons[j] = "conflicting_identity_evidence"

            elif result == "uncertain":
                review.update((i, j))
                reasons[i] = "insufficient_identity_evidence"
                reasons[j] = "insufficient_identity_evidence"

    # Merge records only when every record in the groups agrees.
    for i, j in matches:
        first_group = None
        second_group = None

        for group in groups:
            if i in group:
                first_group = group

            if j in group:
                second_group = group

        if first_group is second_group:
            continue

        can_merge = True

        for first in first_group:
            for second in second_group:
                if _compare_records(
                    details[first], details[second]
                ) != "match":
                    can_merge = False
                    break

            if not can_merge:
                break

        if can_merge:
            first_group.extend(second_group)
            groups.remove(second_group)
        else:
            review.update(first_group + second_group)

            for index in first_group + second_group:
                reasons[index] = "ambiguous_identity"

    results = [None] * len(records)

    for group in groups:
        linked = len(group) > 1
        identifiers = _get_group_identifiers(group, details)

        canonical_id = None
        pseudonym = None
        confidence = 0.0

        needs_review = any(index in review for index in group)

        # A stable registry entry requires trusted identifiers.
        if not identifiers and not needs_review:
            needs_review = True

            for index in group:
                reasons[index] = "insufficient_identity_evidence"

        if needs_review:
            canonical_id = None

        else:
            try:
                canonical_id = registry.get_or_create_identity(
                    identifiers
                )

                pseudonym = generate_pseudonym(
                    canonical_id,
                    secret
                )

                confidence = 0.99 if identifiers else 0.0

                if linked:
                    confidence = 0.99

            except RegistryConflictError:
                canonical_id = None
                pseudonym = None
                needs_review = True

                for index in group:
                    reasons[index] = "registry_identity_conflict"

        for index in group:
            record = records[index]

            if not isinstance(record, dict):
                record = {}

            source = record.get("source") or {}

            if not isinstance(source, dict):
                source = {}

            results[index] = {
                "source_file": source.get("file"),
                "record_id": record.get("record_id"),
                "locator": source.get("locator"),
                "identity": {
                    "canonical_id": canonical_id,
                    "confidence": confidence,
                    "matched": linked and canonical_id is not None,
                    "review_required": needs_review,
                    "review_reason": (
                        reasons.get(index) if needs_review else None
                    )
                },
                "pseudonym": pseudonym
            }

    return results
