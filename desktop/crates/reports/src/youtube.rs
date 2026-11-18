//! Long videos and Shorts from the per-run `upload.json` and `metadata.json` records.

use std::fs;
use std::path::{Path, PathBuf};

use chrono::NaiveDateTime;
use serde::Deserialize;

use crate::catalog::ChannelInfo;
use crate::source::{SourceState, SourceStatus, lenient, read_json};
use crate::time;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VideoKind {
    Long,
    Short,
}

/// Counting rule: a scheduled upload is `Published` once its slot is at or before now and
/// `Scheduled` while the slot is ahead. An upload without a confirmed schedule is a `Draft`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VideoState {
    Published,
    Scheduled,
    Draft,
}

impl VideoState {
    pub fn label(self) -> &'static str {
        match self {
            Self::Published => "publicado",
            Self::Scheduled => "agendado",
            Self::Draft => "rascunho",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct VideoRecord {
    pub channel: &'static str,
    pub kind: VideoKind,
    /// Run directory name.
    pub run: String,
    pub title: String,
    pub slot: Option<NaiveDateTime>,
    pub video_id: String,
    pub url: String,
    pub scheduled: bool,
    pub thumbnail: Option<PathBuf>,
}

impl VideoRecord {
    pub fn state(&self, now: NaiveDateTime) -> VideoState {
        match self.slot {
            Some(slot) if self.scheduled && !self.video_id.is_empty() => {
                if slot <= now {
                    VideoState::Published
                } else {
                    VideoState::Scheduled
                }
            }
            _ => VideoState::Draft,
        }
    }

    pub fn link(&self) -> String {
        if !self.url.is_empty() {
            self.url.clone()
        } else if !self.video_id.is_empty() {
            format!("https://youtu.be/{}", self.video_id)
        } else {
            String::new()
        }
    }
}

/// Every run of one channel (long videos) or of its Shorts folder.
#[derive(Debug, Clone)]
pub struct RunsReport {
    pub videos: Vec<VideoRecord>,
    /// Run folders that have no `upload.json` yet.
    pub without_upload: usize,
    pub source: SourceStatus,
}

impl RunsReport {
    pub fn is_available(&self) -> bool {
        self.source.is_available()
    }
}

#[derive(Debug, Default, Deserialize)]
struct UploadFile {
    #[serde(default, rename = "videoId", deserialize_with = "lenient::string")]
    video_id: String,
    #[serde(default, deserialize_with = "lenient::string")]
    url: String,
    #[serde(default, deserialize_with = "lenient::string")]
    slot: String,
    #[serde(default, deserialize_with = "lenient::boolean")]
    scheduled: bool,
}

#[derive(Debug, Default, Deserialize)]
struct MetadataFile {
    #[serde(default, deserialize_with = "lenient::string")]
    title: String,
}

pub fn load_runs(root: &Path, channel: &'static ChannelInfo, kind: VideoKind) -> RunsReport {
    let (directory, label) = match kind {
        VideoKind::Long => (channel.runs_dir(root), format!("{} · vídeos", channel.name)),
        VideoKind::Short => (
            channel.shorts_dir(root),
            format!("{} · shorts", channel.name),
        ),
    };
    let mut source = SourceStatus::new(&label, root, &directory);
    let mut report = RunsReport {
        videos: Vec::new(),
        without_upload: 0,
        source: source.clone(),
    };
    let entries = match fs::read_dir(&directory) {
        Ok(entries) => entries,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return report,
        Err(error) => {
            source.state = SourceState::Invalid(error.to_string());
            report.source = source;
            return report;
        }
    };
    source.state = SourceState::Ok;
    let mut runs: Vec<PathBuf> = entries
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| path.is_dir())
        .collect();
    runs.sort();
    for run in runs {
        let upload_path = run.join("upload.json");
        let upload: UploadFile = match read_json(&upload_path) {
            Ok(Some(upload)) => upload,
            Ok(None) => {
                report.without_upload += 1;
                continue;
            }
            Err(_) => {
                source.skipped += 1;
                continue;
            }
        };
        let name = run
            .file_name()
            .map(|value| value.to_string_lossy().into_owned())
            .unwrap_or_default();
        let thumbnail = run.join("thumbnail.png");
        report.videos.push(VideoRecord {
            channel: channel.slug,
            kind,
            title: title_for(&run, &name),
            slot: time::parse_slot(&upload.slot),
            video_id: upload.video_id,
            url: upload.url,
            scheduled: upload.scheduled,
            thumbnail: thumbnail.is_file().then_some(thumbnail),
            run: name,
        });
    }
    source.records = report.videos.len();
    report.source = source;
    report
}

/// Title from `metadata.json`, then the first line of `topic.txt`, then the folder name.
fn title_for(run: &Path, fallback: &str) -> String {
    if let Ok(Some(metadata)) = read_json::<MetadataFile>(&run.join("metadata.json")) {
        let title = metadata.title.trim();
        if !title.is_empty() {
            return title.to_owned();
        }
    }
    if let Ok(topic) = fs::read_to_string(run.join("topic.txt"))
        && let Some(line) = topic.lines().map(str::trim).find(|line| !line.is_empty())
    {
        return line.to_owned();
    }
    fallback.replace('-', " ")
}
