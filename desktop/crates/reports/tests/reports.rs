//! Fixture-based behavior of the aggregation: a month with published, scheduled and empty
//! channels, missing and broken records, and the Community history fallback.

use std::fs;
use std::path::Path;

use chrono::{NaiveDate, NaiveDateTime};
use reports::overview::{channel_summaries, channel_videos, overview, shorts};
use reports::snapshot::Binding;
use reports::{Period, Snapshot, SourceState, VideoKind, VideoState};

fn at(text: &str) -> NaiveDateTime {
    reports::time::parse_slot(text).expect("valid fixture time")
}

fn november() -> Period {
    Period::this_month(NaiveDate::from_ymd_opt(2026, 11, 17).unwrap())
}

fn write(root: &Path, relative: &str, content: &str) {
    let path = root.join(relative);
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, content).unwrap();
}

fn upload(root: &Path, runs: &str, run: &str, slot: &str, scheduled: bool, title: &str) {
    write(
        root,
        &format!("{runs}/{run}/upload.json"),
        &format!(
            r#"{{"videoId":"id-{run}","url":"https://youtu.be/id-{run}","slot":"{slot}","visibility":"scheduled","endScreen":true,"scheduled":{scheduled},"futureField":{{"x":1}}}}"#
        ),
    );
    write(
        root,
        &format!("{runs}/{run}/metadata.json"),
        &format!(r#"{{"title":"{title}","description":"d","tags":"a,b"}}"#),
    );
}

/// Zaflas: two published and one scheduled in November, one in December, one draft, one run
/// still without upload, two Shorts. Fallem Prince: one published in October only.
/// Every other channel has no runs folder.
fn fixture() -> tempfile::TempDir {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    let zaflas = ".local/ytbot/channels/zaflas/runs";
    upload(
        root,
        zaflas,
        "a",
        "2026-11-02 12:00",
        true,
        "Calagem e Gessagem",
    );
    upload(
        root,
        zaflas,
        "b",
        "2026-11-17 12:00",
        true,
        "Água e Rebanho",
    );
    upload(
        root,
        zaflas,
        "c",
        "2026-11-20 12:00",
        true,
        "Adubação Fosfatada",
    );
    upload(
        root,
        zaflas,
        "d",
        "2026-12-01 12:00",
        true,
        "Secagem de Grãos",
    );
    upload(
        root,
        zaflas,
        "e",
        "2026-11-05 12:00",
        false,
        "Rascunho incerto",
    );
    fs::create_dir_all(root.join(zaflas).join("in-production")).unwrap();
    write(root, &format!("{zaflas}/broken/upload.json"), "{not json");
    let shorts_dir = ".local/ytbot/channels/zaflas/shorts";
    upload(
        root,
        shorts_dir,
        "s1",
        "2026-11-10 09:00",
        true,
        "Short publicado",
    );
    upload(
        root,
        shorts_dir,
        "s2",
        "2026-11-18 18:00",
        true,
        "Short agendado",
    );
    write(root, &format!("{shorts_dir}/s2/thumbnail.png"), "png");
    upload(
        root,
        ".local/ytbot/runs",
        "f1",
        "2026-10-30 00:00",
        true,
        "Fallem de outubro",
    );
    write(
        root,
        ".local/accounts/registry.json",
        r#"{"schema":1,"accounts":{"zaflas":{"id":"zaflas","label":"Zaflas","cdp_port":9302}},
            "bindings":{"zaflas":{"account_id":"zaflas","channel_id":"UCi2aftoK7vlS3A6OozMHXKg"},
                        "vocal-pages":{"account_id":"vocal","channel_id":"UC-wrong"}}}"#,
    );
    temp
}

