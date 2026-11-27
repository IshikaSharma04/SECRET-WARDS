
from collections import defaultdict

from modules.identity import normalize_name
from modules.pseudonym import generate_pseudonym, load_secret
from modules.identity_registry import (
    IdentityRegistry,
    RegistryConflictError
)


LOCAL_IDENTIFIER_TYPES = {
    "UHID",
    "MRN",
    "HOSPITAL_ID"
}


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

    hospital = str(
        source.get("hospital_id") or ""
    ).strip().casefold()

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
        relation = str(
            item.get("relation") or ""
        ).strip().casefold()

        confidence = _get_confidence(item.get("confidence"))

        if name and relation and confidence >= 0.90:
            relatives.add((relation, name))

    for item in candidates.get("identifiers") or []:
        if not isinstance(item, dict):
            continue

        kind = str(
            item.get("type") or ""
        ).strip().upper()

        value = str(
            item.get("value") or ""
        ).strip().casefold()

        confidence = _get_confidence(item.get("confidence"))

        if not kind or not value:
            continue

        if kind in LOCAL_IDENTIFIER_TYPES:
            if hospital and confidence >= 0.90:
                identifiers.add((hospital, kind, value))

        elif kind in ("ABHA", "AADHAAR", "AADHAR"):
            if item.get("verified") is True and confidence >= 0.95:
                identifiers.add(("GLOBAL", kind, value))

        elif kind in ("INSURANCE", "INSURANCE_ID", "POLICY_ID"):
            scope = str(
                item.get("scope") or ""
            ).strip().casefold()

            if scope and item.get("verified") is True and confidence >= 0.95:
                identifiers.add(("INSURANCE", scope, kind, value))

    secondary = candidates.get("secondary_clues") or {}

    if not isinstance(secondary, dict):
        secondary = {}

    dob = secondary.get("dob")

    if not isinstance(dob, str):
        dob = None
    else:
        dob = dob.strip()

        if not dob:
            dob = None

    age = secondary.get("age")

    if (
        isinstance(age, bool)
        or not isinstance(age, int)
        or age < 0
        or age > 120
    ):
        age = None

    village = normalize_name(secondary.get("village"))
    locality = normalize_name(secondary.get("locality"))

    return {
        "hospital": hospital,
        "names": names,
        "relatives": relatives,
        "identifiers": identifiers,
        "dob": dob,
        "age": age,
        "village": village,
        "locality": locality
    }


def _get_entity_key(detail, index):
    """
    Records with the same local patient identifier belong to
    the same local entity.

    Records without a local identifier are treated separately
    to avoid assuming that their clues are unique.
    """
    local_ids = sorted(
        identifier
        for identifier in detail["identifiers"]
        if identifier[1] in LOCAL_IDENTIFIER_TYPES
    )

    if local_ids:
        return tuple(local_ids)

    return ("RECORD", index)


def _build_uniqueness_index(details):
    """
    Build indexes for clues used in cross-hospital matching.

    A clue is unique only when it identifies at most one distinct
    local patient entity within each hospital.
    """
    relative_index = defaultdict(lambda: defaultdict(set))
    dob_index = defaultdict(lambda: defaultdict(set))
    village_age_index = defaultdict(lambda: defaultdict(list))

    for index, detail in enumerate(details):
        hospital = detail["hospital"]

        if not hospital:
            continue

        entity_key = _get_entity_key(detail, index)

        for relation, relative_name in detail["relatives"]:
            for patient_name in detail["names"]:
                key = (patient_name, relation, relative_name)
                relative_index[key][hospital].add(entity_key)

        if detail["dob"]:
            for patient_name in detail["names"]:
                key = (patient_name, detail["dob"])
                dob_index[key][hospital].add(entity_key)

        if detail["village"] and detail["age"] is not None:
            for patient_name in detail["names"]:
                key = (patient_name, detail["village"])

                village_age_index[key][hospital].append(
                    (detail["age"], entity_key)
                )

    return {
        "relative": relative_index,
        "dob": dob_index,
        "village_age": village_age_index
    }


def _is_unique(index, key):
    hospitals = index.get(key)

    if not hospitals:
        return False

    return all(
        len(entities) <= 1
        for entities in hospitals.values()
    )


def _village_age_is_unique(
    index,
    patient_name,
    village,
    first_age,
    second_age
):
    if abs(first_age - second_age) > 1:
        return False

    key = (patient_name, village)
    hospitals = index.get(key)

    if not hospitals:
        return False

    for entries in hospitals.values():
        matching_entities = {
            entity_key
            for age, entity_key in entries
            if (
                abs(age - first_age) <= 1
                and abs(age - second_age) <= 1
            )
        }

        if len(matching_entities) > 1:
            return False

    return True


