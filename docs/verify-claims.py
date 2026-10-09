#!/usr/bin/env python3
"""Fact-check the lines a pull request adds to the skills.

    python3 docs/verify-claims.py --base origin/add-initial-skills
    python3 docs/verify-claims.py --diff pr.diff --body pr-body.md --report out.md

Every added line in `SKILL.md`, `skills/**/*.md` or `docs/versioned-facts.md`
is a claim. Its checkable values are numbers of four or more digits, versions,
hex IDs and backticked names. Each claim goes through three steps:

1. Facts. A line matching a fact's `pattern` in docs/versioned-facts.md must
   agree with the fact's `value` and, when the fact has an `upstream` oracle,
   with the value upstream states today. Disagreement is a contradiction (❌).
2. Sources the author linked in the PR description.
3. The canonical set: the ZIPs the line cites, then the source of
   zcashlabs/thus-spoke-zakura and zakura-core/zakura (one tarball each), where
   a backticked name must appear and a backticked path must exist.

A claim is verified (✅) when every checkable value in it was confirmed by a
fact oracle or appears in a fetched source. Otherwise it is unverified (⚠️)
and left to the reviewer. Every verdict is an exact string match; nothing here
guesses. Network failures only ever produce ⚠️.

Exit 1 only when there is a contradiction. Standard library only.
"""
import argparse
import importlib.util
import io
import os
import re
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_spec = importlib.util.spec_from_file_location("check_facts", os.path.join(ROOT, "docs", "check-facts.py"))
check_facts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_facts)
UpstreamError = check_facts.UpstreamError

MARKER = "<!-- zcash-skills-fact-check -->"
COMMENT_LIMIT = 60_000

# Hosts the checker will fetch from. Author-supplied links elsewhere are listed
# in the report but not fetched.
ALLOWED_HOSTS = {
    "raw.githubusercontent.com",
    "github.com",
    "zips.z.cash",
    "zcash.readthedocs.io",
    "z.cash",
}
CANONICAL_REPOS = [
    ("zcashlabs/thus-spoke-zakura", "main"),
    ("zakura-core/zakura", "main"),
]
ARCHIVE_MAX_BYTES = 50_000_000
SOURCE_FILE_MAX_BYTES = 1_000_000
TEXT_EXTENSIONS = (".rs", ".toml", ".md", ".ts", ".tsx", ".js", ".yml", ".yaml", ".sh", ".json", ".sql", ".proto")

BACKTICK_RE = re.compile(r"`([^`\n]+)`")
HEX_RE = re.compile(r"\b0x[0-9A-Fa-f]{6,}\b")
VERSION_RE = re.compile(r"(?<![\w.])v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?(?![\w])")
NUMBER_RE = re.compile(r"(?<![\w.,])(?:\d{1,3}(?:,\d{3})+|\d{4,})(?![\w]|[.,]\d)")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
ZIP_RE = re.compile(r"\bZIPs? ?-?(\d{1,4})\b|zip-(\d{4})", re.I)
LINK_TARGET_RE = re.compile(r"\]\([^)]*\)")
URL_RE = re.compile(r"https?://[^\s)>\]\"'`]+")
PATH_EXT_RE = re.compile(r"\.(?:rs|toml|md|ts|tsx|yml|yaml|sh|json)$")
PLACEHOLDER_CHARS = set("{}[]*…<>")


# ------------------------------------------------------------------- inputs

def in_scope(path):
    return path.endswith(".md") and (path == "SKILL.md" or path.startswith("skills/") or path == "docs/versioned-facts.md")


def parse_diff(diff):
    """Return [(path, line_no, text)] for lines the diff adds to in-scope files."""
    claims, path, line_no = [], None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            path = target[2:] if target.startswith("b/") else None
            continue
        if raw.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", raw)
            line_no = int(m.group(1)) if m else 0
            continue
        if path is None or raw.startswith(("--- ", "diff ", "index ")):
            continue
        if raw.startswith("+"):
            if in_scope(path):
                claims.append((path, line_no, raw[1:]))
            line_no += 1
        elif raw.startswith(" "):
            line_no += 1
    return claims


