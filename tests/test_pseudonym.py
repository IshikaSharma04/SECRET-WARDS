import os
import unittest
from unittest.mock import patch

from modules.pseudonym import generate_pseudonym, load_secret


class PatientPseudonymTest(unittest.TestCase):

    def setUp(self):
        self.test_secret = b"raksha-local-test-key"

    def test_patient_reference_stays_consistent(self):
        patient_reference = "CAN_0001"

        first_result = generate_pseudonym(patient_reference, self.test_secret)
        second_result = generate_pseudonym(patient_reference, self.test_secret)

        self.assertEqual(first_result, second_result)

    def test_separate_patients_receive_separate_references(self):
        first_patient = generate_pseudonym("CAN_0001", self.test_secret)
        second_patient = generate_pseudonym("CAN_0002", self.test_secret)

        self.assertNotEqual(first_patient, second_patient)

    def test_secret_rotation_changes_patient_reference(self):
        original_reference = generate_pseudonym(
            "CAN_0001", b"previous-secret"
        )
        updated_reference = generate_pseudonym(
            "CAN_0001", b"replacement-secret"
        )

        self.assertNotEqual(original_reference, updated_reference)

    def test_generated_reference_matches_required_format(self):
        patient_reference = generate_pseudonym(
            "CAN_0001", self.test_secret
        )

        self.assertTrue(patient_reference.startswith("PAT_"))
        self.assertEqual(len(patient_reference), 30)

    def test_missing_secret_stops_generation_setup(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                load_secret()

    def test_blank_secret_is_not_accepted(self):
        with patch.dict(os.environ, {"RAKSHA_SECRET": "   "}):
            with self.assertRaises(RuntimeError):
                load_secret()

    def test_empty_canonical_reference_is_rejected(self):
        with self.assertRaises(ValueError):
            generate_pseudonym("", self.test_secret)

    def test_invalid_secret_type_is_rejected(self):
        with self.assertRaises(ValueError):
            generate_pseudonym("CAN_0001", "plain-text-secret")


if __name__ == "__main__":
    unittest.main()