def _has_conflicting_identifiers(first_ids, second_ids):
    for first_id in first_ids:
        for second_id in second_ids:
            if (
                first_id[:-1] == second_id[:-1]
                and first_id[-1] != second_id[-1]
            ):
                return True

    return False


def _compare_records(first, second, uniqueness):
    first_ids = first["identifiers"]
    second_ids = second["identifiers"]

    shared_names = first["names"] & second["names"]

    # Contradictory DOBs must be checked before accepting shared IDs.
    if first["dob"] and second["dob"]:
        if first["dob"] != second["dob"]:
            return "conflict"

    shared_ids = first_ids & second_ids

    if shared_ids:
        if first["names"] and second["names"]:
            if first["names"].isdisjoint(second["names"]):
                return "conflict"

        return "match"

    # Different patient names mean these are not a match.
    if not shared_names:
        return "no_match"

    # Different identifiers in the same scope conflict when
    # the patient name is also shared.
    if _has_conflicting_identifiers(first_ids, second_ids):
        return "conflict"

    shared_relatives = first["relatives"] & second["relatives"]

    # Shared patient name and relative.
    for relation, relative_name in shared_relatives:
        for patient_name in shared_names:
            key = (patient_name, relation, relative_name)

            if _is_unique(uniqueness["relative"], key):
                return "match"

    # Shared patient name and exact DOB.
    if first["dob"] and second["dob"]:
        for patient_name in shared_names:
            key = (patient_name, first["dob"])

            if _is_unique(uniqueness["dob"], key):
                return "match"

    # Shared patient name, village and age within one year.
    if (
        first["village"]
        and first["village"] == second["village"]
        and first["age"] is not None
        and second["age"] is not None
    ):
        for patient_name in shared_names:
            if _village_age_is_unique(
                uniqueness["village_age"],
                patient_name,
                first["village"],
                first["age"],
                second["age"]
            ):
                return "match"

    return "uncertain"


def _get_group_identifiers(group, details):
    identifiers = set()

    for index in group:
        identifiers.update(details[index]["identifiers"])

    return sorted(identifiers)


def _find_group(index, groups):
    for group in groups:
        if index in group:
            return group

    return None


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

    uniqueness = _build_uniqueness_index(details)

    groups = [[i] for i in range(len(records))]
    review = set()
    reasons = {}
    matches = []
    uncertain_pairs = []

    # Identify confirmed matches, conflicts and uncertain pairs.
    for i in range(len(details)):
        for j in range(i + 1, len(details)):
            result = _compare_records(
                details[i],
                details[j],
                uniqueness
            )

            if result == "match":
                matches.append((i, j))

            elif result == "conflict":
                review.update((i, j))
                reasons[i] = "conflicting_identity_evidence"
                reasons[j] = "conflicting_identity_evidence"

            elif result == "uncertain":
                uncertain_pairs.append((i, j))

    # Merge only when every record in the two groups agrees.
    for i, j in matches:
        first_group = _find_group(i, groups)
        second_group = _find_group(j, groups)

        if first_group is None or second_group is None:
            continue

        if first_group is second_group:
            continue

        can_merge = True

        for first in first_group:
            for second in second_group:
                if _compare_records(
                    details[first],
                    details[second],
                    uniqueness
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

    # An uncertain comparison should not invalidate a confirmed
    # group merely because an unrelated record has weak evidence.
    #
    # If both sides are separate confirmed groups, keep both under
    # review because their relationship remains unresolved.
    for i, j in uncertain_pairs:
        first_group = _find_group(i, groups)
        second_group = _find_group(j, groups)

        if first_group is None or second_group is None:
            continue

        if first_group is second_group:
            continue

        if len(first_group) > 1 and len(second_group) == 1:
            review.add(j)
            reasons[j] = "insufficient_identity_evidence"

        elif len(second_group) > 1 and len(first_group) == 1:
            review.add(i)
            reasons[i] = "insufficient_identity_evidence"

        else:
            review.update(first_group + second_group)

            for index in first_group + second_group:
                reasons[index] = "insufficient_identity_evidence"

    results = [None] * len(records)

    for group in groups:
        linked = len(group) > 1
        identifiers = _get_group_identifiers(group, details)

        canonical_id = None
        pseudonym = None
        confidence = 0.0

        needs_review = any(
            index in review
            for index in group
        )

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