def is_claim(path, text):
    s = text.strip()
    if not s or s.startswith("```") or set(s) <= set("|-: "):
        return False
    if path == "docs/versioned-facts.md":
        # Fact table rows and fact values; the rest of the file explains the format.
        return s.startswith("|") or s.startswith("value:")
    return True


def is_path(value):
    return "/" in value or PATH_EXT_RE.search(value) is not None


def values_in(text):
    """The checkable values in a line, in order, without duplicates."""
    text = LINK_TARGET_RE.sub("]", text)  # link targets are not claims
    text = URL_RE.sub("", text)
    found = []
    for tok in BACKTICK_RE.findall(text):
        tok = tok.strip().removesuffix("()")
        if len(tok) > 2 and " " not in tok and "..." not in tok and not PLACEHOLDER_CHARS & set(tok):
            found.append(tok)
    plain = DATE_RE.sub("", ZIP_RE.sub("", BACKTICK_RE.sub(" ", text)))
    for rx in (HEX_RE, VERSION_RE, NUMBER_RE):
        found += rx.findall(plain)
    seen, out = set(), []
    for tok in found:
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def source_links(body):
    """URLs the author listed in the PR description."""
    body = re.sub(r"(?s)<!--.*?-->", "", body or "")  # the template's example links
    seen, out = set(), []
    for url in URL_RE.findall(body):
        url = url.rstrip(".,;:")
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


# ------------------------------------------------------------------ sources

def raw_url(url):
    """Map a page URL to something fetchable as text, or None if not allowed."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or host not in ALLOWED_HOSTS:
        return None
    if host == "github.com":
        m = re.match(r"^/([^/]+)/([^/]+)/blob/(.+)$", parsed.path)
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}" if m else None
    return url


def html_to_text(text):
    if "<html" not in text[:2000].lower():
        return text
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"&nbsp;|&#160;", " ", text)


def fetch_archive(url):
    """Fetch a .tar.gz and return {path: text} for its source files."""
    req = urllib.request.Request(url, headers={"User-Agent": "zcash-skills-fact-check"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read(ARCHIVE_MAX_BYTES)
        files = {}
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar:
                if not member.isfile() or member.size > SOURCE_FILE_MAX_BYTES or not member.name.endswith(TEXT_EXTENSIONS):
                    continue
                path = member.name.split("/", 1)[1]  # drop the "<repo>-<ref>/" prefix
                files[path] = tar.extractfile(member).read().decode("utf-8", "replace")
        return files
    except (OSError, tarfile.TarError, IndexError) as e:
        raise UpstreamError(f"{url}: {e}") from e


class Sources:
    """Fetches and caches source text; records failures instead of raising."""

    def __init__(self, fetch, fetch_archive=fetch_archive):
        self.fetch = fetch
        self.fetch_archive = fetch_archive
        self._cache = {}
        self._repos = {}
        self.failures = []

    def text(self, url, record=True):
        if url not in self._cache:
            try:
                self._cache[url] = html_to_text(self.fetch(url))
            except UpstreamError as e:
                self._cache[url] = None
                if record:
                    self.failures.append(str(e))
        return self._cache[url]

    def zip_text(self, num):
        """A ZIP's source from zcash/zips; newer ZIPs are .md, older ones .rst."""
        base = f"https://raw.githubusercontent.com/zcash/zips/main/zips/zip-{num:04d}"
        for ext in ("md", "rst"):
            body = self.text(f"{base}.{ext}", record=False)
            if body is not None:
                return f"zip-{num:04d}.{ext}", body
        self.failures.append(f"{base}.md / .rst: not found")
        return f"zip-{num:04d}", None

    def zips_for(self, line):
        nums = sorted({int(m.group(1) or m.group(2)) for m in ZIP_RE.finditer(line)})
        return [self.zip_text(n) for n in nums]

    def repo(self, name, ref):
        if name not in self._repos:
            url = f"https://codeload.github.com/{name}/tar.gz/{ref}"
            try:
                self._repos[name] = self.fetch_archive(url)
            except UpstreamError as e:
                self._repos[name] = None
                self.failures.append(str(e))
        return self._repos[name]

    def find_upstream(self, value):
        """Where the canonical repos confirm a backticked name or path, or None."""
        for name, ref in CANONICAL_REPOS:
            files = self.repo(name, ref) or {}
            short = name.split("/")[1]
            if is_path(value):
                if value.endswith("/"):  # a directory
                    hits = [p for p in files if p.startswith(value) or ("/" + value) in p]
                else:
                    hits = [p for p in files if p == value or p.endswith("/" + value)]
                if hits:
                    return f"{short}/{min(hits, key=len)}"
        for name, ref in CANONICAL_REPOS:  # a name, or a path the code builds at runtime
            for path, body in (self.repo(name, ref) or {}).items():
                if value in body:
                    return f"{name.split('/')[1]}/{path}"
        return None


