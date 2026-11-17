//! Decoupled domain layer for the YoutubeBot desktop manager.

pub mod actions;
pub mod model;
pub mod state;

pub use actions::{CliActions, SessionActions};
pub use model::SessionInfo;
pub use state::StateLoader;
