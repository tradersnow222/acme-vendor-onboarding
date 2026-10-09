import copy
import json
import re
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.samples import load_sample

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / ".cursor" / "skills" / "validate-intake" / "SKILL.md"
PATH_PATTERN = re.compile(r"(?:\.cursor|scripts|data|templates|config|tests)/[\w./-]*\w/?")


def skill_commands(text):
    blocks = re.findall(r"```\n(.*?)```", text, re.S)
    return [line for block in blocks for line in block.splitlines() if line.startswith("python3 ")]


def run_command(command, placeholders):
    args = [placeholders.get(arg, arg) for arg in shlex.split(command)]
    key = args[2] if args[1] == "-m" else args[1]
    return key, subprocess.run(args, cwd=REPO, capture_output=True, text=True)


class ValidateIntakeSkillTest(unittest.TestCase):
    def setUp(self):
        self.text = SKILL.read_text()

    def test_frontmatter_and_length(self):
        frontmatter = self.text.split("---\n")[1]
        self.assertIn("name: validate-intake\n", frontmatter)
        self.assertRegex(frontmatter, r"description: Check .+ Use when .+")
        self.assertLess(len(self.text.splitlines()), 40)

    def test_named_paths_exist(self):
        paths = set(PATH_PATTERN.findall(self.text))
        self.assertTrue({"scripts/intake_check.py", "scripts/followup.py"} <= paths)
        for path in paths:
            self.assertTrue((REPO / path).exists(), path)

    def test_commands_run_on_asana_sample(self):
        fields = copy.deepcopy(load_sample("asana")["expected"]["intake"]["fields"])
        fields["business_owner"]["value"] = None
        with tempfile.TemporaryDirectory() as tmp:
            fields_file = Path(tmp) / "fields.json"
            fields_file.write_text(json.dumps(fields))
            placeholders = {
                "<sample>": "asana",
                "<YYYY-MM-DD>": "2026-10-09",
                "<rounds_done>": "0",
                "<fields.json>": str(fields_file),
            }
            outputs = {}
            for command in skill_commands(self.text):
                key, result = run_command(command, placeholders)
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs[key] = result.stdout

        self.assertEqual(set(outputs), {"scripts.intake_check", "scripts.followup", "-c"})
        self.assertEqual(
            outputs["scripts.intake_check"],
            "VR-0003: intake complete\n  ask for: none\n  confirm: none\n  fill from research: none\n",
        )
        self.assertEqual(outputs["scripts.followup"], "VR-0003: follow-up questions: none\n")
        live = json.loads(outputs["-c"])
        self.assertEqual(live["ask_for"], ["business_owner"])
        self.assertEqual(live["complete"], False)
        self.assertEqual(live["questions"], [{
            "field": "business_owner",
            "kind": "ask",
            "question": "Who is the business owner? Please give a named person, not a team.",
        }])


if __name__ == "__main__":
    unittest.main()
