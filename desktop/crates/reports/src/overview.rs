//! Pure aggregation over a [`Snapshot`]: no I/O, deterministic for a given `now`.
//!
//! A count is `None` when its source has no record ("sem registro") and `Some(0)` when the
//! source exists but nothing falls in the period.

use chrono::NaiveDateTime;

use crate::community::CommunityEntry;
use crate::snapshot::{Binding, ChannelData, Snapshot};
use crate::time::Period;
use crate::youtube::{VideoKind, VideoRecord, VideoState};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UpcomingItem {
    pub slot: NaiveDateTime,
    pub channel: &'static str,
    pub channel_name: &'static str,
    pub title: String,
    pub kind: VideoKind,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Overview {
    pub published: Option<usize>,
    pub scheduled: Option<usize>,
    pub drafts: usize,
    pub shorts_published: Option<usize>,
    pub shorts_scheduled: Option<usize>,
    pub x_posts: Option<usize>,
    pub x_replies: Option<usize>,
    pub whatsapp_received: Option<usize>,
    pub products: Option<usize>,
    pub upcoming: Vec<UpcomingItem>,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct StateCounts {
    pub published: usize,
    pub scheduled: usize,
    pub drafts: usize,
}

/// Counts the videos whose slot falls in the period. Drafts have no reliable slot, so every
/// draft is counted regardless of the period.
pub fn count_states<'a>(
    videos: impl IntoIterator<Item = &'a VideoRecord>,
    period: &Period,
    now: NaiveDateTime,
) -> StateCounts {
    let mut counts = StateCounts::default();
    for video in videos {
        match video.state(now) {
            VideoState::Draft => counts.drafts += 1,
            VideoState::Published if period.contains_opt(video.slot) => counts.published += 1,
            VideoState::Scheduled if period.contains_opt(video.slot) => counts.scheduled += 1,
            _ => {}
        }
    }
    counts
}

fn selected<'a>(
    snapshot: &'a Snapshot,
    channel: Option<&'a str>,
) -> impl Iterator<Item = &'a ChannelData> {
    snapshot
        .channels
        .iter()
        .filter(move |data| channel.is_none_or(|slug| data.info.slug == slug))
}