#[test]
fn month_counts_split_published_and_scheduled_at_now() {
    let temp = fixture();
    let now = at("2026-11-17 13:00");
    let snapshot = Snapshot::load(temp.path(), now);
    let totals = overview(&snapshot, &november(), None, now, 10);
    assert_eq!(
        totals.published,
        Some(2),
        "slots at or before now count as published"
    );
    assert_eq!(totals.scheduled, Some(1), "December is outside the month");
    assert_eq!(totals.drafts, 1);
    assert_eq!(totals.shorts_published, Some(1));
    assert_eq!(totals.shorts_scheduled, Some(1));
    assert_eq!(totals.x_posts, None, "missing X journal is not zero");
    assert_eq!(totals.whatsapp_received, None);
    assert_eq!(totals.products, None);

    let upcoming: Vec<(String, VideoKind)> = totals
        .upcoming
        .iter()
        .map(|item| (reports::time::format_slot(item.slot), item.kind))
        .collect();
    assert_eq!(
        upcoming,
        vec![
            ("qua 18/11 18:00".to_owned(), VideoKind::Short),
            ("sex 20/11 12:00".to_owned(), VideoKind::Long),
            ("ter 01/12 12:00".to_owned(), VideoKind::Long),
        ]
    );
}

#[test]
fn the_slot_boundary_is_inclusive_for_published() {
    let temp = fixture();
    let snapshot = Snapshot::load(temp.path(), at("2026-11-17 12:00"));
    let totals = overview(
        &snapshot,
        &november(),
        Some("zaflas"),
        at("2026-11-17 12:00"),
        0,
    );
    assert_eq!(totals.published, Some(2));
    let before = overview(
        &snapshot,
        &november(),
        Some("zaflas"),
        at("2026-11-17 11:59"),
        0,
    );
    assert_eq!(before.published, Some(1));
    assert_eq!(before.scheduled, Some(2));
}

#[test]
fn channel_filter_and_empty_channels_degrade_to_no_record() {
    let temp = fixture();
    let now = at("2026-11-17 13:00");
    let snapshot = Snapshot::load(temp.path(), now);
    let zanata = overview(&snapshot, &november(), Some("zanata"), now, 10);
    assert_eq!(zanata.published, None);
    assert_eq!(zanata.scheduled, None);
    assert_eq!(zanata.shorts_published, None);
    assert!(zanata.upcoming.is_empty());

    let fallem = overview(&snapshot, &november(), Some("fallem-prince"), now, 10);
    assert_eq!(
        fallem.published,
        Some(0),
        "the folder exists, nothing in November"
    );
    let october = Period::from_inputs("01/10/2026", "31/10/2026").unwrap();
    let fallem_october = overview(&snapshot, &october, Some("fallem-prince"), now, 10);
    assert_eq!(fallem_october.published, Some(1));
}

#[test]
fn channel_summaries_report_binding_last_and_next() {
    let temp = fixture();
    let now = at("2026-11-17 13:00");
    let snapshot = Snapshot::load(temp.path(), now);
    let summaries = channel_summaries(&snapshot, &november(), now);
    assert_eq!(summaries.len(), 8);
    let zaflas = summaries
        .iter()
        .find(|summary| summary.slug == "zaflas")
        .unwrap();
    assert!(matches!(zaflas.binding, Binding::Bound { ref label, .. } if label == "Zaflas"));
    assert_eq!(zaflas.counts.published, 2);
    assert_eq!(zaflas.counts.scheduled, 1);
    assert_eq!(zaflas.without_upload, 1);
    assert_eq!(zaflas.last_published.as_ref().unwrap().0, "Água e Rebanho");
    assert_eq!(
        zaflas.next_scheduled.as_ref().unwrap().1,
        at("2026-11-20 12:00")
    );
    let vocal = summaries
        .iter()
        .find(|summary| summary.slug == "vocal-pages")
        .unwrap();
    assert!(matches!(vocal.binding, Binding::Mismatch { .. }));
    assert!(!vocal.available);
    let fallem = summaries
        .iter()
        .find(|summary| summary.slug == "fallem-prince")
        .unwrap();
    assert_eq!(fallem.binding, Binding::Unbound);

    let zaflas_source = &snapshot.channel("zaflas").unwrap().runs.source;
    assert_eq!(
        zaflas_source.skipped, 1,
        "the broken upload.json is skipped, not fatal"
    );
}

