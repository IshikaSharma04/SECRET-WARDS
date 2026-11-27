
import json
import os
import hmac
import hashlib
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from modules.identity_registry import (
    IdentityRegistry,
    RegistryConflictError
)


class IdentityRegistryTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry_path = Path(self.temp_dir.name) / "registry.json"
        self.secret = b"test-registry-secret"

        self.registry = IdentityRegistry(
            path=self.registry_path,
            secret=self.secret
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_new_identity_is_created(self):
        identifier = ("hosp_a", "uhid", "patient-001")

        canonical_id = self.registry.get_or_create_identity(
            [identifier]
        )

        self.assertTrue(canonical_id.startswith("CAN_"))
        self.assertTrue(self.registry_path.exists())

    def test_same_identifier_returns_same_identity(self):
        identifier = ("hosp_a", "uhid", "patient-001")

        first_id = self.registry.get_or_create_identity([identifier])
        second_id = self.registry.get_or_create_identity([identifier])

        self.assertEqual(first_id, second_id)

    def test_identity_stays_same_after_reloading_registry(self):
        identifier = ("hosp_a", "uhid", "patient-001")

        first_id = self.registry.get_or_create_identity([identifier])

        new_registry = IdentityRegistry(
            path=self.registry_path,
            secret=self.secret
        )

        second_id = new_registry.get_or_create_identity([identifier])

        self.assertEqual(first_id, second_id)

    def test_new_identifier_can_be_added_to_existing_identity(self):
        first_identifier = ("hosp_a", "uhid", "patient-001")
        second_identifier = ("hosp_b", "uhid", "patient-778")

        canonical_id = self.registry.get_or_create_identity(
            [first_identifier]
        )

        self.registry.add_identifiers(
            canonical_id,
            [second_identifier]
        )

        found_id = self.registry.find_identity(
            [second_identifier]
        )

        self.assertEqual(canonical_id, found_id)

    def test_different_secrets_produce_different_fingerprints(self):
        identifier = ("hosp_a", "uhid", "patient-001")

        first = self.registry.fingerprint_identifier(identifier)

        second_registry = IdentityRegistry(
            path=self.registry_path,
            secret=b"different-secret"
        )

        second = second_registry.fingerprint_identifier(identifier)

        self.assertNotEqual(first, second)

    def test_raw_identifier_is_not_saved(self):
        identifier = ("hosp_a", "uhid", "patient-001")

        self.registry.get_or_create_identity([identifier])

        saved_data = self.registry_path.read_text(encoding="utf-8")

        self.assertNotIn("patient-001", saved_data)
        self.assertNotIn("hosp_a", saved_data)

    def test_identifiers_from_different_patients_raise_conflict(self):
        first_identifier = ("hosp_a", "uhid", "patient-001")
        second_identifier = ("hosp_b", "uhid", "patient-002")

        self.registry.get_or_create_identity([first_identifier])
        self.registry.get_or_create_identity([second_identifier])

        with self.assertRaises(RegistryConflictError):
            self.registry.find_identity([
                first_identifier,
                second_identifier
            ])

    def test_identifier_cannot_be_assigned_to_two_patients(self):
        first_identifier = ("hosp_a", "uhid", "patient-001")
        second_identifier = ("hosp_b", "uhid", "patient-002")

        first_id = self.registry.get_or_create_identity(
            [first_identifier]
        )

        second_id = self.registry.get_or_create_identity(
            [second_identifier]
        )

        with self.assertRaises(RegistryConflictError):
            self.registry.add_identifiers(
                second_id,
                [first_identifier]
            )

        self.assertEqual(
            first_id,
            self.registry.find_identity([first_identifier])
        )

    def test_missing_raksha_secret_is_rejected(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                IdentityRegistry(path=self.registry_path)

    def test_registry_key_is_derived_from_raksha_secret(self):
        master_secret = "test-master-secret"

        expected_key = hmac.new(
            master_secret.encode("utf-8"),
            b"RAKSHA:IDENTITY-REGISTRY-KEY:v1",
            hashlib.sha256
        ).digest()

        with patch.dict(
            os.environ,
            {"RAKSHA_SECRET": master_secret},
            clear=True
        ):
            env_registry = IdentityRegistry(
                path=self.registry_path
            )

        explicit_registry = IdentityRegistry(
            path=self.registry_path,
            secret=expected_key
        )

        identifier = ("hosp_a", "uhid", "patient-001")

        self.assertEqual(
            env_registry.fingerprint_identifier(identifier),
            explicit_registry.fingerprint_identifier(identifier)
        )

    def test_different_raksha_secrets_produce_different_registry_keys(self):
        identifier = ("hosp_a", "uhid", "patient-001")

        with patch.dict(
            os.environ,
            {"RAKSHA_SECRET": "first-secret"},
            clear=True
        ):
            first_registry = IdentityRegistry(
                path=self.registry_path
            )

        with patch.dict(
            os.environ,
            {"RAKSHA_SECRET": "second-secret"},
            clear=True
        ):
            second_registry = IdentityRegistry(
                path=self.registry_path
            )

        self.assertNotEqual(
            first_registry.fingerprint_identifier(identifier),
            second_registry.fingerprint_identifier(identifier)
        )

    def test_corrupted_registry_is_rejected(self):
        self.registry_path.write_text(
            "{invalid json",
            encoding="utf-8"
        )

        with self.assertRaises(RuntimeError):
            IdentityRegistry(
                path=self.registry_path,
                secret=self.secret
            )


if __name__ == "__main__":
    unittest.main()
