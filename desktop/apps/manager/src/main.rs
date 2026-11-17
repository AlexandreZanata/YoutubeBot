//! YoutubeBot desktop manager: read-only reports over the private records plus the bounded
//! open/stop session actions of the typed Python CLI.
//!
//! Disk reads and CLI actions run on worker threads; results come back through
//! `slint::invoke_from_event_loop`, so the window never blocks.

mod thumbs;
mod view;

slint::include_modules!();

use std::cell::RefCell;
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::time::Duration;

use manager_core::settings::{REFRESH_CHOICES, Settings, Theme as ThemeChoice};
use manager_core::{CliActions, SessionActions, SessionInfo, StateLoader};
use reports::time::{format_datetime, parse_date_input};
use reports::{CHANNELS, Period, Snapshot};
use slint::{ComponentHandle, Image, Rgba8Pixel, SharedPixelBuffer, Timer, TimerMode};

use view::{Context, model, no_notice, notice};

/// Live sessions are re-read this often while the app is open.
const SESSIONS_POLL: Duration = Duration::from_secs(5);

struct App {
    root: PathBuf,
    root_origin: String,
    settings: Settings,
    settings_path: Option<PathBuf>,
    snapshot: Option<Snapshot>,
    sessions: Vec<SessionInfo>,
    sessions_error: Option<String>,
    /// Visible row → index in `sessions` (after search).
    session_rows: Vec<usize>,
    /// Visible card → channel slug (after search).
    channel_rows: Vec<&'static str>,
    period: Period,
    channel: Option<&'static str>,
    search: String,
    open_channel: Option<&'static str>,
    loading: bool,
    generation: u64,
    thumbs: HashMap<PathBuf, Image>,
    pending_thumbs: HashSet<PathBuf>,
}

thread_local! {
    static APP: RefCell<Option<App>> = const { RefCell::new(None) };
}

fn with_app<R>(action: impl FnOnce(&mut App) -> R) -> Option<R> {
    APP.with(|cell| cell.borrow_mut().as_mut().map(action))
}

fn resolve_root(settings: &Settings) -> (PathBuf, String) {
    if let Some(value) = std::env::var_os("YTBOT_ROOT") {
        return (
            PathBuf::from(value),
            "variável YTBOT_ROOT (tem prioridade)".into(),
        );
    }
    if let Some(path) = settings
        .root
        .as_ref()
        .filter(|path| path.join(".local").is_dir())
    {
        return (path.clone(), "escolhida em Configurações".into());
    }
    let root = manager_core::state::project_root().unwrap_or_default();
    (root, "detectada automaticamente".into())
}

fn home_relative(path: &Path) -> String {
    match std::env::var_os("HOME").map(PathBuf::from) {
        Some(home) if path.starts_with(&home) => {
            format!("~/{}", path.strip_prefix(&home).unwrap_or(path).display())
        }
        _ => path.display().to_string(),
    }
}

fn refresh_label(seconds: u32) -> String {
    match seconds {
        0 => "desligada".into(),
        value if value < 60 => format!("a cada {value} s"),
        value => format!("a cada {} min", value / 60),
    }
}

fn save_settings(app: &App) -> Result<(), String> {
    let Some(path) = &app.settings_path else {
        return Err("sem HOME: preferências não podem ser salvas".into());
    };
    app.settings.save(path).map_err(|error| error.to_string())
}

fn set_status(ui: &AppWindow, message: impl Into<slint::SharedString>) {
    ui.global::<Store>().set_status_text(message.into());
}

fn clamp(current: i32, length: usize) -> i32 {
    if current >= length as i32 {
        -1
    } else {
        current
    }
}

fn render_sessions(ui: &AppWindow, app: &mut App) {
    let store = ui.global::<Store>();
    let (rows, indices) = view::sessions(&app.sessions, &app.search, &app.root);
    store.set_session_current(clamp(store.get_session_current(), rows.len()));
    store.set_sessions_notice(match &app.sessions_error {
        Some(error) => notice(3, "Não foi possível ler as sessões", error),
        None if rows.is_empty() && !app.search.is_empty() => notice(
            1,
            "Nada encontrado",
            format!("Nenhuma sessão corresponde a “{}”.", app.search),
        ),
        None if rows.is_empty() => notice(
            1,
            "Nenhuma sessão",
            "Nenhum registro de conta foi encontrado.",
        ),
        None => no_notice(),
    });
    store.set_sessions(model(rows));
    app.session_rows = indices;
}

