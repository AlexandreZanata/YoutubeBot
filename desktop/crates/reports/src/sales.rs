//! Zaflas sales agent Central: `.local/commercial/whatsapp/sales/central.json`, written by the
//! Python agent after every cycle (contract: docs/COMMERCIAL-WHATSAPP-SALES.md).
//!
//! Client fichas ("what the client wants") point at files under
//! `.local/commercial/whatsapp/sales/clientes/<slug>-<lead>/`. Every path is resolved and
//! checked to stay inside that folder; a ficha or media item that leaves it is dropped.

use std::path::{Component, Path, PathBuf};

use chrono::NaiveDateTime;
use serde::Deserialize;
use serde_json::Value;

use crate::source::{SourceStatus, lenient, load_json};
use crate::time;

pub const CENTRAL_PATH: &str = ".local/commercial/whatsapp/sales/central.json";
pub const CLIENTS_DIR: &str = ".local/commercial/whatsapp/sales/clientes";

/// Extensions a ficha's media file may have to be handed to `xdg-open`: pictures, audio,
/// video and office/text documents. Anything else (scripts, `.desktop` launchers, archives)
/// is only reachable through "Abrir pasta".
const OPENABLE_EXTENSIONS: &[&str] = &[
    "jpg", "jpeg", "png", "webp", "gif", "heic", "ogg", "oga", "opus", "mp3", "m4a", "aac", "wav",
    "amr", "mp4", "3gp", "mov", "webm", "mkv", "pdf", "txt", "csv", "doc", "docx", "xls", "xlsx",
    "ppt", "pptx", "odt", "ods", "odp", "rtf",
];

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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FichaField {
    pub label: String,
    pub value: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FichaSection {
    pub title: String,
    pub items: Vec<FichaField>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MediaKind {
    Image,
    Audio,
    Video,
    Document,
}

impl MediaKind {
    /// `image`, `audio` and `video` as written by the agent; anything else is a document.
    fn parse(value: &str) -> Self {
        match value.trim().to_lowercase().as_str() {
            "image" => Self::Image,
            "audio" => Self::Audio,
            "video" => Self::Video,
            _ => Self::Document,
        }
    }
}

/// A photo, audio, video or document the client sent, inside the ficha's own folder.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FichaMedia {
    pub kind: MediaKind,
    /// Absolute, `..`-free path inside the ficha folder (canonical when the file exists).
    pub path: PathBuf,
    pub name: String,
    pub caption: String,
    pub at: Option<NaiveDateTime>,
}

/// What a client who accepted a quote wants, built by the agent in `clientes/<slug>-<lead>/`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Ficha {
    pub lead: String,
    pub label: String,
    pub name: String,
    pub state: String,
    pub state_label: String,
    /// `site` or `sistema` (lowercase; anything else is kept as written).
    pub kind: String,
    /// Free text such as "coletando dados" or "quer comprar".
    pub status: String,
    pub updated_at: Option<NaiveDateTime>,
    pub resumo: String,
    pub sections: Vec<FichaSection>,
    pub pendencias: Vec<String>,
    pub duvidas: Vec<String>,
    pub media: Vec<FichaMedia>,
    /// `ficha.md` inside the clients folder, when the agent wrote one.
    pub ficha_md: Option<PathBuf>,
    /// The client folder, strictly inside `clientes/`.
    pub folder: PathBuf,
    pub phone: String,
    /// A safe `https://wa.me/<digits>` link, or empty.
    pub wa_link: String,
}

#[derive(Debug, Clone)]
pub struct SalesReport {
    pub generated_at: Option<NaiveDateTime>,
    pub states: Vec<StateCount>,
    pub interventions: Vec<Intervention>,
    pub messages: Vec<SalesMessage>,
    /// Newest first; fichas with a path outside the clients folder are dropped.
    pub fichas: Vec<Ficha>,
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
    /// Parsed item by item, so one broken ficha never fails the page.
    #[serde(default)]
    fichas: Value,
}

