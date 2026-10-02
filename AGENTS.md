# AGENTS.md

This repository is a library of agent skills for Zcash development: each skill
is a directory under `skills/` containing a `SKILL.md` plus optional
`references/*.md` (loaded on demand) and `scripts/*`.

## Skill format

- `SKILL.md` frontmatter: `name` (lowercase-hyphen, equals the directory name)
  and `description` (when-to-load triggers, not a summary of the body). No
  other fields.
- Bodies are direct instructions to the agent, concrete over abstract. Keep
  them short; push depth into `references/` one level deep and link with a
  relative path like `[payments](references/payments.md)`.
- Router skills (`zcash`, `ths`) route work to specialists with a link table;
  they deliberately do not duplicate specialist content.
- Skills describe *evidence-seeking behavior*: name the oracle (a test, a
  vector, a boundary check) a claim needs, rather than asserting facts that
  drift. Version-pinned facts (image tags, crate versions, file paths, test
  names) must be checked against the target repo at use time and updated here
  when they change.

## Editing rules

- Keep `skills/` self-contained: no toolchain config, no build output, no
  vendored upstream docs.
- When upstream facts change (e.g. THS renames a crate or bumps the pinned
  `zakuracore/zakura` image), update every skill that names the old fact —
  grep for the old string, don't patch only the file you noticed.
- `ths-*` skills describe the Thus Spoke Zakura repository; verify against its
  current `AGENTS.md` and source before asserting them, and keep statements
  marked as "current" honest or rephrase them as things to verify.
- Never include real key material, seeds, or mainnet addresses in examples.
  Use the documented Regtest fixtures (the public THS mnemonic, `uregtest1`
  addresses, ZIP 321 testnet examples) or published test vectors.

## Checks

There is no build. Before committing, verify:

- every `skills/*/SKILL.md` parses as YAML frontmatter with `name` matching the
  directory and `description` present;
- every relative `[label](../other/SKILL.md)` or `[label](references/x.md)`
  link resolves to a file that exists;
- no secrets or real address material beyond documented public fixtures;
- `docs/index.html`'s embedded manifest is current — run
  `python3 docs/gen-manifest.py` after adding/removing `.md` files.