fn render_shorts(ui: &AppWindow, app: &mut App) -> Vec<PathBuf> {
    let Some(snapshot) = &app.snapshot else {
        return Vec::new();
    };
    let context = Context {
        snapshot,
        period: &app.period,
        now: view::now(),
        search: &app.search,
        channel: app.channel,
    };
    let shorts = view::shorts(&context, &app.thumbs);
    let store = ui.global::<Store>();
    store.set_short_current(clamp(store.get_short_current(), shorts.rows.len()));
    store.set_shorts(model(shorts.rows));
    store.set_shorts_notice(shorts.notice);
    store.set_shorts_summary(shorts.summary.into());
    shorts.missing_thumbs
}

fn render_channel_detail(ui: &AppWindow, app: &App) {
    let (Some(snapshot), Some(slug)) = (&app.snapshot, app.open_channel) else {
        return;
    };
    let context = Context {
        snapshot,
        period: &app.period,
        now: view::now(),
        search: &app.search,
        channel: app.channel,
    };
    let store = ui.global::<Store>();
    if let Some((card, rows, state)) = view::channel_detail(&context, slug) {
        store.set_video_current(clamp(store.get_video_current(), rows.len()));
        store.set_channel_detail(card);
        store.set_videos(model(rows));
        store.set_videos_notice(state);
    }
}

fn render_settings(ui: &AppWindow, app: &App) {
    let store = ui.global::<Store>();
    let now = view::now();
    let renderer = std::env::var("SLINT_BACKEND").unwrap_or_else(|_| "femtovg (OpenGL)".into());
    let facts = vec![
        Fact {
            label: "Versão".into(),
            value: env!("CARGO_PKG_VERSION").into(),
            tone: 0,
        },
        Fact {
            label: "Renderizador".into(),
            value: renderer.into(),
            tone: 0,
        },
        Fact {
            label: "Fuso horário".into(),
            value: reports::time::TIMEZONE.into(),
            tone: 0,
        },
        Fact {
            label: "Agora".into(),
            value: format_datetime(now).into(),
            tone: 0,
        },
        Fact {
            label: "Registros".into(),
            value: refresh_label(app.settings.refresh_seconds).into(),
            tone: 0,
        },
        Fact {
            label: "Sessões".into(),
            value: "a cada 5 s".into(),
            tone: 0,
        },
        Fact {
            label: "Preferências".into(),
            value: app
                .settings_path
                .as_deref()
                .map(home_relative)
                .unwrap_or_else(|| "não salvas (sem HOME)".into())
                .into(),
            tone: 0,
        },
    ];
    store.set_app_facts(model(facts));
    store.set_root_source(
        format!(
            "Em uso: {} · origem: {}",
            home_relative(&app.root),
            app.root_origin
        )
        .into(),
    );
    let index = REFRESH_CHOICES
        .iter()
        .position(|value| *value == app.settings.refresh_seconds)
        .unwrap_or(2);
    store.set_refresh_index(index as i32);
}