#[derive(Debug, Default, Deserialize)]
struct FichaLine {
    #[serde(default, deserialize_with = "lenient::string")]
    lead: String,
    #[serde(default, deserialize_with = "lenient::string")]
    label: String,
    #[serde(default, deserialize_with = "lenient::string")]
    name: String,
    #[serde(default, deserialize_with = "lenient::string")]
    state: String,
    #[serde(default, deserialize_with = "lenient::string")]
    state_label: String,
    #[serde(default, deserialize_with = "lenient::string")]
    kind: String,
    #[serde(default, deserialize_with = "lenient::string")]
    status: String,
    #[serde(default, deserialize_with = "lenient::string")]
    updated_at: String,
    #[serde(default, deserialize_with = "lenient::string")]
    resumo: String,
    #[serde(default, deserialize_with = "lenient::list")]
    sections: Vec<SectionLine>,
    #[serde(default, deserialize_with = "lenient::strings")]
    pendencias: Vec<String>,
    #[serde(default, deserialize_with = "lenient::strings")]
    duvidas: Vec<String>,
    #[serde(default, deserialize_with = "lenient::list")]
    media: Vec<MediaLine>,
    #[serde(default, deserialize_with = "lenient::string")]
    ficha_md: String,
    #[serde(default, deserialize_with = "lenient::string")]
    folder: String,
    #[serde(default, deserialize_with = "lenient::string")]
    phone: String,
    #[serde(default, deserialize_with = "lenient::string")]
    wa_link: String,
}

#[derive(Debug, Default, Deserialize)]
struct SectionLine {
    #[serde(default, deserialize_with = "lenient::string")]
    title: String,
    #[serde(default, deserialize_with = "lenient::list")]
    items: Vec<FieldLine>,
}

#[derive(Debug, Default, Deserialize)]
struct FieldLine {
    #[serde(default, deserialize_with = "lenient::string")]
    label: String,
    #[serde(default, deserialize_with = "lenient::string")]
    value: String,
}

#[derive(Debug, Default, Deserialize)]
struct MediaLine {
    #[serde(default, deserialize_with = "lenient::string")]
    kind: String,
    #[serde(default, deserialize_with = "lenient::string")]
    path: String,
    #[serde(default, deserialize_with = "lenient::string")]
    name: String,
    #[serde(default, deserialize_with = "lenient::string")]
    caption: String,
    #[serde(default, deserialize_with = "lenient::string")]
    at: String,
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
        fichas: Vec::new(),
        leads: file.leads.len(),
        source,
    };
    report.fichas = load_fichas(root, file.fichas, &mut report.source.skipped);
    report.source.records = report.leads;
    report
}

/// Every valid ficha, newest first. Unparsable fichas, fichas whose folder or `ficha.md`
/// leaves the clients folder and media outside their ficha's folder are dropped and counted
/// in `skipped`.
fn load_fichas(root: &Path, value: Value, skipped: &mut usize) -> Vec<Ficha> {
    let Value::Array(items) = value else {
        return Vec::new();
    };
    let clients = bases(&root.join(CLIENTS_DIR));
    let mut fichas: Vec<Ficha> = items
        .into_iter()
        .filter_map(|item| {
            let ficha = serde_json::from_value::<FichaLine>(item)
                .ok()
                .and_then(|line| ficha_from(line, &clients, skipped));
            if ficha.is_none() {
                *skipped += 1;
            }
            ficha
        })
        .collect();
    // Stable: the agent's order wins between equal (or missing) timestamps.
    fichas.sort_by_key(|ficha| std::cmp::Reverse(ficha.updated_at));
    fichas
}

