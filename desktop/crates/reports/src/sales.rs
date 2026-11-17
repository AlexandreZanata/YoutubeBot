//! Zaflas sales agent Central: `.local/commercial/whatsapp/sales/central.json`, written by the
//! Python agent after every cycle (contract: docs/COMMERCIAL-WHATSAPP-SALES.md).

use std::path::{Path, PathBuf};

use chrono::NaiveDateTime;
use serde::Deserialize;

use crate::source::{SourceStatus, lenient, load_json};
use crate::time;

pub const CENTRAL_PATH: &str = ".local/commercial/whatsapp/sales/central.json";
const CLIENTS_DIR: &str = ".local/commercial/whatsapp/sales/clientes";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StateCount {
    pub state: String,
    pub label: String,
    pub group: String,
    pub owner: bool,
    pub count: usize,
}

/// A conversation the owner must take over.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Intervention {
    pub lead: String,
    pub label: String,
    pub name: String,
    pub contact_name: String,
    pub phone: String,
    pub wa_link: String,
    pub state: String,
    pub state_label: String,
    /// hot | needed | alert
    pub priority: String,
    pub priority_label: String,
    pub reason: String,
    pub last_message: String,
    pub at: Option<NaiveDateTime>,
    pub ficha: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SalesMessage {
    pub at: Option<NaiveDateTime>,
    pub label: String,
    pub name: String,
    /// "in" from the contact, "out" from the bot or the owner.
    pub dir: String,
    pub text: String,
    pub media: String,
    pub needs_owner: bool,
}

#[derive(Debug, Clone)]
pub struct SalesReport {
    pub generated_at: Option<NaiveDateTime>,
    pub states: Vec<StateCount>,
    pub interventions: Vec<Intervention>,
    pub messages: Vec<SalesMessage>,
    pub leads: usize,
    pub source: SourceStatus,
}

#[derive(Debug, Default, Deserialize)]
struct CentralFile {
    #[serde(default, deserialize_with = "lenient::string")]
    generated_at: String,
    #[serde(default)]
    states: Vec<StateLine>,
    #[serde(default)]
    interventions: Vec<InterventionLine>,
    #[serde(default)]
    messages: Vec<MessageLine>,
    #[serde(default)]
    leads: Vec<serde_json::Value>,
}

#[derive(Debug, Default, Deserialize)]
struct StateLine {
    #[serde(default, deserialize_with = "lenient::string")]
    state: String,
    #[serde(default, deserialize_with = "lenient::string")]
    label: String,
    #[serde(default, deserialize_with = "lenient::string")]
    group: String,
    #[serde(default, deserialize_with = "lenient::boolean")]
    owner: bool,
    #[serde(default, deserialize_with = "lenient::number")]
    count: Option<f64>,
}

#[derive(Debug, Default, Deserialize)]
struct InterventionLine {
    #[serde(default, deserialize_with = "lenient::string")]
    lead: String,
    #[serde(default, deserialize_with = "lenient::string")]
    label: String,
    #[serde(default, deserialize_with = "lenient::string")]
    name: String,
    #[serde(default, deserialize_with = "lenient::string")]
    contact_name: String,
    #[serde(default, deserialize_with = "lenient::string")]
    phone: String,
    #[serde(default, deserialize_with = "lenient::string")]
    wa_link: String,
    #[serde(default, deserialize_with = "lenient::string")]
    state: String,
    #[serde(default, deserialize_with = "lenient::string")]
    state_label: String,
    #[serde(default, deserialize_with = "lenient::string")]
    priority: String,
    #[serde(default, deserialize_with = "lenient::string")]
    priority_label: String,
    #[serde(default, deserialize_with = "lenient::string")]
    reason: String,
    #[serde(default, deserialize_with = "lenient::string")]
    last_message: String,
    #[serde(default, deserialize_with = "lenient::string")]
    at: String,
    #[serde(default, deserialize_with = "lenient::string")]
    ficha: String,
}