def contains(text, value):
    if re.fullmatch(r"[\d,]+", value):
        return re.search(rf"(?<!\d){re.escape(value.replace(',', ''))}(?!\d)", text.replace(",", "")) is not None
    return value in text


# ------------------------------------------------------------------ verdicts

def fact_check(line, facts, sources, upstream_cache):
    """Check a line against versioned facts.

    Returns (contradictions, confirmed_values, notes)."""
    contradictions, confirmed, notes = [], set(), []
    for f in facts:
        if "pattern" not in f:
            continue
        for m in re.finditer(f["pattern"], line):
            hit = m.group(0)
            if f.get("kind") == "forbid":
                contradictions.append(f"`{hit}` is a stale claim ({f['id']}: {f.get('source', 'see versioned-facts.md')})")
                continue
            if f["value"] not in hit and hit not in f["value"]:
                contradictions.append(f"`{hit}` conflicts with {f['id']} = `{f['value']}` in versioned-facts.md")
                continue
            if "upstream" not in f:
                confirmed.add(hit)
                continue
            if f["id"] not in upstream_cache:
                try:
                    upstream_cache[f["id"]] = (check_facts.upstream_value(f, fetch=sources.fetch), None)
                except UpstreamError as e:
                    upstream_cache[f["id"]] = (None, str(e))
            current, err = upstream_cache[f["id"]]
            if err:
                notes.append(f"{f['id']}: upstream unreachable, not re-checked")
            elif check_facts.agrees(f, current):
                confirmed.add(hit)
            else:
                contradictions.append(f"`{hit}` matches versioned-facts.md, but {f['upstream']} now says `{current}` ({f['id']})")
    return contradictions, confirmed, notes


def verify(claims, facts, links, fetch, fetch_archive=fetch_archive):
    """Return the list of result dicts and the Sources used."""
    sources = Sources(fetch, fetch_archive)
    provided = []
    for url in links:
        fetchable = raw_url(url)
        provided.append((url, fetchable, sources.text(fetchable) if fetchable else None))
    upstream_cache, results = {}, []

    for path, line_no, text in claims:
        if not is_claim(path, text):
            continue
        values = values_in(text)
        res = {"where": f"{path}:{line_no}", "text": text.strip()}
        contradictions, confirmed, notes = fact_check(text, facts, sources, upstream_cache)
        if contradictions:
            res.update(verdict="❌", evidence="; ".join(contradictions))
            results.append(res)
            continue
        if not values:
            res.update(verdict="⚠️", evidence="no checkable value", prose=True)
            results.append(res)
            continue

        evidence, missing = [], []
        canonical = None
        backticked = set(values_in(" ".join(f"`{b}`" for b in BACKTICK_RE.findall(text))))
        for v in values:
            if any(v in c or c in v for c in confirmed):
                evidence.append(f"`{v}` fact oracle")
                continue
            hit = next((url for url, _, body in provided if body and contains(body, v)), None)
            if hit:
                evidence.append(f"`{v}` in [PR source]({hit})")
                continue
            if canonical is None:
                canonical = sources.zips_for(text)
            hit = next((name for name, body in canonical if body and contains(body, v)), None)
            if not hit and v in backticked:
                hit = sources.find_upstream(v)
            if hit:
                evidence.append(f"`{v}` in {hit}")
            else:
                missing.append(v)
        if missing:
            looked = [name for name, body in (canonical or []) if body]
            where = ", ".join((["the PR's sources"] if provided else []) + looked + ["THS/Zakura source"])
            res.update(verdict="⚠️", evidence=", ".join(f"`{v}`" for v in missing) + f" not found in {where}")
        else:
            res.update(verdict="✅", evidence=", ".join(evidence))
        if notes:
            res["evidence"] += " (" + "; ".join(notes) + ")"
        results.append(res)
    return results, provided, sources


