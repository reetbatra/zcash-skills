"""Tests for docs/check-facts.py and docs/verify-claims.py. No network.

    python3 -m unittest discover -s tests
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "docs", filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vc = load("verify_claims", "verify-claims.py")
cf = vc.check_facts  # one copy, so both modules share UpstreamError

FACTS = [
    {"id": "zakura-image", "value": "zakuracore/zakura:1.6.0", "pattern": r"zakuracore/zakura:[0-9a-zA-Z.\-]+",
     "upstream": "https://raw.githubusercontent.com/o/r/main/runtime.rs", "extract": r'const ZAKURA_IMAGE: &str = "([^"]+)"'},
    {"id": "faucet", "kind": "forbid", "pattern": r"faucet has no idempotency", "source": "api.rs"},
]
RUNTIME_RS = 'const ZAKURA_IMAGE: &str = "zakuracore/zakura:1.6.0";\n'
ZIP_259 = "CONSENSUS_BRANCH_ID\n: `0x77190AD9`\n\nACTIVATION_HEIGHT (NU7)\n: Testnet: 4465026\n: Mainnet: TBD\n"
REPO = {"crates/ths-server/src/db.rs": "fn claim_address_faucet() {}\n", "Cargo.toml": '[workspace.package]\nversion = "0.3.0"\n'}


def fake_fetch(pages):
    def fetch(url, headers=None):
        if pages.get(url) is None:
            raise cf.UpstreamError(f"{url}: HTTP Error 404: Not Found")
        return pages[url]
    return fetch


def fake_archive(url):
    if "thus-spoke-zakura" in url:
        return REPO
    raise cf.UpstreamError(f"{url}: unreachable")


def diff_for(path, *lines, start=10):
    added = "".join(f"+{line}\n" for line in lines)
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -{start},1 +{start},{len(lines) + 1} @@\n context\n{added}"


def run(lines, links=(), pages=None, path="skills/zakura/SKILL.md"):
    pages = {FACTS[0]["upstream"]: RUNTIME_RS, **(pages or {})}
    results, _, sources = vc.verify(vc.parse_diff(diff_for(path, *lines)), FACTS, list(links), fake_fetch(pages), fake_archive)
    return results, sources


class ParseTests(unittest.TestCase):
    def test_added_lines_get_new_file_line_numbers(self):
        claims = vc.parse_diff(diff_for("skills/zakura/SKILL.md", "first", "second", start=40))
        self.assertEqual(claims, [("skills/zakura/SKILL.md", 41, "first"), ("skills/zakura/SKILL.md", 42, "second")])

    def test_only_skill_files_are_in_scope(self):
        for path in ("README.md", "docs/check-facts.py", "index.html"):
            self.assertEqual(vc.parse_diff(diff_for(path, "x")), [])
        for path in ("SKILL.md", "skills/zcash/SKILL.md", "docs/versioned-facts.md"):
            self.assertEqual(len(vc.parse_diff(diff_for(path, "x"))), 1)

    def test_versioned_facts_only_counts_rows_and_values(self):
        self.assertTrue(vc.is_claim("docs/versioned-facts.md", "| Pinned node image | `zakuracore/zakura:1.6.0` |"))
        self.assertTrue(vc.is_claim("docs/versioned-facts.md", "value: 0x77190AD9"))
        self.assertFalse(vc.is_claim("docs/versioned-facts.md", "pattern: 0x77190AD9"))
        self.assertFalse(vc.is_claim("docs/versioned-facts.md", "A block may instead set `kind: forbid`"))

    def test_values_skip_dates_zip_numbers_links_and_placeholders(self):
        line = ("NU7 Testnet height 4,465,026 (2026-10-06), see ZIP 2003 and [ZIP 259](https://zips.z.cash/zip-0259); "
                "image `zakuracore/zakura:1.6.0`, `ths:send:{json}`, `zakura-*`, `regtest_network()`, v1.2.0, `0x77190AD9`")
        self.assertEqual(vc.values_in(line), ["zakuracore/zakura:1.6.0", "regtest_network", "0x77190AD9", "v1.2.0", "4,465,026"])

    def test_template_example_links_are_not_sources(self):
        body = "Fix.\n\nSource(s) of truth:\n<!-- e.g. https://zips.z.cash/zip-0259 -->\n- https://zips.z.cash/zip-0258.\n"
        self.assertEqual(vc.source_links(body), ["https://zips.z.cash/zip-0258"])


class VerdictTests(unittest.TestCase):
    def verdicts(self, results):
        return [r["verdict"] for r in results]

    def test_value_that_disagrees_with_a_fact_is_a_contradiction(self):
        results, _ = run(["THS pins `zakuracore/zakura:1.5.0`."])
        self.assertEqual(self.verdicts(results), ["❌"])
        self.assertIn("zakura-image", results[0]["evidence"])

    def test_fact_that_upstream_moved_past_is_a_contradiction(self):
        moved = {FACTS[0]["upstream"]: 'const ZAKURA_IMAGE: &str = "zakuracore/zakura:1.7.0";'}
        results, _ = run(["THS pins `zakuracore/zakura:1.6.0`."], pages=moved)
        self.assertEqual(self.verdicts(results), ["❌"])
        self.assertIn("now says `zakuracore/zakura:1.7.0`", results[0]["evidence"])

    def test_fact_confirmed_upstream_is_verified(self):
        results, _ = run(["THS pins `zakuracore/zakura:1.6.0`."])
        self.assertEqual(self.verdicts(results), ["✅"])

    def test_unreachable_upstream_never_fails(self):
        results, _ = run(["THS pins `zakuracore/zakura:1.6.0`."], pages={FACTS[0]["upstream"]: None})
        self.assertEqual(self.verdicts(results), ["⚠️"])  # not re-verified, so left for review
        self.assertIn("upstream unreachable", results[0]["evidence"])

    def test_forbidden_claim_is_a_contradiction(self):
        results, _ = run(["The address faucet has no idempotency key."])
        self.assertEqual(self.verdicts(results), ["❌"])

    def test_linked_source_verifies_its_values(self):
        url = "https://github.com/zcash/zips/blob/main/zips/zip-0259.md"
        raw = "https://raw.githubusercontent.com/zcash/zips/main/zips/zip-0259.md"
        results, _ = run(["NU7 uses branch ID `0x77190AD9`."], links=[url], pages={raw: ZIP_259})
        self.assertEqual(self.verdicts(results), ["✅"])
        self.assertIn("PR source", results[0]["evidence"])

    def test_cited_zip_is_fetched_with_rst_fallback(self):
        rst = "https://raw.githubusercontent.com/zcash/zips/main/zips/zip-0316.rst"
        results, sources = run(["ZIP 316 caps an encoding at 1024 bytes."], pages={rst: "... at most 1024 bytes ..."})
        self.assertEqual(self.verdicts(results), ["✅"])
        self.assertIn("zip-0316.rst", results[0]["evidence"])
        self.assertEqual(sources.failures, [])  # the .md miss is expected, not a failure

    def test_names_and_paths_are_found_in_upstream_source(self):
        results, _ = run(["`claim_address_faucet` lives in `crates/ths-server/src/db.rs`."])
        self.assertEqual(self.verdicts(results), ["✅"])
        self.assertIn("thus-spoke-zakura/crates/ths-server/src/db.rs", results[0]["evidence"])

    def test_unknown_name_is_left_for_review(self):
        results, _ = run(["Call `list_accounts_for_ui` first."])
        self.assertEqual(self.verdicts(results), ["⚠️"])
        self.assertIn("`list_accounts_for_ui` not found", results[0]["evidence"])

    def test_line_with_nothing_to_match_is_prose(self):
        results, _ = run(["Prefer evidence over memory."])
        self.assertTrue(results[0].get("prose"))

    def test_disallowed_host_is_listed_not_fetched(self):
        fetched = []

        def fetch(url, headers=None):
            fetched.append(url)
            return RUNTIME_RS
        _, provided, _ = vc.verify(vc.parse_diff(diff_for("SKILL.md", "x")), FACTS, ["https://example.com/post", "http://zips.z.cash/zip-0259"], fetch, fake_archive)
        self.assertEqual(fetched, [])
        self.assertEqual([p[1] for p in provided], [None, None])


class ReportTests(unittest.TestCase):
    def test_missing_sources_asks_the_author(self):
        results, sources = run(["Prefer evidence over memory."])
        report = vc.render(results, [], sources)
        self.assertTrue(report.startswith(vc.MARKER))
        self.assertIn("No sources in the PR description", report)

    def test_pipes_in_claims_do_not_break_the_table(self):
        self.assertEqual(vc.cell("a | b"), "a \\| b")


class CheckFactsTests(unittest.TestCase):
    def test_agrees_ignores_commas_backticks_and_case(self):
        self.assertTrue(cf.agrees({"value": "4,465,026"}, "4465026"))
        self.assertTrue(cf.agrees({"value": "Rust 1.98.0"}, "1.98.0"))
        self.assertTrue(cf.agrees({"value": "0x77190AD9"}, "0x77190ad9"))
        self.assertFalse(cf.agrees({"value": "4,465,026"}, "4465027"))

    def test_repo_oracles_extract_from_upstream_formats(self):
        facts = {f["id"]: f for f in cf.load_facts()}
        samples = {
            "nu7-testnet-height": (ZIP_259, "4465026"),
            "nu7-branch-id": (ZIP_259, "0x77190AD9"),
            "nu63-branch-id": ("CONSENSUS_BRANCH_ID\n: 0x37A5165B\n", "0x37A5165B"),
            "nu63-mainnet-height": ("ACTIVATION_HEIGHT (NU6.3)\n: Testnet: 4134000\n: Mainnet: 3428143\n", "3428143"),
            "ths-workspace-version": ('[workspace]\nresolver = "2"\n\n[workspace.package]\nversion = "0.3.0"\n', "0.3.0"),
            "ths-rust-toolchain": ('[toolchain]\nchannel = "1.98.0"\n', "1.98.0"),
            "zakura-image": (RUNTIME_RS, "zakuracore/zakura:1.6.0"),
        }
        for fid, (text, want) in samples.items():
            with self.subTest(fid):
                got = cf.upstream_value(facts[fid], fetch=lambda url, text=text: text)
                self.assertEqual(got, want)
                self.assertTrue(cf.agrees(facts[fid], got))

    def test_nu7_height_pattern_catches_comma_grouped_heights(self):
        import re
        fact = {f["id"]: f for f in cf.load_facts()}["nu7-testnet-height"]
        hit = re.search(fact["pattern"], "NU7 activated on Testnet at height 4,465,027.").group(0)
        self.assertNotIn(fact["value"], hit)

    def test_repo_is_clean_offline(self):
        out = subprocess.run([sys.executable, os.path.join(ROOT, "docs", "check-facts.py")], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout)


class CliTests(unittest.TestCase):
    def test_out_of_scope_diff_exits_zero(self):
        with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as fh:
            fh.write(diff_for("README.md", "anything"))
        try:
            out = subprocess.run([sys.executable, os.path.join(ROOT, "docs", "verify-claims.py"), "--diff", fh.name], capture_output=True, text=True)
        finally:
            os.unlink(fh.name)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("No added lines", out.stdout)


if __name__ == "__main__":
    unittest.main()
