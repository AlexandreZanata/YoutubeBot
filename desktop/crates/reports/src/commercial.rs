//! Commercial module records: WhatsApp Web events and rules, Mercado Livre captures.

use std::collections::{BTreeMap, HashSet};
use std::path::Path;

use chrono::NaiveDateTime;
use serde::Deserialize;

use crate::social::{NetworkAccount, load_account};
use crate::source::{SourceStatus, lenient, load_json, load_jsonl};
use crate::time::{self, Period};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WaMessage {
    pub id: String,
    pub chat: String,
    pub text: String,
    /// When the listener recorded the event.
    pub at: Option<NaiveDateTime>,
    /// Time label shown by WhatsApp Web, e.g. `11:58 AM`.
    pub message_at: String,
    pub allowed: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WaRules {
    /// `allow` or `block`.
    pub mode: String,
    pub contacts: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WaSend {
    pub state: String,
    pub at: Option<NaiveDateTime>,
}

/// Latest received message per contact.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WaContact {
    pub chat: String,
    pub last_text: String,
    pub last_at: Option<NaiveDateTime>,
    pub message_at: String,
    pub count: usize,
    pub allowed: bool,
}

#[derive(Debug, Clone, Default)]
pub struct WhatsAppReport {
    pub account: Option<NetworkAccount>,
    pub rules: Option<WaRules>,
    /// Unique messages in file order.
    pub messages: Vec<WaMessage>,
    pub sends: Vec<WaSend>,
    pub sources: Vec<SourceStatus>,
}

#[derive(Debug, Default, Deserialize)]
struct EventLine {
    #[serde(default, deserialize_with = "lenient::string")]
    id: String,
    #[serde(default, deserialize_with = "lenient::string")]
    at: String,
    #[serde(default, deserialize_with = "lenient::string")]
    message_at: String,
    #[serde(default, deserialize_with = "lenient::string")]
    chat: String,
    #[serde(default, deserialize_with = "lenient::string")]
    text: String,
    #[serde(default, deserialize_with = "lenient::boolean")]
    allowed: bool,
}

#[derive(Debug, Default, Deserialize)]
struct JournalLine {
    #[serde(default, deserialize_with = "lenient::string")]
    state: String,
    #[serde(default, deserialize_with = "lenient::string")]
    at: String,
}

#[derive(Debug, Default, Deserialize)]
struct RulesFile {
    #[serde(default, deserialize_with = "lenient::string")]
    mode: String,
    #[serde(default)]
    contacts: Vec<serde_json::Value>,
}

pub fn load_whatsapp(root: &Path) -> WhatsAppReport {
    let base = root.join(".local/commercial/whatsapp");
    let (account, account_source) =
        load_account(root, "commercial", "whatsapp", "WhatsApp · sessão");
    let mut report = WhatsAppReport {
        account,
        ..WhatsAppReport::default()
    };
    report.sources.push(account_source);

    let rules_path = base.join("rules.json");
    let mut rules_source = SourceStatus::new("WhatsApp · regras", root, &rules_path);
    report.rules = load_json::<RulesFile>(&rules_path, &mut rules_source).map(|rules| WaRules {
        mode: rules.mode,
        contacts: rules
            .contacts
            .into_iter()
            .filter_map(|value| value.as_str().map(str::to_owned))
            .collect(),
    });
    rules_source.records = report
        .rules
        .as_ref()
        .map_or(0, |rules| rules.contacts.len());
    report.sources.push(rules_source);

    let events_path = base.join("events.jsonl");
    let mut events_source = SourceStatus::new("WhatsApp · mensagens recebidas", root, &events_path);
    let mut seen = HashSet::new();
    for line in load_jsonl::<EventLine>(&events_path, &mut events_source) {
        let key = if line.id.is_empty() {
            format!("{}|{}|{}", line.chat, line.message_at, line.text)
        } else {
            line.id.clone()
        };
        if !seen.insert(key) {
            continue;
        }
        report.messages.push(WaMessage {
            id: line.id,
            chat: line.chat,
            text: line.text,
            at: time::parse_timestamp(&line.at),
            message_at: line.message_at,
            allowed: line.allowed,
        });
    }
    events_source.records = report.messages.len();
    report.sources.push(events_source);

    let journal_path = base.join("journal.jsonl");
    let mut journal_source = SourceStatus::new("WhatsApp · envios", root, &journal_path);
    report.sends = load_jsonl::<JournalLine>(&journal_path, &mut journal_source)
        .into_iter()
        .map(|line| WaSend {
            at: time::parse_timestamp(&line.at),
            state: line.state,
        })
        .collect();
    report.sources.push(journal_source);
    report
}

impl WhatsAppReport {
    pub fn events_available(&self) -> bool {
        self.sources
            .iter()
            .any(|source| source.label == "WhatsApp · mensagens recebidas" && source.is_available())
    }

    pub fn received_in(&self, period: &Period) -> usize {
        self.messages
            .iter()
            .filter(|message| period.contains_opt(message.at))
            .count()
    }

    /// One row per contact with its latest message, newest contact first.
    pub fn contacts(&self, period: Option<&Period>) -> Vec<WaContact> {
        let mut contacts: BTreeMap<&str, WaContact> = BTreeMap::new();
        for message in &self.messages {
            if period.is_some_and(|period| !period.contains_opt(message.at)) {
                continue;
            }
            let entry = contacts.entry(&message.chat).or_insert_with(|| WaContact {
                chat: message.chat.clone(),
                last_text: String::new(),
                last_at: None,
                message_at: String::new(),
                count: 0,
                allowed: message.allowed,
            });
            entry.count += 1;
            if entry.last_at <= message.at {
                entry.last_at = message.at;
                entry.last_text = message.text.clone();
                entry.message_at = message.message_at.clone();
                entry.allowed = message.allowed;
            }
        }
        let mut rows: Vec<WaContact> = contacts.into_values().collect();
        rows.sort_by(|left, right| {
            right
                .last_at
                .cmp(&left.last_at)
                .then(left.chat.cmp(&right.chat))
        });
        rows
    }

    /// Send journal entries in the period grouped by state, e.g. `sent`, `dry-run`.
    pub fn sends_in(&self, period: &Period) -> BTreeMap<String, usize> {
        let mut counts = BTreeMap::new();
        for send in self
            .sends
            .iter()
            .filter(|send| period.contains_opt(send.at))
        {
            *counts.entry(send.state.clone()).or_insert(0) += 1;
        }
        counts
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Product {
    pub title: String,
    pub price: Option<f64>,
    pub currency: String,
    pub commission: String,
    pub brand: String,
    pub link: String,
}

/// `products.json` is a snapshot of the latest capture, not a history.
#[derive(Debug, Clone, Default)]
pub struct MercadoLivreReport {
    pub account: Option<NetworkAccount>,
    pub query: String,
    pub captured_at: Option<NaiveDateTime>,
    pub products: Vec<Product>,
    pub sources: Vec<SourceStatus>,
}

#[derive(Debug, Default, Deserialize)]
struct ProductsFile {
    #[serde(default, deserialize_with = "lenient::string")]
    query: String,
    #[serde(default, deserialize_with = "lenient::string")]
    captured_at: String,
    #[serde(default)]
    products: Vec<ProductRecord>,
}

#[derive(Debug, Default, Deserialize)]
struct ProductRecord {
    #[serde(default, deserialize_with = "lenient::string")]
    title: String,
    #[serde(default, deserialize_with = "lenient::number")]
    price: Option<f64>,
    #[serde(default, deserialize_with = "lenient::string")]
    currency: String,
    #[serde(default, deserialize_with = "lenient::string")]
    commission: String,
    #[serde(default, deserialize_with = "lenient::string")]
    brand: String,
    #[serde(default, deserialize_with = "lenient::string")]
    share_link: String,
    #[serde(default, deserialize_with = "lenient::string")]
    product_url: String,
}

pub fn load_mercadolivre(root: &Path) -> MercadoLivreReport {
    let (account, account_source) =
        load_account(root, "commercial", "mercadolivre", "Mercado Livre · sessão");
    let mut report = MercadoLivreReport {
        account,
        ..MercadoLivreReport::default()
    };
    report.sources.push(account_source);
    let path = root.join(".local/commercial/mercadolivre/products.json");
    let mut source = SourceStatus::new("Mercado Livre · última captura", root, &path);
    if let Some(file) = load_json::<ProductsFile>(&path, &mut source) {
        report.query = file.query;
        report.captured_at = time::parse_timestamp(&file.captured_at);
        report.products = file
            .products
            .into_iter()
            .map(|product| Product {
                link: if product.share_link.is_empty() {
                    product.product_url
                } else {
                    product.share_link
                },
                title: product.title,
                price: product.price,
                currency: product.currency,
                commission: product.commission,
                brand: product.brand,
            })
            .collect();
        source.records = report.products.len();
    }
    report.sources.push(source);
    report
}

impl MercadoLivreReport {
    pub fn products_available(&self) -> bool {
        self.sources.last().is_some_and(SourceStatus::is_available)
    }

    /// Products of the latest capture when that capture happened inside the period.
    pub fn captured_in(&self, period: &Period) -> usize {
        if period.contains_opt(self.captured_at) {
            self.products.len()
        } else {
            0
        }
    }
}

/// `R$ 1.299,90` style formatting for BRL; other currencies keep their code.
pub fn format_price(price: Option<f64>, currency: &str) -> String {
    let Some(value) = price else {
        return "sem preço".into();
    };
    let cents = (value * 100.0).round() as i64;
    let (units, fraction) = (cents / 100, (cents % 100).abs());
    let digits = units.abs().to_string();
    let mut grouped = String::new();
    for (index, digit) in digits.chars().enumerate() {
        if index > 0 && (digits.len() - index) % 3 == 0 {
            grouped.push('.');
        }
        grouped.push(digit);
    }
    let sign = if units < 0 { "-" } else { "" };
    let symbol = match currency {
        "" | "BRL" => "R$".to_owned(),
        other => other.to_owned(),
    };
    format!("{symbol} {sign}{grouped},{fraction:02}")
}