#[test]
fn channel_videos_and_shorts_are_sorted_with_states() {
    let temp = fixture();
    let now = at("2026-11-17 13:00");
    let snapshot = Snapshot::load(temp.path(), now);
    let rows = channel_videos(&snapshot, "zaflas", Some(&november()), now);
    let titles: Vec<(&str, VideoState)> = rows
        .iter()
        .map(|(video, state)| (video.title.as_str(), *state))
        .collect();
    assert_eq!(
        titles,
        vec![
            ("Adubação Fosfatada", VideoState::Scheduled),
            ("Água e Rebanho", VideoState::Published),
            ("Rascunho incerto", VideoState::Draft),
            ("Calagem e Gessagem", VideoState::Published),
        ]
    );
    assert_eq!(channel_videos(&snapshot, "zaflas", None, now).len(), 5);
    let short_rows = shorts(&snapshot, now);
    assert_eq!(short_rows.len(), 2);
    assert!(short_rows[0].0.thumbnail.is_some());
    assert!(short_rows[1].0.thumbnail.is_none());
}

#[test]
fn an_empty_project_never_invents_numbers() {
    let temp = tempfile::tempdir().unwrap();
    let now = at("2026-11-17 13:00");
    let snapshot = Snapshot::load(temp.path(), now);
    let totals = overview(&snapshot, &november(), None, now, 10);
    assert_eq!(totals, reports::Overview::default());
    assert!(
        snapshot
            .sources()
            .iter()
            .all(|source| source.state == SourceState::Missing)
    );
}

#[test]
fn community_history_is_preferred_over_the_single_entry() {
    let temp = fixture();
    let root = temp.path();
    write(
        root,
        ".local/ytbot/channels/zaflas/community.json",
        r#"{"state":"posted","topic":"Último","text":"t","image":null,"at":"2026-11-16T07:05:22"}"#,
    );
    let now = at("2026-11-17 13:00");
    let single = Snapshot::load(root, now);
    let zaflas = &single.channel("zaflas").unwrap().community;
    assert!(!zaflas.from_history);
    assert_eq!(zaflas.posted_in(&november()), 1);

    write(
        root,
        ".local/ytbot/channels/zaflas/community-history.jsonl",
        concat!(
            r#"{"state":"started","topic":"A","at":"2026-11-14T07:00:00","channel":"zaflas"}"#,
            "\n",
            r#"{"state":"posted","topic":"A","at":"2026-11-14T07:01:00","channel":"zaflas"}"#,
            "\n",
            "garbage line\n",
            r#"{"state":"started","topic":"B","at":"2026-11-16T07:05:00"}"#,
            "\n",
            r#"{"state":"unconfirmed","topic":"B","at":"2026-11-16T07:06:00"}"#,
            "\n",
            r#"{"state":"posted","topic":"C","at":"2026-10-31T07:00:00"}"#,
            "\n",
        ),
    );
    let history = Snapshot::load(root, now);
    let community = &history.channel("zaflas").unwrap().community;
    assert!(community.from_history);
    assert_eq!(community.source.skipped, 1);
    assert_eq!(community.posted_in(&november()), 1);
    assert_eq!(community.latest_posted().unwrap().topic, "A");
    assert_eq!(community.latest().unwrap().state, "unconfirmed");
}

