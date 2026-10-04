#!/usr/bin/env python3
"""Regenerate the markdown-file manifest embedded in index.html.

Run from the repository root after adding or removing .md files:

    python3 docs/gen-manifest.py

With --check, report whether the embedded manifest is current without
rewriting index.html; exits 1 when it is stale. CI runs this mode.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "index.html")
MARKERS = re.compile(r"/\*MANIFEST\*/(.*?)/\*END\*/", re.S)

files = sorted(
    os.path.relpath(os.path.join(dirpath, name), ROOT)
    for dirpath, _, names in os.walk(ROOT)
    for name in names
    if name.endswith(".md") and ".git" not in os.path.relpath(dirpath, ROOT).split(os.sep)
)

html = open(INDEX).read()
match = MARKERS.search(html)
if match is None:
    raise SystemExit("manifest markers not found in index.html")

if "--check" in sys.argv[1:]:
    embedded = json.loads(match.group(1))
    if embedded == files:
        print(f"manifest current ({len(files)} files)")
        sys.exit(0)
    for path in sorted(set(files) - set(embedded)):
        print(f"missing from manifest: {path}")
    for path in sorted(set(embedded) - set(files)):
        print(f"listed but not on disk: {path}")
    raise SystemExit("manifest stale: run python3 docs/gen-manifest.py")

new = html[: match.start()] + "/*MANIFEST*/" + json.dumps(files) + "/*END*/" + html[match.end() :]
open(INDEX, "w").write(new)
print(f"{len(files)} files in manifest")
