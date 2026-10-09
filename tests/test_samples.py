import csv
import unittest

from scripts.check_pack import check_pack
from scripts.route import inputs_from_sample, route_request
from scripts.samples import SAMPLES_DIR, list_samples, load_sample

EXPECTED = {
    "zendesk": {"request_id": "VR-0001", "route": ["manager", "security"], "days_open": 1.1},
    "figma": {"request_id": "VR-0002", "route": ["manager"], "days_open": 0.2},
    "asana": {"request_id": "VR-0003", "route": ["manager"], "days_open": 0.9},
}


class SamplesTest(unittest.TestCase):
    def test_lists_all_samples(self):
        self.assertEqual(list_samples(), ["zendesk", "figma", "asana"])

    def test_loads_each_sample_by_short_name_and_id(self):
        for name, want in EXPECTED.items():
            for key in (name, want["request_id"]):
                with self.subTest(key=key):
                    sample = load_sample(key)
                    self.assertEqual(sample["request_id"], want["request_id"])
                    self.assertEqual(sample["expected"]["routing"]["route"], want["route"])
                    self.assertEqual(sample["expected"]["status"]["days_open"], want["days_open"])

    def test_every_sample_has_a_passing_pack(self):
        for name in list_samples():
            with self.subTest(sample=name):
                sample = load_sample(name)
                pack = sample["expected"]["pack"]
                exceptions = sample["expected"]["status"]["exceptions"]
                result = check_pack(pack["rows"])
                self.assertEqual(result["reasons"], [])
                self.assertTrue(result["passed"])
                self.assertEqual(result["not_found"], pack["check"]["not_found"])
                self.assertEqual(result["not_found"], exceptions["not_found_pack_rows"])
                self.assertEqual(pack["check"]["rows"], len(pack["rows"]))
                self.assertEqual(
                    exceptions["total"],
                    exceptions["missing_intake_fields"] + exceptions["not_found_pack_rows"] + exceptions["rejections"],
                )
                self.assertEqual(route_request(**inputs_from_sample(sample))["route"], sample["expected"]["routing"]["route"])

        for name in ("figma", "asana"):
            with self.subTest(sample=name, check="fetch log"):
                sample = load_sample(name)
                rows = sample["expected"]["pack"]["rows"]
                log_path = SAMPLES_DIR / f"{sample['request_id'].lower()}-{name}-fetch-log.csv"
                with open(log_path, newline="") as f:
                    fetched_ok = {row["url"] for row in csv.DictReader(f) if row["http_status"] == "200"}
                for row in rows:
                    for url in row["source_urls"]:
                        self.assertIn(url, fetched_ok, f"{row['id']} cites an unlogged URL")
                assumptions = [row["id"] for row in rows if row["id"].startswith("R10") and row["label"] == "ASSUMPTION"]
                self.assertEqual(len(assumptions), 1)

    def test_unknown_name_raises(self):
        with self.assertRaises(KeyError):
            load_sample("slack")
