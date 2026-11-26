
import unittest

from modules.hospital_identification import identify_hospital


class TestHospitalIdentification(unittest.TestCase):

    def test_hospital_from_json_metadata(self):
        metadata = {
            "document_metadata": {
                "_export_meta": {
                    "hospital": "Sanjeevani Multispeciality Hospital"
                }
            }
        }

        result = identify_hospital(metadata)

        self.assertEqual(
            result["hospital_name"],
            "Sanjeevani Multispeciality Hospital"
        )
        self.assertEqual(result["evidence_source"], "json_metadata")
        self.assertEqual(result["confidence"], "high")

    def test_hospital_from_explicit_field(self):
        record = {
            "hospital_name": "Jeevan Jyoti Charitable Hospital",
            "patient_name": "Aarav Sharma",
            "uhid": "JJH-1024"
        }

        result = identify_hospital(record)

        self.assertEqual(
            result["hospital_name"],
            "Jeevan Jyoti Charitable Hospital"
        )
        self.assertEqual(result["evidence_source"], "explicit_field")
        self.assertEqual(result["confidence"], "high")

    def test_hospital_from_fhir_organization(self):
        record = {
            "resourceType": "Organization",
            "id": "hospital-001",
            "name": "Arogya Seva Sadan"
        }

        result = identify_hospital(record)

        self.assertEqual(
            result["hospital_name"],
            "Arogya Seva Sadan"
        )
        self.assertEqual(result["evidence_source"], "fhir_organization")
        self.assertEqual(result["confidence"], "high")

    def test_unknown_hospital_returns_none(self):
        record = {
            "patient_name": "Rahul Verma",
            "age": 42,
            "diagnosis": "Fever"
        }

        result = identify_hospital(record)

        self.assertIsNone(result["hospital_name"])
        self.assertIsNone(result["evidence_source"])
        self.assertEqual(result["confidence"], "unknown")

    def test_none_metadata_does_not_crash(self):
        result = identify_hospital(None)

        self.assertIsNone(result["hospital_name"])
        self.assertEqual(result["confidence"], "unknown")

    def test_non_dictionary_metadata_does_not_crash(self):
        result = identify_hospital("hospital metadata")

        self.assertIsNone(result["hospital_name"])
        self.assertEqual(result["confidence"], "unknown")

    def test_invalid_document_metadata_does_not_crash(self):
        result = identify_hospital({
            "document_metadata": "invalid metadata"
        })

        self.assertIsNone(result["hospital_name"])
        self.assertEqual(result["confidence"], "unknown")

    def test_invalid_export_metadata_does_not_crash(self):
        result = identify_hospital({
            "document_metadata": {
                "_export_meta": ["invalid"]
            }
        })

        self.assertIsNone(result["hospital_name"])
        self.assertEqual(result["confidence"], "unknown")


if __name__ == "__main__":
    unittest.main()
