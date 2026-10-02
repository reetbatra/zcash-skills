# Wallet server

## Current ownership map

| Boundary | Current owner |
| --- | --- |
| Initialization and service process | `crates/ths-server/src/main.rs` |
| Zakura JSON-RPC and node-selected chain checkpoint | `crates/ths-server/src/rpc.rs` |
| lightwalletd download, rewind, transparent discovery, scan ranges | `crates/ths-server/src/reconcile.rs` |
| Pinned Zakura wallet API, balances, payment creation | `crates/ths-server/src/wallet.rs` |
| Public accounts, activity, idempotency, treasury cursor type | `crates/ths-server/src/db.rs` |
| Atomic treasury reward import, cursor extension, rewind | `crates/ths-server/src/wallet/recovery.rs` |
| HTTP API, published wallet snapshot, send/faucet/mining, reconciliation | `crates/ths-server/src/api.rs` |

Inspect `Cargo.toml` and `crates/ths-server/Cargo.toml` before using upstream wallet documentation. This repository imports Zakura wallet crates (`zakura-keys`, `zakura-primitives`, `zakura-client-backend`, `zakura-client-sqlite`, `zakura-proofs`, `zakura-orchard`, `zakura-sapling-crypto`, `zakura-pczt`, `zakura-transparent`, `zakura-zip321`) under `zcash_*` aliases at exact-pinned versions. API semantics and compatibility claims must follow the resolved source.

The wallet database keeps legacy `ext_tsz_*` schema names and migration UUIDs on purpose — a comment in `wallet.rs` requires keeping them stable for existing wallets. Do not rename them when following the `tsz-*` → `ths-*` crate rename elsewhere.

## Sync and balance publication

The path is Zakura checkpoint → lightwalletd indexed data → wallet database → `AppState::refresh_wallet_snapshot` → `/api/v1/accounts` → dashboard query. `synchronize_wallet` holds the sync lock, checks a shared deadline, runs `reconcile::sync_wallet`, then publishes the snapshot. The ready snapshot is guarded by a scanned-versus-observed chain checkpoint check. Failures before that publication leave the earlier account snapshot in place. `refresh_wallet_snapshot` publishes accounts and ready status before `reconcile_unconfirmed`; if activity reconciliation then fails, sync changes status to error while those newer accounts remain published. Test and report this boundary precisely when changing sync behavior.

At startup, `main.rs::serve` checks dependencies, synchronizes, and provisions Account 1 with 5 Ironwood ZEC before starting the background sync loop. The loop checks about every two seconds. `/api/v1/health` can return 200 with a prior successful sync even if the current wallet-sync state is `error`; runtime readiness probes this health route. For a stale balance after startup, compare `/api/v1/status` wallet-sync state and scanned/observed height **and hash**, then `/api/v1/accounts`. A green health check establishes less than a current, ready wallet snapshot. `reconcile.rs::within_deadline` applies per-operation and shared sync deadlines, so locate the phase that timed out.

In `reconcile.rs`, separate reorg detection and rewind, subtree-root updates, transparent output discovery, and prioritized shielded scan ranges. Check which operation advances each cursor and whether the write is durable before a progress claim. The node tip, lightwalletd tip, wallet scanned checkpoint, and user-facing balance can differ transiently. Equal heights do not prove equal block hashes.

Public transparent discovery and treasury reward discovery deliberately use different paths. `wallet.rs::public_transparent_queries` covers accounts 1–5; `reconcile.rs::refresh_transparent_outputs` streams lightwalletd UTXOs for those queries with the selected start height. Account 6 is excluded. For treasury coinbase rewards, `api.rs::replenish_treasury` walks the node's block/coinbase evidence through `discover_reward`, then `wallet/recovery.rs` imports the reward and advances `ext_tsz_treasury_cursor`. A claim that public UTXO streaming alone fixes treasury scale misses the separate reward path.

## Treasury and payments

Accounts 1–5 are public development accounts. Account 6 (`TREASURY_ACCOUNT_ID`) is the miner and faucet treasury; it must stay out of account lists, displayed balances, and routine user transparent queries. Reward discovery has a persisted treasury cursor; reorg handling and immature coinbase outputs affect when funds can be spent. A change to bulk or incremental reward processing must preserve the cursor's chain identity and make the next faucet request work after a large reward history.

The send/faucet flow uses claim-before-work: `claim_transfer` (account send) or `claim_faucet` (account faucet) validates the request and persists an activity row keyed by the idempotency key **before** any wallet call. A replayed key returns the existing activity. Pending rows in `prepared`/`broadcast` status drive `submit_prepared`, which can retransmit the same signed transaction; `confirm_after_mining` reconciles inclusion. Prepared payments are persisted in `ext_tsz_prepared_payments` (txid, raw transaction, expiry height) so a restart can recover identity. Inspect the actual failure window between these steps before changing retry behavior — a timed-out response does not prove no transaction was sent, and `reconcile_unconfirmed` in the background snapshot path can later confirm the same activity from chain evidence.

For faucet changes, inspect the `FaucetRuntime` and `PaymentSubmitter` seams plus `prepare_with_replenishment`/`replenish_treasury` before introducing another abstraction. The public-address faucet path (`faucet_address` → `require_faucet_address` → `synchronize_latest` → `prepare_with_replenishment` → `wallet.broadcast` → `mine_and_sync` → RPC `transaction` lookup → `confirmed_block_hash`) does not create an activity row or require an idempotency key; do not describe account Send's replay guarantees as covering it. Preserve its actual validation, account boundaries, and exact zatoshi arithmetic. Use existing `ApiError`/`ApiResult` for HTTP failures.

