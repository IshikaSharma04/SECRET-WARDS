
import unittest
import unicodedata

from modules.identity import normalize_name


class TestIdentity(unittest.TestCase):

    def test_name_cleanup(self):
        cases = [
            ("Dr. Rahul Sharma", "rahul sharma"),
            ("RAHUL SHARMA", "rahul sharma"),
            ("Rahul-Sharma", "rahul sharma"),
            ("R. Sharma", "r sharma"),
            ("Amit Kumar", "amit kumar"),
        ]

        for name, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(normalize_name(name), expected)

    def test_hindi_name_cleanup(self):
        cases = [
            ("श्री राहुल शर्मा", "राहुल शर्मा"),
            ("डॉ. राहुल शर्मा", "राहुल शर्मा"),
            ("श्रीमती सीमा देवी", "सीमा देवी"),
            ("सुश्री प्रिया वर्मा", "प्रिया वर्मा"),
            ("कुमारी नेहा शर्मा", "नेहा शर्मा"),
        ]

        for name, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(normalize_name(name), expected)

    def test_extra_spaces(self):
        name1 = normalize_name("Rahul Sharma")
        name2 = normalize_name("  RAHUL    SHARMA  ")

        self.assertEqual(name1, name2)

    def test_punctuation_cleanup(self):
        self.assertEqual(
            normalize_name("Rahul, Sharma."),
            "rahul sharma"
        )

    def test_unicode_normalization(self):
        name = "श्री राहुल शर्मा"
        normalized = normalize_name(name)

        self.assertEqual(normalized, "राहुल शर्मा")
        self.assertEqual(
            normalized,
            unicodedata.normalize("NFKC", normalized)
        )

    def test_multiple_leading_titles(self):
        self.assertEqual(
            normalize_name("Dr. Mr. Rahul Sharma"),
            "rahul sharma"
        )

    def test_invalid_names(self):
        for name in ["", "   ", None, 123]:
            with self.subTest(name=name):
                self.assertIsNone(normalize_name(name))

    def test_name_without_title(self):
        self.assertEqual(
            normalize_name("Amit Kumar"),
            "amit kumar"
        )


if __name__ == "__main__":
    unittest.main()
