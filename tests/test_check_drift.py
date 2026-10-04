import contextlib
import io
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
import unittest.mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import check_drift  # noqa: E402

THS_FILES = {
    "README.md": "| `ths start --port-offset 10` | Start shifted |\n| `ths endpoints --json` | Print |\n",
    "crates/ths-cli/src/main.rs": textwrap.dedent("""\
        enum Command {
            Start { no_open: bool, port_offset: u16 },
            Endpoints,
        }
        struct Cli { name: String, json: bool }
        """),
    "crates/ths-cli/src/runtime.rs": textwrap.dedent("""\
        const ZAKURA_IMAGE: &str = "zakuracore/zakura:1.6.0";
        fn delete_instance_resources(&self) { docker(["rm", "-f", &target]); }
        fn write_metadata() { fs::write("instance.json", data); }
        """),
    "crates/ths-server/src/api.rs": textwrap.dedent("""\
        pub async fn accounts() {}
        fn router() { route("/accounts", get(accounts)); }
        """),
    "crates/ths-server/src/wallet/recovery.rs": "pub fn commit_treasury_discovery() {}\n",
    "web/src/App.tsx": "const routes = ['/explorer/tx'];\nexport function useAccounts() {}\n",
}

SKILL = textwrap.dedent("""\
    ---
    name: ths-demo
    description: Use when testing drift.
    ---

    Read `crates/ths-cli/src/runtime.rs` and `wallet/recovery.rs::commit_treasury_discovery`.
    Run `ths start --port-offset 10` or `ths endpoints --json`; open `/explorer/tx/:txid`.
    Query `/api/v1/accounts` through `useAccounts()`; metadata lives in `instance.json`.
    Cleanup goes through `delete_instance_resources` and pulls `zakuracore/zakura:1.6.0`.
    Plain words such as `orchard` or `linux/amd64` are not references.
    """)

CONFIG = textwrap.dedent("""\
    ref_scope = ["skills/ths-*/**"]
    ignore_refs = ["linux/amd64"]

    [[anchor]]
    id = "gap"
    claim = "Cleanup deletes by name."
    skills = [{ file = "skills/ths-demo/SKILL.md", text = "Cleanup goes through `delete_instance_resources`" }]
    evidence = [
      { file = "crates/ths-cli/src/runtime.rs", contains = 'docker(["rm", "-f", &target])' },
      { file = "crates/ths-cli/src/runtime.rs", absent = "owned_resource" },
      { file = "crates/ths-cli/src/runtime.rs", regex = 'fn delete_instance_resources\\(' },
    ]

    [[value]]
    id = "image"
    claim = "Pinned image."
    source = { file = "crates/ths-cli/src/runtime.rs", regex = 'const ZAKURA_IMAGE: &str = "([^"]+)";' }
    pattern = 'zakuracore/zakura:[0-9][0-9A-Za-z._-]*'
    """)


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class DriftFixture(unittest.TestCase):
    def setUp(self):
        self.skills = tempfile.mkdtemp()
        self.ths = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.skills)
        self.addCleanup(shutil.rmtree, self.ths)
        for rel, text in THS_FILES.items():
            write(self.ths, rel, text)
        write(self.skills, "skills/ths-demo/SKILL.md", SKILL)
        self.config = os.path.join(self.skills, "anchors.toml")
        write(self.skills, "anchors.toml", CONFIG)

    def run_drift(self):
        return check_drift.run(self.ths, self.config, root=self.skills)

    def edit_ths(self, rel, old, new):
        path = os.path.join(self.ths, rel)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(old, text)
        write(self.ths, rel, text.replace(old, new))


