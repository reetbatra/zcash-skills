#!/usr/bin/env python3
"""Check that versioned facts stated in the skills match docs/versioned-facts.md.

Each ```facts block in versioned-facts.md declares a canonical `value` and a
`pattern` (regex). The checker scans every .md file in the repo for pattern
matches and reports matches that differ from the canonical value — the signal
that a skill went stale after an upstream bump (image tag, version, height).

It also warns when a fact's `verified` date is older than STALE_DAYS — a prompt
to re-verify, not a failure. Facts without a `pattern` are date-only.

Run from anywhere:  python3 docs/check-facts.py
Exit 0 = clean (or only stale-date warnings); exit 1 = contradictory values.
"""
import os
import re
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FACTS = os.path.join(ROOT, "docs", "versioned-facts.md")
STALE_DAYS = 90


def load_facts():
    text = open(FACTS).read()
    facts = []
    for block in re.findall(r"```facts\n(.*?)```", text, re.S):
        f = dict(re.findall(r"^(\w+):\s*(.+)$", block, re.M))
        if "id" in f:
            facts.append(f)
    return facts


def md_files():
    for dirpath, _, names in os.walk(ROOT):
        rel = os.path.relpath(dirpath, ROOT)
        if ".git" in rel.split(os.sep):
            continue
        for name in names:
            if name.endswith(".md"):
                yield os.path.join(dirpath, name)


def main():
    facts = load_facts()
    mismatches, warnings = [], []
    today = date.today()

    for f in facts:
        age = (today - date.fromisoformat(f["verified"])).days if "verified" in f else None
        if age is not None and age > STALE_DAYS:
            warnings.append(f"{f['id']}: verified {f.get('verified')} is {age}d old — re-check source")
        if "pattern" not in f:
            continue
        rx = re.compile(f["pattern"])
        for path in md_files():
            if os.path.abspath(path) == FACTS:
                continue
            for i, line in enumerate(open(path), 1):
                for m in rx.finditer(line):
                    if f["value"] not in m.group(0) and m.group(0) not in f["value"]:
                        rel = os.path.relpath(path, ROOT)
                        mismatches.append(
                            f"{rel}:{i}: '{m.group(0)}' conflicts with {f['id']} = '{f['value']}'"
                        )

    for w in warnings:
        print(f"WARN  {w}")
    for m in mismatches:
        print(f"STALE {m}")
    if mismatches:
        print(f"\n{len(mismatches)} possible stale reference(s); update the file or versioned-facts.md")
        return 1
    print(f"{len(facts)} facts checked, {len(warnings)} age warning(s), no contradictions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
