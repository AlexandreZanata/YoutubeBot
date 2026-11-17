//! Reads the private registries written by the Python bot.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::Deserialize;

use crate::model::SessionInfo;

const NETWORKS: &[(&str, &str, &str)] = &[
    ("commercial", "whatsapp", "WhatsApp"),
    ("commercial", "mercadolivre", "Mercado Livre"),
    ("social", "x", "X"),
    ("social", "instagram", "Instagram"),
];

#[derive(Debug, Default, Deserialize)]
struct Registry {
    #[serde(default)]
    accounts: BTreeMap<String, AccountRecord>,
    #[serde(default)]
    bindings: BTreeMap<String, Binding>,
}

#[derive(Debug, Deserialize)]
struct AccountRecord {
    #[serde(default)]
    id: String,
    #[serde(default)]
    label: String,
    #[serde(default)]
    cdp_port: u16,
    #[serde(default)]
    browser_mode: String,
}

#[derive(Debug, Deserialize)]
struct Binding {
    #[serde(default)]
    account_id: String,
    #[serde(default)]
    channel_id: String,
}

#[derive(Debug, Deserialize)]
struct NetworkAccount {
    #[serde(default)]
    state: String,
    #[serde(default)]
    handle: String,
    #[serde(default)]
    display_name: String,
    #[serde(default)]
    verified_at: String,
}

/// Loads every session known to the project from disk.
pub struct StateLoader {
    root: PathBuf,
}

impl StateLoader {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    pub fn load(&self) -> Result<Vec<SessionInfo>> {
        let mut sessions = self.youtube_sessions()?;
        sessions.extend(self.network_sessions()?);
        sessions.sort_by(|left, right| {
            (
                left.scope.as_str(),
                left.network.as_str(),
                left.label.as_str(),
            )
                .cmp(&(
                    right.scope.as_str(),
                    right.network.as_str(),
                    right.label.as_str(),
                ))
        });
        Ok(sessions)
    }

    fn youtube_sessions(&self) -> Result<Vec<SessionInfo>> {
        let path = self.root.join(".local/accounts/registry.json");
        let Ok(text) = fs::read_to_string(&path) else {
            return Ok(Vec::new());
        };
        let registry: Registry = serde_json::from_str(&text)
            .with_context(|| format!("invalid registry: {}", path.display()))?;
        let channels: BTreeMap<&str, &str> = registry
            .bindings
            .values()
            .map(|binding| (binding.account_id.as_str(), binding.channel_id.as_str()))
            .collect();
        let mut sessions = Vec::new();
        for account in registry.accounts.values() {
            let id = if account.id.is_empty() {
                continue;
            } else {
                account.id.clone()
            };
            let channel = channels.get(id.as_str()).copied().unwrap_or("");
            let running = chrome_lock_pid(&self.root.join(".local/accounts/browser").join(&id))
                .is_some_and(pid_alive);
            sessions.push(SessionInfo {
                label: if account.label.is_empty() {
                    id.clone()
                } else {
                    account.label.clone()
                },
                network: "YouTube".into(),
                key: id.clone(),
                channel: channel.to_owned(),
                status: if account.cdp_port > 0 {
                    "configurado".into()
                } else {
                    "sem navegador".into()
                },
                detail: if account.browser_mode.is_empty() {
                    format!("CDP {}", account.cdp_port)
                } else {
                    format!("{} · CDP {}", account.browser_mode, account.cdp_port)
                },
                port: account.cdp_port,
                scope: "youtube".into(),
                running,
                mode: String::new(),
                id,
            });
        }
        Ok(sessions)
    }

    fn network_sessions(&self) -> Result<Vec<SessionInfo>> {
        let mut sessions = Vec::new();
        for (scope, key, display) in NETWORKS {
            let directory = self.root.join(".local").join(scope).join(key);
            let path = directory.join("account.json");
            let (running, mode) = browser_process(&directory.join("browser.pid"));
            let Ok(text) = fs::read_to_string(&path) else {
                sessions.push(SessionInfo {
                    id: format!("{scope}:{key}"),
                    label: (*display).to_owned(),
                    network: (*display).to_owned(),
                    key: (*key).to_owned(),
                    channel: String::new(),
                    status: "não conectado".into(),
                    detail: "sem sessão salva".into(),
                    port: 0,
                    scope: (*scope).to_owned(),
                    running,
                    mode: mode.clone(),
                });
                continue;
            };
            let account: NetworkAccount = serde_json::from_str(&text)
                .with_context(|| format!("invalid account: {}", path.display()))?;
            sessions.push(SessionInfo {
                id: format!("{scope}:{key}"),
                label: if account.display_name.is_empty() {
                    (*display).to_owned()
                } else {
                    account.display_name.clone()
                },
                network: (*display).to_owned(),
                key: (*key).to_owned(),
                channel: account.handle.clone(),
                status: if account.state.is_empty() {
                    "desconhecido".into()
                } else {
                    account.state.clone()
                },
                detail: account.verified_at.clone(),
                port: 0,
                scope: (*scope).to_owned(),
                running,
                mode,
            });
        }
        Ok(sessions)
    }
}

#[derive(Debug, Deserialize)]
struct BrowserPid {
    #[serde(default)]
    pid: u32,
    #[serde(default)]
    mode: String,
}

/// `browser.pid` written by the commercial/social runtime: alive flag and window mode.
fn browser_process(path: &Path) -> (bool, String) {
    let Some(record) = fs::read_to_string(path)
        .ok()
        .and_then(|text| serde_json::from_str::<BrowserPid>(&text).ok())
    else {
        return (false, String::new());
    };
    if record.pid > 0 && pid_alive(record.pid) {
        (true, record.mode)
    } else {
        (false, String::new())
    }
}

/// Chrome's `SingletonLock` is a symlink to `<host>-<pid>` while the profile is open.
fn chrome_lock_pid(profile: &Path) -> Option<u32> {
    let target = fs::read_link(profile.join("SingletonLock")).ok()?;
    let text = target.to_string_lossy();
    text.rsplit('-').next()?.parse().ok()
}

/// Read-only liveness check through `/proc`; never signals the process.
fn pid_alive(pid: u32) -> bool {
    Path::new("/proc").join(pid.to_string()).is_dir()
}

/// Absolute root used by the desktop app: the repository above `desktop/`.
pub fn project_root() -> Result<PathBuf> {
    project_root_with(None)
}

/// `YTBOT_ROOT`, then the root chosen in Settings (when it has `.local/`), then the current
/// directory, then the repository that contains this workspace.
pub fn project_root_with(preferred: Option<&Path>) -> Result<PathBuf> {
    if let Ok(value) = std::env::var("YTBOT_ROOT") {
        return Ok(PathBuf::from(value));
    }
    if let Some(path) = preferred.filter(|path| path.join(".local").is_dir()) {
        return Ok(path.to_path_buf());
    }
    let current = std::env::current_dir().context("current directory is unavailable")?;
    if current.join(".local").is_dir() {
        return Ok(current);
    }
    if let Some(parent) = Path::new(env!("CARGO_MANIFEST_DIR")).parent() {
        let root = parent.parent().unwrap_or(parent);
        if root.join(".local").is_dir() {
            return Ok(root.to_path_buf());
        }
    }
    Ok(current)
}
