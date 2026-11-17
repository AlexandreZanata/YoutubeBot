//! Owner preferences for the desktop manager, stored outside the repository in
//! `$XDG_CONFIG_HOME/ytbot-manager/settings.json`. This is the only file the app writes.

use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Theme {
    Light,
    #[default]
    Dark,
}

/// Allowed refresh intervals in seconds; 0 turns automatic refresh off.
pub const REFRESH_CHOICES: [u32; 4] = [0, 30, 60, 300];

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    pub theme: Theme,
    pub refresh_seconds: u32,
    /// Project root chosen in Settings; `YTBOT_ROOT` still wins when set.
    pub root: Option<PathBuf>,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            theme: Theme::Dark,
            refresh_seconds: 60,
            root: None,
        }
    }
}

impl Settings {
    /// Missing or unreadable settings fall back to the defaults; unknown fields are ignored.
    pub fn load(path: &Path) -> Self {
        let mut settings: Self = fs::read_to_string(path)
            .ok()
            .and_then(|text| serde_json::from_str(&text).ok())
            .unwrap_or_default();
        if !REFRESH_CHOICES.contains(&settings.refresh_seconds) {
            settings.refresh_seconds = Self::default().refresh_seconds;
        }
        settings
    }

    /// Atomic write (temporary file + rename) with a private directory.
    pub fn save(&self, path: &Path) -> Result<()> {
        let parent = path.parent().context("settings path has no parent")?;
        fs::create_dir_all(parent)
            .with_context(|| format!("cannot create {}", parent.display()))?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = fs::set_permissions(parent, fs::Permissions::from_mode(0o700));
        }
        let temporary = path.with_extension("json.tmp");
        let text = serde_json::to_string_pretty(self)? + "\n";
        fs::write(&temporary, text)
            .with_context(|| format!("cannot write {}", temporary.display()))?;
        fs::rename(&temporary, path)
            .with_context(|| format!("cannot replace {}", path.display()))?;
        Ok(())
    }

    /// `$YTBOT_MANAGER_CONFIG`, else `$XDG_CONFIG_HOME/ytbot-manager/settings.json`,
    /// else `~/.config/ytbot-manager/settings.json`.
    pub fn default_path() -> Option<PathBuf> {
        if let Some(path) = std::env::var_os("YTBOT_MANAGER_CONFIG") {
            return Some(PathBuf::from(path));
        }
        let base = std::env::var_os("XDG_CONFIG_HOME")
            .map(PathBuf::from)
            .filter(|path| path.is_absolute())
            .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".config")))?;
        Some(base.join("ytbot-manager").join("settings.json"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn settings_round_trip_and_tolerate_unknown_or_invalid_values() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("nested/settings.json");
        assert_eq!(Settings::load(&path), Settings::default());

        let settings = Settings {
            theme: Theme::Light,
            refresh_seconds: 300,
            root: Some(PathBuf::from("/srv/ytbot")),
        };
        settings.save(&path).unwrap();
        assert_eq!(Settings::load(&path), settings);

        fs::write(
            &path,
            r#"{"theme":"light","refresh_seconds":7,"future":true}"#,
        )
        .unwrap();
        let loaded = Settings::load(&path);
        assert_eq!(loaded.theme, Theme::Light);
        assert_eq!(loaded.refresh_seconds, 60, "an unsupported interval resets");

        fs::write(&path, "{broken").unwrap();
        assert_eq!(Settings::load(&path), Settings::default());
    }
}
