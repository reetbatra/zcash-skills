---
name: zakura
description: Use when running, integrating, or reviewing the Zakura Zcash full node (zakurad, zakuracore/zakura image, zakura-* crates), including zcashd compatibility mode, pruning and snapshots, Regtest deployments like Thus Spoke Zakura, or its experimental P2P v2 stack.
---

# Zakura

Zakura is a consensus-compatible Zcash full node in Rust, forked from [Zebra](https://github.com/ZcashFoundation/zebra) and developed at [zakura-core/zakura](https://github.com/zakura-core/zakura). It is a node — validation, networking, chain state — not a wallet. Do not treat it as a renamed `zcashd`: the legacy wallet/RPC surface runs through zcashd-compat mode or Zallet, not inside `zakurad`. See [the node reference](references/node.md) for install paths, compat topology, and the crate map.

## Core workflow

1. Resolve the deployment shape before advising: binary installer, Docker image (`zakuracore/zakura`), crates.io build, or embedded in a stack like Thus Spoke Zakura. Each has different versioning.
2. Identify which RPC surface the consumer needs. Modern gRPC/JSON-RPC is served by the node and indexers; legacy `zcashd` wallet RPCs exist only under zcashd-compat (a supervised or externally managed `zcashd` P2P sidecar — Zakura is the network-facing node, zcashd talks only to it).
3. Check pruning and snapshot assumptions before promising historical data. A pruned node keeps configurable retention, not full history; snapshots (~11 GB pruned) bootstrap ~680× faster than P2P sync but trade away trustless verification of the skipped range.
4. Keep feature maturity honest: P2P v2 (QUIC/iroh-based transport, mempool aggregation aimed at Project Tachyon) is experimental, off by default on Mainnet, and has known DoS risks.

## Boundaries that matter

- Zakura validates and serves chain data; a separate lightwallet service (lightwalletd today, Zaino going forward) serves light clients; wallet construction lives in the `librustzcash`/`zakura-*` client crates. A `zakurad` RPC answer is node truth, not wallet state.
- Regtest is a supported deployment — Thus Spoke Zakura pins `zakuracore/zakura:1.6.0` for exactly this — but a Regtest result proves nothing about Mainnet peer behavior, which is where zcashd-compat and P2P v2 live.
- The `zakura-*` crate family splits in two: node crates (`zakura-chain`, `zakura-state`, `zakura-consensus`, `zakura-network`, `zakura-rpc`, `zakura-script`, `zakura-node-services`, `zakura-header-chain`, …) mirroring the `zebra_*` layout, and crypto/wallet crates in `zakura-core/common` + `zakura-core/wallet-libraries` (`zakura-keys`, `zakura-primitives`, `zakura-proofs`, `zakura-orchard`, `zakura-sapling-crypto`, `zakura-transparent`, `zakura-zip321`, `zakura-pczt`, `zakura-client-backend`, `zakura-client-sqlite`, `zakura-wallet-lib`). Dependents import the latter under `zcash_*` aliases — resolve the real package names in `Cargo.toml` before reading docs.

## Review examples

- "Run a Zcash node" is ambiguous: sync target, disk budget (pruning), bootstrap path (snapshot vs P2P), and whether the caller needs legacy `zcashd` RPCs all change the answer.
- A `zcashd` RPC call failing against `zakurad` directly is expected, not a bug — check whether the deployment runs the compat sidecar.
- Claiming "5× faster than Zebra" or snapshot speedups is a benchmark claim about a pinned version and workload; report the measurement or omit it.

Report the Zakura version or image tag, network, deployment shape, enabled modes (compat, pruning retention, P2P v2), and which layer answered each observation.