fn ficha_from(line: FichaLine, clients: &[PathBuf], skipped: &mut usize) -> Option<Ficha> {
    if line.lead.trim().is_empty() {
        return None;
    }
    let folder = resolve_within(&line.folder, clients)?;
    let ficha_md = if line.ficha_md.trim().is_empty() {
        None
    } else {
        Some(resolve_within(&line.ficha_md, clients)?)
    };
    // The folder may be written through a symlinked root, the media through its target (or
    // the other way round): accept both spellings of the same folder.
    let mut own = bases(Path::new(&line.folder));
    if !own.contains(&folder) {
        own.push(folder.clone());
    }
    let media = line
        .media
        .into_iter()
        .filter_map(|item| {
            let path = resolve_within(&item.path, &own);
            if path.is_none() {
                *skipped += 1;
            }
            let path = path?;
            let name = if item.name.trim().is_empty() {
                path.file_name()?.to_string_lossy().into_owned()
            } else {
                item.name
            };
            Some(FichaMedia {
                kind: MediaKind::parse(&item.kind),
                path,
                name,
                caption: item.caption,
                at: time::parse_timestamp(&item.at),
            })
        })
        .collect();
    let sections = line
        .sections
        .into_iter()
        .map(|section| FichaSection {
            title: section.title,
            items: section
                .items
                .into_iter()
                .filter(|item| !item.label.trim().is_empty() || !item.value.trim().is_empty())
                .map(|item| FichaField {
                    label: item.label,
                    value: item.value,
                })
                .collect(),
        })
        .filter(|section| !section.items.is_empty())
        .collect();
    Some(Ficha {
        updated_at: time::parse_timestamp(&line.updated_at),
        lead: line.lead,
        label: line.label,
        name: line.name,
        state: line.state,
        state_label: line.state_label,
        kind: line.kind.trim().to_lowercase(),
        status: line.status,
        resumo: line.resumo,
        sections,
        pendencias: line.pendencias,
        duvidas: line.duvidas,
        media,
        ficha_md,
        folder,
        phone: line.phone,
        wa_link: if safe_wa_link(&line.wa_link) {
            line.wa_link
        } else {
            String::new()
        },
    })
}

/// An absolute path with `.` removed, or `None` when it is relative or has a `..` component.
fn lexical(path: &Path) -> Option<PathBuf> {
    if !path.is_absolute() {
        return None;
    }
    let mut clean = PathBuf::new();
    for component in path.components() {
        match component {
            Component::ParentDir => return None,
            Component::CurDir => {}
            other => clean.push(other),
        }
    }
    Some(clean)
}

/// The lexical and (when it exists) canonical spellings of a directory.
fn bases(directory: &Path) -> Vec<PathBuf> {
    let mut found: Vec<PathBuf> = std::path::absolute(directory)
        .ok()
        .and_then(|path| lexical(&path))
        .into_iter()
        .collect();
    if let Ok(canonical) = directory.canonicalize()
        && !found.contains(&canonical)
    {
        found.push(canonical);
    }
    found
}

/// `value` resolved strictly inside one of `bases`: canonical when it exists (so a symlink
/// cannot leave the folder), lexical otherwise. Relative paths and `..` are always refused.
fn resolve_within(value: &str, bases: &[PathBuf]) -> Option<PathBuf> {
    let path = lexical(Path::new(value.trim()))?;
    let resolved = path.canonicalize().unwrap_or(path);
    bases
        .iter()
        .any(|base| resolved.starts_with(base) && resolved != *base)
        .then_some(resolved)
}

/// An existing file or folder strictly inside `within`, both resolved through symlinks.
fn existing_within(path: &Path, within: &Path) -> Option<PathBuf> {
    let base = within.canonicalize().ok()?;
    let target = path.canonicalize().ok()?;
    (target.starts_with(&base) && target != base).then_some(target)
}

impl Ficha {
    /// The client folder, re-checked on disk, for "Abrir pasta".
    pub fn open_folder(&self, root: &Path) -> Option<PathBuf> {
        let folder = existing_within(&self.folder, &root.join(CLIENTS_DIR))?;
        folder.is_dir().then_some(folder)
    }

    /// The `ficha.md`, re-checked on disk, for "Abrir ficha.md".
    pub fn open_markdown(&self, root: &Path) -> Option<PathBuf> {
        safe_ficha(root, &self.ficha_md.as_ref()?.to_string_lossy())
    }

    /// Media file `index`, re-checked on disk: a regular file inside this ficha's folder with
    /// an extension from [`OPENABLE_EXTENSIONS`].
    pub fn open_media(&self, root: &Path, index: usize) -> Option<PathBuf> {
        let folder = self.open_folder(root)?;
        let path = existing_within(&self.media.get(index)?.path, &folder)?;
        let extension = path.extension()?.to_string_lossy().to_lowercase();
        (path.is_file() && OPENABLE_EXTENSIONS.contains(&extension.as_str())).then_some(path)
    }

    pub fn count(&self, kind: MediaKind) -> usize {
        self.media.iter().filter(|media| media.kind == kind).count()
    }
}

impl SalesReport {
    pub fn available(&self) -> bool {
        self.source.is_available()
    }

    pub fn ficha(&self, lead: &str) -> Option<&Ficha> {
        self.fichas.iter().find(|ficha| ficha.lead == lead)
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
