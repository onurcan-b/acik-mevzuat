import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "betikler" / "senkronize.py"
SPEC = importlib.util.spec_from_file_location("senkronize", MODULE_PATH)
sync = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(sync)


class SyncHelpersTest(unittest.TestCase):
    def test_slugify_turkish(self):
        self.assertEqual(sync.slugify("Türk Ceza Kanunu"), "turk-ceza-kanunu")

    def test_normalize_date(self):
        self.assertEqual(sync.normalize_date("12/10/2004"), "2004-10-12")
        self.assertEqual(sync.normalize_date("2004-10-12T00:00:00Z"), "2004-10-12")

    def test_extract_accepted_date(self):
        text = "Kanun No. 5237\nKabul Tarihi : 26.9.2004"
        self.assertEqual(sync.extract_accepted_date(text), "2004-09-26")

    def test_html_normalization(self):
        text = sync.normalize_document(
            "<html><body><p>Madde 1</p><p>  Birinci   fıkra. </p></body></html>"
        )
        self.assertIn("Madde 1", text)
        self.assertIn("Birinci fıkra.", text)
        self.assertNotIn("<p>", text)


if __name__ == "__main__":
    unittest.main()
