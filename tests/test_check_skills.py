import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import check_skills  # noqa: E402

GOOD_SKILL = """\
---
name: demo
description: Use when testing the checker.
---

# Demo

See [the reference](references/ref.md) and [the router](../other/SKILL.md).
"""


FACTS = """\
# Versioned facts

```facts
id: demo-image
value: example/node:1.2.0
pattern: example/node:[0-9.]+
verified: 2999-01-01
```
"""


class Fixture:
    """A throwaway skills repository with working docs/gen-manifest.py and docs/check-facts.py."""

    def __init__(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "docs"))
        for script in ("gen-manifest.py", "check-facts.py"):
            shutil.copy(os.path.join(ROOT, "docs", script), os.path.join(self.root, "docs"))
        self.write("index.html", "<script>const FILES = /*MANIFEST*/[]/*END*/;</script>")
        self.write("docs/versioned-facts.md", FACTS)
        self.write("skills/demo/SKILL.md", GOOD_SKILL)
        self.write("skills/demo/references/ref.md", "# Ref\n")
        self.write("skills/other/SKILL.md", GOOD_SKILL.replace("name: demo", "name: other").replace("references/ref.md", "../demo/references/ref.md"))
        self.regenerate()

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(text))

    def regenerate(self):
        subprocess.run([sys.executable, "docs/gen-manifest.py"], cwd=self.root, check=True, capture_output=True)

    def problems(self):
        _, results = check_skills.run(self.root)
        return {name: [str(p) for p in found] for name, found in results}

    def cleanup(self):
        shutil.rmtree(self.root)


class CheckSkillsTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.cleanup)

    def test_valid_repository_passes(self):
        self.assertEqual(self.fx.problems(), {"frontmatter": [], "links": [], "secrets": [], "manifest": [], "facts": []})

    def test_frontmatter_name_must_match_directory(self):
        self.fx.write("skills/demo/SKILL.md", GOOD_SKILL.replace("name: demo", "name: demo-skill"))
        self.assertIn("does not match directory `demo`", " ".join(self.fx.problems()["frontmatter"]))

    def test_frontmatter_rejects_extra_fields_and_empty_description(self):
        text = GOOD_SKILL.replace("description: Use when testing the checker.", "description:\nversion: 2")
        self.fx.write("skills/demo/SKILL.md", text)
        found = " ".join(self.fx.problems()["frontmatter"])
        self.assertIn("unexpected frontmatter field `version`", found)
        self.assertIn("missing or empty `description`", found)

    def test_frontmatter_rejects_block_scalars_and_missing_fence(self):
        self.fx.write("skills/demo/SKILL.md", GOOD_SKILL.replace("description: Use when testing the checker.", "description: >"))
        self.assertIn("block scalar", " ".join(self.fx.problems()["frontmatter"]))
        self.fx.write("skills/demo/SKILL.md", "# no frontmatter\n")
        self.assertIn("must start on line 1", " ".join(self.fx.problems()["frontmatter"]))

    def test_directory_without_skill_file(self):
        os.makedirs(os.path.join(self.fx.root, "skills", "empty"))
        self.assertIn("skills/empty/SKILL.md: missing SKILL.md", self.fx.problems()["frontmatter"])

    def test_broken_relative_link_reports_file_and_line(self):
        self.fx.write("skills/demo/SKILL.md", GOOD_SKILL.replace("references/ref.md", "references/gone.md"))
        self.assertEqual(self.fx.problems()["links"], ["skills/demo/SKILL.md:8: broken link: references/gone.md"])

    def test_links_ignore_external_anchors_code_and_fences(self):
        body = GOOD_SKILL + textwrap.dedent("""\
            [site](https://zips.z.cash/) [top](#demo) [ref section](references/ref.md#ref)
            Inline example: `[label](references/x.md)`
            ```
            [fenced](does/not/exist.md)
            ```
            """)
        self.fx.write("skills/demo/SKILL.md", body)
        self.assertEqual(self.fx.problems()["links"], [])

    def test_mainnet_address_is_flagged_but_testnet_is_not(self):
        self.fx.write("skills/demo/references/ref.md", "Pay tmEZhbWHTpdKMw5it8YDspUXSMGQyFwovpU on testnet.\n")
        self.assertEqual(self.fx.problems()["secrets"], [])
        self.fx.write("skills/demo/references/ref.md", "Pay t1Hsc1LR8yKnbbe3twRp88p6vFfC5t7DLbs on mainnet.\n")
        self.assertIn("mainnet transparent address", " ".join(self.fx.problems()["secrets"]))

    def test_zip_test_vectors_are_allowed(self):
        line = "Round-trip fixture from ZIP 320: `t1VmmGiyjVNeCjxDZzg7vZmd99WyzVby9yC` <-> `tex1s2rt77ggv6q989lr49rkgzmh5slsksa9khdgte`.\n"
        self.fx.write("skills/demo/references/ref.md", line)
        self.assertEqual(self.fx.problems()["secrets"], [])

    def test_credentials_are_flagged(self):
        self.fx.write("skills/demo/references/ref.md", "token ghp_" + "a" * 36 + "\n")
        self.assertIn("GitHub token", " ".join(self.fx.problems()["secrets"]))

    def test_stale_manifest_is_reported(self):
        self.fx.write("skills/demo/references/new.md", "# New\n")
        found = " ".join(self.fx.problems()["manifest"])
        self.assertIn("missing from manifest: skills/demo/references/new.md", found)
        self.fx.regenerate()
        self.assertEqual(self.fx.problems()["manifest"], [])

    def test_contradicted_fact_reports_file_and_line(self):
        self.fx.write("skills/demo/references/ref.md", "# Ref\n\nRun example/node:1.2.0 locally.\n")
        self.assertEqual(self.fx.problems()["facts"], [])
        self.fx.write("skills/demo/references/ref.md", "# Ref\n\nRun example/node:1.1.9 locally.\n")
        self.assertEqual(
            self.fx.problems()["facts"],
            ["skills/demo/references/ref.md:3: 'example/node:1.1.9' conflicts with demo-image = 'example/node:1.2.0'"],
        )


class RepositoryTest(unittest.TestCase):
    def test_this_repository_passes(self):
        _, results = check_skills.run(ROOT)
        self.assertEqual({name: [str(p) for p in found] for name, found in results if found}, {})


if __name__ == "__main__":
    unittest.main()
