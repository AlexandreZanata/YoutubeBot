//! Read-only aggregation of the private records written by the Python bot.
//!
//! Loading ([`Snapshot::load`]) is the only part that touches the disk. Every count is a pure
//! function of a snapshot, a [`Period`] and the current time in America/Cuiaba, so the desktop
//! UI only formats what this crate returns. Nothing here writes, opens a network connection or
//! reads credentials.

pub mod catalog;
pub mod commercial;
pub mod community;
pub mod overview;
pub mod sales;
pub mod search;
pub mod snapshot;
pub mod social;
pub mod source;
pub mod time;
pub mod youtube;

pub use catalog::{CHANNELS, ChannelInfo};
pub use overview::{ChannelSummary, Overview, UpcomingItem};
pub use snapshot::Snapshot;
pub use source::{SourceState, SourceStatus};
pub use time::{Period, PeriodKind};
pub use youtube::{VideoKind, VideoRecord, VideoState};

/// Re-exported so callers can name the timestamps without depending on chrono directly.
pub use chrono::{NaiveDate, NaiveDateTime};