fn render_all(ui: &AppWindow, app: &mut App) {
    let store = ui.global::<Store>();
    store.set_loading(app.loading);
    store.set_has_data(app.snapshot.is_some());
    store.set_period_label(app.period.label().into());
    store.set_root_notice(if app.root.join(".local").is_dir() {
        no_notice()
    } else {
        notice(
            2,
            "Registros privados não encontrados",
            format!(
                "{} não tem a pasta .local/. Escolha a raiz do projeto em Configurações ou defina YTBOT_ROOT.",
                home_relative(&app.root)
            ),
        )
    });
    render_settings(ui, app);
    render_sessions(ui, app);

    let missing_thumbs = render_shorts(ui, app);
    if let Some(snapshot) = &app.snapshot {
        let now = view::now();
        let context = Context {
            snapshot,
            period: &app.period,
            now,
            search: &app.search,
            channel: app.channel,
        };
        store.set_kpis(model(view::kpis(&context)));
        let (upcoming, upcoming_notice, upcoming_summary) = view::upcoming(&context);
        store.set_upcoming_summary(upcoming_summary.into());
        store.set_upcoming_current(clamp(store.get_upcoming_current(), upcoming.len()));
        store.set_upcoming(model(upcoming));
        store.set_upcoming_notice(upcoming_notice);

        let (cards, slugs, cards_notice) = view::channel_cards(&context);
        store.set_channel_current(clamp(store.get_channel_current(), cards.len()));
        store.set_channels(model(cards));
        store.set_channels_notice(cards_notice);
        app.channel_rows = slugs;

        let x = view::x(&context);
        store.set_x_current(clamp(store.get_x_current(), x.rows.len()));
        store.set_x_facts(model(x.facts));
        store.set_x_kpis(model(x.kpis));
        store.set_x_posts(model(x.rows));
        store.set_x_notice(x.notice);

        let whatsapp = view::whatsapp(&context);
        store.set_contact_current(clamp(store.get_contact_current(), whatsapp.rows.len()));
        store.set_wa_facts(model(whatsapp.facts));
        store.set_wa_rules_label(whatsapp.rules_label.into());
        store.set_wa_rules(model(whatsapp.rules.into_iter().map(Into::into).collect()));
        store.set_wa_contacts(model(whatsapp.rows));
        store.set_wa_notice(whatsapp.notice);

        let (ml_facts, products, ml_notice) = view::mercadolivre(&context);
        store.set_ml_facts(model(ml_facts));
        store.set_products(model(products));
        store.set_ml_notice(ml_notice);

        let sources = view::sources(snapshot, &app.search);
        store.set_source_current(clamp(store.get_source_current(), sources.len()));
        store.set_sources(model(sources));
        store.set_login_banner(view::login_banner(snapshot).into());
    }
    render_channel_detail(ui, app);
    request_thumbs(ui, app, missing_thumbs);
}

fn request_thumbs(ui: &AppWindow, app: &mut App, paths: Vec<PathBuf>) {
    let paths: Vec<PathBuf> = paths
        .into_iter()
        .filter(|path| app.pending_thumbs.insert(path.clone()))
        .collect();
    if paths.is_empty() {
        return;
    }
    let weak = ui.as_weak();
    std::thread::spawn(move || {
        let decoded: Vec<(PathBuf, Option<SharedPixelBuffer<Rgba8Pixel>>)> = paths
            .into_iter()
            .map(|path| {
                let buffer = thumbs::decode(&path);
                (path, buffer)
            })
            .collect();
        let _ = slint::invoke_from_event_loop(move || {
            let Some(ui) = weak.upgrade() else { return };
            with_app(|app| {
                for (path, buffer) in decoded {
                    app.pending_thumbs.remove(&path);
                    // A file that cannot be decoded keeps the "sem thumb" placeholder.
                    let image = buffer.map(Image::from_rgba8).unwrap_or_default();
                    app.thumbs.insert(path, image);
                }
                render_shorts(&ui, app);
            });
        });
    });
}

/// Reads every source on a worker thread. A newer reload supersedes an older one.
fn reload(ui: &AppWindow, manual: bool) {
    let Some((root, generation)) = with_app(|app| {
        app.loading = true;
        app.generation += 1;
        if manual {
            app.thumbs.clear();
        }
        (app.root.clone(), app.generation)
    }) else {
        return;
    };
    let store = ui.global::<Store>();
    store.set_loading(true);
    set_status(ui, "Lendo registros…");
    let weak = ui.as_weak();
    std::thread::spawn(move || {
        let snapshot = Snapshot::load(&root, view::now());
        let sessions = StateLoader::new(&root)
            .load()
            .map_err(|error| format!("{error:#}"));
        let _ = slint::invoke_from_event_loop(move || {
            let Some(ui) = weak.upgrade() else { return };
            with_app(|app| {
                if app.generation != generation {
                    return;
                }
                app.loading = false;
                let videos: usize = snapshot
                    .channels
                    .iter()
                    .map(|data| data.runs.videos.len())
                    .sum();
                let shorts: usize = snapshot
                    .channels
                    .iter()
                    .filter_map(|data| data.shorts.as_ref())
                    .map(|shorts| shorts.videos.len())
                    .sum();
                let problems = snapshot
                    .sources()
                    .iter()
                    .filter(|source| matches!(source.state, reports::SourceState::Invalid(_)))
                    .count();
                match sessions {
                    Ok(sessions) => {
                        app.sessions = sessions;
                        app.sessions_error = None;
                    }
                    Err(error) => app.sessions_error = Some(error),
                }
                app.snapshot = Some(snapshot);
                let store = ui.global::<Store>();
                store.set_updated_text(
                    format!("Atualizado às {}", view::now().format("%H:%M:%S")).into(),
                );
                set_status(
                    &ui,
                    format!(
                        "{} vídeos e {} shorts lidos · {} sessões{}",
                        videos,
                        shorts,
                        app.sessions.len(),
                        if problems > 0 {
                            format!(" · {problems} registro(s) inválido(s), veja Configurações")
                        } else {
                            String::new()
                        }
                    ),
                );
                render_all(&ui, app);
            });
        });
    });
}

