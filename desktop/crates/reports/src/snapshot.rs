//! One read of every source. Loading is the only I/O; aggregation works on the snapshot.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use chrono::NaiveDateTime;
use serde::Deserialize;

use crate::catalog::{CHANNELS, ChannelInfo};
use crate::commercial::{self, MercadoLivreReport, WhatsAppReport};
use crate::community::{self, CommunityReport};
use crate::social::{self, XReport};
use crate::source::{SourceStatus, lenient, load_json};
use crate::time;
use crate::youtube::{self, RunsReport, VideoKind};

/// How the account registry binds a channel to an upload profile.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Binding {
    /// Bound to the expected channel ID.
    Bound { account: String, label: String },
    /// Bound, but to a different channel ID than the catalog expects.
    Mismatch { account: String, channel_id: String },
    /// No binding in the registry (or no registry at all).
    Unbound,
}

#[derive(Debug, Clone)]
pub struct ChannelData {
    pub info: &'static ChannelInfo,
    pub runs: RunsReport,
    pub shorts: Option<RunsReport>,
    pub community: CommunityReport,
    pub binding: Binding,
}

/// `.local/ytbot/needs-login.json`, written when a session really expired.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LoginRequest {
    pub profile: String,
    pub reason: String,
    pub at: Option<NaiveDateTime>,
}

#[derive(Debug, Clone)]
pub struct Snapshot {
    pub root: PathBuf,
    pub loaded_at: NaiveDateTime,
    pub channels: Vec<ChannelData>,
    pub x: XReport,
    pub whatsapp: WhatsAppReport,
    pub mercadolivre: MercadoLivreReport,
    pub login_request: Option<LoginRequest>,
    pub registry: SourceStatus,
}

#[derive(Debug, Default, Deserialize)]
struct RegistryFile {
    #[serde(default)]
    accounts: BTreeMap<String, RegistryAccount>,
    #[serde(default)]
    bindings: BTreeMap<String, RegistryBinding>,
}

#[derive(Debug, Default, Deserialize)]
struct RegistryAccount {
    #[serde(default, deserialize_with = "lenient::string")]
    label: String,
}

#[derive(Debug, Default, Deserialize)]
struct RegistryBinding {
    #[serde(default, deserialize_with = "lenient::string")]
    account_id: String,
    #[serde(default, deserialize_with = "lenient::string")]
    channel_id: String,
}

#[derive(Debug, Default, Deserialize)]
struct LoginMarker {
    #[serde(default, deserialize_with = "lenient::string")]
    name: String,
    #[serde(default, deserialize_with = "lenient::string")]
    reason: String,
    #[serde(default, deserialize_with = "lenient::string")]
    at: String,
}

impl Snapshot {
    pub fn load(root: &Path, now: NaiveDateTime) -> Self {
        let registry_path = root.join(".local/accounts/registry.json");
        let mut registry = SourceStatus::new("Contas YouTube (registro)", root, &registry_path);
        let file = load_json::<RegistryFile>(&registry_path, &mut registry).unwrap_or_default();
        registry.records = file.accounts.len();

        let channels = CHANNELS
            .iter()
            .map(|info| ChannelData {
                info,
                runs: youtube::load_runs(root, info, VideoKind::Long),
                shorts: info
                    .has_shorts
                    .then(|| youtube::load_runs(root, info, VideoKind::Short)),
                community: community::load_community(root, info),
                binding: binding_for(&file, info),
            })
            .collect();

        let marker_path = root.join(".local/ytbot/needs-login.json");
        let login_request = crate::source::read_json::<LoginMarker>(&marker_path)
            .ok()
            .flatten()
            .map(|marker| LoginRequest {
                profile: marker.name,
                reason: marker.reason,
                at: time::parse_timestamp(&marker.at),
            });

        Self {
            root: root.to_path_buf(),
            loaded_at: now,
            channels,
            x: social::load_x(root),
            whatsapp: commercial::load_whatsapp(root),
            mercadolivre: commercial::load_mercadolivre(root),
            login_request,
            registry,
        }
    }

    pub fn channel(&self, slug: &str) -> Option<&ChannelData> {
        self.channels
            .iter()
            .find(|channel| channel.info.slug == slug)
    }

    /// Every source with its state, for the read-only diagnostics table.
    pub fn sources(&self) -> Vec<SourceStatus> {
        let mut sources = vec![self.registry.clone()];
        for channel in &self.channels {
            sources.push(channel.runs.source.clone());
            if let Some(shorts) = &channel.shorts {
                sources.push(shorts.source.clone());
            }
            sources.push(channel.community.source.clone());
        }
        sources.extend(self.x.sources.iter().cloned());
        sources.extend(self.whatsapp.sources.iter().cloned());
        sources.extend(self.mercadolivre.sources.iter().cloned());
        sources
    }
}

fn binding_for(file: &RegistryFile, info: &ChannelInfo) -> Binding {
    let Some(binding) = file.bindings.get(info.slug) else {
        return Binding::Unbound;
    };
    if binding.channel_id != info.channel_id {
        return Binding::Mismatch {
            account: binding.account_id.clone(),
            channel_id: binding.channel_id.clone(),
        };
    }
    let label = file
        .accounts
        .get(&binding.account_id)
        .map(|account| account.label.clone())
        .filter(|label| !label.is_empty())
        .unwrap_or_else(|| binding.account_id.clone());
    Binding::Bound {
        account: binding.account_id.clone(),
        label,
    }
}
