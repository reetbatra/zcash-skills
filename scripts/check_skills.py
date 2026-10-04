#!/usr/bin/env python3
"""Run the pre-commit checks listed in AGENTS.md.

    python3 scripts/check_skills.py

Checks, in order:

1. frontmatter: every skills/*/SKILL.md has YAML frontmatter with exactly
   `name` (lowercase-hyphen, equal to the directory name) and a non-empty
   `description`;
2. links: every relative markdown link in a tracked .md file resolves to a
   file that exists;
3. secrets: no mainnet Zcash key or address material (ZIP test vectors in
   PUBLIC_VECTORS excepted) and no common credential formats;
4. manifest: index.html's embedded file list is current
   (delegates to `docs/gen-manifest.py --check`);
5. facts: versioned claims agree with docs/versioned-facts.md
   (delegates to `docs/check-facts.py`).

Exits 1 and prints one `path:line: message` per problem when any check fails.
Standard library only; Python 3.9+.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
FRONTMATTER_KEYS = {"name", "description"}

# [label](target) and ![alt](target); the target stops at whitespace or ')'.
LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "#")

# Mainnet strings published as test vectors in a ZIP. They are public
# documentation, so the secrets check skips them. Add one only with its source.
PUBLIC_VECTORS = {
    "t1VmmGiyjVNeCjxDZzg7vZmd99WyzVby9yC",  # ZIP 320 round-trip example
    "tex1s2rt77ggv6q989lr49rkgzmh5slsksa9khdgte",  # ZIP 320 round-trip example
}

BECH32 = "[02-9ac-hj-np-z]"
BASE58 = "[1-9A-HJ-NP-Za-km-z]"
SECRET_PATTERNS = [
    ("mainnet unified address", re.compile(rf"\bu1{BECH32}{{100,}}")),
    ("mainnet unified viewing key", re.compile(rf"\bu(?:view|ivk)1{BECH32}{{50,}}")),
    ("mainnet Sapling address", re.compile(rf"\bzs1{BECH32}{{70,}}")),
    ("mainnet Sapling viewing key", re.compile(rf"\bzxview(?:s|i)1{BECH32}{{50,}}")),
    ("mainnet spending key", re.compile(rf"\bsecret-extended-key-main1{BECH32}{{50,}}")),
    ("mainnet TEX address", re.compile(rf"\btex1{BECH32}{{38,}}")),
    ("mainnet transparent address", re.compile(rf"\bt[13]{BASE58}{{33}}\b")),
    ("extended private key", re.compile(rf"\b[xyz]prv{BASE58}{{100,}}")),
    ("PEM private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("API secret key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{32,}")),
]


class Problem:
    def __init__(self, path, line, message):
        self.path, self.line, self.message = path, line, message

    def __str__(self):
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}: {self.message}"


def tracked_markdown(root):
    """Return repository-relative .md paths, preferring git's tracked set."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.md"],
            cwd=root, capture_output=True, text=True, check=True,
        ).stdout
        return sorted(p for p in out.splitlines() if p)
    except (FileNotFoundError, subprocess.CalledProcessError):
        # Not a git checkout (for example, a test fixture directory).
        return sorted(
            os.path.relpath(os.path.join(d, n), root)
            for d, dirs, names in os.walk(root)
            if ".git" not in os.path.relpath(d, root).split(os.sep)
            for n in names
            if n.endswith(".md")
        )


