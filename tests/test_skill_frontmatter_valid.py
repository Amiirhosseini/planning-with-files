"""Guard: every SKILL.md frontmatter must be valid, loadable YAML.

Regression test for the v3.1.2 -> v3.1.3 break: an unquoted description that
contained ': ' (colon followed by space) turned the frontmatter into an invalid
YAML mapping ("mapping values are not allowed here"), which breaks skill loading
and the model-triggering description field. The version-parity check is a regex
and did not catch it, so this validates the frontmatter as actual YAML.

Discovery must include hidden adapter directories (`.agents/`, `.codex/`,
`.cursor/`, etc.). `glob.glob('**/SKILL.md')` skips those; `Path.rglob` does not.

clawhub-upload/SKILL.md is gitignored and may be absent on a fresh clone; rglob
simply does not find it then, which is fine.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_VALID_SKILL = """\
---
name: fixture-valid
description: "A temporary valid skill for discovery tests"
---

# Fixture
"""

_MALFORMED_SKILL = """\
---
name: fixture-bad
description: breaks: because unquoted colon-space
---

# Fixture
"""


def _skill_md_files(root=None):
    """Discover SKILL.md under root, including hidden directories."""
    root = Path(root) if root is not None else REPO_ROOT
    out = []
    for p in root.rglob("SKILL.md"):
        parts = p.parts
        if ".git" in parts or "node_modules" in parts:
            continue
        out.append(p)
    return out


def _frontmatter(text):
    if not text.startswith("---"):
        return None
    segments = text.split("---", 2)
    if len(segments) < 3:
        return None
    return segments[1]


def _description_line(frontmatter):
    for line in frontmatter.splitlines():
        if line.startswith("description:"):
            return line
    return None


def _tracked_skill_md_files():
    try:
        out = subprocess.check_output(
            ["git", "ls-files", "-z", "*SKILL.md"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    if not out:
        return []
    return [REPO_ROOT / p for p in out.decode("utf-8").split("\0") if p]


class SkillFrontmatterTests(unittest.TestCase):
    def test_files_found(self):
        self.assertTrue(_skill_md_files(), "no SKILL.md files discovered")

    def test_discovers_tracked_hidden_adapter_skills(self):
        discovered = {p.resolve() for p in _skill_md_files()}
        tracked = _tracked_skill_md_files()
        self.assertTrue(tracked, "git ls-files found no SKILL.md")
        missing = [p for p in tracked if p.resolve() not in discovered]
        self.assertEqual(
            missing,
            [],
            "tracked SKILL.md not discovered (hidden dirs?): "
            + ", ".join(str(p.relative_to(REPO_ROOT)) for p in missing),
        )

    def test_every_skill_has_frontmatter_and_description(self):
        for f in _skill_md_files():
            fm = _frontmatter(f.read_text(encoding="utf-8"))
            self.assertIsNotNone(fm, f"{f} has no '---' frontmatter block")
            self.assertIsNotNone(
                _description_line(fm), f"{f} frontmatter has no description:"
            )

    def test_unquoted_description_has_no_colon_space(self):
        # Dependency-free guard for the exact v3.1.2 break.
        for f in _skill_md_files():
            fm = _frontmatter(f.read_text(encoding="utf-8"))
            if fm is None:
                continue
            line = _description_line(fm)
            if line is None:
                continue
            value = line[len("description:"):].strip()
            if value[:1] in ('"', "'"):
                continue  # quoted scalars may safely contain colons
            self.assertNotIn(
                ": ",
                value,
                f"{f}: unquoted description contains ': ', which YAML parses as a "
                f"mapping and breaks frontmatter loading. Quote the value.",
            )

    def test_frontmatter_parses_as_yaml(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        for f in _skill_md_files():
            fm = _frontmatter(f.read_text(encoding="utf-8"))
            if fm is None:
                continue
            try:
                data = yaml.safe_load(fm)
            except Exception as exc:  # noqa: BLE001
                self.fail(f"{f}: frontmatter is not valid YAML: {exc}")
            self.assertIsInstance(data, dict, f"{f}: frontmatter is not a mapping")
            self.assertIsInstance(
                data.get("description"),
                str,
                f"{f}: description missing or not a string after YAML parse",
            )
            self.assertTrue(
                data["description"].strip(), f"{f}: description is empty"
            )

    def test_hidden_valid_skill_is_discovered(self):
        tmp = Path(tempfile.mkdtemp(prefix=".pwf_fm_", dir=REPO_ROOT))
        try:
            skill = tmp / "SKILL.md"
            skill.write_text(_VALID_SKILL, encoding="utf-8")
            discovered = {p.resolve() for p in _skill_md_files()}
            self.assertIn(
                skill.resolve(),
                discovered,
                "valid SKILL.md under a hidden directory was not discovered",
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_hidden_malformed_skill_fails_yaml(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        tmp = Path(tempfile.mkdtemp(prefix=".pwf_fm_", dir=REPO_ROOT))
        try:
            skill = tmp / "SKILL.md"
            skill.write_text(_MALFORMED_SKILL, encoding="utf-8")
            fm = _frontmatter(skill.read_text(encoding="utf-8"))
            self.assertIsNotNone(fm)
            with self.assertRaises(Exception):
                data = yaml.safe_load(fm)
                # Some YAML engines may load a broken mapping as a dict with
                # wrong shape; treat non-string description as failure too.
                if isinstance(data, dict) and isinstance(data.get("description"), str):
                    raise AssertionError("expected malformed frontmatter to fail")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