### Reward-discovery trace

`prepare_with_replenishment` distinguishes the wallet's `ScanRequired` from `InsufficientFunds`. The first path retries after sync and may mine forward from the birthday; the second uses the SDK's deficit to seek enough spendable rewards. `replenish_treasury` checks the persisted cursor's receiver and selected-chain hash, walks reward candidates, and mines until a candidate can mature. `discover_reward` verifies coinbase, unspent/spender evidence, and the selected chain hash around the wallet commit. `wallet/recovery.rs::commit_treasury_discovery` stores the reward and advances the cursor in one database transaction with a compare-and-swap check.

**Worked large-history diagnosis:** A faucet stalls after 10,000 mined blocks. First determine whether the wallet returned `ScanRequired` or `InsufficientFunds`; those trigger different work. Then compare the persisted cursor's height, hash, and receiver with the selected chain, inspect coinbase maturity and SDK spendability, and measure bulk catch-up separately from the next incremental block. The narrow test `insufficient_funds_discovers_only_the_needed_mature_reward_and_retries` checks the deficit path; the ignored large-history Docker case checks the real stack. A treasury total balance is not a substitute for the wallet's proposal result.

**Cursor interruption example:** Let the persisted treasury cursor be `(H, hash H, receiver R)`. Discovery checks block `H+1` on the selected chain and, if it contains a relevant reward, commits both the imported transaction and cursor `(H+1, hash H+1, R)` in one wallet database transaction. A failure before that commit must leave both at `H`; a restart rechecks `H+1`. A reorg that replaces `hash H+1` must rewind the imported reward and cursor together. The tests `failed_cursor_commit_rolls_back_reward_import_and_reopen_keeps_progress` and `rewind_updates_sdk_and_cursor_atomically` directly exercise these boundaries; `known_spender_must_be_stored_and_spend_the_exact_reward_output` checks spent-reward evidence. These are stronger oracles than a successful faucet HTTP response.

### Send failure windows

| Point of failure | Persisted or external effect to check |
| --- | --- |
| Before `claim_transfer`/`claim_faucet` | Validation or replay lookup failed; no activity row exists for this request |
| After claim, before `submit_prepared` | An activity row exists; wallet sync/proposal may have failed before prepare — no transaction is established |
| After broadcast, before confirmation | A transaction with a known txid exists; reconcile it before any replacement, replay can still attempt mining |
| After mining, before response | The response may be lost although the original txid is included; reconcile chain and row identity |

This table describes possible boundaries, not proof that each state is currently recovered automatically. For a money-flow change, force the relevant boundary and assert the activity row, txid, chain inclusion, and final wallet snapshot independently.

## Evidence by claim

| Claim | Nearest useful evidence |
| --- | --- |
| Snapshot reads and pre-publication failure | `account_reads_return_the_snapshot_without_contacting_lightwalletd`, `synchronization_failure_preserves_the_last_good_snapshot`; neither proves preservation after activity reconciliation fails |
| Reorg or scan range | `same_height_and_lower_tip_reorgs_find_the_last_common_block`, `scan_ranges_are_split_without_gaps` |
| Hidden treasury or transparent scope | `creates_user_accounts_and_hidden_treasury`, `routine_transparent_queries_exclude_the_treasury` |
| Input validation and replay identity | `invalid_sends_are_rejected_before_replay_or_synchronization`, `a_valid_replay_returns_the_original_without_the_wallet_or_network`; the latter returns the original row but can still attempt RPC and mining for a pending activity |
| Real broadcast recovery | The ignored live `broadcast_recovers_after_auto_mine_failure` case through `ths-regtest-verifier` |

Run `AGENTS.md` Rust checks after `crates/` edits. Rebuild the app image before a live `ths` run reflects server source changes. Keep Docker-free seam tests for logic that does not require a real node or proof.

## Worked task: external-address faucet times out

**Input:** A client calls `faucet_address` with a valid Regtest destination and loses the HTTP response after the server may have broadcast and mined. This endpoint has no idempotency key or activity row, unlike `faucet` to an account. Its path is `require_faucet_address` → wallet sync → `prepare_with_replenishment` → `wallet.broadcast` → `mine_and_sync` → RPC transaction lookup → confirmed block hash.

| Observation after timeout | Safe conclusion |
| --- | --- |
| Original txid and confirmed block found | Payment occurred; a new faucet request could pay again |
| Broadcast tx found but no block | Reconcile that transaction before any replacement |
| No txid was returned and chain/treasury history is uncertain | The HTTP timeout alone cannot prove no payment occurred |

For a retry change, inject a failure after `prepare_with_replenishment`/broadcast and before the HTTP response. `FaucetRuntime` covers replenishment and preparation, but `faucet_address` then calls concrete `mine_and_sync` and RPC lookup; that seam alone cannot test a second endpoint request. Use a handler-level seam or controlled integration stack for the response-loss and retry oracle. A lower-level `FaucetRuntime` test can separately assert the first outgoing txid. Test both an account faucet replay with the same key and the distinct external-address endpoint so the contracts cannot be confused. If the desired behavior is replay-safe external faucet requests, the implementation needs a durable intent/transaction identity before it can promise that behavior; document the gap rather than claiming it exists.

```console
rg -n 'async fn faucet_address|async fn fund_from_treasury|async fn prepare_with_replenishment|async fn confirm_after_mining' crates/ths-server/src/api.rs
cargo test -p ths-server insufficient_funds_discovers_only_the_needed_mature_reward_and_retries
```

The existing test covers treasury replenishment, not the external endpoint's unknown-response retry. Add the failure-window regression at the narrowest seam, then run the required Rust checks.
