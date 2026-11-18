//! X (Twitter) records: published posts, replies, discovery and the logged account.

use std::collections::{BTreeMap, HashMap};
use std::path::Path;

use chrono::NaiveDateTime;
use serde::Deserialize;

use crate::source::{SourceStatus, lenient, load_json};
use crate::time::{self, Period};

/// `account.json` written by `social status` / `commercial status`.
#[derive(Debug, Clone, Default, PartialEq, Eq, Deserialize)]
pub struct NetworkAccount {
    #[serde(default, deserialize_with = "lenient::string")]
    pub state: String,
    #[serde(default, deserialize_with = "lenient::string")]
    pub handle: String,
    #[serde(default, deserialize_with = "lenient::string")]
    pub display_name: String,
    #[serde(default, deserialize_with = "lenient::string")]
    pub verified_at: String,
}

impl NetworkAccount {
    pub fn verified(&self) -> Option<NaiveDateTime> {
        time::parse_timestamp(&self.verified_at)
    }

    pub fn logged_in(&self) -> bool {
        self.state == "logged-in"
    }
}

pub fn load_account(
    root: &Path,
    scope: &str,
    network: &str,
    label: &str,
) -> (Option<NetworkAccount>, SourceStatus) {
    let path = root
        .join(".local")
        .join(scope)
        .join(network)
        .join("account.json");
    let mut source = SourceStatus::new(label, root, &path);
    let account = load_json::<NetworkAccount>(&path, &mut source);
    source.records = usize::from(account.is_some());
    (account, source)
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct XPost {
    pub id: String,
    pub state: String,
    /// Text from the agenda item, when the agenda is available.
    pub text: String,
    pub url: String,
    pub posted_at: Option<NaiveDateTime>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct XReply {
    pub state: String,
    pub posted_at: Option<NaiveDateTime>,
}

#[derive(Debug, Clone, Default)]
pub struct XReport {
    pub account: Option<NetworkAccount>,
    /// Newest first.
    pub posts: Vec<XPost>,
    pub replies: Vec<XReply>,
    pub discovery_items: usize,
    pub discovery_at: Option<NaiveDateTime>,
    pub sources: Vec<SourceStatus>,
}

#[derive(Debug, Default, Deserialize)]
struct PostsFile {
    #[serde(default)]
    posts: BTreeMap<String, PostRecord>,
}

#[derive(Debug, Default, Deserialize)]
struct PostRecord {
    #[serde(default, deserialize_with = "lenient::string")]
    state: String,
    #[serde(default, deserialize_with = "lenient::string")]
    item_id: String,
    #[serde(default, deserialize_with = "lenient::string")]
    tweet_url: String,
    #[serde(default, deserialize_with = "lenient::string")]
    posted_at: String,
}

#[derive(Debug, Default, Deserialize)]
struct RepliesFile {
    #[serde(default)]
    replies: BTreeMap<String, ReplyRecord>,
}

#[derive(Debug, Default, Deserialize)]
struct ReplyRecord {
    #[serde(default, deserialize_with = "lenient::string")]
    state: String,
    #[serde(default, deserialize_with = "lenient::string")]
    posted_at: String,
}

#[derive(Debug, Default, Deserialize)]
struct DiscoveryFile {
    #[serde(default, deserialize_with = "lenient::string")]
    created_at: String,
    #[serde(default)]
    items: Vec<serde_json::Value>,
}

#[derive(Debug, Default, Deserialize)]
struct AgendaFile {
    #[serde(default)]
    items: Vec<AgendaItem>,
}

#[derive(Debug, Default, Deserialize)]
struct AgendaItem {
    #[serde(default, deserialize_with = "lenient::string")]
    id: String,
    #[serde(default, deserialize_with = "lenient::string")]
    text: String,
}

pub fn load_x(root: &Path) -> XReport {
    let base = root.join(".local/social/x");
    let (account, account_source) = load_account(root, "social", "x", "X · sessão");
    let mut report = XReport {
        account,
        ..XReport::default()
    };
    report.sources.push(account_source);

    let agenda_path = root.join(".local/promotion/agenda.json");
    let mut agenda_source = SourceStatus::new("X · agenda (texto dos posts)", root, &agenda_path);
    let texts: HashMap<String, String> = load_json::<AgendaFile>(&agenda_path, &mut agenda_source)
        .map(|agenda| {
            agenda
                .items
                .into_iter()
                .map(|item| (item.id, item.text))
                .collect()
        })
        .unwrap_or_default();
    agenda_source.records = texts.len();

    let posts_path = base.join("posts.json");
    let mut posts_source = SourceStatus::new("X · posts", root, &posts_path);
    if let Some(file) = load_json::<PostsFile>(&posts_path, &mut posts_source) {
        report.posts = file
            .posts
            .into_iter()
            .map(|(key, post)| {
                let id = if post.item_id.is_empty() {
                    key
                } else {
                    post.item_id
                };
                XPost {
                    text: texts.get(&id).cloned().unwrap_or_default(),
                    id,
                    state: post.state,
                    url: post.tweet_url,
                    posted_at: time::parse_timestamp(&post.posted_at),
                }
            })
            .collect();
        report
            .posts
            .sort_by_key(|post| std::cmp::Reverse(post.posted_at));
        posts_source.records = report.posts.len();
    }
    report.sources.push(posts_source);
    report.sources.push(agenda_source);

    let replies_path = base.join("replies.json");
    let mut replies_source = SourceStatus::new("X · respostas", root, &replies_path);
    if let Some(file) = load_json::<RepliesFile>(&replies_path, &mut replies_source) {
        report.replies = file
            .replies
            .into_values()
            .map(|reply| XReply {
                state: reply.state,
                posted_at: time::parse_timestamp(&reply.posted_at),
            })
            .collect();
        replies_source.records = report.replies.len();
    }
    report.sources.push(replies_source);

    let discovery_path = base.join("discovery.json");
    let mut discovery_source = SourceStatus::new("X · discovery", root, &discovery_path);
    if let Some(file) = load_json::<DiscoveryFile>(&discovery_path, &mut discovery_source) {
        report.discovery_items = file.items.len();
        report.discovery_at = time::parse_timestamp(&file.created_at);
        discovery_source.records = file.items.len();
    }
    report.sources.push(discovery_source);
    report
}

impl XReport {
    pub fn posts_available(&self) -> bool {
        self.sources
            .iter()
            .any(|source| source.label == "X · posts" && source.is_available())
    }

    pub fn replies_available(&self) -> bool {
        self.sources
            .iter()
            .any(|source| source.label == "X · respostas" && source.is_available())
    }

    /// Published posts (state `posted`) in the period; deleted ones do not count.
    pub fn posts_in(&self, period: &Period) -> usize {
        self.posts
            .iter()
            .filter(|post| post.state == "posted" && period.contains_opt(post.posted_at))
            .count()
    }

    pub fn posts_listed_in(&self, period: &Period) -> Vec<&XPost> {
        self.posts
            .iter()
            .filter(|post| period.contains_opt(post.posted_at))
            .collect()
    }

    /// Replies in the period by state: (`posted`, everything else such as `unconfirmed`).
    pub fn replies_in(&self, period: &Period) -> (usize, usize) {
        self.replies
            .iter()
            .filter(|reply| period.contains_opt(reply.posted_at))
            .fold((0, 0), |(posted, other), reply| {
                if reply.state == "posted" {
                    (posted + 1, other)
                } else {
                    (posted, other + 1)
                }
            })
    }
}
