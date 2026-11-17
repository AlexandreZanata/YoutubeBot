//! Off-thread thumbnail decoding for the Shorts list. Only the pixel buffer crosses threads;
//! the `slint::Image` is created on the UI thread.

use std::fs;
use std::path::Path;

use slint::{Rgba8Pixel, SharedPixelBuffer};

/// Twice the 54x96 cell, so the image stays sharp on HiDPI screens.
const WIDTH: u32 = 108;
const HEIGHT: u32 = 192;
/// Never decode an unexpectedly large file.
const MAX_BYTES: u64 = 25 * 1024 * 1024;

pub fn decode(path: &Path) -> Option<SharedPixelBuffer<Rgba8Pixel>> {
    if fs::metadata(path).ok()?.len() > MAX_BYTES {
        return None;
    }
    let image = image::open(path).ok()?;
    let thumbnail = image.thumbnail(WIDTH, HEIGHT).to_rgba8();
    Some(SharedPixelBuffer::clone_from_slice(
        thumbnail.as_raw(),
        thumbnail.width(),
        thumbnail.height(),
    ))
}