def read(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as fh:
        return fh.read()


def check_frontmatter(root):
    problems = []
    skills_dir = os.path.join(root, "skills")
    if not os.path.isdir(skills_dir):
        return [Problem("skills/", 0, "directory not found")]
    for entry in sorted(os.listdir(skills_dir)):
        if not os.path.isdir(os.path.join(skills_dir, entry)):
            continue
        rel = f"skills/{entry}/SKILL.md"
        if not os.path.isfile(os.path.join(root, rel)):
            problems.append(Problem(rel, 0, "missing SKILL.md"))
            continue
        lines = read(root, rel).split("\n")
        if not lines or lines[0].strip() != "---":
            problems.append(Problem(rel, 1, "frontmatter must start on line 1 with '---'"))
            continue
        try:
            end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
        except StopIteration:
            problems.append(Problem(rel, 1, "frontmatter is not closed with '---'"))
            continue
        fields = {}
        for i in range(1, end):
            raw = lines[i]
            if not raw.strip():
                continue
            match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", raw)
            if match is None:
                problems.append(Problem(rel, i + 1, f"unsupported frontmatter line: {raw.strip()!r} (use single-line `key: value`)"))
                continue
            key, value = match.group(1), match.group(2).strip()
            if value in ("|", ">", "|-", ">-"):
                problems.append(Problem(rel, i + 1, f"`{key}` uses a block scalar; keep it on one line"))
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            if key in fields:
                problems.append(Problem(rel, i + 1, f"duplicate frontmatter key `{key}`"))
            fields[key] = (value, i + 1)
        for key in sorted(set(fields) - FRONTMATTER_KEYS):
            problems.append(Problem(rel, fields[key][1], f"unexpected frontmatter field `{key}` (only name and description are allowed)"))
        name = fields.get("name", ("", 0))[0]
        if "name" not in fields:
            problems.append(Problem(rel, 1, "missing `name`"))
        elif name != entry:
            problems.append(Problem(rel, fields["name"][1], f"name `{name}` does not match directory `{entry}`"))
        elif not NAME_RE.match(name):
            problems.append(Problem(rel, fields["name"][1], f"name `{name}` is not lowercase-hyphen"))
        if not fields.get("description", ("", 0))[0]:
            problems.append(Problem(rel, fields.get("description", ("", 1))[1], "missing or empty `description`"))
    return problems


def prose_lines(text):
    """Yield (line_number, line) outside fenced code blocks."""
    fenced = False
    for number, line in enumerate(text.split("\n"), 1):
        if FENCE_RE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            yield number, line


def check_links(root, md_files):
    problems = []
    for rel in md_files:
        base = os.path.dirname(os.path.join(root, rel))
        for number, line in prose_lines(read(root, rel)):
            stripped = re.sub(r"`[^`]*`", "", line)  # links inside inline code are examples
            for match in LINK_RE.finditer(stripped):
                target = match.group(1)
                if target.startswith(EXTERNAL_PREFIXES) or re.match(r"^[a-z][a-z0-9+.-]*:", target):
                    continue
                path = target.split("#", 1)[0]
                if not path:
                    continue
                if not os.path.exists(os.path.normpath(os.path.join(base, path))):
                    problems.append(Problem(rel, number, f"broken link: {target}"))
    return problems


def check_secrets(root, md_files):
    problems = []
    for rel in md_files:
        for number, line in enumerate(read(root, rel).split("\n"), 1):
            for vector in PUBLIC_VECTORS:
                line = line.replace(vector, " ")
            for label, pattern in SECRET_PATTERNS:
                match = pattern.search(line)
                if match:
                    problems.append(Problem(rel, number, f"possible {label}: {match.group(0)[:16]}…"))
    return problems


def check_manifest(root):
    script = os.path.join(root, "docs", "gen-manifest.py")
    if not os.path.isfile(script):
        return [Problem("docs/gen-manifest.py", 0, "not found")]
    result = subprocess.run([sys.executable, script, "--check"], cwd=root, capture_output=True, text=True)
    if result.returncode == 0:
        return []
    detail = (result.stdout + result.stderr).strip().replace("\n", "; ")
    return [Problem("index.html", 0, detail)]


def check_facts(root):
    script = os.path.join(root, "docs", "check-facts.py")
    if not os.path.isfile(script):
        return [Problem("docs/check-facts.py", 0, "not found")]
    result = subprocess.run([sys.executable, script], cwd=root, capture_output=True, text=True)
    if result.returncode == 0:
        return []
    stale = [line[len("STALE "):] for line in result.stdout.splitlines() if line.startswith("STALE ")]
    if not stale:
        return [Problem("docs/check-facts.py", 0, (result.stdout + result.stderr).strip().replace("\n", "; "))]
    problems = []
    for line in stale:
        path, number, message = line.split(":", 2)
        problems.append(Problem(path, int(number), message.strip()))
    return problems


def run(root):
    md_files = tracked_markdown(root)
    results = [
        ("frontmatter", check_frontmatter(root)),
        ("links", check_links(root, md_files)),
        ("secrets", check_secrets(root, md_files)),
        ("manifest", check_manifest(root)),
        ("facts", check_facts(root)),
    ]
    return md_files, results


def main():
    md_files, results = run(ROOT)
    failed = False
    for name, problems in results:
        status = "ok" if not problems else f"{len(problems)} problem(s)"
        print(f"{name:12} {status}")
        for problem in problems:
            print(f"  {problem}")
        failed |= bool(problems)
    print(f"checked {len(md_files)} markdown files")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
