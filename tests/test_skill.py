"""The bundled skills follow the Agent Skills specification (https://agentskills.io/specification)."""
import re
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "skills"


def frontmatter(text: str) -> dict:
    """Minimal YAML subset: top-level `key: value` pairs and one nested mapping level."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise AssertionError("SKILL.md must start with YAML frontmatter")
    data, parent = {}, None
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        if line.startswith("  ") and parent:
            k, v = line.strip().split(":", 1)
            data[parent][k.strip()] = v.strip().strip('"')
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if v:
            data[k] = v.strip('"')
            parent = None
        else:
            data[k], parent = {}, k
    return data


class SkillSpecTests(unittest.TestCase):
    def test_every_skill_is_valid(self):
        skills = [p for p in SKILLS.iterdir() if p.is_dir()]
        self.assertTrue(skills)
        allowed = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
        for folder in skills:
            text = (folder / "SKILL.md").read_text(encoding="utf-8").replace("\r\n", "\n")
            fm = frontmatter(text)
            self.assertLessEqual(set(fm) - allowed, set(), folder.name)
            name = fm["name"]
            self.assertEqual(name, folder.name, "name must match the folder")
            self.assertRegex(name, r"^[a-z0-9]+(-[a-z0-9]+)*$")
            self.assertLessEqual(len(name), 64)
            self.assertTrue(0 < len(fm["description"]) <= 1024)
            self.assertLessEqual(len(fm.get("compatibility", "")), 500)
            self.assertTrue(all(isinstance(v, str) for v in fm.get("metadata", {}).values()))
            self.assertLess(len(text.splitlines()), 500, "keep SKILL.md under 500 lines")
            for link in re.findall(r"\]\(((?!https?:)[^)#]+)\)", text):   # relative links resolve, one level deep
                self.assertTrue((folder / link).is_file(), link)
                self.assertLessEqual(len(Path(link).parts), 2, link)


    def test_our_own_instructions_pass_lint(self):
        """Skills and templates stay small and calm: no shouting, within token budgets."""
        from orrin import lint
        files = list(SKILLS.glob("*/SKILL.md")) + list((SKILLS.parent / "orrin" / "templates").rglob("*.md"))
        problems = [w for f in files for w in lint.check_text(f.name, f.read_text(encoding="utf-8"))]
        self.assertEqual(problems, [])
        lane = (SKILLS / "orrin-lane" / "SKILL.md").read_text(encoding="utf-8")
        self.assertLess(lint.tokens(lane), 1100, "the lane skill is read by every worker; keep it near 1k tokens")

    def test_command_references_match(self):
        a = (SKILLS / "orrin" / "references" / "COMMANDS.md").read_text(encoding="utf-8")
        b = (SKILLS / "orrin-lane" / "references" / "COMMANDS.md").read_text(encoding="utf-8")
        self.assertEqual(a, b, "keep both skills' COMMANDS.md identical (copy orrin's)")

    def test_every_cli_command_is_documented(self):
        from orrin import cli
        text = (SKILLS / "orrin" / "references" / "COMMANDS.md").read_text(encoding="utf-8")
        parser = cli.build_parser()
        sub = next(a for a in parser._actions if a.dest == "cmd")
        for name, sp in sub.choices.items():
            self.assertIn(f"orrin {name}" if name not in ("data",) else "orrin data", text, name)
            for action in sp._actions:
                for nested_name in getattr(action, "choices", None) or {}:
                    if isinstance(action.choices, dict):
                        self.assertIn(nested_name, text, f"{name} {nested_name}")


if __name__ == "__main__":
    unittest.main()