fn poll_sessions(ui: &AppWindow) {
    let Some(root) = with_app(|app| app.root.clone()) else {
        return;
    };
    let weak = ui.as_weak();
    std::thread::spawn(move || {
        let result = StateLoader::new(&root)
            .load()
            .map_err(|error| format!("{error:#}"));
        let _ = slint::invoke_from_event_loop(move || {
            let Some(ui) = weak.upgrade() else { return };
            with_app(|app| {
                let changed = match &result {
                    Ok(sessions) => *sessions != app.sessions || app.sessions_error.is_some(),
                    Err(error) => app.sessions_error.as_ref() != Some(error),
                };
                if !changed {
                    return;
                }
                match result {
                    Ok(sessions) => {
                        app.sessions = sessions;
                        app.sessions_error = None;
                    }
                    Err(error) => app.sessions_error = Some(error),
                }
                render_sessions(&ui, app);
            });
        });
    });
}

fn run_action(ui: &AppWindow, row: i32, open: bool) {
    let Some((session, root)) = with_app(|app| {
        let index = *app.session_rows.get(usize::try_from(row).ok()?)?;
        Some((app.sessions.get(index)?.clone(), app.root.clone()))
    })
    .flatten() else {
        return;
    };
    let store = ui.global::<Store>();
    store.set_action_busy(true);
    set_status(
        ui,
        format!(
            "{} {}…",
            if open {
                "Abrindo janela de"
            } else {
                "Parando navegador de"
            },
            session.label
        ),
    );
    let weak = ui.as_weak();
    std::thread::spawn(move || {
        let actions = CliActions::new(root);
        let result = if open {
            actions.open(&session)
        } else {
            actions.stop(&session)
        };
        let message = match result {
            Ok(_) if open => format!("Janela aberta: {}", session.label),
            Ok(_) => format!("Navegador parado: {}", session.label),
            Err(error) => format!(
                "Falha ao {} {}: {}",
                if open { "abrir" } else { "parar" },
                session.label,
                view::excerpt(&error.to_string(), 160)
            ),
        };
        let _ = slint::invoke_from_event_loop(move || {
            let Some(ui) = weak.upgrade() else { return };
            ui.global::<Store>().set_action_busy(false);
            set_status(&ui, message);
            poll_sessions(&ui);
        });
    });
}

fn restart_refresh_timer(timer: &Rc<Timer>, ui: &AppWindow, seconds: u32) {
    timer.stop();
    if seconds == 0 {
        return;
    }
    let weak = ui.as_weak();
    timer.start(
        TimerMode::Repeated,
        Duration::from_secs(u64::from(seconds)),
        move || {
            let Some(ui) = weak.upgrade() else { return };
            if with_app(|app| app.loading) == Some(false) {
                reload(&ui, false);
            }
        },
    );
}

fn expand_home(value: &str) -> PathBuf {
    match (value.strip_prefix("~/"), std::env::var_os("HOME")) {
        (Some(rest), Some(home)) => PathBuf::from(home).join(rest),
        _ => PathBuf::from(value),
    }
}