class ClassifyTest(unittest.TestCase):
    def test_token_kinds(self):
        cases = {
            "crates/ths-cli/src/main.rs": ("path", "crates/ths-cli/src/main.rs"),
            "web/src/hooks/": ("path", "web/src/hooks"),
            "useServerEvents.ts": ("file", "useServerEvents.ts"),
            "reconcile.rs::within_deadline": ("qualified", "reconcile.rs::within_deadline"),
            "wallet/recovery.rs::commit_treasury_discovery": ("qualified", "wallet/recovery.rs::commit_treasury_discovery"),
            "Runtime::status": ("qualified", "Runtime::status"),
            "TREASURY_ACCOUNT_ID": ("ident", "TREASURY_ACCOUNT_ID"),
            "useAccounts()": ("ident", "useAccounts"),
            "chainValueZat": ("ident", "chainValueZat"),
            "/api/v1/accounts": ("route", "/api/v1/accounts"),
            "--port-offset": ("flag", "--port-offset"),
            "zakuracore/zakura:1.6.0": None,
            "ghcr.io/zcashlabs/thus-spoke-zakura-app:0.3.0": None,
            "ths --name alpha start": ("command", "ths --name alpha start"),
        }
        for token, expected in cases.items():
            with self.subTest(token=token):
                self.assertEqual(check_drift.classify(token), expected)

    def test_prose_and_placeholders_are_skipped(self):
        for token in ["orchard", "Ironwood", "ths-<name>-app", "['activity', limit]", "https://zips.z.cash", "a b"]:
            with self.subTest(token=token):
                self.assertIsNone(check_drift.classify(token))


class ReferencesTest(DriftFixture):
    def test_all_references_resolve(self):
        refs, (checked, unique), anchors, _ = self.run_drift()
        self.assertEqual(refs, [])
        self.assertEqual(unique, 9)  # path, qualified, 2 commands, 2 routes, 2 idents, runtime file
        self.assertTrue(all(not a["broken"] and not a["stale_skill"] for a in anchors))

    def test_renamed_crate_is_reported(self):
        os.rename(os.path.join(self.ths, "crates/ths-cli"), os.path.join(self.ths, "crates/tsz-cli"))
        refs, _, _, _ = self.run_drift()
        self.assertIn(("crates/ths-cli/src/runtime.rs", "path not found"), [(r["token"], r["reason"]) for r in refs])

    def test_removed_symbol_flag_and_route_are_reported(self):
        self.edit_ths("crates/ths-server/src/wallet/recovery.rs", "commit_treasury_discovery", "commit_discovery")
        self.edit_ths("crates/ths-cli/src/main.rs", "port_offset", "offset")
        self.edit_ths("README.md", "--port-offset 10", "--offset 10")
        self.edit_ths("crates/ths-server/src/api.rs", '"/accounts"', '"/wallets"')
        reasons = {r["token"]: r["reason"] for r in self.run_drift()[0]}
        self.assertIn("not found in wallet/recovery.rs", reasons["wallet/recovery.rs::commit_treasury_discovery"])
        self.assertIn("flag not defined", reasons["ths start --port-offset 10"])
        self.assertIn("route not found", reasons["/api/v1/accounts"])

    def test_renamed_subcommand_after_global_flag_is_reported(self):
        write(self.skills, "skills/ths-demo/SKILL.md", SKILL + "Run `ths --name alpha start` or `ths --name alpha up`.\n")
        reasons = {r["token"]: r["reason"] for r in self.run_drift()[0]}
        self.assertNotIn("ths --name alpha start", reasons)
        self.assertEqual(reasons["ths --name alpha up"], "no ths subcommand among `alpha`, `up`")

    def test_runtime_file_must_be_named_in_source(self):
        self.edit_ths("crates/ths-cli/src/runtime.rs", '"instance.json"', '"state.json"')
        self.assertIn("instance.json", [r["token"] for r in self.run_drift()[0]])


