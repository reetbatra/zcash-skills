# Versioned facts

Single source of truth for version- and date-sensitive claims used by the
skills. When upstream changes one of these, update the value **and** the
`verified` date here, then run `python3 docs/check-facts.py` to find skill text
that disagrees. `pattern` is a Python regex — the checker flags any repo `.md`
file whose match text differs from `value`.

## Protocol / network upgrades

| Fact | Value | Verified | Source |
| --- | --- | --- | --- |
| Current deployed upgrade | NU6.3 (Ironwood, v6 tx format) | 2026-10-06 | [ZIP 258](https://zips.z.cash/zip-0258) |
| NU7 status | Draft; Testnet activation height 4,465,026 (2026-10-06); Mainnet height assigned 2026-10-20, activation target 2026-11-05 | 2026-10-06 | [ZIP 259](https://zips.z.cash/zip-0259) |
| NU7 consensus branch ID | `0x77190AD9` | 2026-10-06 | ZIP 259 |
| NU7 min network protocol version | Testnet `170180` / Mainnet `170190` | 2026-10-06 | ZIP 259 |
| NU7 block spacing / shielded action limits | 25 s; global 330, Orchard 330, Ironwood 330, Sapling 300 I/O, Sprout 0 | 2026-10-06 | [ZIP 218](https://zips.z.cash/zip-0218) |
| NU7 default expiry delta guidance | 120 blocks (was 40; ~50 min wall-clock) — non-consensus | 2026-10-06 | ZIP 218 |
| NU6.3 Mainnet activation | height 3,428,143 (2026-07-28) — confirm against ZIP 258 | 2026-10-06 | ZIP 258 |
| ZIP 316 (Unified Addresses) | Revision 0 active; Revision 2 draft | 2026-10-06 | [ZIP 316](https://zips.z.cash/zip-0316) |
| ZIP 317 (conventional fee) | Rev 0 active; Rev 1 (Ironwood contribution) enacted at NU6.3; Rev 2 draft | 2026-10-06 | [ZIP 317](https://zips.z.cash/zip-0317) |
| ZIP 320 (TEX addresses) | Active; `tex`/`textest` HRP, Bech32m P2PKH re-encode | 2026-10-06 | [ZIP 320](https://zips.z.cash/zip-0320) |
| ZIP 321 (payment URIs) | Active | 2026-10-06 | [ZIP 321](https://zips.z.cash/zip-0321) |

## Thus Spoke Zakura (`zcashlabs/thus-spoke-zakura`)

| Fact | Value | Verified | Source |
| --- | --- | --- | --- |
| Workspace version | `0.2.1` | 2026-10-02 | `Cargo.toml` |
| Packages / binary | `ths-cli`, `ths-server`; package `thus-spoke-zakura`, binary `ths` | 2026-10-02 | `Cargo.toml` |
| Rust toolchain | `1.98.0` (`rust-toolchain.toml`); Node `24` for `web/` | 2026-10-02 | `rust-toolchain.toml`, `ci.yml` |
| Pinned node image | `zakuracore/zakura:1.6.0` (`ZAKURA_IMAGE` in `runtime.rs`) | 2026-10-02 | `crates/ths-cli/src/runtime.rs` |
| App / lightwalletd images | `ghcr.io/zcashlabs/thus-spoke-zakura-app`, `-lightwalletd` | 2026-10-02 | `runtime.rs`, `release.yml` |
| Wallet crate pins | `zakura-{keys,primitives,proofs,orchard,zip321,...} = 2.2.0`; `zakura-client-{backend,sqlite} = 0.1.0-rc7`, imported under `zcash_*` aliases | 2026-10-02 | `crates/ths-server/Cargo.toml` |
| Account layout | accounts `1..=5` user-facing; account `6` treasury/miner | 2026-10-02 | `db.rs` |
| Default loopback ports | dashboard `32805`, RPC `18232`, lightwalletd `9067`, P2P `18233` (+offset stride 10) | 2026-10-02 | `runtime.rs` |
| Shielded pool | Ironwood; `orchard` rejected as destination pool post-NU6.3 | 2026-10-02 | `api.rs`, `wallet.rs` |
| Wallet DB schema names | `ext_tsz_*` — intentionally kept for migration stability despite the crate rename | 2026-10-02 | `wallet.rs` comment |
| Dev API env var | `THS_DEV_API` (not `TSZ_DEV_API`) | 2026-10-02 | `AGENTS.md` |
| Regtest NU activation | NU6–NU6.3 at height 1 in generated `zakurad.toml`; `regtest_network().nu7 = None` | 2026-10-06 | `main.rs`, `wallet.rs` |
| CI live cases | `activity_recovery` runs `broadcast_recovers_after_auto_mine_failure` + `concurrent_identical_sends_have_one_chain_effect`; the 10k-block case is not in CI | 2026-10-06 | `ci.yml` |

## Machine-checkable facts

Each block maps a `pattern` (regex appearing in repo docs) to the canonical
`value`. The checker fails on mismatched matches; anything without a pattern is
date-only. Keep one `pattern` per fact; make it match the whole token
(e.g. `name:version`).

```facts
id: zakura-image
value: zakuracore/zakura:1.6.0
pattern: zakuracore/zakura:[0-9a-zA-Z.\-]+
verified: 2026-10-02
source: crates/ths-cli/src/runtime.rs (ZAKURA_IMAGE)
```

```facts
id: ths-rust-toolchain
value: Rust 1.98.0
pattern: Rust 1\.[0-9]+\.[0-9]+|rust-toolchain[^;\n]*1\.[0-9]+\.[0-9]+
verified: 2026-10-02
source: rust-toolchain.toml
```

```facts
id: nu7-testnet-height
value: 4,465,026
pattern: 4,?465,?026|NU7[^\n]{0,40}Testnet[^\n]{0,40}[0-9]{6,}
verified: 2026-10-06
source: ZIP 259
```
