---
name: ths-dashboard
description: Use when changing Thus Spoke Zakura's React dashboard, wallet or explorer views, web API schemas, query hooks, mutations, or server-event updates.
---

# THS dashboard

Read the current repository `AGENTS.md` and [dashboard](references/dashboard.md). Follow data from `ths-server` through `web/src/lib/api` and query hooks into the affected view.

Keep the server wallet snapshot authoritative for balances. Reuse Zod schemas, query keys, mutation invalidation, and SSE handling rather than introducing another account-state store. Check loading, error, and stale-result behavior when the server syncs or chain state changes. Use Node 24 and run the repository's web checks after changing `web/`. Rebuild the app image before claiming a live dashboard reflects source edits.

## Core workflow

1. Trace the response from Rust endpoint through Zod schema, query key, hook, and affected component.
2. For a mutation, check both successful invalidation and later SSE-driven refresh.
3. Test valid, pending, error, and stale-result states at the real query owner.
4. Run the web checks and verify the built frontend artifact if the claim is about a running container.

## Review examples

- A stale balance after mining starts at `/api/v1/accounts`: compare its snapshot with the `useAccounts()` cache before changing UI state.
- A money change checks wallet `bigint` fields and explorer `number` fields separately; the current schemas do not give both paths the same arithmetic representation.
- A new server field updates the Zod schema, request helper, affected query or mutation, view, and boundary test in that order.
