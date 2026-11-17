# Desktop manager

The desktop manager is a Rust + Slint application under `desktop/`. It lists every session the
bot knows and offers two bounded actions per network: open the visible login window and stop
the hidden browser.

## Contract

- Read-only view: the app never writes private state. It reads
  `.local/accounts/registry.json`, `.local/commercial/<network>/account.json` and
  `.local/social/<network>/account.json`.
- Actions call the typed Python CLI (`python3 -m tools.ytbot commercial|social open|stop
  --network <key>`) with a fixed argument list. No shell, no arbitrary commands.
- YouTube channels are displayed with their binding and CDP port; they have no browser action
  because their pipeline is driven by `run`, `shorts` and `distribute`.
- A missing or unreadable registry shows the network as "não conectado"; it never fabricates a
  session.

## Layers

| Layer | Crate | Responsibility |
| --- | --- | --- |
| Domain | `manager-core` | `SessionInfo`, registry parsing, action trait |
| Action adapter | `manager-core::actions` | `CliActions` invoking the Python CLI |
| UI | `apps/manager` | Slint window, filters, selection, callbacks |
| Entry point | `apps/manager/src/main.rs` | wiring, threading, status messages |

The UI depends on the domain; the domain never depends on Slint.

## Build

```bash
cd desktop
cargo build
cargo test
./target/debug/manager-app
```

`YTBOT_ROOT` overrides the project root when the app is launched outside the repository.

## Extending safely

- New network: add it to `NETWORKS` in `state.rs`, to the filter list in `app.slint`, and, if
  it has a CLI session, to `CliActions`.
- New action: extend the `SessionActions` trait; keep the UI calling only the trait.
- Never import Slint types into `manager-core`.
