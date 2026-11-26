
import unittest

from modules.pii_detection import detect_pii, detect_filename_pii


class TestPIIDetection(unittest.TestCase):

    def test_patient_name(self):
        patient = {"patient_name": "Test Patient"}

        results = detect_pii(patient, source_type="csv")

        self.assertEqual(results[0]["category"], "PATIENT_NAME")

    def test_relative_name(self):
        text = "C/O Test Relative"

        results = detect_pii(text)

        self.assertEqual(results[0]["category"], "RELATIVE_NAME")

    def test_phone_number(self):
        text = "Contact: 9876543210"

        results = detect_pii(text)

        self.assertTrue(any(
            result["category"] == "PHONE" for result in results
        ))

    def test_aadhaar_number(self):
        text = "Aadhaar: 1234 5678 9012"

        results = detect_pii(text)

        self.assertTrue(any(
            result["category"] == "AADHAAR" for result in results
        ))

    def test_pan_number(self):
        text = "PAN: ABCDE1234F"

        results = detect_pii(text)

        self.assertTrue(any(
            result["category"] == "PAN" for result in results
        ))

    def test_hindi_relative_name(self):
        text = "पिता: परीक्षण नाम"

        results = detect_pii(text)

        self.assertTrue(any(
            result["category"] == "RELATIVE_NAME" for result in results
        ))

    def test_hinglish_patient_name(self):
        text = "Patient name: परीक्षण Kumar"

        results = detect_pii(text)

        self.assertTrue(any(
            result["category"] == "PATIENT_NAME" for result in results
        ))

    def test_nested_json(self):
        patient = {
            "patients": [
                {
                    "patient_name": "Test Patient",
                    "contact": {
                        "phone": "9876543210"
                    }
                }
            ]
        }

        results = detect_pii(
            patient,
            source_type="json",
            base_path="/"
        )

        paths = [result["path"] for result in results]

        self.assertIn("/patients/0/patient_name", paths)
        self.assertIn("/patients/0/contact/phone", paths)

    def test_known_patient_name(self):
        text = "Test Patient was admitted yesterday."

        results = detect_pii(
            text,
            known_names=["Test Patient"]
        )

        self.assertTrue(any(
            result["category"] == "PATIENT_NAME" for result in results
        ))

    def test_filename(self):
        results = detect_filename_pii(
            "registration/Test Patient.csv",
            known_names=["Test Patient"]
        )

        self.assertTrue(any(
            result["target"] == "filename" for result in results
        ))

    def test_medical_complaint(self):
        text = "C/O fever"

        results = detect_pii(text)

        self.assertFalse(any(
            result["category"] == "RELATIVE_NAME" for result in results
        ))

    def test_doctor_name(self):
        text = "Dr. Test Doctor examined the patient."

        results = detect_pii(
            text,
            known_names=["Test Doctor"]
        )

        self.assertFalse(any(
            result["category"] == "PATIENT_NAME" for result in results
        ))

    def test_detection_details(self):
        patient = {"patient_name": "Test Patient"}

        results = detect_pii(
            patient,
            source_type="csv",
            record_id="REC_001",
            source_file="registration/test.csv"
        )

        result = results[0]

        self.assertEqual(result["action"], "REDACT")
        self.assertEqual(result["record_id"], "REC_001")
        self.assertEqual(result["source_file"], "registration/test.csv")

    def test_detected_text_matches_offsets(self):
        text = "Patient name: Test Patient"

        results = detect_pii(text)

        result = next(
            item for item in results
            if item["category"] == "PATIENT_NAME"
        )

        detected_text = text[result["start"]:result["end"]]

        self.assertEqual(detected_text, "Test Patient")

    # New tests for name normalization

    def test_known_name_with_different_capitalization(self):
        text = "RAHUL SHARMA was admitted yesterday."

        results = detect_pii(
            text,
            known_names=["Dr. Rahul Sharma"]
        )

        self.assertTrue(any(
            result["category"] == "PATIENT_NAME"
            for result in results
        ))

    def test_known_name_with_extra_spaces(self):
        text = "Rahul   Sharma was admitted yesterday."

        results = detect_pii(
            text,
            known_names=["Rahul Sharma"]
        )

        result = next(
            item for item in results
            if item["category"] == "PATIENT_NAME"
        )

        detected_text = text[result["start"]:result["end"]]

        self.assertEqual(detected_text, "Rahul   Sharma")

    def test_known_hindi_name_with_title(self):
        text = "राहुल शर्मा अस्पताल में भर्ती हुए।"

        results = detect_pii(
            text,
            known_names=["श्री राहुल शर्मा"]
        )

        self.assertTrue(any(
            result["category"] == "PATIENT_NAME"
            for result in results
        ))


    def test_abha_number(self):
        text = "ABHA No: 12345678901234"
        results = detect_pii(text)

        detection = next(
            item for item in results if item["category"] == "ABHA"
        )

        self.assertEqual(
            text[detection["start"]:detection["end"]],
            "12345678901234"
        )

    def test_pin_code(self):
        text = "PIN: 560001"
        results = detect_pii(text)

        detection = next(
            item for item in results if item["category"] == "PIN_CODE"
        )

        self.assertEqual(
            text[detection["start"]:detection["end"]],
            "560001"
        )

    def test_insurance_id(self):
        text = "Policy No: POL123456"
        results = detect_pii(text)

        detection = next(
            item for item in results
            if item["category"] == "INSURANCE_ID"
        )

        self.assertEqual(
            text[detection["start"]:detection["end"]],
            "POL123456"
        )

    def test_uhid_labelled_identifier(self):
        text = "UHID: HOSP12345"
        results = detect_pii(text)

        detection = next(
            item for item in results if item["category"] == "UHID"
        )

        self.assertEqual(
            text[detection["start"]:detection["end"]],
            "HOSP12345"
        )



if __name__ == "__main__":
    unittest.main()
