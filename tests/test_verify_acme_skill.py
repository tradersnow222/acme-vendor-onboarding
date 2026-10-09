import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.samples import list_samples, load_sample

REPO = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO / ".cursor" / "skills" / "verify-acme"
SKILL = SKILL_DIR / "SKILL.md"
TICKETS_DIR = REPO / "tickets"
PATH_PATTERN = re.compile(r"(?:\.cursor|scripts|data|templates|config|tests)/[\w./-]*\w/?")
SECTIONS = ["Launch", "Doctor", "Drive", "Evidence", "Cleanup"]
FEATURE_H2S = ["Sub-features", "How to get to it (user POV)", "Driving it with make run", "Gotchas"]
STEP_LINE = re.compile(r"^[1-8]\. \[(script|model|person)\] ")


def end_state(text, label):
    return re.search(rf"^- {label}: (.+)$", text, re.M).group(1)


class VerifyAcmeSkillTest(unittest.TestCase):
    def setUp(self):
        self.text = SKILL.read_text()

    def test_frontmatter_and_length(self):
        frontmatter = self.text.split("---\n")[1]
        self.assertIn("name: verify-acme\n", frontmatter)
        self.assertRegex(frontmatter, r"description: Prove .+ end to end from the command line.+ Use after any change and before a demo\.")
        self.assertLess(len(self.text.splitlines()), 60)

    def test_named_paths_exist(self):
        paths = set(PATH_PATTERN.findall(self.text))
        self.assertIn(".cursor/skills/verify-acme/features/README.md", paths)
        self.assertIn("scripts/run.py", paths)
        for path in paths:
            self.assertTrue((REPO / path).exists(), path)

    def test_sections(self):
        headings = re.findall(r"^## (.+)$", self.text, re.M)
        self.assertEqual(headings, SECTIONS)

    def test_feature_files_match_samples(self):
        for name in list_samples():
            with self.subTest(sample=name):
                text = (SKILL_DIR / "features" / f"{name}.md").read_text()
                expected = load_sample(name)["expected"]
                self.assertEqual(re.findall(r"^## (.+)$", text, re.M), FEATURE_H2S)
                self.assertEqual(end_state(text, "Route"), ", ".join(expected["routing"]["route"]))
                self.assertEqual(end_state(text, "Decision"), expected["status"]["decision"])
                self.assertEqual(end_state(text, "Days open"), str(expected["status"]["days_open"]))

    def test_dry_run_for_each_sample(self):
        tickets_before = sorted(TICKETS_DIR.iterdir())
        env = {key: value for key, value in os.environ.items() if key != "CURSOR_API_KEY"}
        for name in list_samples():
            with self.subTest(sample=name), tempfile.TemporaryDirectory() as tmp:
                result = subprocess.run(
                    [sys.executable, "-m", "scripts.run", name],
                    cwd=REPO, capture_output=True, text=True, env={**env, "TMPDIR": tmp},
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                lines = result.stdout.splitlines()
                self.assertEqual(len(lines), 8)
                for number, line in enumerate(lines, start=1):
                    self.assertRegex(line, STEP_LINE)
                    self.assertTrue(line.startswith(f"{number}. "), line)
        self.assertEqual(sorted(TICKETS_DIR.iterdir()), tickets_before)


if __name__ == "__main__":
    unittest.main()
