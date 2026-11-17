//! Session actions, decoupled from the UI through a small trait.

use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{Result, bail};

use crate::model::SessionInfo;

pub trait SessionActions {
    fn open(&self, session: &SessionInfo) -> Result<String>;
    fn stop(&self, session: &SessionInfo) -> Result<String>;
}

/// Runs the existing typed Python CLI; no shell, no arbitrary arguments.
#[derive(Clone)]
pub struct CliActions {
    root: PathBuf,
}

impl CliActions {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    fn run(&self, scope: &str, action: &str, network: &str) -> Result<String> {
        let output = Command::new("python3")
            .current_dir(&self.root)
            .args(["-m", "tools.ytbot", scope, action, "--network", network])
            .output()?;
        let text = String::from_utf8_lossy(&output.stdout).trim().to_owned();
        if !output.status.success() {
            let error = String::from_utf8_lossy(&output.stderr).trim().to_owned();
            bail!("{}", if error.is_empty() { text } else { error });
        }
        Ok(text)
    }

    fn dispatch(&self, session: &SessionInfo, action: &str) -> Result<String> {
        match session.scope.as_str() {
            "commercial" | "social" => self.run(&session.scope, action, &session.key),
            _ => bail!("ações de navegador não se aplicam a {}", session.network),
        }
    }
}

impl SessionActions for CliActions {
    fn open(&self, session: &SessionInfo) -> Result<String> {
        self.dispatch(session, "open")
    }

    fn stop(&self, session: &SessionInfo) -> Result<String> {
        self.dispatch(session, "stop")
    }
}

pub fn command_preview(root: &Path, session: &SessionInfo, action: &str) -> Option<String> {
    matches!(session.scope.as_str(), "commercial" | "social").then(|| {
        format!(
            "python3 -m tools.ytbot {} {} --network {}",
            session.scope, action, session.key
        )
        .replace(root.to_string_lossy().as_ref(), ".")
    })
}