# ------------------------------------------------------------------- report

def cell(text, limit=140):
    # Claim text comes from the PR: keep it from breaking the table or pinging people.
    text = text.replace("|", "\\|").replace("\n", " ").replace("@", "@\u200b")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render(results, provided, sources):
    bad = [r for r in results if r["verdict"] == "❌"]
    good = [r for r in results if r["verdict"] == "✅"]
    prose = [r for r in results if r.get("prose")]
    unverified = [r for r in results if r["verdict"] == "⚠️" and not r.get("prose")]

    out = [MARKER, f"### Fact check: {len(bad)} contradicted, {len(good)} verified, {len(unverified) + len(prose)} for review", ""]
    if not results:
        out.append("No added lines in `SKILL.md`, `skills/` or `docs/versioned-facts.md`.")
        return "\n".join(out) + "\n"
    if provided:
        listed = []
        for url, fetchable, body in provided:
            state = "fetched" if body is not None else ("not fetched: only GitHub file links and the Zcash docs/ZIP sites are read" if fetchable is None else "fetch failed")
            listed.append(f"[{cell(url, 80)}]({url}) ({state})")
        out.append("Sources from the PR description: " + ", ".join(listed) + ".")
    else:
        out.append(
            "**No sources in the PR description.** Under `Source(s) of truth:`, link the upstream files, "
            "ZIPs or docs pages that back these changes. This check runs again when you edit the description."
        )
    out.append("")
    rows = bad + unverified + good
    if rows:
        out += ["| | Line | Claim | Evidence |", "| --- | --- | --- | --- |"]
        out += [f"| {r['verdict']} | `{r['where']}` | {cell(r['text'])} | {cell(r['evidence'], 300)} |" for r in rows]
        out.append("")
    if prose:
        out.append(f"<details><summary>⚠️ {len(prose)} changed line(s) with no number, version or name to match; review by hand</summary>\n")
        out += [f"- `{r['where']}` {cell(r['text'], 160)}" for r in prose]
        out += ["", "</details>", ""]
    if sources.failures:
        out.append("<details><summary>Fetch failures (advisory, not a failed check)</summary>\n")
        out += [f"- {cell(f, 200)}" for f in sources.failures]
        out += ["", "</details>", ""]
    out.append(
        "_✅ and ❌ are exact matches against `docs/versioned-facts.md` and its upstream oracles, the PR's sources, "
        "the ZIPs a line cites, and THS/Zakura source. ⚠️ needs a human. Only ❌ fails the check._"
    )
    report = "\n".join(out) + "\n"
    if len(report) > COMMENT_LIMIT:
        report = report[:COMMENT_LIMIT] + "\n\n_Report truncated; the full report is in the job summary._\n"
    return report


def main():
    parser = argparse.ArgumentParser(description="Fact-check the lines a PR adds to the skills.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--diff", help="unified diff file (e.g. from `gh pr diff`)")
    src.add_argument("--base", help="git ref to diff HEAD against (three-dot)")
    parser.add_argument("--body", help="file holding the PR description")
    parser.add_argument("--facts", default=check_facts.FACTS, help="versioned-facts.md to use (default: this repo's)")
    parser.add_argument("--report", help="write the markdown report here as well as to stdout")
    args = parser.parse_args()

    if args.diff:
        diff = open(args.diff, encoding="utf-8").read()
    else:
        diff = subprocess.run(["git", "diff", f"{args.base}...HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    body = open(args.body, encoding="utf-8").read() if args.body else ""

    results, provided, sources = verify(parse_diff(diff), check_facts.load_facts(args.facts), source_links(body), check_facts.fetch)
    report = render(results, provided, sources)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write(report)
    print(report)
    return 1 if any(r["verdict"] == "❌" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
