//! The registered YouTube channels. This table mirrors `tools/ytbot/channels.py`;
//! `tests/test_desktop_catalog.py` fails when the two drift apart.

use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ChannelInfo {
    pub slug: &'static str,
    pub name: &'static str,
    pub handle: &'static str,
    pub channel_id: &'static str,
    /// Whether the channel publishes vertical Shorts (only Zaflas today).
    pub has_shorts: bool,
}

pub const CHANNELS: &[ChannelInfo] = &[
    ChannelInfo {
        slug: "fallem-prince",
        name: "fallem prince",
        handle: "@fallemprince",
        channel_id: "UCc288lF54UDCCGhTKIkr7BQ",
        has_shorts: false,
    },
    ChannelInfo {
        slug: "whispers-from-heaven",
        name: "Whispers From Heaven",
        handle: "@WhispersFromHeaven1",
        channel_id: "UCEE9qAtucy5OZcjvcyytu4w",
        has_shorts: false,
    },
    ChannelInfo {
        slug: "zaflas",
        name: "Zaflas",
        handle: "@zaflas",
        channel_id: "UCi2aftoK7vlS3A6OozMHXKg",
        has_shorts: true,
    },
    ChannelInfo {
        slug: "infinite-random-worlds",
        name: "Infinite Random Worlds",
        handle: "@InfiniteRandomWorlds",
        channel_id: "UCY3Zp50I6Y6semQQccJxRPg",
        has_shorts: false,
    },
    ChannelInfo {
        slug: "vocal-pages",
        name: "Vocal Pages",
        handle: "@VocalPages01",
        channel_id: "UCm13oIPS1W43j9BYo0kewcQ",
        has_shorts: false,
    },
    ChannelInfo {
        slug: "zanata",
        name: "zanata",
        handle: "@zanatareal",
        channel_id: "UCx0AE-elCyDhfY0d1hQIwdw",
        has_shorts: false,
    },
    ChannelInfo {
        slug: "reflection",
        name: "the word of reflection",
        handle: "@thewordofreflection",
        channel_id: "UCISw6UDaFINPRuuMr0s7tpA",
        has_shorts: false,
    },
];

pub fn find(slug: &str) -> Option<&'static ChannelInfo> {
    CHANNELS.iter().find(|channel| channel.slug == slug)
}

impl ChannelInfo {
    /// Fallem Prince keeps the legacy layout directly under `.local/ytbot`.
    pub fn data_dir(&self, root: &Path) -> PathBuf {
        let base = root.join(".local").join("ytbot");
        if self.slug == "fallem-prince" {
            base
        } else {
            base.join("channels").join(self.slug)
        }
    }

    pub fn runs_dir(&self, root: &Path) -> PathBuf {
        self.data_dir(root).join("runs")
    }

    pub fn shorts_dir(&self, root: &Path) -> PathBuf {
        self.data_dir(root).join("shorts")
    }
}
