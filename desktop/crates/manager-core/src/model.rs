//! Domain model shared by the desktop manager and its UI.

/// One managed session: a YouTube channel profile or a logged network account.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SessionInfo {
    pub id: String,
    pub label: String,
    pub network: String,
    pub key: String,
    pub channel: String,
    pub status: String,
    pub detail: String,
    pub port: u16,
    pub scope: String,
    /// A browser process for this profile is alive right now.
    pub running: bool,
    /// `hidden` or `visible` when the bot recorded it; empty otherwise.
    pub mode: String,
}

impl SessionInfo {
    pub fn supports_actions(&self) -> bool {
        matches!(self.scope.as_str(), "commercial" | "social")
    }
}
