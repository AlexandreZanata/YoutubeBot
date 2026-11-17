//! Tolerant readers: a missing file is "sem registro", a broken one is reported, unknown
//! fields are ignored and a bad JSONL line is skipped and counted.

use std::fs;
use std::io::ErrorKind;
use std::path::Path;

use serde::de::DeserializeOwned;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SourceState {
    /// Read successfully.
    Ok,
    /// The file or directory does not exist.
    Missing,
    /// Present but unreadable or not valid JSON.
    Invalid(String),
}

/// Diagnostic line for one data source, shown in Settings.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SourceStatus {
    pub label: String,
    /// Path relative to the project root.
    pub path: String,
    pub state: SourceState,
    /// Records read from the source.
    pub records: usize,
    /// Records or lines that could not be parsed and were ignored.
    pub skipped: usize,
}

impl SourceStatus {
    pub fn new(label: &str, root: &Path, path: &Path) -> Self {
        Self {
            label: label.to_owned(),
            path: relative(root, path),
            state: SourceState::Missing,
            records: 0,
            skipped: 0,
        }
    }

    pub fn is_available(&self) -> bool {
        self.state == SourceState::Ok
    }
}

pub fn relative(root: &Path, path: &Path) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .to_string_lossy()
        .into_owned()
}

/// `Ok(None)` when the file does not exist.
pub fn read_json<T: DeserializeOwned>(path: &Path) -> Result<Option<T>, String> {
    let text = match fs::read_to_string(path) {
        Ok(text) => text,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.to_string()),
    };
    serde_json::from_str(&text)
        .map(Some)
        .map_err(|error| format!("JSON inválido: {error}"))
}

/// Reads a JSON file into `status`, returning the value when it parsed.
pub fn load_json<T: DeserializeOwned>(path: &Path, status: &mut SourceStatus) -> Option<T> {
    match read_json(path) {
        Ok(Some(value)) => {
            status.state = SourceState::Ok;
            Some(value)
        }
        Ok(None) => {
            status.state = SourceState::Missing;
            None
        }
        Err(error) => {
            status.state = SourceState::Invalid(error);
            None
        }
    }
}

/// Reads every valid line of a JSONL file; invalid lines are counted in `skipped`.
pub fn load_jsonl<T: DeserializeOwned>(path: &Path, status: &mut SourceStatus) -> Vec<T> {
    let text = match fs::read_to_string(path) {
        Ok(text) => text,
        Err(error) if error.kind() == ErrorKind::NotFound => {
            status.state = SourceState::Missing;
            return Vec::new();
        }
        Err(error) => {
            status.state = SourceState::Invalid(error.to_string());
            return Vec::new();
        }
    };
    status.state = SourceState::Ok;
    let mut values = Vec::new();
    for line in text.lines().filter(|line| !line.trim().is_empty()) {
        match serde_json::from_str(line) {
            Ok(value) => values.push(value),
            Err(_) => status.skipped += 1,
        }
    }
    status.records = values.len();
    values
}

/// Deserializes a string field that may be `null`, a number or absent.
pub mod lenient {
    use serde::{Deserialize, Deserializer};
    use serde_json::Value;

    pub fn string<'de, D: Deserializer<'de>>(deserializer: D) -> Result<String, D::Error> {
        Ok(match Value::deserialize(deserializer)? {
            Value::String(text) => text,
            Value::Number(number) => number.to_string(),
            Value::Bool(flag) => flag.to_string(),
            _ => String::new(),
        })
    }

    pub fn boolean<'de, D: Deserializer<'de>>(deserializer: D) -> Result<bool, D::Error> {
        Ok(matches!(
            Value::deserialize(deserializer)?,
            Value::Bool(true)
        ))
    }

    pub fn number<'de, D: Deserializer<'de>>(deserializer: D) -> Result<Option<f64>, D::Error> {
        Ok(match Value::deserialize(deserializer)? {
            Value::Number(number) => number.as_f64(),
            Value::String(text) => text.replace(',', ".").trim().parse().ok(),
            _ => None,
        })
    }
}
