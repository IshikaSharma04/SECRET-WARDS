
import unittest

from modules.identity import normalize_name


class TestIdentity(unittest.TestCase):

    def test_name_cleanup(self):
        cases = [
            ("Dr. Rahul Sharma", "rahul sharma"),
            ("RAHUL SHARMA", "rahul sharma"),
            ("Rahul-Sharma", "rahul sharma"),
            ("श्री राहुल शर्मा", "राहुल शर्मा"),
            ("डॉ. राहुल शर्मा", "राहुल शर्मा"),
            ("श्रीमती सीमा देवी", "सीमा देवी"),
            ("R. Sharma", "r sharma"),
        ]

        for name, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(normalize_name(name), expected)

    def test_extra_spaces(self):
        name1 = normalize_name("Rahul Sharma")
        name2 = normalize_name("  RAHUL    SHARMA  ")

        self.assertEqual(name1, name2)

    def test_invalid_names(self):
        for name in ["", "   ", None, 123]:
            with self.subTest(name=name):
                self.assertIsNone(normalize_name(name))

    def test_name_without_title(self):
        self.assertEqual(normalize_name("Amit Kumar"), "amit kumar")


if __name__ == "__main__":
    unittest.main()