#[test]
fn networks_count_posts_messages_and_captures_in_the_period() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    write(
        root,
        ".local/social/x/posts.json",
        r#"{"schema":1,"posts":{
            "P01-old":{"state":"deleted","item_id":"P01","tweet_url":"u0","posted_at":"2026-11-15T06:58:45"},
            "P01":{"state":"posted","item_id":"P01","tweet_url":"u1","posted_at":"2026-11-15T07:12:21"},
            "P02":{"state":"posted","item_id":"P02","tweet_url":"u2","posted_at":"2026-10-20T05:12:41"}}}"#,
    );
    write(
        root,
        ".local/promotion/agenda.json",
        r#"{"items":[{"id":"P01","text":"Texto do post um"}]}"#,
    );
    write(
        root,
        ".local/social/x/replies.json",
        r#"{"replies":{"1":{"state":"posted","posted_at":"2026-11-16T10:00:00"},
                       "2":{"state":"unconfirmed","posted_at":"2026-11-16T11:00:00"}}}"#,
    );
    write(
        root,
        ".local/commercial/whatsapp/events.jsonl",
        concat!(
            r#"{"id":"1","at":"2026-11-17T12:35:50","message_at":"11:58 AM","chat":"Ana","text":"oi","allowed":false}"#,
            "\n",
            r#"{"id":"2","at":"2026-11-17T12:40:00","message_at":"12:32 PM","chat":"Bruno","text":"pedido","allowed":true}"#,
            "\n",
            r#"{"id":"2","at":"2026-11-17T12:41:00","message_at":"12:32 PM","chat":"Bruno","text":"pedido","allowed":true}"#,
            "\n",
            r#"{"id":"3","at":"2026-10-01T09:00:00","message_at":"9:00 AM","chat":"Ana","text":"antigo","allowed":false}"#,
            "\n",
        ),
    );
    write(
        root,
        ".local/commercial/whatsapp/rules.json",
        r#"{"mode":"allow","contacts":["Bruno"]}"#,
    );
    write(
        root,
        ".local/commercial/mercadolivre/products.json",
        r#"{"query":"mouse","captured_at":"2026-11-16T12:39:39","products":[
            {"title":"Mouse","price":20.99,"currency":"BRL","commission":"12%","share_link":"s"},
            {"title":"Teclado","price":"1299.9","currency":"BRL"}]}"#,
    );
    let now = at("2026-11-17 13:00");
    let snapshot = Snapshot::load(root, now);
    let totals = overview(&snapshot, &november(), None, now, 10);
    assert_eq!(
        totals.x_posts,
        Some(1),
        "deleted and October posts do not count"
    );
    assert_eq!(totals.x_replies, Some(1));
    assert_eq!(
        totals.whatsapp_received,
        Some(2),
        "duplicate event ids count once"
    );
    assert_eq!(totals.products, Some(2));
    assert_eq!(snapshot.x.posts[0].text, "Texto do post um");

    let contacts = snapshot.whatsapp.contacts(Some(&november()));
    assert_eq!(contacts.len(), 2);
    assert_eq!(contacts[0].chat, "Bruno");
    assert_eq!(contacts[0].count, 1);
    let all_time = snapshot.whatsapp.contacts(None);
    let ana = all_time
        .iter()
        .find(|contact| contact.chat == "Ana")
        .unwrap();
    assert_eq!((ana.count, ana.last_text.as_str()), (2, "oi"));
    assert_eq!(
        snapshot.whatsapp.rules.as_ref().unwrap().contacts,
        vec!["Bruno"]
    );

    let december = Period::from_inputs("01/12/2026", "31/12/2026").unwrap();
    assert_eq!(snapshot.mercadolivre.captured_in(&december), 0);
    assert_eq!(
        reports::commercial::format_price(snapshot.mercadolivre.products[1].price, "BRL"),
        "R$ 1.299,90"
    );
}

#[test]
fn a_broken_network_file_is_reported_not_fatal() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    write(root, ".local/social/x/posts.json", "[1, 2");
    write(
        root,
        ".local/commercial/whatsapp/account.json",
        r#"{"state":"logged-in","extra":[1]}"#,
    );
    let snapshot = Snapshot::load(root, at("2026-11-17 13:00"));
    let posts = snapshot
        .sources()
        .into_iter()
        .find(|source| source.path == ".local/social/x/posts.json")
        .unwrap();
    assert!(matches!(posts.state, SourceState::Invalid(_)));
    assert!(snapshot.whatsapp.account.as_ref().unwrap().logged_in());
    let totals = overview(&snapshot, &november(), None, at("2026-11-17 13:00"), 10);
    assert_eq!(totals.x_posts, None);
}
