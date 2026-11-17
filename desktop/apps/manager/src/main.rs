//! YoutubeBot desktop manager: read-only registry view plus bounded session actions.

use std::cell::RefCell;
use std::rc::Rc;

use manager_core::{CliActions, SessionActions, SessionInfo, StateLoader};
use slint::VecModel;

slint::include_modules!();

struct AppState {
    all: Vec<SessionInfo>,
    actions: CliActions,
}

impl AppState {
    fn filtered(&self, filter: &str) -> Vec<SessionInfo> {
        if filter.is_empty() || filter == "all" {
            self.all.clone()
        } else {
            self.all
                .iter()
                .filter(|session| session.network == filter)
                .cloned()
                .collect()
        }
    }
}

fn rows(sessions: &[SessionInfo]) -> Vec<SessionRow> {
    sessions
        .iter()
        .map(|session| SessionRow {
            id: session.id.clone().into(),
            label: session.label.clone().into(),
            network: session.network.clone().into(),
            channel: session.channel.clone().into(),
            status: session.status.clone().into(),
            detail: session.detail.clone().into(),
            key: session.key.clone().into(),
            scope: session.scope.clone().into(),
            actionable: session.supports_actions(),
        })
        .collect()
}

fn apply_filter(ui: &AppWindow, state: &Rc<RefCell<AppState>>, filter: &str) {
    let sessions = state.borrow().filtered(filter);
    let model = Rc::new(VecModel::from(rows(&sessions)));
    ui.set_sessions(model.into());
    ui.set_active_filter(filter.into());
    ui.set_selected(-1);
    ui.set_status_text(format!("{} sessão(ões) exibida(s)", sessions.len()).into());
}

fn main() -> Result<(), slint::PlatformError> {
    let root = manager_core::state::project_root()
        .map_err(|error| slint::PlatformError::Other(error.to_string()))?;
    let loader = StateLoader::new(&root);
    let all = loader
        .load()
        .map_err(|error| slint::PlatformError::Other(error.to_string()))?;
    let state = Rc::new(RefCell::new(AppState {
        all,
        actions: CliActions::new(root),
    }));

    let ui = AppWindow::new()?;
    let model = Rc::new(VecModel::from(rows(&state.borrow().all)));
    ui.set_sessions(model.into());
    ui.set_status_text(format!("{} sessão(ões) carregada(s)", state.borrow().all.len()).into());

    let weak = ui.as_weak();
    let state_refresh = state.clone();
    ui.on_refresh(move || {
        let Some(ui) = weak.upgrade() else { return };
        let loader = StateLoader::new(manager_core::state::project_root().unwrap_or_default());
        match loader.load() {
            Ok(all) => {
                state_refresh.borrow_mut().all = all;
                let filter = ui.get_active_filter().to_string();
                apply_filter(&ui, &state_refresh, &filter);
            }
            Err(error) => ui.set_status_text(format!("Falha ao ler o registro: {error}").into()),
        }
    });

    let weak = ui.as_weak();
    let state_filter = state.clone();
    ui.on_filter_changed(move |filter| {
        let Some(ui) = weak.upgrade() else { return };
        apply_filter(&ui, &state_filter, filter.as_str());
    });

    let weak = ui.as_weak();
    let state_open = state.clone();
    ui.on_open_selected(move |index| {
        let Some(ui) = weak.upgrade() else { return };
        let sessions = state_open
            .borrow()
            .filtered(ui.get_active_filter().as_str());
        let Some(session) = sessions.get(index as usize).cloned() else {
            return;
        };
        let actions = state_open.borrow().actions.clone();
        let weak = ui.as_weak();
        std::thread::spawn(move || {
            let message = match actions.open(&session) {
                Ok(_) => format!("Janela aberta: {}", session.label),
                Err(error) => format!("Falha ao abrir {}: {error}", session.label),
            };
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(ui) = weak.upgrade() {
                    ui.set_status_text(message.into());
                }
            });
        });
    });

    let weak = ui.as_weak();
    let state_stop = state.clone();
    ui.on_stop_selected(move |index| {
        let Some(ui) = weak.upgrade() else { return };
        let sessions = state_stop
            .borrow()
            .filtered(ui.get_active_filter().as_str());
        let Some(session) = sessions.get(index as usize).cloned() else {
            return;
        };
        let actions = state_stop.borrow().actions.clone();
        let weak = ui.as_weak();
        std::thread::spawn(move || {
            let message = match actions.stop(&session) {
                Ok(_) => format!("Navegador parado: {}", session.label),
                Err(error) => format!("Falha ao parar {}: {error}", session.label),
            };
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(ui) = weak.upgrade() {
                    ui.set_status_text(message.into());
                }
            });
        });
    });

    ui.run()
}