/// Overview cards for a period, optionally restricted to one channel. The X, WhatsApp and
/// Mercado Livre cards are network-wide and ignore the channel filter.
pub fn overview(
    snapshot: &Snapshot,
    period: &Period,
    channel: Option<&str>,
    now: NaiveDateTime,
    upcoming_limit: usize,
) -> Overview {
    let channels: Vec<&ChannelData> = selected(snapshot, channel).collect();

    let long: Vec<&ChannelData> = channels
        .iter()
        .copied()
        .filter(|data| data.runs.is_available())
        .collect();
    let long_counts = count_states(long.iter().flat_map(|data| &data.runs.videos), period, now);

    let shorts: Vec<&ChannelData> = channels
        .iter()
        .copied()
        .filter(|data| {
            data.shorts
                .as_ref()
                .is_some_and(|shorts| shorts.is_available())
        })
        .collect();
    let short_counts = count_states(
        shorts
            .iter()
            .filter_map(|data| data.shorts.as_ref())
            .flat_map(|shorts| &shorts.videos),
        period,
        now,
    );

    let mut upcoming: Vec<UpcomingItem> = channels
        .iter()
        .flat_map(|data| {
            data.runs
                .videos
                .iter()
                .chain(data.shorts.iter().flat_map(|shorts| &shorts.videos))
                .filter(|video| video.state(now) == VideoState::Scheduled)
                .filter_map(|video| {
                    Some(UpcomingItem {
                        slot: video.slot?,
                        channel: data.info.slug,
                        channel_name: data.info.name,
                        title: video.title.clone(),
                        kind: video.kind,
                    })
                })
        })
        .collect();
    upcoming.sort_by(|left, right| {
        left.slot
            .cmp(&right.slot)
            .then(left.channel.cmp(right.channel))
    });
    upcoming.truncate(upcoming_limit);

    let (posted_replies, _) = snapshot.x.replies_in(period);
    Overview {
        published: (!long.is_empty()).then_some(long_counts.published),
        scheduled: (!long.is_empty()).then_some(long_counts.scheduled),
        drafts: long_counts.drafts,
        shorts_published: (!shorts.is_empty()).then_some(short_counts.published),
        shorts_scheduled: (!shorts.is_empty()).then_some(short_counts.scheduled),
        x_posts: snapshot
            .x
            .posts_available()
            .then(|| snapshot.x.posts_in(period)),
        x_replies: snapshot.x.replies_available().then_some(posted_replies),
        whatsapp_received: snapshot
            .whatsapp
            .events_available()
            .then(|| snapshot.whatsapp.received_in(period)),
        products: snapshot
            .mercadolivre
            .products_available()
            .then(|| snapshot.mercadolivre.captured_in(period)),
        upcoming,
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChannelSummary {
    pub slug: &'static str,
    pub name: &'static str,
    pub handle: &'static str,
    pub binding: Binding,
    /// False when the runs folder does not exist.
    pub available: bool,
    pub counts: StateCounts,
    pub without_upload: usize,
    pub last_published: Option<(String, NaiveDateTime)>,
    pub next_scheduled: Option<(String, NaiveDateTime)>,
    pub community_last: Option<CommunityEntry>,
    pub community_in_period: usize,
}

pub fn channel_summaries(
    snapshot: &Snapshot,
    period: &Period,
    now: NaiveDateTime,
) -> Vec<ChannelSummary> {
    snapshot
        .channels
        .iter()
        .map(|data| {
            let videos = &data.runs.videos;
            let last_published = videos
                .iter()
                .filter(|video| video.state(now) == VideoState::Published)
                .filter_map(|video| Some((video.title.clone(), video.slot?)))
                .max_by_key(|(_, slot)| *slot);
            let next_scheduled = videos
                .iter()
                .filter(|video| video.state(now) == VideoState::Scheduled)
                .filter_map(|video| Some((video.title.clone(), video.slot?)))
                .min_by_key(|(_, slot)| *slot);
            ChannelSummary {
                slug: data.info.slug,
                name: data.info.name,
                handle: data.info.handle,
                binding: data.binding.clone(),
                available: data.runs.is_available(),
                counts: count_states(videos, period, now),
                without_upload: data.runs.without_upload,
                last_published,
                next_scheduled,
                community_last: data.community.latest().cloned(),
                community_in_period: data.community.posted_in(period),
            }
        })
        .collect()
}

/// Videos of one channel (long and Shorts), newest slot first. With a period, drafts are kept
/// and dated videos must fall inside it.
pub fn channel_videos<'a>(
    snapshot: &'a Snapshot,
    slug: &str,
    period: Option<&Period>,
    now: NaiveDateTime,
) -> Vec<(&'a VideoRecord, VideoState)> {
    let Some(data) = snapshot.channel(slug) else {
        return Vec::new();
    };
    let mut rows: Vec<(&VideoRecord, VideoState)> = data
        .runs
        .videos
        .iter()
        .map(|video| (video, video.state(now)))
        .filter(|(video, state)| {
            *state == VideoState::Draft
                || period.is_none_or(|period| period.contains_opt(video.slot))
        })
        .collect();
    rows.sort_by_key(|row| std::cmp::Reverse(row.0.slot));
    rows
}

/// Shorts of every channel that has them, newest slot first.
pub fn shorts(snapshot: &Snapshot, now: NaiveDateTime) -> Vec<(&VideoRecord, VideoState)> {
    let mut rows: Vec<(&VideoRecord, VideoState)> = snapshot
        .channels
        .iter()
        .filter_map(|data| data.shorts.as_ref())
        .flat_map(|shorts| &shorts.videos)
        .map(|video| (video, video.state(now)))
        .collect();
    rows.sort_by_key(|row| std::cmp::Reverse(row.0.slot));
    rows
}
