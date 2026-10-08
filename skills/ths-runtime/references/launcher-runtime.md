# Launcher and Docker runtime

## Where behavior lives

| Concern | Current owner |
| --- | --- |
| Command syntax and dispatch | `crates/ths-cli/src/main.rs` (`thus-spoke-zakura` package, `ths` binary) |
| Instance naming, images, containers, volumes, ports, shutdown | `crates/ths-cli/src/runtime.rs` |
| Self-update and uninstall | `crates/ths-cli/src/updater.rs`, `install.sh` |
| Source-built app and lightwalletd images | `Dockerfile`, `docker/lightwalletd.Dockerfile` |

Resolve the actual checked-out symbols before editing; this map is navigation, not a substitute for reading the full function and its callers. A CLI request may cross into `ths-server` over HTTP, so inspect both ends of a changed command.

## Instance lifecycle

`Runtime::start_with` deletes stale resources for the selected name, allocates the stack, waits for readiness, runs until shutdown, and deletes the selected instance. `CleanupOnDrop` covers early exits. For any change in this path, walk normal shutdown, Ctrl+C, failure before the first resource, failure after each resource, readiness failure, and browser-open failure.

`CleanupOnDrop` is armed before the initial `host.delete` call. If that first delete fails, Drop attempts deletion again. Treat a repeated delete as a reachable path and preserve the original error context. The fake `StartHost` tests verify call order and selected instance names, while actual resource ownership is decided in the Docker operations.

The required invariant is ownership: a name collision is not proof that a preexisting Docker resource belongs to this instance. Resources are named from `prefix()` (`ths-<name>-{app,lightwalletd,zakura,init}` containers, `ths-<name>-{chain,wallet,lightwalletd,config}` volumes, `ths-<name>` network). Containers, volumes, and the network are all created with a `com.zakura.ths.instance=<name>` label, and `owned_resource` gates both reuse (`ensure_*`) and deletion (`delete_instance_resources_with_mode`). It refuses a resource whose label names another instance or is missing ("not owned by ths instance"), and a name Docker lists more than once. Route any new reuse or deletion path through `owned_resource`. Check containers, network, volumes, and the instance metadata directory independently; cleanup can fail partway through, and the metadata directory is removed only after every Docker removal succeeds. Report cleanup errors rather than hiding them.

Host-published ports stay on `127.0.0.1`. Container-internal services may listen on `0.0.0.0`. Keep the runtime Regtest-only and verify the selected image is the exact tag the launcher intends to run — the node image is pinned in `runtime.rs` (e.g. `ZAKURA_IMAGE = "zakuracore/zakura:1.6.0"`; check the constant, not this paragraph). The unit tests at the end of `runtime.rs` cover name validation, interruption cleanup calls, readiness, browser failure, and version-locked images. The fake allocator creates no Docker resources, so those tests do not prove safe cleanup after partial real allocation or a name collision.

### Status and endpoint diagnosis

`Runtime::endpoints` reads persisted `instance.json`; it does not prove a service is currently listening. `Runtime::status` first tries live endpoint inspection, falls back to persisted metadata, and treats a `container_running` inspection error as `false`. A status response containing a dashboard URL can therefore coexist with a stopped container or a Docker inspection failure.

If `ths status --json` shows a URL that does not respond, compare the live app container and host-published ports with `instance.json`; then separate a stopped container from an inspection error. Check readiness at the endpoint before claiming the stack is healthy.

## Source versus running artifact

`ths` uses images, not edited source files. After server or web changes, `cargo run -p thus-spoke-zakura -- build --dev` builds local images for the next launch. A running container still has its existing image; identify the image and instance actually exercised before claiming a live result. `cargo run -p thus-spoke-zakura -- <args>` invokes the source launcher; the package name is not `ths`.

For new or changed flags, update the command table in `README.md`. Run Rust checks after `crates/` edits and `tests/install.sh` after `install.sh` edits. Image names, tags, dependencies, workflows, and updater behavior have release impact under `AGENTS.md`; read `RELEASING.md` and use `ths-release` when touching them.

## Review examples

- **New `ths` command:** verify parsing, JSON/text output where supported, errors, server API contract, README table, and an end-to-end invocation against the source-built artifact if the behavior needs Docker.
- **Startup fix:** prove that the failing checkpoint is reachable and only owned resources are removed on each exit; a happy-path start test alone is insufficient.
- **Image change:** state which exact tags are selected by `build`, `pull`, and `start`, and how the change affects existing released launchers.

## Worked task: a foreign resource has our instance name

**Input:** An unrelated Docker daemon already contains a container named `ths-alpha-app`, or a volume such as `ths-alpha-wallet`. The user runs `ths --name alpha start`. `start_with` calls deletion before allocation, and `owned_resource` must refuse the foreign resource because its `com.zakura.ths.instance` label does not name `alpha`. The prefix and expected resource names come from `prefix`, `ensure_*`, and `delete_instance_resources_with_mode` in `runtime.rs`. Use this task when changing anything on the reuse or deletion path.

1. In an isolated disposable Docker environment, create one deliberately foreign resource with the colliding name and record its Docker ID, labels, and data. Use a unique test name; never run this collision test against a shared daemon.
2. Exercise the ownership check at the shared reuse/deletion boundary. An unowned name must cause a clear error before `start`, `stop`, `reset`, or partial-start cleanup mutates it. A resource with matching ownership metadata may follow the existing instance lifecycle. A network created by THS before thus-spoke-zakura#133 has no label, so it is refused too; say so in the change if users may still have one.
3. Recheck the foreign resource by **ID and data**, not name alone. Assert no new app allocation happened, its metadata directory was not removed, and a normally owned instance still cleans up on shutdown and interruption.

`RecordingHost` lifecycle tests only observe `delete:<name>` calls. Ownership is covered through the `DockerResourceCommands` seam with `RecordingDocker`: `foreign_volume_collision_preserves_all_resources`, `foreign_container_collision_is_not_deleted`, `unlabeled_network_collision_preserves_data_and_metadata`, `partial_startup_cleanup_removes_only_owned_resources`, and `owned_resources_still_clean_up`. Extend those for a new path, and still run step 3 against a disposable daemon before claiming real Docker behavior.

**Fast navigation and checks:**

```console
rg -n 'start_with|delete_instance_resources|owned_resource|ensure_network|ensure_volume|ensure_app|label\(' crates/ths-cli/src/runtime.rs
cargo test -p thus-spoke-zakura
cargo fmt --all -- --check
```

The first command locates every branch that can reuse or remove a resource. The Cargo test is a fast local gate; run the full `AGENTS.md` Rust checks after changing `crates/` and use a disposable Docker daemon for the collision oracle.
