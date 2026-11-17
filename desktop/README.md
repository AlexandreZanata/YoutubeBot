# YoutubeBot Manager (desktop)

A small Rust + Slint desktop app that lists every session the project knows: YouTube channel
profiles, WhatsApp Web, Mercado Livre, X and Instagram. It is a read-only view of the private
registries plus bounded actions that call the typed Python CLI.

## Structure

```text
desktop/
├── Cargo.toml                 workspace
├── apps/manager/              Slint binary
│   ├── build.rs               compiles ui/app.slint (fluent-dark)
│   ├── src/main.rs            view model, callbacks, threads
│   └── ui/app.slint           window layout and components
└── crates/manager-core/       domain layer, no UI dependency
    ├── src/model.rs           SessionInfo
    ├── src/state.rs           registry readers
    ├── src/actions.rs         SessionActions trait + CliActions
    └── tests/state.rs         registry parsing tests
```

`manager-core` knows nothing about Slint. The app maps `SessionInfo` to the generated
`SessionRow` struct, so the UI can be replaced without touching the domain.

## Data sources

| Source | File | Used for |
| --- | --- | --- |
| YouTube accounts | `.local/accounts/registry.json` | label, CDP port, channel binding |
| Commercial | `.local/commercial/<network>/account.json` | WhatsApp, Mercado Livre |
| Social | `.local/social/<network>/account.json` | X, Instagram |

Nothing is written by the app. Missing files show as "não conectado".

## Actions

| Scope | Open | Stop |
| --- | --- | --- |
| `commercial` | `python3 -m tools.ytbot commercial open --network <key>` | `... stop ...` |
| `social` | `python3 -m tools.ytbot social open --network <key>` | `... stop ...` |
| `youtube` | not applicable | not applicable |

Commands run through `std::process::Command` with a fixed argument list, never a shell.

## Build and run

```bash
cd desktop
cargo build
cargo test
./target/debug/manager-app
```

The app finds the project root through `YTBOT_ROOT`, the current directory, or the workspace
location, in that order.

## UI

- Header with refresh.
- Left filter by network.
- Center list of sessions with status.
- Right details with the channel, status and the two actions.
- Footer status line reports the result of the last action.

## Extending

1. Add a network constant in `crates/manager-core/src/state.rs` (`NETWORKS`).
2. If it needs actions, add the CLI scope in `actions.rs`.
3. Add a filter item in `ui/app.slint`.
4. Keep the domain free of Slint types.
