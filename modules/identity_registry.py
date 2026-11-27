
import os
import json
import hmac
import hashlib
import uuid
import tempfile

from pathlib import Path


class RegistryConflictError(Exception):
    pass


class IdentityRegistry:
    def __init__(self, path=None, secret=None):
        if secret is None:
            master_secret = os.getenv("RAKSHA_SECRET")

            if not master_secret or not master_secret.strip():
                raise RuntimeError("RAKSHA_SECRET is missing")

            # Derive a separate key for identity registry operations.
            secret = hmac.new(
                master_secret.encode("utf-8"),
                b"RAKSHA:IDENTITY-REGISTRY-KEY:v1",
                hashlib.sha256
            ).digest()

        if not isinstance(secret, bytes) or not secret:
            raise ValueError("Invalid registry secret")

        self.secret = secret

        if path is None:
            path = (
                Path(__file__).resolve().parent.parent
                / "state"
                / "identity_registry.json"
            )

        self.path = Path(path)
        self.data = self.load_registry()

    def load_registry(self):
        if not self.path.exists():
            return {"version": 1, "identities": {}}

        try:
            with open(self.path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError("Could not read identity registry") from error

        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Invalid identity registry")

        identities = data.get("identities")

        if not isinstance(identities, dict):
            raise ValueError("Invalid registry structure")

        # An identifier must never point to two different patients.
        used_fingerprints = set()

        for canonical_id, details in identities.items():
            if (
                not isinstance(canonical_id, str)
                or not canonical_id.startswith("CAN_")
            ):
                raise ValueError("Invalid canonical ID")

            if not isinstance(details, dict):
                raise ValueError("Invalid identity entry")

            fingerprints = details.get("fingerprints")

            if not isinstance(fingerprints, list):
                raise ValueError("Invalid fingerprints")

            for fingerprint in fingerprints:
                if (
                    not isinstance(fingerprint, str)
                    or len(fingerprint) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in fingerprint
                    )
                ):
                    raise ValueError("Invalid fingerprint")

                if fingerprint in used_fingerprints:
                    raise RegistryConflictError(
                        "Fingerprint belongs to multiple identities"
                    )

                used_fingerprints.add(fingerprint)

        return data

    def fingerprint_identifier(self, identifier):
        if not isinstance(identifier, (tuple, list)) or len(identifier) < 2:
            raise ValueError("Invalid identifier")

        parts = []

        for value in identifier:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Invalid identifier value")

            parts.append(value.strip().casefold())

        # Only the HMAC fingerprint is saved, never the original identifier.
        message = json.dumps(
            parts,
            ensure_ascii=False,
            separators=(",", ":")
        ).encode("utf-8")

        message = b"RAKSHA:IDENTITY-REGISTRY:v1:" + message

        return hmac.new(
            self.secret,
            message,
            hashlib.sha256
        ).hexdigest()

    def get_fingerprints(self, identifiers):
        if not identifiers:
            raise ValueError("At least one identifier is required")

        return {
            self.fingerprint_identifier(identifier)
            for identifier in identifiers
        }

    def find_identity(self, identifiers):
        fingerprints = self.get_fingerprints(identifiers)
        found_ids = set()

        for canonical_id, details in self.data["identities"].items():
            saved = set(details["fingerprints"])

            if fingerprints.intersection(saved):
                found_ids.add(canonical_id)

        if len(found_ids) > 1:
            raise RegistryConflictError(
                "Identifiers point to different identities"
            )

        if found_ids:
            return next(iter(found_ids))

        return None

    def get_or_create_identity(self, identifiers):
        canonical_id = self.find_identity(identifiers)

        if canonical_id is None:
            # Generate the internal ID only once and persist it.
            canonical_id = "CAN_" + uuid.uuid4().hex.upper()

            self.data["identities"][canonical_id] = {
                "fingerprints": []
            }

        self.add_identifiers(canonical_id, identifiers)

        return canonical_id

    def add_identifiers(self, canonical_id, identifiers):
        if (
            not isinstance(canonical_id, str)
            or not canonical_id.startswith("CAN_")
        ):
            raise ValueError("Invalid canonical ID")

        fingerprints = self.get_fingerprints(identifiers)

        # Check for conflicts before changing the registry.
        for other_id, details in self.data["identities"].items():
            if other_id == canonical_id:
                continue

            saved = set(details["fingerprints"])

            if fingerprints.intersection(saved):
                raise RegistryConflictError(
                    "Identifier is already assigned to another identity"
                )

        if canonical_id not in self.data["identities"]:
            self.data["identities"][canonical_id] = {
                "fingerprints": []
            }

        saved = self.data["identities"][canonical_id]["fingerprints"]

        for fingerprint in fingerprints:
            if fingerprint not in saved:
                saved.append(fingerprint)

        self.save_registry()

    def save_registry(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                suffix=".tmp",
                delete=False
            ) as file:
                json.dump(self.data, file, indent=2)
                file.write("\n")
                temp_path = file.name

            # Replace the old file only after the new one is completely written.
            os.replace(temp_path, self.path)

        except OSError as error:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

            raise RuntimeError("Could not save identity registry") from error
