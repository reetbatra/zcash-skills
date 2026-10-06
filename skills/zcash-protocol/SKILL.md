---
name: zcash-protocol
description: Use when changing or evaluating Zcash consensus rules, network-upgrade activation, transaction encodings, proof verification, or node validation.
---

# Zcash protocol

Read [protocol and consensus](references/protocol-consensus.md). Resolve the target network, block height, activated upgrade, transaction version, and governing specification revision before editing or reviewing consensus-sensitive code.

The current surface is NU6.3 (Ironwood: v6 transactions, the sealed Orchard pool) with NU7 ([ZIP 259](https://zips.z.cash/zip-0259)) on Testnet — 25-second blocks, per-pool shielded action limits, v4 transactions disallowed (Sprout permanently unspendable), 60% fee burn, NSM issuance. NU7 adds no new transaction format, but signatures commit to a consensus branch ID, so a transaction signed pre-activation is invalid post-activation. Expiry is still in blocks; ZIP 218 moves the default `txexpirydelta` to 120 to preserve ~50-minute wall-clock expiry at 25-second spacing. Keep consensus validity distinct from node mempool policy and wallet construction choices. Use the applicable protocol specification and ZIPs to define expected behavior; use the pinned implementation to locate the code path. Exercise exact boundary heights, malformed encodings, and published vectors where applicable. Investigate differences between implementations — e.g. [Zebra](https://github.com/ZcashFoundation/zebra) versus [Zakura](https://github.com/zakura-core/zakura) — before deciding which is correct.

## Core workflow

1. State the exact rule and its activation context before examining the implementation.
2. Trace the byte representation and validation call reached at the target height.
3. Derive positive and negative cases from the rule and [official test vectors](https://github.com/zcash/zcash-test-vectors).
4. Run the relevant node or primitive tests; report the rule, vectors, configurations, and remaining uncertainty.

## Review examples

- For a rule activated at `H`, exercise `H-1`, `H`, and `H+1` with the same encoded case where the format permits it.
- For expiry height `N`, check block validity at `N` and `N+1`; do not use mempool rejection as the consensus oracle.
- For a fee dispute, identify whether the claim comes from ZIP 317 wallet guidance, node relay policy, or an actual block-validity rule.
- For an Orchard-pool claim post-NU6.3, name whether it is a spend (allowed, with `enableCrossAddress` off), a change note, or a new output (forbidden — that output belongs to Ironwood).
- For a NU7 rehearsal on Regtest, assign the upgrade a deferred activation height in the node's regtest parameters and verify the wallet's activation map matches — wallet and node disagreeing about `nu7` is a real failure mode.

Report the governing document revision, target network and height, exact bytes or vector, code path reached, and which layer accepted or rejected it.
