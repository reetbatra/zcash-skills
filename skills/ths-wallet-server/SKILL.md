---
name: ths-wallet-server
description: Use when changing Thus Spoke Zakura wallet sync, treasury rewards, send or faucet behavior, ths-server APIs, balances, activity, or persistent wallet state.
---

# THS wallet server

Read the current repository `AGENTS.md` and [wallet server](references/wallet-server.md). Trace node RPC and lightwalletd data through the pinned Zakura wallet crates, the server snapshot, and the API result. Use `zcash-wallet`, `zcash-payments`, or `zcash-light-client` for the Zcash semantics touched by the change.

Keep accounts 1–5 user-facing and account 6 internal. Preserve the wallet snapshot as the balance source. For account Send and faucet, retain the claim-before-work pattern (`claim_transfer` / `claim_faucet` / `claim_address_faucet` persist intent keyed by the idempotency key before any wallet call), transaction identity, and activity recovery; the address faucet keeps the same contract in its own `address_faucets` table. Use the existing `ApiError`/`ApiResult` pattern and repository test seams. Run Rust checks after `crates/` changes and select a live Docker case when a real proof, node, or retained wallet store is necessary to establish the claim.

## Core workflow

1. Locate the owning step in RPC, lightwalletd download, wallet SDK, local store, snapshot, or API.
2. Follow a normal request and its hardest failure path, including retry after a persisted or broadcast effect.
3. Choose the nearest existing test seam and assert the consequential wallet, activity, and chain state.
4. Rebuild the app image before a live `ths` run and report which binary/image the evidence exercised.

## Review examples

- A pending Send replay returns the stored activity but can still drive `submit_prepared` → broadcast and mining. Check activity identity and side effects separately.
- A wallet sync may publish new account balances before later activity reconciliation fails. Inspect status and balance publication at the actual failure step.
- The account faucet and address faucet share the claim-before-work contract and one idempotency key space, but persist in different tables (`activities` vs `address_faucets`) — a key used by one is rejected by the other. Name the selected endpoint before claiming its recovery behavior.
