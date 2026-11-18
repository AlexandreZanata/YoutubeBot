# YoutubeBot Manager (desktop)

Rust + Slint desktop app with monthly metrics for every channel and network the project
manages, plus the bounded open/stop session actions of the typed Python CLI. It reads the
private records and writes nothing but its own preferences. Contract, screens, keyboard and
design system: [docs/DESKTOP.md](../docs/DESKTOP.md).

## Structure

```text
desktop/
├── Cargo.toml                    workspace
├── apps/manager/                 Slint binary
│   ├── build.rs                  compiles ui/app.slint (fluent, light/dark at runtime)
│   ├── icon.svg                  menu icon installed by scripts/install.sh
│   ├── src/main.rs               threads, timers, callbacks, preferences
│   ├── src/view.rs               reports → display structs (formatting only)
│   ├── src/thumbs.rs             off-thread thumbnail decoding (Shorts, ficha photos)
│   ├── tests/contrast.rs         WCAG AA check of the theme tokens
│   └── ui/
│       ├── theme.slint           design tokens (colors, spacing, radii, type)
│       ├── store.slint           view-model structs, Store and Bridge globals
│       ├── controls.slint        buttons, nav, badges, cards, states, lists
│       ├── pages.slint           the eight pages (Central first, with the ficha detail)
│       └── app.slint             window, sidebar, header, shortcuts, footer
├── crates/reports/               pure aggregation, no UI
│   ├── src/time.rs               America/Cuiaba clock, periods, pt-BR formatting
│   ├── src/catalog.rs            channel table (mirrors tools/ytbot/channels.py)
│   ├── src/youtube.rs            runs and Shorts from upload/metadata records
│   ├── src/community.rs          history with single-entry fallback
│   ├── src/social.rs             X posts, replies, discovery
│   ├── src/commercial.rs         WhatsApp events/rules, Mercado Livre capture
│   ├── src/sales.rs              sales agent Central (central.json), client fichas, safe targets
│   ├── src/snapshot.rs           one read of every source
│   ├── src/overview.rs           counts per period/channel, upcoming slots
│   ├── examples/summary.rs       month summary in the terminal
│   ├── tests/reports.rs          fixture months: published, scheduled, empty, broken
│   └── tests/sales.rs            Central and fichas: defaults, path rejection, safe opens
├── crates/manager-core/          sessions, live browser state, settings, CLI actions
└── scripts/
    ├── install.sh                release build, ~/.local/bin binary and menu entry
    ├── demo_root.py              synthetic project root for review
    └── capture.py                screenshots of every page on a private Xvfb display
```

## Build and run

```bash
cd desktop
cargo build
./target/debug/manager-app
```

The root is `YTBOT_ROOT`, else the one chosen in Configurações, else the current directory,
else the repository that contains `desktop/`.

Install for the desktop owner (release binary in `~/.local/bin/ytbot-manager`, icon and the
"YoutubeBot Manager" menu entry, which sets `YTBOT_ROOT` to the folder with `.local/`):

```bash
bash desktop/scripts/install.sh
bash desktop/scripts/install.sh --root /path/to/project
```

Run it again after an update; it replaces the binary in place.

## Check

```bash
cd desktop
cargo fmt --all --check
cargo clippy --workspace --all-targets
cargo test --workspace
```

`npm run verify` at the repository root also runs `tests/test_desktop_catalog.py`, and CI runs
`cargo fmt --check` plus the `reports` and `manager-core` tests.

Month summary without the UI:

```bash
cargo run -p reports --example summary -- /path/to/project
```

## Review with synthetic data

```bash
python3 desktop/scripts/demo_root.py /tmp/ytbot-demo
YTBOT_ROOT=/tmp/ytbot-demo desktop/target/debug/manager-app
python3 desktop/scripts/capture.py --root /tmp/ytbot-demo --theme light --out docs/images/desktop
python3 desktop/scripts/capture.py --root /tmp/ytbot-demo --theme dark --out docs/images/desktop
python3 desktop/scripts/capture.py --root /tmp/ytbot-demo --theme light --out /tmp/shots \
    --size 1920x1080 --only central,ficha-detail,ficha-detail-end
```

`capture.py` needs `Xvfb` and ImageMagick `import`; never point it at the real root when the
images are meant for Git. `--size` resizes the window to the virtual screen (the default
1280x800 keeps the committed names; other sizes add `-WIDTHxHEIGHT`), `--only` limits the
shots.

## Extending

- New record: add a tolerant reader and a pure count to `crates/reports` with a fixture test,
  then format it in `view.rs` and lay it out in `pages.slint`.
- New network session: add it to `NETWORKS` in `manager-core/src/state.rs` and, if it has a CLI
  session, to `CliActions`.
- New color: add it to `theme.slint` on one `dark ? … : …` line and to the pairs in
  `tests/contrast.rs`.
- Keep Slint types out of `reports` and `manager-core`.
