//! Off-thread thumbnail decoding for the Shorts list and the ficha photo gallery. Only the
//! pixel buffer crosses threads; the `slint::Image` is created on the UI thread.

use std::fs;
use std::path::{Path, PathBuf};

use slint::{Rgba8Pixel, SharedPixelBuffer};

/// Twice the 54x96 Shorts cell, so the image stays sharp on HiDPI screens.
pub const SHORT: (u32, u32) = (108, 192);
/// Twice the 160 px gallery tile.
pub const PHOTO: (u32, u32) = (320, 320);
/// Never decode an unexpectedly large file.
const MAX_BYTES: u64 = 25 * 1024 * 1024;

/// One image to decode. `key` is the path the view knows (the cache key); `file` is the
/// checked file to read, `None` when it is missing or refused (the tile keeps its
/// placeholder without a decode).
pub struct Request {
    pub key: PathBuf,
    pub file: Option<PathBuf>,
    pub size: (u32, u32),
}

impl Request {
    pub fn same(path: PathBuf, size: (u32, u32)) -> Self {
        Self {
            key: path.clone(),
            file: Some(path),
            size,
        }
    }
}

pub fn decode(path: &Path, (width, height): (u32, u32)) -> Option<SharedPixelBuffer<Rgba8Pixel>> {
    if fs::metadata(path).ok()?.len() > MAX_BYTES {
        return None;
    }
    let image = image::open(path).ok()?;
    let thumbnail = image.thumbnail(width, height).to_rgba8();
    Some(SharedPixelBuffer::clone_from_slice(
        thumbnail.as_raw(),
        thumbnail.width(),
        thumbnail.height(),
    ))
}
