
import unittest

from modules.normalization import build_normalized_records


class TestNormalization(unittest.TestCase):

    def setUp(self):
        self.ingestion_result = {
            "source_file": "registration/patients.json",
            "format": "JSON",
            "status": "SUCCESS",
            "error_code": None,
            "records": [
                {
                    "locator": "/patients/0",
                    "data": {
                        "patient_name": "Aarav Sharma",
                        "father_name": "Rohan Sharma",
                        "uhid": "JJH-1024",
                        "aadhaar": "1234 5678 9012",
                        "mobile": "9876543210"
                    }
                }
            ],
            "metadata": {
                "hospital_id": "HOSP_001",
                "encoding": "utf-8",
                "record_count": 1,
                "document_metadata": {
                    "_export_meta": {
                        "hospital": "Jeevan Jyoti Hospital"
                    }
                }
            },
            "warnings": []
        }

    def test_builds_normalized_record(self):
        results = build_normalized_records(self.ingestion_result)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["record_id"], "REC_001")

    def test_preserves_source_information(self):
        results = build_normalized_records(self.ingestion_result)
        source = results[0]["source"]

        self.assertEqual(source["hospital_id"], "HOSP_001")
        self.assertEqual(source["file"], "registration/patients.json")
        self.assertEqual(source["locator"], "/patients/0")

    def test_identifies_hospital_from_metadata(self):
        results = build_normalized_records(self.ingestion_result)

        self.assertEqual(
            results[0]["hospital"]["hospital_name"],
            "Jeevan Jyoti Hospital"
        )
        self.assertEqual(
            results[0]["hospital"]["evidence_source"],
            "json_metadata"
        )

    def test_extracts_patient_and_relative_names(self):
        results = build_normalized_records(self.ingestion_result)
        candidates = results[0]["identity_candidates"]

        self.assertEqual(
            candidates["patient_names"][0]["value"],
            "Aarav Sharma"
        )
        self.assertEqual(
            candidates["relative_names"][0]["value"],
            "Rohan Sharma"
        )
        self.assertEqual(
            candidates["relative_names"][0]["relation"],
            "father"
        )

    def test_extracts_identifiers(self):
        results = build_normalized_records(self.ingestion_result)
        identifiers = results[0]["identity_candidates"]["identifiers"]

        identifier_types = [
            item["type"] for item in identifiers
        ]

        self.assertIn("UHID", identifier_types)
        self.assertIn("AADHAAR", identifier_types)

        aadhaar = next(
            item for item in identifiers
            if item["type"] == "AADHAAR"
        )

        self.assertFalse(aadhaar["verified"])

    def test_runs_pii_detection(self):
        results = build_normalized_records(self.ingestion_result)

        categories = [
            item["category"]
            for item in results[0]["detections"]
        ]

        self.assertIn("PATIENT_NAME", categories)
        self.assertIn("RELATIVE_NAME", categories)
        self.assertIn("UHID", categories)
        self.assertIn("AADHAAR", categories)
        self.assertIn("PHONE", categories)

    def test_unknown_hospital_is_not_guessed(self):
        ingestion_result = {
            **self.ingestion_result,
            "metadata": {
                "hospital_id": None,
                "encoding": "utf-8",
                "record_count": 1,
                "document_metadata": {}
            }
        }

        results = build_normalized_records(ingestion_result)

        self.assertIsNone(
            results[0]["hospital"]["hospital_name"]
        )
        self.assertIsNone(results[0]["source"]["hospital_id"])

    def test_conflicting_hospital_evidence_across_records_returns_unknown(self):
        ingestion_result = {
            **self.ingestion_result,
            "records": [
                self.ingestion_result["records"][0],
                {
                    "locator": "/fhir/organization/0",
                    "data": {
                        "resourceType": "Organization",
                        "name": "Arogya Seva Sadan"
                    }
                }
            ]
        }

        results = build_normalized_records(ingestion_result)

        self.assertIsNone(
            results[0]["hospital"]["hospital_name"]
        )
        self.assertEqual(
            results[0]["hospital"]["confidence"],
            "unknown"
        )

    def test_failed_ingestion_returns_empty_list(self):
        ingestion_result = {
            "source_file": "bad.json",
            "format": "JSON",
            "status": "MALFORMED",
            "records": [],
            "metadata": {},
            "warnings": []
        }

        results = build_normalized_records(ingestion_result)
        self.assertEqual(results, [])

    def test_detects_pii_in_document_metadata(self):
        ingestion_result = {
            **self.ingestion_result,
            "metadata": {
                **self.ingestion_result["metadata"],
                "document_metadata": {
                    "_export_meta": {
                        "hospital": "Jeevan Jyoti Hospital",
                        "contact_phone": "9123456780"
                    }
                }
            }
        }

        results = build_normalized_records(ingestion_result)

        metadata_phone_detections = [
            detection
            for detection in results[0]["detections"]
            if detection["category"] == "PHONE"
            and "metadata.document_metadata" in detection["path"]
        ]

        self.assertTrue(metadata_phone_detections)


if __name__ == "__main__":
    unittest.main()
