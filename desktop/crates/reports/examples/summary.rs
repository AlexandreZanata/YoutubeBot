//! Prints the current month's counts for a project root, for diagnostics without the UI:
//! `cargo run -p reports --example summary -- /path/to/project`

use std::path::PathBuf;

use reports::overview::{channel_summaries, overview};
use reports::{Period, Snapshot, SourceState, time};

fn show(value: Option<usize>) -> String {
    value.map_or_else(|| "sem registro".to_owned(), |count| count.to_string())
}

fn main() {
    let root = std::env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));
    let now = time::now();
    let snapshot = Snapshot::load(&root, now);
    let period = Period::this_month(now.date());
    let totals = overview(&snapshot, &period, None, now, 5);
    println!(
        "período: {} (agora {})",
        period.label(),
        time::format_datetime(now)
    );
    println!("vídeos publicados: {}", show(totals.published));
    println!("vídeos agendados: {}", show(totals.scheduled));
    println!("rascunhos: {}", totals.drafts);
    println!(
        "shorts publicados/agendados: {}/{}",
        show(totals.shorts_published),
        show(totals.shorts_scheduled)
    );
    println!("posts no X: {}", show(totals.x_posts));
    println!("respostas no X: {}", show(totals.x_replies));
    println!("mensagens WhatsApp: {}", show(totals.whatsapp_received));
    println!("produtos capturados: {}", show(totals.products));
    for summary in channel_summaries(&snapshot, &period, now) {
        println!(
            "  {:<24} publicados {:>3}  agendados {:>3}  rascunhos {:>2}  próximo {}",
            summary.name,
            summary.counts.published,
            summary.counts.scheduled,
            summary.counts.drafts,
            summary
                .next_scheduled
                .map(|(_, slot)| time::format_slot(slot))
                .unwrap_or_else(|| "—".into())
        );
    }
    for item in &totals.upcoming {
        println!(
            "  próximo: {} · {}",
            time::format_slot(item.slot),
            item.channel_name
        );
    }
    for source in snapshot.sources() {
        if !matches!(source.state, SourceState::Ok) {
            println!("  fonte {:?}: {}", source.state, source.path);
        }
    }
}