fn main() -> Result<(), slint::PlatformError> {
    let settings_path = Settings::default_path();
    let settings = settings_path
        .as_deref()
        .map(Settings::load)
        .unwrap_or_default();
    let (root, root_origin) = resolve_root(&settings);
    let today = view::now().date();

    let ui = AppWindow::new()?;
    ui.global::<Theme>()
        .set_dark(settings.theme == ThemeChoice::Dark);
    let store = ui.global::<Store>();
    store.set_root_input(home_relative(&root).into());
    let mut options: Vec<slint::SharedString> = vec!["Todos os canais".into()];
    options.extend(
        CHANNELS
            .iter()
            .map(|channel| slint::SharedString::from(channel.name)),
    );
    store.set_channel_options(model(options));
    let refresh_seconds = settings.refresh_seconds;

    APP.with(|cell| {
        *cell.borrow_mut() = Some(App {
            root,
            root_origin,
            settings,
            settings_path,
            snapshot: None,
            sessions: Vec::new(),
            sessions_error: None,
            session_rows: Vec::new(),
            channel_rows: Vec::new(),
            period: Period::this_month(today),
            channel: None,
            search: String::new(),
            open_channel: None,
            loading: true,
            generation: 0,
            thumbs: HashMap::new(),
            pending_thumbs: HashSet::new(),
        });
    });
    with_app(|app| render_all(&ui, app));

    let refresh_timer = Rc::new(Timer::default());
    restart_refresh_timer(&refresh_timer, &ui, refresh_seconds);
    let sessions_timer = Timer::default();
    {
        let weak = ui.as_weak();
        sessions_timer.start(TimerMode::Repeated, SESSIONS_POLL, move || {
            if let Some(ui) = weak.upgrade() {
                poll_sessions(&ui);
            }
        });
    }

    let bridge = ui.global::<Bridge>();
    let weak = ui.as_weak();
    bridge.on_refresh(move || {
        if let Some(ui) = weak.upgrade() {
            reload(&ui, true);
        }
    });

    let weak = ui.as_weak();
    bridge.on_navigate(move |page| {
        let Some(ui) = weak.upgrade() else { return };
        let store = ui.global::<Store>();
        store.set_page(page);
        store.set_search_text("".into());
        if page == 1 {
            store.set_channel_open(false);
        }
        with_app(|app| {
            app.search.clear();
            render_all(&ui, app);
        });
    });

    let weak = ui.as_weak();
    bridge.on_search_changed(move |text| {
        let Some(ui) = weak.upgrade() else { return };
        with_app(|app| {
            app.search = text.to_string();
            render_all(&ui, app);
        });
    });

    let weak = ui.as_weak();
    bridge.on_period_picked(move |index| {
        let Some(ui) = weak.upgrade() else { return };
        let store = ui.global::<Store>();
        store.set_period_index(index);
        store.set_period_error("".into());
        with_app(|app| {
            let today = view::now().date();
            match index {
                0 => app.period = Period::this_month(today),
                1 => app.period = Period::last_30_days(today),
                _ => {
                    if parse_date_input(&store.get_custom_start()).is_none() {
                        store.set_custom_start(
                            app.period.start.format("%d/%m/%Y").to_string().into(),
                        );
                    }
                    if parse_date_input(&store.get_custom_end()).is_none() {
                        store.set_custom_end(app.period.end.format("%d/%m/%Y").to_string().into());
                    }
                    return;
                }
            }
            render_all(&ui, app);
        });
    });

    let weak = ui.as_weak();
    bridge.on_apply_custom_period(move |start, end| {
        let Some(ui) = weak.upgrade() else { return };
        let store = ui.global::<Store>();
        match Period::from_inputs(&start, &end) {
            Ok(period) => {
                store.set_period_error("".into());
                with_app(|app| {
                    app.period = period;
                    render_all(&ui, app);
                });
            }
            Err(error) => store.set_period_error(error.to_string().into()),
        }
    });

    let weak = ui.as_weak();
    bridge.on_channel_filter_picked(move |index| {
        let Some(ui) = weak.upgrade() else { return };
        with_app(|app| {
            app.channel = usize::try_from(index - 1)
                .ok()
                .and_then(|position| CHANNELS.get(position))
                .map(|channel| channel.slug);
            render_all(&ui, app);
        });
    });

    let weak = ui.as_weak();
    bridge.on_open_channel(move |index| {
        let Some(ui) = weak.upgrade() else { return };
        with_app(|app| {
            let Some(slug) = usize::try_from(index)
                .ok()
                .and_then(|position| app.channel_rows.get(position).copied())
            else {
                return;
            };
            app.open_channel = Some(slug);
            let store = ui.global::<Store>();
            store.set_video_current(-1);
            render_channel_detail(&ui, app);
            store.set_channel_open(true);
        });
    });

    let weak = ui.as_weak();
    bridge.on_open_session(move |row| {
        if let Some(ui) = weak.upgrade() {
            run_action(&ui, row, true);
        }
    });

    let weak = ui.as_weak();
    bridge.on_stop_session(move |row| {
        if let Some(ui) = weak.upgrade() {
            run_action(&ui, row, false);
        }
    });

    let weak = ui.as_weak();
    bridge.on_theme_picked(move |dark| {
        let Some(ui) = weak.upgrade() else { return };
        ui.global::<Theme>().set_dark(dark);
        let saved = with_app(|app| {
            app.settings.theme = if dark {
                ThemeChoice::Dark
            } else {
                ThemeChoice::Light
            };
            save_settings(app)
        });
        set_status(
            &ui,
            match saved {
                Some(Err(error)) => format!("Tema aplicado, mas não salvo: {error}"),
                _ => format!("Tema {} salvo", if dark { "escuro" } else { "claro" }),
            },
        );
    });

    let weak = ui.as_weak();
    let timer = refresh_timer.clone();
    bridge.on_refresh_interval_picked(move |index| {
        let Some(ui) = weak.upgrade() else { return };
        let Some(seconds) = usize::try_from(index)
            .ok()
            .and_then(|position| REFRESH_CHOICES.get(position).copied())
        else {
            return;
        };
        let saved = with_app(|app| {
            app.settings.refresh_seconds = seconds;
            let saved = save_settings(app);
            render_settings(&ui, app);
            saved
        });
        restart_refresh_timer(&timer, &ui, seconds);
        set_status(
            &ui,
            match saved {
                Some(Err(error)) => format!("Intervalo aplicado, mas não salvo: {error}"),
                _ => format!("Atualização automática {}", refresh_label(seconds)),
            },
        );
    });

    let weak = ui.as_weak();
    bridge.on_apply_root(move |value| {
        let Some(ui) = weak.upgrade() else { return };
        let store = ui.global::<Store>();
        let path = expand_home(value.trim());
        if !path.is_absolute() || !path.join(".local").is_dir() {
            store.set_root_error(
                format!(
                    "{} não é uma raiz válida: use um caminho absoluto com a pasta .local/.",
                    path.display()
                )
                .into(),
            );
            return;
        }
        let env_wins = std::env::var_os("YTBOT_ROOT").is_some();
        store.set_root_error(if env_wins {
            "Salvo, mas YTBOT_ROOT está definida e continua com prioridade.".into()
        } else {
            "".into()
        });
        let saved = with_app(|app| {
            app.settings.root = Some(path.clone());
            let saved = save_settings(app);
            (app.root, app.root_origin) = resolve_root(&app.settings);
            app.snapshot = None;
            app.open_channel = None;
            store.set_root_input(home_relative(&app.root).into());
            render_all(&ui, app);
            saved
        });
        if let Some(Err(error)) = saved {
            store.set_root_error(format!("Raiz aplicada, mas não salva: {error}").into());
        }
        store.set_channel_open(false);
        reload(&ui, true);
    });

    let weak = ui.as_weak();
    bridge.on_reset_root(move || {
        let Some(ui) = weak.upgrade() else { return };
        let store = ui.global::<Store>();
        store.set_root_error("".into());
        with_app(|app| {
            app.settings.root = None;
            if let Err(error) = save_settings(app) {
                store.set_root_error(format!("Raiz restaurada, mas não salva: {error}").into());
            }
            (app.root, app.root_origin) = resolve_root(&app.settings);
            app.snapshot = None;
            app.open_channel = None;
            store.set_root_input(home_relative(&app.root).into());
            render_all(&ui, app);
        });
        store.set_channel_open(false);
        reload(&ui, true);
    });

    reload(&ui, false);
    ui.show()?;
    // The initial size is applied once the window exists; afterwards the owner resizes freely.
    let weak = ui.as_weak();
    Timer::single_shot(Duration::from_millis(0), move || {
        if let Some(ui) = weak.upgrade() {
            ui.window().set_size(slint::LogicalSize::new(1280.0, 800.0));
        }
    });
    slint::run_event_loop()?;
    ui.hide()
}
