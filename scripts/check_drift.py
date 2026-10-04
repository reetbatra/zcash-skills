#!/usr/bin/env python3
"""Check the ths-* skills against a Thus Spoke Zakura checkout.

    git clone https://github.com/zcashlabs/thus-spoke-zakura ../thus-spoke-zakura
    python3 scripts/check_drift.py --ths ../thus-spoke-zakura

Two layers, both configured in scripts/ths-anchors.toml:

references  Every backticked token in the ths-* skills that names something
            in THS (a path, file, symbol, `file.rs::fn`, CLI command or flag,
            or API route) must still exist there. This catches renames and
            removals, such as the `tsz-*` to `ths-*` crate rename.

anchors     Version-pinned claims (activation heights, the cleanup gap,
            account roles, the pinned node image, ...) are each tied to the
            THS source that makes them true. When that source changes, the
            claim is reported with every skill passage that states it.

Exits 0 when everything resolves, 1 on drift, 2 on a usage or config error.
`--markdown` prints a report suitable for a GitHub step summary or issue.
Standard library only; Python 3.11+ (tomllib).
"""
import argparse
import fnmatch
import os
import re
import subprocess
import sys
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(ROOT, "scripts", "ths-anchors.toml")

SOURCE_EXTENSIONS = (".rs", ".ts", ".tsx", ".js", ".toml", ".yml", ".yaml", ".sh", ".json", ".md", ".css", ".html")
FILE_EXTENSIONS = ("rs", "ts", "tsx", "js", "md", "yml", "yaml", "toml", "sh", "json", "lock", "css", "html")
SKIP_DIRS = {".git", "target", "node_modules", "dist"}

TOKEN_RE = re.compile(r"`([^`\n]+)`")
FILENAME_RE = re.compile(rf"^[A-Za-z0-9_.-]+\.(?:{'|'.join(FILE_EXTENSIONS)})$")
QUALIFIED_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_./-]*(?:::[A-Za-z_][A-Za-z0-9_]*)+(?:\(\))?$")
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\(\))?$")
FLAG_RE = re.compile(r"^--[a-z][a-z0-9-]*$")
IMAGE_RE = re.compile(r"^[a-z0-9.-]+(?:/[a-z0-9._-]+)+:[A-Za-z0-9._-]+$")


class ConfigError(Exception):
    pass


def norm(text):
    return " ".join(text.split())