#[derive(Debug, Default, Deserialize)]
struct MessageLine {
    #[serde(default, deserialize_with = "lenient::string")]
    at: String,
    #[serde(default, deserialize_with = "lenient::string")]
    label: String,
    #[serde(default, deserialize_with = "lenient::string")]
    name: String,
    #[serde(default, deserialize_with = "lenient::string")]
    dir: String,
    #[serde(default, deserialize_with = "lenient::string")]
    text: String,
    #[serde(default, deserialize_with = "lenient::string")]
    media: String,
    #[serde(default, deserialize_with = "lenient::boolean")]
    needs_owner: bool,
}

pub fn load_sales(root: &Path) -> SalesReport {
    let path = root.join(CENTRAL_PATH);
    let mut source = SourceStatus::new("Vendas WhatsApp · central", root, &path);
    let file = load_json::<CentralFile>(&path, &mut source).unwrap_or_default();
    let mut report = SalesReport {
        generated_at: time::parse_timestamp(&file.generated_at),
        states: file
            .states
            .into_iter()
            .filter(|line| !line.state.is_empty())
            .map(|line| StateCount {
                label: if line.label.is_empty() {
                    line.state.clone()
                } else {
                    line.label
                },
                state: line.state,
                group: line.group,
                owner: line.owner,
                count: line.count.map_or(0, |count| count.max(0.0) as usize),
            })
            .collect(),
        interventions: file
            .interventions
            .into_iter()
            .filter(|line| !line.lead.is_empty())
            .map(|line| Intervention {
                at: time::parse_timestamp(&line.at),
                lead: line.lead,
                label: line.label,
                name: line.name,
                contact_name: line.contact_name,
                phone: line.phone,
                wa_link: line.wa_link,
                state: line.state,
                state_label: line.state_label,
                priority: line.priority,
                priority_label: line.priority_label,
                reason: line.reason,
                last_message: line.last_message,
                ficha: line.ficha,
            })
            .collect(),
        messages: file
            .messages
            .into_iter()
            .map(|line| SalesMessage {
                at: time::parse_timestamp(&line.at),
                label: line.label,
                name: line.name,
                dir: line.dir,
                text: line.text,
                media: line.media,
                needs_owner: line.needs_owner,
            })
            .collect(),
        leads: file.leads.len(),
        source,
    };
    report.source.records = report.leads;
    report
}

impl SalesReport {
    pub fn available(&self) -> bool {
        self.source.is_available()
    }

    /// Leads waiting for the owner (sum of the owner states).
    pub fn owner_total(&self) -> usize {
        self.states
            .iter()
            .filter(|state| state.owner)
            .map(|state| state.count)
            .sum()
    }

    /// (group, total) in the order the agent wrote the states.
    pub fn groups(&self) -> Vec<(String, usize)> {
        let mut groups: Vec<(String, usize)> = Vec::new();
        for state in &self.states {
            match groups.iter_mut().find(|(group, _)| *group == state.group) {
                Some((_, total)) => *total += state.count,
                None => groups.push((state.group.clone(), state.count)),
            }
        }
        groups
    }
}

/// Only `https://wa.me/<10 to 15 digits>` may be opened from the Central.
pub fn safe_wa_link(link: &str) -> bool {
    link.strip_prefix("https://wa.me/").is_some_and(|digits| {
        (10..=15).contains(&digits.len()) && digits.bytes().all(|byte| byte.is_ascii_digit())
    })
}

/// A `ficha.md` inside the project's private client folders, or `None`.
pub fn safe_ficha(root: &Path, ficha: &str) -> Option<PathBuf> {
    if ficha.is_empty() {
        return None;
    }
    let base = root.join(CLIENTS_DIR).canonicalize().ok()?;
    let path = Path::new(ficha).canonicalize().ok()?;
    (path.starts_with(&base) && path.file_name()? == "ficha.md" && path.is_file()).then_some(path)
}
