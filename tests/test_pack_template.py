import json
import re
import unittest
from pathlib import Path

from scripts.check_pack import check_pack
from scripts.samples import load_sample

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = json.loads((REPO_ROOT / "templates" / "research_pack.json").read_text())
CHECKLIST = (REPO_ROOT / ".cursor" / "rules" / "research-checklist.mdc").read_text()
ZENDESK_ROWS = {row["id"]: row for row in load_sample("zendesk")["expected"]["pack"]["rows"]}
ITEM_IDS = [f"R{n}" for n in range(1, 12)]


class PackTemplateTest(unittest.TestCase):
    def test_rows_cover_r1_to_r11_with_checklist_items(self):
        checklist_items = re.findall(r"^\| (R\d+) \| (.+?) \|", CHECKLIST, re.MULTILINE)
        self.assertEqual([row["id"] for row in TEMPLATE["rows"]], ITEM_IDS)
        self.assertEqual([(row["id"], row["item"]) for row in TEMPLATE["rows"]], checklist_items)
        self.assertEqual(TEMPLATE["request_id"], "")
        for row in TEMPLATE["rows"]:
            with self.subTest(row=row["id"]):
                self.assertEqual(
                    {key: row[key] for key in row if key not in ("id", "item")},
                    {"value": "", "source_urls": [], "checked_date": "", "status": "not_found", "label": "PUBLIC"},
                )

    def test_blank_template_fails(self):
        reasons = []
        for row_id in ITEM_IDS:
            reasons += [f"{row_id} has no source URL", f"{row_id} has bad checked_date ''"]
        reasons += ["R1 must be found", "R3 must be found", "R4 must be found", "R10 must be found"]
        self.assertEqual(check_pack(TEMPLATE["rows"]), {"passed": False, "reasons": reasons, "not_found": 11})

    def test_filled_template_passes(self):
        rows = []
        for row in TEMPLATE["rows"]:
            source = ZENDESK_ROWS.get(row["id"]) or ZENDESK_ROWS[row["id"] + "a"]
            rows.append({
                **row,
                "value": source["value"],
                "source_urls": source["source_urls"],
                "checked_date": source["checked_date"],
                "status": "found",
            })
        self.assertEqual(check_pack(rows), {"passed": True, "reasons": [], "not_found": 0})
