
import unittest

from main import get_hospital_id, safe_hospital_id


class TestHospitalId(unittest.TestCase):

    def test_safe_hospital_id(self):
        self.assertEqual(
            safe_hospital_id("Arogya Seva Sadan"),
            "arogya_seva_sadan"
        )

    def test_safe_hospital_id_preserves_hindi(self):
        self.assertEqual(
            safe_hospital_id("आरोग्य सेवा सदन"),
            "आरोग्य_सेवा_सदन"
        )

    def test_safe_hospital_id_rejects_empty_values(self):
        self.assertIsNone(safe_hospital_id(None))
        self.assertIsNone(safe_hospital_id(""))
        self.assertIsNone(safe_hospital_id("   "))

    def test_hospital_from_document_metadata(self):
        ingestion = {
            "metadata": {
                "document_metadata": {
                    "_export_meta": {
                        "hospital": "Arogya Seva Sadan"
                    }
                }
            },
            "records": []
        }

        self.assertEqual(
            get_hospital_id(ingestion),
            "arogya_seva_sadan"
        )

    def test_multiple_organizations_same_hospital(self):
        ingestion = {
            "metadata": {},
            "records": [
                {
                    "data": {
                        "resourceType": "Organization",
                        "name": "Arogya Seva Sadan"
                    }
                },
                {
                    "data": {
                        "resourceType": "Organization",
                        "name": "AROGYA SEVA SADAN"
                    }
                }
            ]
        }

        self.assertEqual(
            get_hospital_id(ingestion),
            "arogya_seva_sadan"
        )

    def test_conflicting_organizations_return_none(self):
        ingestion = {
            "metadata": {},
            "records": [
                {
                    "data": {
                        "resourceType": "Organization",
                        "name": "Arogya Seva Sadan"
                    }
                },
                {
                    "data": {
                        "resourceType": "Organization",
                        "name": "Jeevan Jyoti Hospital"
                    }
                }
            ]
        }

        self.assertIsNone(get_hospital_id(ingestion))

    def test_conflicting_document_and_organization_return_none(self):
        ingestion = {
            "metadata": {
                "document_metadata": {
                    "_export_meta": {
                        "hospital": "Arogya Seva Sadan"
                    }
                }
            },
            "records": [
                {
                    "data": {
                        "resourceType": "Organization",
                        "name": "Jeevan Jyoti Hospital"
                    }
                }
            ]
        }

        self.assertIsNone(get_hospital_id(ingestion))

    def test_conflicting_explicit_fields_return_none(self):
        ingestion = {
            "metadata": {
                "hospital_name": "Arogya Seva Sadan",
                "facility_name": "Jeevan Jyoti Hospital"
            },
            "records": []
        }

        self.assertIsNone(get_hospital_id(ingestion))

    def test_unknown_hospital_returns_none(self):
        ingestion = {
            "metadata": {},
            "records": []
        }

        self.assertIsNone(get_hospital_id(ingestion))


if __name__ == "__main__":
    unittest.main()
