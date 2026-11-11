import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class ForkDocsTest(unittest.TestCase):
    def test_readme_leads_with_the_demo_note_and_the_footer(self):
        text = (REPO / "README.md").read_text()
        self.assertIn("Acme is a demo company with synthesized people.", text)
        self.assertTrue(text.rstrip().endswith("Built by Matt Snow on Grok Bot."))
        lowered = text.lower()
        self.assertNotIn("not affiliated", lowered)
        self.assertNotIn("unofficial", lowered)
        self.assertIn("VENDOR_ONBOARDING_REPO", text)
        self.assertIn("CURSOR_API_KEY", text)
        self.assertIn("config/company.json", text)

    def test_data_handling_and_license(self):
        handling = (REPO / "DATA-HANDLING.md").read_text()
        for phrase in [
            "W-9 received",
            "tickets/",
            "packs/",
            "runs/",
            "audit",
            "forking company is responsible",
            "as-is",
        ]:
            self.assertIn(phrase, handling)
        license_text = (REPO / "LICENSE").read_text()
        self.assertIn("MIT License", license_text)
        self.assertIn("Copyright (c) 2026 Matt Snow", license_text)
        self.assertIn("AS IS", license_text)


if __name__ == "__main__":
    unittest.main()
