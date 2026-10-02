---
name: zcash-light-client
description: Use when building or debugging Zcash light-client scanning, compact-block sync, note or UTXO discovery, commitment trees, reorg handling, and wallet recovery.
---

# Zcash light client

Read [scanning and integration](references/scanning-integration.md). Identify the actual node, lightwallet service, wallet database, and application path, with their exact versions. The serving layer has shifted over time — lightwalletd (Go) is the legacy service; [Zaino](https://github.com/zingolabs/zaino) is the Rust indexer succeeding it, and both appear in deployed stacks (Thus Spoke Zakura still ships lightwalletd). Distinguish node tip, server indexed range, wallet scanned checkpoint, and spendable state.

For a sync change, follow block continuity, birthday and tree initialization, note and transparent output discovery, nullifier tracking, cursor persistence, and rollback. Prove that interruption or reorg cannot publish a cursor ahead of the durable wallet state. Use the wallet's rewind and rescan APIs for recovery.

## Core workflow

1. Record a height-and-hash checkpoint for each layer and the wallet's durable scan state.
2. Trace one batch from downloaded block through decryption, tree/witness updates, database commit, and published cursor.
3. Exercise interruption and a controlled reorg at the actual commit boundary.
4. Compare notes, spends, UTXOs, witnesses, and checkpoint after one-pass versus incremental scan.

A controlled block source can establish wallet logic; a claim about the service's response, limits, or indexing needs a service-backed run with the selected client.

## Review examples

- Equal node and wallet heights with different hashes are a fork signal. Find the common ancestor and test rewind plus replacement scanning.
- A cursor that advances before wallet effects are durable can skip a note after restart. Test interruption on each side of the commit boundary with a retained store.
- A transparent `startHeight` or page limit in a request does not establish a bounded backend query. Measure or inspect the selected service implementation.
- Indexer version gaps are real: e.g. a Zaino release may lag a node's `valuePools` schema after a network upgrade (the `ironwood` pool field broke older Zaino against Zebra 6). Check the pair, not each component alone.

Report node, service, and wallet checkpoints separately, including hashes; state whether the test used a controlled source or the actual service. Local chain consistency does not establish that a remote service supplied the best chain.
