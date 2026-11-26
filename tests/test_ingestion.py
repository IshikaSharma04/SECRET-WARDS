import json
import tempfile
import unittest
from pathlib import Path

from modules.ingestion import ingest_file


class TestIngestion(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_file(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_csv_ingestion(self):
        path = self.create_file(
            "patients.csv",
            b"name,age\nAarav,25\nRiya,30\n"
        )

        result = ingest_file(path, "HOSP_001", self.root)

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["format"], "CSV")
        self.assertEqual(len(result["records"]), 2)
        self.assertEqual(result["records"][0]["locator"], "row:0")
        self.assertEqual(result["records"][0]["data"]["age"], "25")

    def test_tsv_ingestion(self):
        path = self.create_file(
            "patients.tsv",
            b"name\tage\nAarav\t25\n"
        )

        result = ingest_file(path, "HOSP_001", self.root)

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["format"], "TSV")
        self.assertEqual(len(result["records"]), 1)

    def test_json_array_ingestion(self):
        content = json.dumps([
            {"patient": "Patient A"},
            {"patient": "Patient B"}
        ]).encode("utf-8")

        path = self.create_file("patients.json", content)
        result = ingest_file(path, "HOSP_001", self.root)

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(len(result["records"]), 2)
        self.assertEqual(result["records"][0]["locator"], "/0")
        self.assertEqual(result["records"][1]["locator"], "/1")

    def test_fhir_bundle_ingestion(self):
        bundle = {
            "resourceType": "Bundle",
            "type": "collection",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": "patient-1"
                    }
                },
                {
                    "resource": {
                        "resourceType": "Practitioner",
                        "id": "doctor-1"
                    }
                }
            ]
        }

        path = self.create_file(
            "bundle.json",
            json.dumps(bundle).encode("utf-8")
        )

        result = ingest_file(path, "HOSP_001", self.root)

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["format"], "FHIR")
        self.assertEqual(len(result["records"]), 2)
        self.assertEqual(
            result["records"][0]["locator"],
            "/entry/0/resource"
        )
        self.assertEqual(
            result["records"][0]["data"]["resourceType"],
            "Patient"
        )

    def test_nested_opd_json_ingestion(self):
        data = {
            "_export_meta": {
                "hospital": "Example Hospital"
            },
            "visits": [
                {
                    "visit_id": "V001",
                    "complaints": "Fever"
                },
                {
                    "visit_id": "V002",
                    "complaints": "Cough"
                }
            ]
        }

        path = self.create_file(
            "opd.json",
            json.dumps(data).encode("utf-8")
        )

        result = ingest_file(path, "HOSP_001", self.root)

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(len(result["records"]), 2)
        self.assertEqual(
            result["records"][0]["locator"],
            "/visits/0"
        )
        self.assertEqual(
            result["records"][1]["locator"],
            "/visits/1"
        )
        self.assertEqual(
            result["metadata"]["document_metadata"]["_export_meta"]["hospital"],
            "Example Hospital"
        )


    def test_text_ingestion(self):
        path = self.create_file(
            "notes.txt",
            "Patient visit notes".encode("utf-8")
        )

        result = ingest_file(path, "HOSP_001", self.root)

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["records"][0]["locator"], "doc")
        self.assertEqual(
            result["records"][0]["data"]["text"],
            "Patient visit notes"
        )

    def test_utf16_encoding(self):
        path = self.create_file(
            "notes.txt",
            "Hospital record".encode("utf-16")
        )

        result = ingest_file(path, "HOSP_001", self.root)

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["metadata"]["encoding"], "utf-16")

    def test_cp1252_encoding(self):
        path = self.create_file(
            "notes.txt",
            "Patient record €".encode("cp1252")
        )

        result = ingest_file(path, "HOSP_001", self.root)

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["metadata"]["encoding"], "cp1252")

    def test_empty_file(self):
        path = self.create_file("empty.txt", b"")

        result = ingest_file(path, "HOSP_001", self.root)

        self.assertEqual(result["status"], "MALFORMED")
        self.assertEqual(result["error_code"], "empty_file")

    def test_malformed_json(self):
        path = self.create_file("broken.json", b'{"patient":')

        result = ingest_file(path, "HOSP_001", self.root)

        self.assertEqual(result["status"], "MALFORMED")
        self.assertEqual(result["error_code"], "invalid_json")

    def test_unsupported_file(self):
        path = self.create_file("document.pdf", b"fake pdf")

        result = ingest_file(path, "HOSP_001", self.root)

        self.assertEqual(result["status"], "UNSUPPORTED")
        self.assertEqual(result["error_code"], "unsupported_format")


if __name__ == "__main__":
    unittest.main()
