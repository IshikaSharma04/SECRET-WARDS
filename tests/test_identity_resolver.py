
import os
import tempfile
import unittest
from pathlib import Path

from modules.identity_resolver import resolve_records


class IdentityResolverTests(unittest.TestCase):

    def setUp(self):
        self.old_secret = os.environ.get("RAKSHA_SECRET")
        self.old_registry_secret = os.environ.get(
            "RAKSHA_REGISTRY_SECRET"
        )

        os.environ["RAKSHA_SECRET"] = "resolver-test-secret"
        os.environ["RAKSHA_REGISTRY_SECRET"] = "registry-test-secret"

        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry_path = Path(self.temp_dir.name) / "registry.json"

    def tearDown(self):
        if self.old_secret is None:
            os.environ.pop("RAKSHA_SECRET", None)
        else:
            os.environ["RAKSHA_SECRET"] = self.old_secret

        if self.old_registry_secret is None:
            os.environ.pop("RAKSHA_REGISTRY_SECRET", None)
        else:
            os.environ["RAKSHA_REGISTRY_SECRET"] = self.old_registry_secret

        self.temp_dir.cleanup()

    def resolve(self, records):
        return resolve_records(
            records,
            registry_path=self.registry_path
        )

    def make_record(
        self,
        record_id,
        hospital,
        name=None,
        uhid=None,
        relatives=None,
        abha=None,
        dob=None,
        age=None,
        village=None,
        locality=None,
        phone=None
    ):
        candidates = {
            "patient_names": [],
            "relative_names": [],
            "identifiers": [],
            "secondary_clues": {
                "dob": dob,
                "age": age,
                "village": village,
                "locality": locality,
            }
        }

        if name:
            candidates["patient_names"].append({
                "value": name,
                "confidence": 0.99
            })

        if relatives:
            candidates["relative_names"] = relatives

        if uhid:
            candidates["identifiers"].append({
                "type": "UHID",
                "value": uhid,
                "confidence": 0.99
            })

        if abha:
            candidates["identifiers"].append({
                "type": "ABHA",
                "value": abha,
                "confidence": 0.99,
                "verified": False
            })

        if phone:
            candidates["identifiers"].append({
                "type": "PHONE",
                "value": phone,
                "confidence": 0.99
            })

        return {
            "record_id": record_id,
            "source": {
                "hospital_id": hospital,
                "file": "patients.csv",
                "locator": "row:0"
            },
            "identity_candidates": candidates
        }

    def make_relative(self, name="Rohan Sharma", relation="father"):
        return {
            "value": name,
            "relation": relation,
            "confidence": 0.99
        }

    def assert_unresolved(self, results):
        for result in results:
            self.assertTrue(result["identity"]["review_required"])
            self.assertIsNone(result["identity"]["canonical_id"])
            self.assertIsNone(result["pseudonym"])

    def test_same_hospital_and_uhid_match(self):
        first = self.make_record(
            "REC_001", "HOSP_A", "Aarav Sharma", "HOSP-A-001"
        )
        second = self.make_record(
            "REC_002", "HOSP_A", "Aarav Sharma", "HOSP-A-001"
        )

        results = self.resolve([first, second])

        self.assertEqual(
            results[0]["identity"]["canonical_id"],
            results[1]["identity"]["canonical_id"]
        )
        self.assertEqual(results[0]["pseudonym"], results[1]["pseudonym"])
        self.assertTrue(results[0]["identity"]["matched"])

    def test_same_uhid_in_different_hospitals_does_not_match(self):
        first = self.make_record(
            "REC_001", "HOSP_A", "Aarav Sharma", "HOSP-A-001"
        )
        second = self.make_record(
            "REC_003", "HOSP_B", "Meera Patel", "HOSP-A-001"
        )

        results = self.resolve([first, second])

        self.assertNotEqual(
            results[0]["identity"]["canonical_id"],
            results[1]["identity"]["canonical_id"]
        )
        self.assertFalse(results[0]["identity"]["matched"])
        self.assertFalse(results[1]["identity"]["matched"])

    def test_name_alone_does_not_link_hospitals(self):
        first = self.make_record(
            "REC_001", "HOSP_A", "Aarav Sharma", "HOSP-A-001"
        )
        second = self.make_record(
            "REC_004", "HOSP_B", "Aarav Sharma", "HOSP-B-778"
        )

        results = self.resolve([first, second])

        self.assertTrue(results[0]["identity"]["review_required"])
        self.assertTrue(results[1]["identity"]["review_required"])
        self.assertIsNone(results[0]["pseudonym"])
        self.assertIsNone(results[1]["pseudonym"])

    def test_unverified_abha_is_not_used_for_matching(self):
        first = self.make_record(
            "REC_001", "HOSP_A", "Aarav Sharma", "HOSP-A-001"
        )
        second = self.make_record(
            "REC_005", "HOSP_B", "Aarav Sharma", abha="12345678901234"
        )

        results = self.resolve([first, second])

        self.assertTrue(results[0]["identity"]["review_required"])
        self.assertTrue(results[1]["identity"]["review_required"])
        self.assertIsNone(results[1]["pseudonym"])

    def test_relative_name_without_patient_name_is_unresolved(self):
        first = self.make_record(
            "REC_006",
            "HOSP_A",
            relatives=[{
                "value": "R Sharma",
                "relation": None,
                "confidence": 0.65
            }]
        )

        result = self.resolve([first])[0]

        self.assertIsNone(result["identity"]["canonical_id"])
        self.assertIsNone(result["pseudonym"])
        self.assertTrue(result["identity"]["review_required"])

    def test_conflicting_names_with_same_uhid_need_review(self):
        first = self.make_record(
            "REC_007", "HOSP_A", "Riya Verma", "HOSP-A-009"
        )
        second = self.make_record(
            "REC_008", "HOSP_A", "Kabir Mehta", "HOSP-A-009"
        )

        results = self.resolve([first, second])

        self.assert_unresolved(results)

    def test_same_patient_can_match_across_hospitals(self):
        first = self.make_record(
            "REC_009",
            "HOSP_A",
            "Aarav Sharma",
            "HOSP-A-001",
            relatives=[self.make_relative()]
        )

        second = self.make_record(
            "REC_010",
            "HOSP_B",
            "Aarav Sharma",
            "HOSP-B-778",
            relatives=[self.make_relative()]
        )

        results = self.resolve([first, second])

        self.assertEqual(
            results[0]["identity"]["canonical_id"],
            results[1]["identity"]["canonical_id"]
        )
        self.assertEqual(results[0]["pseudonym"], results[1]["pseudonym"])
        self.assertTrue(results[0]["identity"]["matched"])
        self.assertTrue(results[1]["identity"]["matched"])

    def test_different_uhids_in_same_hospital_need_review(self):
        first = self.make_record(
            "REC_011", "HOSP_A", "Aarav Sharma", "HOSP-A-001"
        )
        second = self.make_record(
            "REC_012", "HOSP_A", "Aarav Sharma", "HOSP-A-002"
        )

        results = self.resolve([first, second])

        self.assert_unresolved(results)

    def test_different_patients_in_same_hospital_are_not_flagged(self):
        first = self.make_record(
            "REC_013", "HOSP_A", "Aarav Sharma", "HOSP-A-001"
        )
        second = self.make_record(
            "REC_014", "HOSP_A", "Meera Patel", "HOSP-A-002"
        )

        results = self.resolve([first, second])

        self.assertNotEqual(
            results[0]["pseudonym"],
            results[1]["pseudonym"]
        )

        for result in results:
            self.assertFalse(result["identity"]["review_required"])
            self.assertIsNotNone(result["pseudonym"])

    def test_identity_stays_same_across_separate_runs(self):
        first = self.make_record(
            "REC_015", "HOSP_A", "Aarav Sharma", "HOSP-A-001"
        )
        second = self.make_record(
            "REC_016", "HOSP_A", "Aarav Sharma", "HOSP-A-001"
        )

        first_result = self.resolve([first])[0]
        second_result = self.resolve([second])[0]

        self.assertEqual(
            first_result["identity"]["canonical_id"],
            second_result["identity"]["canonical_id"]
        )
        self.assertEqual(
            first_result["pseudonym"],
            second_result["pseudonym"]
        )

    def test_new_hospital_identifier_uses_existing_identity(self):
        first = self.make_record(
            "REC_017",
            "HOSP_A",
            "Aarav Sharma",
            "HOSP-A-001",
            relatives=[self.make_relative()]
        )

        second = self.make_record(
            "REC_018",
            "HOSP_B",
            "Aarav Sharma",
            "HOSP-B-778",
            relatives=[self.make_relative()]
        )

        first_run = self.resolve([first, second])

        later_record = self.make_record(
            "REC_019",
            "HOSP_B",
            "Aarav Sharma",
            "HOSP-B-778",
            relatives=[self.make_relative()]
        )

        second_run = self.resolve([later_record])[0]

        self.assertEqual(
            first_run[0]["identity"]["canonical_id"],
            first_run[1]["identity"]["canonical_id"]
        )
        self.assertEqual(
            first_run[1]["identity"]["canonical_id"],
            second_run["identity"]["canonical_id"]
        )
        self.assertEqual(
            first_run[1]["pseudonym"],
            second_run["pseudonym"]
        )

    def test_same_patient_can_match_using_dob(self):
        first = self.make_record(
            "REC_020",
            "HOSP_A",
            "Anita Sharma",
            "HOSP-A-020",
            dob="1981-01-21"
        )

        second = self.make_record(
            "REC_021",
            "HOSP_B",
            "Anita Sharma",
            "HOSP-B-020",
            dob="1981-01-21"
        )

        results = self.resolve([first, second])

        self.assertEqual(
            results[0]["identity"]["canonical_id"],
            results[1]["identity"]["canonical_id"]
        )
        self.assertEqual(results[0]["pseudonym"], results[1]["pseudonym"])
        self.assertTrue(results[0]["identity"]["matched"])

    def test_same_patient_can_match_using_village_and_age(self):
        first = self.make_record(
            "REC_022",
            "HOSP_A",
            "Geeta Chauhan",
            "HOSP-A-022",
            age=52,
            village="Amarganj Khurd"
        )

        second = self.make_record(
            "REC_023",
            "HOSP_B",
            "Geeta Chauhan",
            "HOSP-B-023",
            age=53,
            village="Amarganj Khurd"
        )

        results = self.resolve([first, second])

        self.assertEqual(
            results[0]["identity"]["canonical_id"],
            results[1]["identity"]["canonical_id"]
        )
        self.assertEqual(results[0]["pseudonym"], results[1]["pseudonym"])

    def test_age_difference_greater_than_one_does_not_match(self):
        first = self.make_record(
            "REC_024",
            "HOSP_A",
            "Geeta Chauhan",
            "HOSP-A-024",
            age=50,
            village="Amarganj Khurd"
        )

        second = self.make_record(
            "REC_025",
            "HOSP_B",
            "Geeta Chauhan",
            "HOSP-B-025",
            age=53,
            village="Amarganj Khurd"
        )

        results = self.resolve([first, second])

        self.assert_unresolved(results)

    def test_conflicting_dobs_need_review(self):
        first = self.make_record(
            "REC_026",
            "HOSP_A",
            "Anita Sharma",
            "HOSP-A-026",
            relatives=[self.make_relative()],
            dob="1981-01-21"
        )

        second = self.make_record(
            "REC_027",
            "HOSP_B",
            "Anita Sharma",
            "HOSP-B-027",
            relatives=[self.make_relative()],
            dob="1982-01-21"
        )

        results = self.resolve([first, second])

        self.assert_unresolved(results)

    def test_shared_uhid_with_conflicting_dobs_needs_review(self):
        first = self.make_record(
            "REC_041",
            "HOSP_A",
            "Anita Sharma",
            "HOSP-A-041",
            dob="1981-01-21"
        )

        second = self.make_record(
            "REC_042",
            "HOSP_A",
            "Anita Sharma",
            "HOSP-A-041",
            dob="1982-01-21"
        )

        results = self.resolve([first, second])

        self.assert_unresolved(results)

    def test_uncertain_third_record_does_not_invalidate_confirmed_local_match(self):
        first = self.make_record(
            "REC_043",
            "HOSP_A",
            "Anita Sharma",
            "HOSP-A-043"
        )

        second = self.make_record(
            "REC_044",
            "HOSP_A",
            "Anita Sharma",
            "HOSP-A-043"
        )

        third = self.make_record(
            "REC_045",
            "HOSP_B",
            "Anita Sharma",
            "HOSP-B-045"
        )

        results = self.resolve([first, second, third])

        self.assertEqual(
            results[0]["identity"]["canonical_id"],
            results[1]["identity"]["canonical_id"]
        )
        self.assertEqual(
            results[0]["pseudonym"],
            results[1]["pseudonym"]
        )
        self.assertFalse(results[0]["identity"]["review_required"])
        self.assertFalse(results[1]["identity"]["review_required"])

        self.assertTrue(results[2]["identity"]["review_required"])
        self.assertIsNone(results[2]["identity"]["canonical_id"])
        self.assertIsNone(results[2]["pseudonym"])

    def test_duplicate_dob_candidates_in_same_hospital_are_ambiguous(self):
        first = self.make_record(
            "REC_028",
            "HOSP_A",
            "Anita Sharma",
            "HOSP-A-028",
            dob="1981-01-21"
        )

        second = self.make_record(
            "REC_029",
            "HOSP_A",
            "Anita Sharma",
            "HOSP-A-029",
            dob="1981-01-21"
        )

        third = self.make_record(
            "REC_030",
            "HOSP_B",
            "Anita Sharma",
            "HOSP-B-030",
            dob="1981-01-21"
        )

        results = self.resolve([first, second, third])

        self.assert_unresolved(results)

    def test_duplicate_relative_candidates_in_same_hospital_are_ambiguous(self):
        first = self.make_record(
            "REC_031",
            "HOSP_A",
            "Aarav Sharma",
            "HOSP-A-031",
            relatives=[self.make_relative()]
        )

        second = self.make_record(
            "REC_032",
            "HOSP_A",
            "Aarav Sharma",
            "HOSP-A-032",
            relatives=[self.make_relative()]
        )

        third = self.make_record(
            "REC_033",
            "HOSP_B",
            "Aarav Sharma",
            "HOSP-B-033",
            relatives=[self.make_relative()]
        )

        results = self.resolve([first, second, third])

        self.assert_unresolved(results)

    def test_duplicate_village_age_candidates_are_ambiguous(self):
        first = self.make_record(
            "REC_034",
            "HOSP_A",
            "Geeta Chauhan",
            "HOSP-A-034",
            age=52,
            village="Amarganj Khurd"
        )

        second = self.make_record(
            "REC_035",
            "HOSP_A",
            "Geeta Chauhan",
            "HOSP-A-035",
            age=53,
            village="Amarganj Khurd"
        )

        third = self.make_record(
            "REC_036",
            "HOSP_B",
            "Geeta Chauhan",
            "HOSP-B-036",
            age=52,
            village="Amarganj Khurd"
        )

        results = self.resolve([first, second, third])

        self.assert_unresolved(results)

    def test_phone_number_alone_is_not_used_for_matching(self):
        first = self.make_record(
            "REC_037",
            "HOSP_A",
            "Aarav Sharma",
            "HOSP-A-037",
            phone="9000000001"
        )

        second = self.make_record(
            "REC_038",
            "HOSP_B",
            "Meera Patel",
            "HOSP-B-038",
            phone="9000000001"
        )

        results = self.resolve([first, second])

        self.assertNotEqual(
            results[0]["identity"]["canonical_id"],
            results[1]["identity"]["canonical_id"]
        )

        for result in results:
            self.assertFalse(result["identity"]["matched"])
            self.assertFalse(result["identity"]["review_required"])

    def test_locality_alone_does_not_link_patients(self):
        first = self.make_record(
            "REC_039",
            "HOSP_A",
            "Aarav Sharma",
            "HOSP-A-039",
            locality="Bengaluru"
        )

        second = self.make_record(
            "REC_040",
            "HOSP_B",
            "Meera Patel",
            "HOSP-B-040",
            locality="Bengaluru"
        )

        results = self.resolve([first, second])

        self.assertNotEqual(
            results[0]["identity"]["canonical_id"],
            results[1]["identity"]["canonical_id"]
        )

        for result in results:
            self.assertFalse(result["identity"]["matched"])
            self.assertFalse(result["identity"]["review_required"])


if __name__ == "__main__":
    unittest.main()
