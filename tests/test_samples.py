import unittest

from scripts.samples import list_samples, load_sample

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

    def test_unknown_name_raises(self):
        with self.assertRaises(KeyError):
            load_sample("slack")
