import unittest

from modules.identity_extraction import extract_identity_candidates


class TestIdentityExtraction(unittest.TestCase):

    def test_patient_name(self):
        result = extract_identity_candidates({
            "patient_name": "Aarav Sharma"
        })

        self.assertEqual(
            result["patient_names"],
            [{"value": "Aarav Sharma", "confidence": 0.99}]
        )

    def test_different_name_fields(self):
        record = {
            "patientName": "Aarav Sharma",
            "father_name": "Rohan Sharma",
            "motherName": "Meera Sharma"
        }

        result = extract_identity_candidates(record)

        patient_names = [item["value"] for item in result["patient_names"]]
        self.assertEqual(patient_names, ["Aarav Sharma"])

        relatives = {
            item["relation"]: item["value"]
            for item in result["relative_names"]
        }

        self.assertEqual(relatives["father"], "Rohan Sharma")
        self.assertEqual(relatives["mother"], "Meera Sharma")

    def test_hospital_identifiers(self):
        record = {
            "uhid": "HOSP-A-001",
            "mrn": "MRN-12345",
            "hospital_patient_id": "PAT-001"
        }

        result = extract_identity_candidates(record)

        identifiers = {
            (item["type"], item["value"])
            for item in result["identifiers"]
        }

        self.assertEqual(identifiers, {
            ("UHID", "HOSP-A-001"),
            ("MRN", "MRN-12345"),
            ("HOSPITAL_ID", "PAT-001")
        })

    def test_abha_and_aadhaar_are_not_verified_automatically(self):
        record = {
            "abha_id": "12345678901234",
            "aadhaar_no": "1234 5678 9012"
        }

        result = extract_identity_candidates(record)

        self.assertEqual(len(result["identifiers"]), 2)
        for identifier in result["identifiers"]:
            self.assertFalse(identifier["verified"])

    def test_insurance_policy_number(self):
        record = {
            "insurance_provider": "Example Insurance",
            "policy_no": "POL-12345"
        }

        result = extract_identity_candidates(record)

        self.assertEqual(result["identifiers"], [{
            "type": "INSURANCE_ID",
            "value": "POL-12345",
            "confidence": 0.99,
            "scope": "example insurance"
        }])

    def test_nested_registration_data(self):
        record = {
            "registration": {
                "patient_name": "Aarav Sharma",
                "identifiers": {
                    "uhid": "HOSP-A-001"
                }
            }
        }

        result = extract_identity_candidates(record)

        self.assertEqual(result["patient_names"][0]["value"], "Aarav Sharma")
        self.assertEqual(result["identifiers"][0]["value"], "HOSP-A-001")

    def test_fhir_patient_name(self):
        record = {
            "resourceType": "Patient",
            "name": [{
                "given": ["Aarav"],
                "family": "Sharma"
            }]
        }

        result = extract_identity_candidates(record)

        self.assertEqual(result["patient_names"][0]["value"], "Aarav Sharma")

    def test_generic_name_field_is_skipped(self):
        result = extract_identity_candidates({
            "name": "Dr. Meera Sharma"
        })

        self.assertEqual(result["patient_names"], [])

    def test_hospital_source_id_is_not_a_patient_identifier(self):
        record = {
            "hospital_id": "HOSP_A",
            "patient_name": "Aarav Sharma"
        }

        result = extract_identity_candidates(record)

        self.assertEqual(result["identifiers"], [])

    def test_empty_and_invalid_records(self):
        for record in ({}, [], None, "", 123):
            with self.subTest(record=record):
                result = extract_identity_candidates(record)

                self.assertEqual(result, {
                    "patient_names": [],
                    "relative_names": [],
                    "identifiers": [],
                    "secondary_clues": {
                        "dob": None,
                        "age": None,
                        "village": None,
                        "locality": None
                    }
                })

    def test_numeric_uhid(self):
        result = extract_identity_candidates({"uhid": 12345})

        self.assertEqual(result["identifiers"][0]["value"], "12345")

    def test_boolean_identifier_is_skipped(self):
        result = extract_identity_candidates({"uhid": True})

        self.assertEqual(result["identifiers"], [])

    def test_fhir_mrn(self):
        record = {
            "resourceType": "Patient",
            "identifier": [{
                "system": "hospital-mrn",
                "value": "MRN-1001"
            }]
        }

        result = extract_identity_candidates(record)

        self.assertEqual(result["identifiers"][0]["type"], "MRN")

    def test_fhir_abha_needs_verification(self):
        record = {
            "resourceType": "Patient",
            "identifier": [{
                "system": "abha",
                "value": "12345678901234"
            }]
        }

        result = extract_identity_candidates(record)
        abha = result["identifiers"][0]

        self.assertEqual(abha["type"], "ABHA")
        self.assertFalse(abha["verified"])

    def test_patient_inside_fhir_bundle(self):
        record = {
            "resourceType": "Bundle",
            "entry": [{
                "resource": {
                    "resourceType": "Patient",
                    "name": [{
                        "given": ["Aarav"],
                        "family": "Sharma"
                    }]
                }
            }]
        }

        result = extract_identity_candidates(record)

        self.assertEqual(result["patient_names"][0]["value"], "Aarav Sharma")

    def test_practitioner_is_not_treated_as_patient(self):
        record = {
            "resourceType": "Bundle",
            "entry": [{
                "resource": {
                    "resourceType": "Practitioner",
                    "name": [{"text": "Meera Sharma"}],
                    "identifier": [{
                        "system": "hospital-mrn",
                        "value": "MRN-999"
                    }]
                }
            }]
        }

        result = extract_identity_candidates(record)

        self.assertEqual(result["patient_names"], [])
        self.assertEqual(result["identifiers"], [])

    # These records use the field names found in the hospital exports.

    def test_arogya_registration(self):
        record = {
            "PatientID": "UHID-TEST-001",
            "LastName": "Patel",
            "FirstName": "Ashok",
            "DOB (MM/DD/YYYY)": "04/20/1979",
            "Guardian": "S/O SHYAM PATEL",
            "City": "Gopaldih",
            "Phone": "9000000001"
        }

        result = extract_identity_candidates(record)

        names = [item["value"] for item in result["patient_names"]]
        self.assertIn("Ashok Patel", names)
        self.assertEqual(result["identifiers"][0]["type"], "HOSPITAL_ID")
        self.assertEqual(result["relative_names"][0]["relation"], "father")
        self.assertEqual(result["secondary_clues"]["locality"], "Gopaldih")
        self.assertIsNone(result["secondary_clues"]["village"])

    def test_city_is_extracted_as_locality(self):
        result = extract_identity_candidates({"city": "Bengaluru"})

        self.assertEqual(
            result["secondary_clues"]["locality"],
            "Bengaluru"
        )
        self.assertIsNone(result["secondary_clues"]["village"])

    def test_invalid_age_is_rejected(self):
        result = extract_identity_candidates({"age": 250})

        self.assertIsNone(result["secondary_clues"]["age"])

    def test_village_is_extracted_correctly(self):
        result = extract_identity_candidates({
            "village": "Jalalpur"
        })

        self.assertEqual(
            result["secondary_clues"]["village"],
            "Jalalpur"
        )
        self.assertIsNone(result["secondary_clues"]["locality"])

    def test_sanjeevani_registration(self):
        record = {
            "UHID": "SNJ/26/TEST001",
            "Patient Name": "Mahesh Chauhan",
            "Age": "48",
            "DOB": "12/04/1977",
            "Relation": "S/o",
            "Relative Name": "Naresh Chauhan",
            "Village/Mohalla": "Durgamau Kalan",
            "Mobile": "9000000002",
            "Aadhaar No": "123456789012"
        }

        result = extract_identity_candidates(record)

        names = [item["value"] for item in result["patient_names"]]
        self.assertIn("Mahesh Chauhan", names)

        relative = result["relative_names"][0]
        self.assertEqual(relative["relation"], "father")
        self.assertEqual(relative["value"], "Naresh Chauhan")

        self.assertEqual(result["secondary_clues"]["age"], 48)
        self.assertEqual(
            result["secondary_clues"]["village"],
            "Durgamau Kalan"
        )

    def test_jeevanjyoti_registration(self):
        record = {
            "Reg No": "JJ-TEST-001",
            "Naam": "à¤°à¤¾à¤®à¥‡à¤¶à¥à¤µà¤° à¤¨à¤¿à¤·à¤¾à¤¦",
            "Ling": "M",
            "Umar": "52",
            "Janm Tithi": "15-08-1974",
            "Pita/Pati ka Naam": "D/o à¤•à¤¿à¤¶à¤¨ à¤¨à¤¿à¤·à¤¾à¤¦",
            "Gaon": "Rampur",
            "Mobile No": "9000000003",
            "Aadhar": "123456789013"
        }

        result = extract_identity_candidates(record)

        names = [item["value"] for item in result["patient_names"]]
        self.assertIn("à¤°à¤¾à¤®à¥‡à¤¶à¥à¤µà¤° à¤¨à¤¿à¤·à¤¾à¤¦", names)

        relative = result["relative_names"][0]
        self.assertEqual(relative["relation"], "father")
        self.assertEqual(relative["value"], "à¤•à¤¿à¤¶à¤¨ à¤¨à¤¿à¤·à¤¾à¤¦")

        self.assertEqual(result["secondary_clues"]["age"], 52)
        self.assertEqual(result["secondary_clues"]["village"], "Rampur")

    def test_dhh_patient_record(self):
        record = {
            "facility": {"name": "District Hospital"},
            "patients": [{
                "uhid": "DHH-TEST-001",
                "name": {
                    "first": "Sunita",
                    "last": "Patel",
                    "local": "à¤¸à¥à¤¨à¥€à¤¤à¤¾ à¤ªà¤Ÿà¥‡à¤²"
                },
                "dob": "1972-07-11",
                "age": 51,
                "guardian": {
                    "relation": "D/o",
                    "name": "Ramesh Patel"
                },
                "contact": {"mobile": "9000000004"},
                "address": {"village": "Bhimpur"}
            }]
        }

        result = extract_identity_candidates(record)

        names = [item["value"] for item in result["patient_names"]]
        self.assertIn("Sunita Patel", names)
        self.assertEqual(result["identifiers"][0]["value"], "DHH-TEST-001")

        relative = result["relative_names"][0]
        self.assertEqual(relative["relation"], "father")
        self.assertEqual(relative["value"], "Ramesh Patel")

        self.assertEqual(result["secondary_clues"]["dob"], "1972-07-11")
        self.assertEqual(result["secondary_clues"]["village"], "Bhimpur")

    def test_arogya_dob_uses_month_day_year(self):
        result = extract_identity_candidates({
            "DOB (MM/DD/YYYY)": "02/09/1977"
        })

        self.assertEqual(
            result["secondary_clues"]["dob"],
            "1977-02-09"
        )

    def test_sanjeevani_dob_uses_day_month_year(self):
        result = extract_identity_candidates({
            "DOB": "02/09/1977"
        })

        self.assertEqual(
            result["secondary_clues"]["dob"],
            "1977-09-02"
        )

    def test_jeevanjyoti_date_uses_day_month_year(self):
        result = extract_identity_candidates({
            "Janm Tithi": "15-08-1974"
        })

        self.assertEqual(
            result["secondary_clues"]["dob"],
            "1974-08-15"
        )

    def test_iso_date_is_preserved(self):
        result = extract_identity_candidates({
            "birthDate": "1972-07-11"
        })

        self.assertEqual(
            result["secondary_clues"]["dob"],
            "1972-07-11"
        )

    def test_ambiguous_unknown_date_format_is_rejected(self):
        result = extract_identity_candidates({
            "date_of_birth": "02/09/1977"
        })

        self.assertIsNone(result["secondary_clues"]["dob"])


if __name__ == "__main__":
    unittest.main()