class Repo:
    """Read-only view of a THS checkout with cached file contents."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self._cache = {}
        self.files = self._list_files()
        self.basenames = {os.path.basename(p) for p in self.files}
        self.dirs = {os.path.dirname(p) for p in self.files}
        for d in list(self.dirs):
            while d:
                d = os.path.dirname(d)
                self.dirs.add(d)
        self.source_files = [p for p in self.files if p.endswith(SOURCE_EXTENSIONS) or os.path.basename(p).startswith("Dockerfile")]

    def _list_files(self):
        try:
            out = subprocess.run(["git", "ls-files"], cwd=self.root, capture_output=True, text=True, check=True).stdout
            files = [p for p in out.splitlines() if p]
            if files:
                return files
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass
        found = []
        for d, dirs, names in os.walk(self.root):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            found += [os.path.relpath(os.path.join(d, n), self.root) for n in names]
        return sorted(found)

    def read(self, rel):
        if rel not in self._cache:
            path = os.path.join(self.root, rel)
            try:
                with open(path, encoding="utf-8") as fh:
                    self._cache[rel] = fh.read()
            except FileNotFoundError:
                self._cache[rel] = None
            except UnicodeDecodeError:
                self._cache[rel] = ""
        return self._cache[rel]

    def grep_word(self, word, files=None):
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(word)}(?![A-Za-z0-9_])")
        return any(pattern.search(self.read(f) or "") for f in (files or self.source_files))

    def grep_text(self, text, files=None):
        return any(text in (self.read(f) or "") for f in (files or self.source_files))


# ---------------------------------------------------------------- references

def classify(token):
    """Return (kind, value) for a backticked token, or None to skip it."""
    t = token.strip()
    if not t or "<" in t or "{" in t or "*" in t or t.startswith(("http://", "https://")):
        return None
    if t.startswith("ths ") or t == "ths":
        return ("command", t)
    if " " in t:
        return None
    if IMAGE_RE.match(t):
        return None  # container image tags are checked by [[value]] anchors
    if FLAG_RE.match(t):
        return ("flag", t)
    if t.startswith("/"):
        return ("route", t)
    if QUALIFIED_RE.match(t):
        return ("qualified", t.removesuffix("()"))
    if "/" in t:
        return ("path", t.rstrip("/"))
    if FILENAME_RE.match(t):
        return ("file", t)
    if IDENT_RE.match(t):
        name = t.removesuffix("()")
        # Only identifiers that look like code: snake_case, camelCase,
        # PascalCase with an inner capital, SCREAMING_CASE, or a call.
        if "_" in name.strip("_") or re.search(r"[a-z][A-Z]", name) or t.endswith("()"):
            return ("ident", name)
    return None


def resolve(kind, value, repo):
    """Return None when the reference resolves, else a reason string."""
    if kind == "path":
        if value in repo.files or value in repo.dirs:
            return None
        if any(f.endswith("/" + value) or f == value for f in repo.files) or any(d.endswith("/" + value) for d in repo.dirs):
            return None
        return "path not found"
    if kind == "file":
        # Tracked files, or files the code creates at runtime (named in a string).
        if value in repo.basenames or repo.grep_text(f'"{value}"'):
            return None
        return "file not found in the repository or named in its source"
    if kind == "qualified":
        head, _, tail = value.rpartition("::")
        file_head = head.split("::")[0]
        if FILENAME_RE.match(os.path.basename(file_head)):
            files = [f for f in repo.files if f == file_head or f.endswith("/" + file_head)]
            if not files:
                return f"file {file_head} not found"
            return None if repo.grep_word(tail, files) else f"`{tail}` not found in {file_head}"
        missing = [part for part in head.split("::") + [tail] if not repo.grep_word(part)]
        return None if not missing else f"`{'`, `'.join(missing)}` not found"
    if kind == "ident":
        return None if repo.grep_word(value) else "symbol not found"
    if kind == "route":
        static = re.split(r"/:", value, maxsplit=1)[0]
        candidates = {static}
        if static.startswith("/api/v1/"):
            candidates.add(static[len("/api/v1"):])
        code = [f for f in repo.source_files if f.startswith(("crates/", "web/src/"))]
        return None if any(repo.grep_text(c, code) for c in candidates) else "route not found in crates/ or web/src/"
    if kind == "flag":
        return resolve_flag(value, repo)
    if kind == "command":
        return resolve_command(value, repo)
    raise ValueError(kind)


def cli_sources(repo):
    return [f for f in repo.files if f.startswith("crates/ths-cli/src/") and f.endswith(".rs")]


def resolve_flag(flag, repo):
    field = flag[2:].replace("-", "_")
    if repo.grep_word(field, cli_sources(repo)) or repo.grep_text(f'long = "{flag[2:]}"', cli_sources(repo)):
        return None
    if repo.grep_text(flag, ["README.md", "docs/cli.md"]):
        return None
    return "flag not defined by the ths CLI"


def resolve_command(command, repo):
    sources = cli_sources(repo)
    candidates = []
    for word in command.split()[1:]:
        if word.startswith("--"):
            reason = resolve_flag(word.split("=", 1)[0], repo)
            if reason:
                return f"{word}: {reason}"
        elif re.match(r"^[a-z][a-z-]*$", word):
            candidates.append(word)
    # Bare words mix subcommands with positional values (`ths --name alpha
    # start`, `ths logs app`), so require at least one to be a subcommand.
    for word in candidates:
        variant = "".join(part.capitalize() for part in word.split("-"))
        if repo.grep_word(variant, sources):
            return None
    if candidates:
        return f"no ths subcommand among `{'`, `'.join(candidates)}`"
    return None


def skill_files(root, scope):
    out = []
    for d, dirs, names in os.walk(os.path.join(root, "skills")):
        for n in names:
            rel = os.path.relpath(os.path.join(d, n), root)
            if n.endswith(".md") and any(fnmatch.fnmatch(rel, pat) for pat in scope):
                out.append(rel)
    return sorted(out)


def check_references(root, repo, config):
    ignore = set(config.get("ignore_refs", []))
    problems, checked = [], 0
    seen = {}
    for rel in skill_files(root, config.get("ref_scope", [])):
        with open(os.path.join(root, rel), encoding="utf-8") as fh:
            for number, line in enumerate(fh, 1):
                for token in TOKEN_RE.findall(line):
                    if token in ignore:
                        continue
                    kind_value = classify(token)
                    if kind_value is None:
                        continue
                    if kind_value not in seen:
                        seen[kind_value] = resolve(*kind_value, repo)
                    checked += 1
                    if seen[kind_value]:
                        problems.append({"file": rel, "line": number, "token": token, "kind": kind_value[0], "reason": seen[kind_value]})
    return problems, checked, len(seen)


# ------------------------------------------------------------------- anchors

def find_text(root, rel, text):
    """Return the 1-based line where `text` starts (whitespace-insensitive), or None."""
    path = os.path.join(root, rel)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    needle = norm(text)
    flat, offsets = [], []
    for i, ch in enumerate(content):
        if ch.isspace():
            if flat and flat[-1] != " ":
                flat.append(" ")
                offsets.append(i)
        else:
            flat.append(ch)
            offsets.append(i)
    at = "".join(flat).find(needle)
    if at < 0:
        return None
    return content.count("\n", 0, offsets[at]) + 1


def evaluate_evidence(item, repo):
    rel = item.get("file")
    if not rel:
        raise ConfigError(f"evidence without `file`: {item}")
    kinds = [k for k in ("contains", "regex", "absent") if k in item]
    if len(kinds) != 1:
        raise ConfigError(f"evidence for {rel} needs exactly one of contains/regex/absent")
    kind = kinds[0]
    content = repo.read(rel)
    if content is None:
        return f"{rel} no longer exists"
    if kind == "contains":
        return None if norm(item["contains"]) in norm(content) else f"{rel} no longer contains `{item['contains']}`"
    if kind == "absent":
        return None if norm(item["absent"]) not in norm(content) else f"{rel} now contains `{item['absent']}`"
    try:
        found = re.search(item["regex"], content, re.M)
    except re.error as error:
        raise ConfigError(f"bad regex for {rel}: {error}") from error
    return None if found else f"{rel} no longer matches /{item['regex']}/"


def check_anchors(root, repo, config):
    results = []
    for anchor in config.get("anchor", []):
        for key in ("id", "claim", "skills", "evidence"):
            if key not in anchor:
                raise ConfigError(f"anchor {anchor.get('id', '?')} is missing `{key}`")
        passages, stale_skill = [], []
        for spot in anchor["skills"]:
            line = find_text(root, spot["file"], spot["text"])
            if line is None:
                stale_skill.append(spot)
            else:
                passages.append(f"{spot['file']}:{line}")
        broken = [r for r in (evaluate_evidence(e, repo) for e in anchor["evidence"]) if r]
        results.append({"id": anchor["id"], "claim": anchor["claim"], "passages": passages, "stale_skill": stale_skill, "broken": broken})

    for value in config.get("value", []):
        source = value["source"]
        content = repo.read(source["file"])
        current = None
        if content is not None:
            match = re.search(source["regex"], content, re.M)
            current = match.group(1) if match else None
        broken, passages = [], []
        if current is None:
            broken.append(f"{source['file']} no longer matches /{source['regex']}/")
        pattern = re.compile(value["pattern"])
        for rel in markdown_files(root):
            with open(os.path.join(root, rel), encoding="utf-8") as fh:
                for number, line in enumerate(fh, 1):
                    for found in pattern.findall(line):
                        passages.append(f"{rel}:{number}")
                        if current is not None and found != current:
                            broken.append(f"{rel}:{number} says `{found}`, THS pins `{current}`")
        results.append({"id": value["id"], "claim": f"{value['claim']} THS: `{current}`", "passages": passages, "stale_skill": [], "broken": broken})
    return results


def markdown_files(root):
    out = []
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        out += [os.path.relpath(os.path.join(d, n), root) for n in names if n.endswith(".md")]
    return sorted(out)


# ------------------------------------------------------------------- report

def ths_revision(path):
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=path, capture_output=True, text=True, check=True).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unknown"


def report_text(refs, ref_stats, anchors, revision):
    lines = [f"THS revision: {revision}"]
    checked, unique = ref_stats
    lines.append(f"references   {checked} checked ({unique} unique), {len(refs)} unresolved")
    for p in refs:
        lines.append(f"  {p['file']}:{p['line']}: `{p['token']}` ({p['kind']}): {p['reason']}")
    failed = [a for a in anchors if a["broken"] or a["stale_skill"]]
    lines.append(f"anchors      {len(anchors)} checked, {len(failed)} drifted")
    for a in failed:
        lines.append(f"  [{a['id']}] {a['claim']}")
        for b in a["broken"]:
            lines.append(f"    evidence changed: {b}")
        for s in a["stale_skill"]:
            lines.append(f"    skill text not found in {s['file']}: \"{s['text']}\" (update the anchor)")
        if a["passages"]:
            lines.append(f"    re-verify: {', '.join(a['passages'])}")
    return "\n".join(lines)


def report_markdown(refs, ref_stats, anchors, revision):
    checked, unique = ref_stats
    failed = [a for a in anchors if a["broken"] or a["stale_skill"]]
    ok = not refs and not failed
    out = [f"### Skill drift vs thus-spoke-zakura@`{revision}`: {'no drift' if ok else 'drift found'}", ""]
    out.append(f"- References: {checked} checked ({unique} unique), **{len(refs)} unresolved**")
    out.append(f"- Anchored claims: {len(anchors)} checked, **{len(failed)} drifted**")
    if refs:
        out += ["", "#### Unresolved references", "", "| Skill | Reference | Kind | Reason |", "| --- | --- | --- | --- |"]
        out += [f"| `{p['file']}:{p['line']}` | `{p['token']}` | {p['kind']} | {p['reason']} |" for p in refs]
    for a in failed:
        out += ["", f"#### `{a['id']}`", "", f"> {a['claim']}", ""]
        out += [f"- Evidence changed: {b}" for b in a["broken"]]
        out += [f"- Skill text not found in `{s['file']}`: \"{s['text']}\" (update the anchor)" for s in a["stale_skill"]]
        if a["passages"]:
            out.append("- Re-verify: " + ", ".join(f"`{p}`" for p in a["passages"]))
    if not ok:
        out += ["", "Fix every skill that states the old fact (see AGENTS.md), then update `scripts/ths-anchors.toml`."]
    return "\n".join(out)


def run(ths_path, config_path=DEFAULT_CONFIG, root=None):
    root = root or ROOT
    if not os.path.isdir(ths_path):
        raise ConfigError(f"THS checkout not found: {ths_path}")
    try:
        with open(config_path, "rb") as fh:
            config = tomllib.load(fh)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{config_path}: {error}") from error
    repo = Repo(ths_path)
    if "crates" not in repo.dirs:
        raise ConfigError(f"{ths_path} does not look like a thus-spoke-zakura checkout (no crates/)")
    refs, checked, unique = check_references(root, repo, config)
    anchors = check_anchors(root, repo, config)
    return refs, (checked, unique), anchors, ths_revision(ths_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ths", required=True, help="path to a thus-spoke-zakura checkout")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="anchor file (default: scripts/ths-anchors.toml)")
    parser.add_argument("--markdown", action="store_true", help="print a markdown report")
    args = parser.parse_args(argv)
    try:
        refs, stats, anchors, revision = run(args.ths, args.config)
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    render = report_markdown if args.markdown else report_text
    print(render(refs, stats, anchors, revision))
    drifted = refs or any(a["broken"] or a["stale_skill"] for a in anchors)
    return 1 if drifted else 0


if __name__ == "__main__":
    sys.exit(main())
