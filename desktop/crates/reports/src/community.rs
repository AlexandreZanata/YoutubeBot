//! Community posts. The bot appends every journal transition to
//! `community-history.jsonl`; older installs only have the last entry in `community.json`.

use std::path::Path;

use chrono::NaiveDateTime;
use serde::Deserialize;

use crate::catalog::ChannelInfo;
use crate::source::{SourceState, SourceStatus, lenient, load_json, load_jsonl};
use crate::time::{self, Period};

pub const HISTORY_FILE: &str = "community-history.jsonl";
pub const LATEST_FILE: &str = "community.json";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommunityEntry {
    /// `started`, `unconfirmed` or `posted`.
    pub state: String,
    pub topic: String,
    pub at: Option<NaiveDateTime>,
}

#[derive(Debug, Clone)]
pub struct CommunityReport {
    /// Chronological entries.
    pub entries: Vec<CommunityEntry>,
    /// True when the append-only history was read; false for the single-entry fallback.
    pub from_history: bool,
    pub source: SourceStatus,
}

#[derive(Debug, Default, Deserialize)]
struct EntryFile {
    #[serde(default, deserialize_with = "lenient::string")]
    state: String,
    #[serde(default, deserialize_with = "lenient::string")]
    topic: String,
    #[serde(default, deserialize_with = "lenient::string")]
    at: String,
}

impl From<EntryFile> for CommunityEntry {
    fn from(entry: EntryFile) -> Self {
        Self {
            at: time::parse_timestamp(&entry.at),
            state: entry.state,
            topic: entry.topic,
        }
    }
}

pub fn load_community(root: &Path, channel: &ChannelInfo) -> CommunityReport {
    let directory = channel.data_dir(root);
    let history = directory.join(HISTORY_FILE);
    let mut source = SourceStatus::new(&format!("{} · comunidade", channel.name), root, &history);
    let lines: Vec<EntryFile> = load_jsonl(&history, &mut source);
    if source.state != SourceState::Missing {
        let mut entries: Vec<CommunityEntry> = lines.into_iter().map(Into::into).collect();
        entries.sort_by_key(|entry| entry.at);
        return CommunityReport {
            entries,
            from_history: true,
            source,
        };
    }
    let latest = directory.join(LATEST_FILE);
    let mut source = SourceStatus::new(
        &format!("{} · comunidade (último)", channel.name),
        root,
        &latest,
    );
    let entries: Vec<CommunityEntry> = load_json::<EntryFile>(&latest, &mut source)
        .map(|entry| vec![entry.into()])
        .unwrap_or_default();
    source.records = entries.len();
    CommunityReport {
        entries,
        from_history: false,
        source,
    }
}

impl CommunityReport {
    pub fn is_available(&self) -> bool {
        self.source.is_available()
    }

    pub fn posted_in(&self, period: &Period) -> usize {
        self.entries
            .iter()
            .filter(|entry| entry.state == "posted" && period.contains_opt(entry.at))
            .count()
    }

    pub fn latest_posted(&self) -> Option<&CommunityEntry> {
        self.entries
            .iter()
            .rev()
            .find(|entry| entry.state == "posted")
    }

    /// The newest entry of any state, used to warn about an unconfirmed publish.
    pub fn latest(&self) -> Option<&CommunityEntry> {
        self.entries.last()
    }
}
