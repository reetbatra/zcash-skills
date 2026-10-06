# zcashskills

Agent skills for building on Zcash — the current stack, not your training data.

Zcash in 2026 is not the Zcash most models learned: `zcashd` is deprecated, ECC
is now ZODL, the Orchard pool was sealed at NU6.3 in favor of Ironwood, and the
dev stack is Zakura + lightwalletd/Zaino + the `librustzcash`/`zakura-*` crates.
Each skill is a `SKILL.md` an agent reads before working; specialists keep depth
in `references/`.

## Skills

| Skill | Scope |
| --- | --- |
| [zcash](skills/zcash/SKILL.md) | Routes Zcash work across wallet, payments, light-client sync, and protocol rules. Start here when the owning layer is unclear. |
| [zcash-wallet](skills/zcash-wallet/SKILL.md) | Accounts, seeds, keys, viewing authority, Unified Addresses, receiver selection, ZIP 321 payment requests. |
| [zcash-payments](skills/zcash-payments/SKILL.md) | Proposals, fees (ZIP 317), input selection, memos, expiry (ZIP 203), broadcast and confirmation. |
| [zcash-light-client](skills/zcash-light-client/SKILL.md) | Compact-block sync, birthdays, commitment trees, reorgs, service boundaries (lightwalletd/Zaino). |
| [zcash-protocol](skills/zcash-protocol/SKILL.md) | Consensus rules, network-upgrade activation, transaction encodings (v5/v6), proof verification, node validation. |
| [zakura](skills/zakura/SKILL.md) | The Zakura full node (`zakurad`): install, zcashd-compat mode, pruning/snapshots, Regtest, P2P v2. |
| [ths](skills/ths/SKILL.md) | Routes work in the [Thus Spoke Zakura](https://github.com/zcashlabs/thus-spoke-zakura) repo — a disposable Zcash Regtest stack. |
| [ths-runtime](skills/ths-runtime/SKILL.md) | `ths` CLI, named Docker instances, service startup/cleanup, images, installer, endpoints. |
| [ths-wallet-server](skills/ths-wallet-server/SKILL.md) | `ths-server` wallet sync, treasury, send/faucet, APIs, activity, persisted state. |
| [ths-dashboard](skills/ths-dashboard/SKILL.md) | React dashboard, API schemas, query hooks, mutations, SSE updates. |
| [ths-regtest-verifier](skills/ths-regtest-verifier/SKILL.md) | Live Docker validation: real proofs, mining, recovery, reward history. |
| [ths-release](skills/ths-release/SKILL.md) | Versioned launcher builds, installer/updater, image tags, release workflows. |

The `zcash-*` skills are implementation-independent — use them with whatever
node/library the project pins. The `ths-*` skills describe a specific repository;
always confirm behavior against its current `AGENTS.md` and source.

## Site

`index.html` renders the skill set as a single static page — serve the repo
root (`python3 -m http.server`) and open `/`, or publish it with GitHub Pages
("Deploy from a branch" → `/ (root)`). After adding or removing `.md` files,
regenerate its embedded file list with `python3 docs/gen-manifest.py`.

## Keeping skills current

The `ths-*` skills name real paths, symbols, commands, and behavior in a
repository that ships several changes a day. CI checks them so a rename or
a fixed bug shows up as a failing check, not as an agent following stale
instructions:

- `scripts/check_skills.py` runs the format, link, secret, manifest, and
  versioned-facts checks from `AGENTS.md`.
- `scripts/check_drift.py --ths <checkout>` resolves every code reference in
  the `ths-*` skills against Thus Spoke Zakura and re-checks the claims pinned
  in `scripts/ths-anchors.toml` (Regtest activation heights, the cleanup
  ownership check, account roles, the node image tag, and others). It runs daily
  against THS `main`.

Both use only the Python standard library (3.11+).

## Usage

Install the whole `skills/` tree into your agent's skills directory — the
routers and references link between siblings (`../zcash-wallet/SKILL.md`,
`references/…`), so copying only some folders breaks routing:

```sh
cp -r skills/* ~/.claude/skills/   # user-wide, Claude Code
cp -r skills/* .agents/skills/     # per-project, Devin-compatible agents
```

The root `SKILL.md` is the entry point for agents that read a URL: point them
at `https://zcashlabs.github.io/zcash-skills/SKILL.md` (or the file itself).
It is not a discoverable skill on its own — each `skills/<name>/SKILL.md` is.

## Sources and provenance

The `zcash-*` and `ths-*` skills were seeded from
[amiabix/zcash-and-ths-skills](https://github.com/amiabix/zcash-and-ths-skills)
and updated against the current
[thus-spoke-zakura](https://github.com/zcashlabs/thus-spoke-zakura) source
(the `tsz-*` crates are now `ths-*`, the shielded pool is Ironwood, and the
pinned node image is `zakuracore/zakura:1.6.0`).

Primary references:

- [zips.z.cash](https://zips.z.cash/) — protocol specification and ZIPs
- [zcash.readthedocs.io](https://zcash.readthedocs.io/en/latest/) — user/dev docs
  ([source](https://github.com/zodl-inc/zcash-docs)); note that several pages
  predate Unified Addresses, NU6, and the zcashd deprecation
- [z.cash/learn](https://z.cash/learn/) — concepts and ecosystem links
- [zcash/zcash-test-vectors](https://github.com/zcash/zcash-test-vectors) —
  official test vectors
- [zakura-core/zakura](https://github.com/zakura-core/zakura) — the Zakura node
- [zcash.github.io/ironwood](https://zcash.github.io/ironwood/) — the Ironwood
  pool book (NU6.3)

## License

MIT