class AnchorsTest(DriftFixture):
    def anchor(self, anchor_id):
        return next(a for a in self.run_drift()[2] if a["id"] == anchor_id)

    def test_passing_anchor_lists_where_the_claim_appears(self):
        gap = self.anchor("gap")
        self.assertEqual(gap["broken"], [])
        self.assertEqual(gap["passages"], ["skills/ths-demo/SKILL.md:9"])

    def test_changed_evidence_fails_the_anchor(self):
        self.edit_ths("crates/ths-cli/src/runtime.rs", 'docker(["rm", "-f", &target]);', "owned_resource(&target)?;")
        broken = " ".join(self.anchor("gap")["broken"])
        self.assertIn("no longer contains", broken)
        self.assertIn("now contains `owned_resource`", broken)

    def test_whitespace_changes_do_not_fail_contains(self):
        self.edit_ths("crates/ths-cli/src/runtime.rs", 'docker(["rm", "-f", &target]);', 'docker(["rm",\n    "-f", &target]);')
        self.assertEqual(self.anchor("gap")["broken"], [])

    def test_edited_skill_text_fails_the_anchor(self):
        write(self.skills, "skills/ths-demo/SKILL.md", SKILL.replace("Cleanup goes through", "Cleanup uses"))
        self.assertEqual(len(self.anchor("gap")["stale_skill"]), 1)

    def test_bumped_image_reports_every_stale_mention(self):
        self.edit_ths("crates/ths-cli/src/runtime.rs", "zakura:1.6.0", "zakura:1.7.0")
        image = self.anchor("image")
        self.assertEqual(image["broken"], ["skills/ths-demo/SKILL.md:9 says `zakuracore/zakura:1.6.0`, THS pins `zakuracore/zakura:1.7.0`"])

    def test_missing_evidence_file(self):
        os.remove(os.path.join(self.ths, "crates/ths-cli/src/runtime.rs"))
        self.assertIn("crates/ths-cli/src/runtime.rs no longer exists", self.anchor("gap")["broken"])


class CliTest(DriftFixture):
    def main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out), unittest.mock.patch.object(check_drift, "ROOT", self.skills):
            code = check_drift.main(["--ths", self.ths, "--config", self.config, *args])
        return code, out.getvalue()

    def test_exit_codes_and_reports(self):
        code, text = self.main()
        self.assertEqual(code, 0, text)
        self.assertIn("0 drifted", text)

        self.edit_ths("crates/ths-cli/src/runtime.rs", "zakura:1.6.0", "zakura:1.7.0")
        code, text = self.main("--markdown")
        self.assertEqual(code, 1)
        self.assertIn("drift found", text)
        self.assertIn("#### `image`", text)

    def test_config_errors_exit_2(self):
        out = io.StringIO()
        with contextlib.redirect_stderr(out):
            self.assertEqual(check_drift.main(["--ths", self.skills, "--config", self.config]), 2)
        self.assertIn("does not look like a thus-spoke-zakura checkout", out.getvalue())
        write(self.skills, "anchors.toml", "[[anchor]]\nid = 'x'\n")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(check_drift.main(["--ths", self.ths, "--config", self.config]), 2)


class ShippedConfigTest(unittest.TestCase):
    def test_anchor_skill_passages_exist(self):
        """Every anchored passage in scripts/ths-anchors.toml is present in this repository."""
        with open(check_drift.DEFAULT_CONFIG, "rb") as fh:
            config = check_drift.tomllib.load(fh)
        for anchor in config["anchor"]:
            for spot in anchor["skills"]:
                with self.subTest(anchor=anchor["id"], file=spot["file"]):
                    self.assertIsNotNone(check_drift.find_text(ROOT, spot["file"], spot["text"]))

    @unittest.skipUnless(os.environ.get("THS_PATH"), "set THS_PATH to a thus-spoke-zakura checkout")
    def test_against_real_ths(self):
        refs, _, anchors, revision = check_drift.run(os.environ["THS_PATH"])
        drifted = [a["id"] for a in anchors if a["broken"] or a["stale_skill"]]
        self.assertEqual((refs, drifted), ([], []), f"drift at THS {revision}")


if __name__ == "__main__":
    unittest.main()
